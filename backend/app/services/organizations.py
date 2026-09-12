import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthenticatedUser, Principal
from app.api.errors import ApiError
from app.core.config import Settings
from app.db.models import OrgRole
from app.schemas.organizations import InvitationCreate, OnboardingRequest, ProfileUpdate


class OrganizationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def onboarding(
        self, user: AuthenticatedUser, payload: OnboardingRequest
    ) -> dict[str, object]:
        result = (
            await self.session.execute(
                text(
                    """
                    select id, name, slug, owner_id, created_at, updated_at
                    from complete_onboarding(
                      :name, :slug, :role, :job_title, :use_cases
                    )
                    """
                ),
                {
                    "name": payload.organization_name,
                    "slug": payload.organization_slug,
                    "role": payload.onboarding_role,
                    "job_title": payload.job_title,
                    "use_cases": payload.selected_use_cases,
                },
            )
        ).mappings().one()
        await self.session.commit()
        return dict(result)

    async def me(self, principal: Principal) -> dict[str, object]:
        row = (
            await self.session.execute(
                text(
                    """
                    select p.id, p.email, p.full_name, p.job_title, p.onboarding_role,
                           p.selected_use_cases, p.onboarding_complete,
                           o.id as organization_id, o.name as organization_name,
                           o.slug as organization_slug, m.role
                    from profiles p
                    join organization_members m on m.user_id = p.id and m.status = 'active'
                    join organizations o on o.id = m.organization_id
                    where p.id = :user_id and o.id = :org_id
                    """
                ),
                {"user_id": principal.user_id, "org_id": principal.organization_id},
            )
        ).mappings().first()
        if row is None:
            raise ApiError(404, "profile_not_found", "Profile not found.")
        return dict(row)

    async def organization(self, principal: Principal) -> dict[str, object]:
        row = (
            await self.session.execute(
                text(
                    """
                    select id, name, slug, owner_id, created_at, updated_at
                    from organizations
                    where id = :org_id
                    """
                ),
                {"org_id": principal.organization_id},
            )
        ).mappings().first()
        if row is None:
            raise ApiError(404, "organization_not_found", "Organization not found.")
        return dict(row)

    async def update_profile(
        self, principal: Principal, payload: ProfileUpdate
    ) -> dict[str, object]:
        row = (
            await self.session.execute(
                text(
                    """
                    update profiles
                    set full_name = :full_name, job_title = :job_title
                    where id = :user_id
                    returning id, email, full_name, job_title, organization_id, onboarding_complete
                    """
                ),
                {
                    "full_name": payload.full_name.strip(),
                    "job_title": payload.job_title.strip() if payload.job_title else None,
                    "user_id": principal.user_id,
                },
            )
        ).mappings().one()
        await self.session.commit()
        return dict(row)

    async def update_organization(self, principal: Principal, name: str) -> dict[str, object]:
        if principal.role not in {OrgRole.owner, OrgRole.administrator}:
            raise ApiError(403, "insufficient_role", "Only owners and administrators can update the organization.")
        row = (
            await self.session.execute(
                text(
                    """
                    update organizations set name = :name
                    where id = :org_id
                    returning id, name, slug, owner_id, created_at, updated_at
                    """
                ),
                {"name": name.strip(), "org_id": principal.organization_id},
            )
        ).mappings().one()
        await self.session.commit()
        return dict(row)

    async def team(self, principal: Principal) -> list[dict[str, object]]:
        rows = (
            await self.session.execute(
                text(
                    """
                    select m.id, m.user_id, p.full_name, p.email, m.role, m.status, m.joined_at
                    from organization_members m
                    join profiles p on p.id = m.user_id
                    where m.organization_id = :org_id
                    order by m.joined_at
                    """
                ),
                {"org_id": principal.organization_id},
            )
        ).mappings()
        return [dict(row) for row in rows]

    async def update_member_role(
        self, principal: Principal, member_id: uuid.UUID, role: str
    ) -> dict[str, object]:
        if principal.role not in {OrgRole.owner, OrgRole.administrator}:
            raise ApiError(
                403,
                "insufficient_role",
                "Only owners and administrators can manage members.",
            )
        row = (
            await self.session.execute(
                text(
                    """
                    update organization_members
                    set role = :role
                    where id = :member_id and organization_id = :org_id and role <> 'owner'
                    returning id, user_id, role, status, joined_at
                    """
                ),
                {
                    "role": role,
                    "member_id": member_id,
                    "org_id": principal.organization_id,
                },
            )
        ).mappings().first()
        if row is None:
            raise ApiError(404, "member_not_found", "Non-owner member not found.")
        await self.session.commit()
        return dict(row)

    async def remove_member(self, principal: Principal, member_id: uuid.UUID) -> None:
        if principal.role not in {OrgRole.owner, OrgRole.administrator}:
            raise ApiError(
                403,
                "insufficient_role",
                "Only owners and administrators can manage members.",
            )
        result = await self.session.execute(
            text(
                """
                delete from organization_members
                where id = :member_id and organization_id = :org_id and role <> 'owner'
                """
            ),
            {"member_id": member_id, "org_id": principal.organization_id},
        )
        if getattr(result, "rowcount", 0) == 0:
            raise ApiError(404, "member_not_found", "Non-owner member not found.")
        await self.session.commit()

    async def invitations(self, principal: Principal) -> list[dict[str, object]]:
        if principal.role not in {OrgRole.owner, OrgRole.administrator}:
            raise ApiError(
                403,
                "insufficient_role",
                "Only owners and administrators can view invitations.",
            )
        rows = (
            await self.session.execute(
                text(
                    """
                    select id, email, role, status, expires_at, created_at
                    from organization_invitations
                    where organization_id = :org_id
                    order by created_at desc
                    """
                ),
                {"org_id": principal.organization_id},
            )
        ).mappings()
        return [dict(row) for row in rows]

    async def revoke_invitation(
        self, principal: Principal, invitation_id: uuid.UUID
    ) -> dict[str, object]:
        if principal.role not in {OrgRole.owner, OrgRole.administrator}:
            raise ApiError(
                403,
                "insufficient_role",
                "Only owners and administrators can revoke invitations.",
            )
        row = (
            await self.session.execute(
                text(
                    """
                    update organization_invitations
                    set status = 'revoked'
                    where id = :invitation_id and organization_id = :org_id and status = 'pending'
                    returning id, email, role, status, expires_at, created_at
                    """
                ),
                {
                    "invitation_id": invitation_id,
                    "org_id": principal.organization_id,
                },
            )
        ).mappings().first()
        if row is None:
            raise ApiError(404, "invitation_not_found", "Pending invitation not found.")
        await self.session.commit()
        return dict(row)

    def _hash_invitation(self, token: str) -> str:
        return hmac.new(
            self.settings.api_key_pepper.encode(), token.encode(), hashlib.sha256
        ).hexdigest()

    async def invite(
        self, principal: Principal, payload: InvitationCreate
    ) -> dict[str, object]:
        if principal.role not in {OrgRole.owner, OrgRole.administrator}:
            raise ApiError(403, "insufficient_role", "Only owners and administrators can invite members.")
        if not self.settings.email_enabled:
            raise ApiError(
                503,
                "email_not_configured",
                "Team invitations are disabled until an email provider is configured.",
            )
        token = secrets.token_urlsafe(40)
        invitation_id = uuid.uuid4()
        email = payload.email.lower()
        await self.session.execute(
            text(
                """
                insert into organization_invitations (
                  id, organization_id, email, role, token_hash, invited_by, expires_at
                ) values (
                  :id, :org_id, :email, :role, :token_hash, :invited_by, :expires_at
                )
                """
            ),
            {
                "id": invitation_id,
                "org_id": principal.organization_id,
                "email": email,
                "role": payload.role,
                "token_hash": self._hash_invitation(token),
                "invited_by": principal.user_id,
                "expires_at": datetime.now(UTC) + timedelta(days=7),
            },
        )
        invite_url = f"{self.settings.frontend_url.rstrip('/')}/auth/accept-invitation?token={token}"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {self.settings.resend_api_key}"},
                json={
                    "from": self.settings.invitation_from_email,
                    "to": [email],
                    "subject": "You are invited to BladeForge AI",
                    "text": f"Accept your organization invitation: {invite_url}",
                },
            )
        if response.status_code >= 300:
            await self.session.rollback()
            raise ApiError(502, "email_delivery_failed", "The invitation email could not be sent.")
        await self.session.commit()
        return {"id": invitation_id, "email": email, "role": payload.role, "status": "pending"}

    async def accept_invitation(
        self, user: AuthenticatedUser, raw_token: str
    ) -> dict[str, object]:
        token_hash = self._hash_invitation(raw_token)
        invitation = (
            await self.session.execute(
                text(
                    """
                    select id, organization_id, email, role, expires_at, status
                    from organization_invitations
                    where token_hash = :token_hash
                    for update
                    """
                ),
                {"token_hash": token_hash},
            )
        ).mappings().first()
        if invitation is None or invitation["status"] != "pending":
            raise ApiError(404, "invitation_not_found", "Invitation is invalid or already used.")
        if invitation["expires_at"] <= datetime.now(UTC):
            await self.session.execute(
                text("update organization_invitations set status = 'expired' where id = :id"),
                {"id": invitation["id"]},
            )
            await self.session.commit()
            raise ApiError(410, "invitation_expired", "Invitation has expired.")
        if not user.email or user.email.lower() != invitation["email"]:
            raise ApiError(403, "invitation_email_mismatch", "Sign in with the invited email address.")
        await self.session.execute(
            text(
                """
                insert into organization_members (organization_id, user_id, role, status)
                values (:org_id, :user_id, :role, 'active')
                on conflict (organization_id, user_id)
                do update set role = excluded.role, status = 'active'
                """
            ),
            {
                "org_id": invitation["organization_id"],
                "user_id": user.user_id,
                "role": invitation["role"],
            },
        )
        await self.session.execute(
            text(
                """
                update profiles
                set organization_id = :org_id, onboarding_complete = true
                where id = :user_id
                """
            ),
            {"org_id": invitation["organization_id"], "user_id": user.user_id},
        )
        await self.session.execute(
            text(
                """
                update organization_invitations
                set status = 'accepted', accepted_by = :user_id, accepted_at = now()
                where id = :id
                """
            ),
            {"user_id": user.user_id, "id": invitation["id"]},
        )
        await self.session.commit()
        return {"organization_id": invitation["organization_id"], "status": "accepted"}

    async def delete_account(self, principal: Principal) -> None:
        now = datetime.now(UTC)
        if principal.issued_at <= 0 or now.timestamp() - principal.issued_at > 600:
            raise ApiError(
                401,
                "recent_authentication_required",
                "Sign in again before deleting the account.",
            )
        if principal.role == OrgRole.owner:
            member_count = int(
                (
                    await self.session.execute(
                        text(
                            """
                            select count(*) from organization_members
                            where organization_id = :org_id and status = 'active'
                            """
                        ),
                        {"org_id": principal.organization_id},
                    )
                ).scalar_one()
            )
            if member_count > 1:
                raise ApiError(
                    409,
                    "ownership_transfer_required",
                    "Transfer organization ownership before deleting this account.",
                )
            await self.session.execute(
                text("delete from organizations where id = :org_id and owner_id = :user_id"),
                {"org_id": principal.organization_id, "user_id": principal.user_id},
            )
        else:
            await self.session.execute(
                text(
                    """
                    delete from organization_members
                    where organization_id = :org_id and user_id = :user_id
                    """
                ),
                {"org_id": principal.organization_id, "user_id": principal.user_id},
            )
        await self.session.commit()
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.delete(
                f"{self.settings.supabase_url.rstrip('/')}/auth/v1/admin/users/{principal.user_id}",
                headers={
                    "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
                    "apikey": self.settings.supabase_service_role_key,
                },
            )
        if response.status_code >= 300:
            raise ApiError(
                502,
                "auth_account_deletion_failed",
                "Organization data was updated, but the Auth account could not be deleted. Contact support.",
            )
