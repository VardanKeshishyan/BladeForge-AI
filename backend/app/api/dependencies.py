import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Annotated

import httpx
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.auth.api_keys import verify_api_key
from app.auth.jwt import JWKSVerifier, TokenVerificationError
from app.core.config import Settings, get_settings
from app.db.models import ApiKey, OrganizationMember, OrgRole
from app.db.session import get_session

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: uuid.UUID
    email: str | None
    issued_at: int


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    email: str | None
    organization_id: uuid.UUID
    role: OrgRole
    auth_type: str = "user"
    issued_at: int = 0


def get_verifier(request: Request) -> JWKSVerifier:
    verifier: JWKSVerifier = request.app.state.jwks_verifier
    return verifier


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    verifier: Annotated[JWKSVerifier, Depends(get_verifier)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AuthenticatedUser:
    if settings.local_auth_disabled:
        row = (
            await session.execute(
                text(
                    """
                    select m.user_id, p.email
                    from organization_members m
                    left join profiles p on p.id = m.user_id
                    where m.status = 'active'
                    order by m.joined_at nulls last, m.created_at
                    limit 1
                    """
                )
            )
        ).mappings().first()
        if row is None:
            raise ApiError(
                500,
                "local_auth_not_configured",
                "Local auth is disabled, but no active organization member exists.",
            )
        return AuthenticatedUser(
            user_id=uuid.UUID(str(row["user_id"])),
            email=row.get("email"),
            issued_at=0,
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "authentication_required", "A valid Bearer token is required.")
    token = credentials.credentials

    try:
        claims = await verifier.verify(token)
        user_id = uuid.UUID(str(claims["sub"]))
        return AuthenticatedUser(
            user_id=user_id,
            email=claims.get("email"),
            issued_at=int(claims.get("iat", 0)),
        )
    except (TokenVerificationError, KeyError, ValueError):
        pass

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": settings.supabase_service_role_key,
                },
            )
        if response.status_code == 200:
            payload = response.json()
            return AuthenticatedUser(
                user_id=uuid.UUID(str(payload["id"])),
                email=payload.get("email"),
                issued_at=0,
            )
    except (httpx.HTTPError, KeyError, ValueError):
        pass

    raise ApiError(401, "invalid_access_token", "The access token is invalid or expired.")


async def current_principal(
    user: Annotated[AuthenticatedUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Principal:
    member = await session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.user_id,
            OrganizationMember.status == "active",
        )
    )
    if member is None:
        raise ApiError(403, "organization_membership_required", "Complete onboarding first.")
    return Principal(
        user_id=user.user_id,
        email=user.email,
        organization_id=member.organization_id,
        role=member.role,
        issued_at=user.issued_at,
    )


def require_roles(*roles: OrgRole):
    async def dependency(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if principal.role not in roles:
            raise ApiError(403, "insufficient_role", "Your organization role cannot perform this action.")
        return principal

    return dependency


async def api_key_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    if credentials is None or not credentials.credentials.startswith("bf_live_"):
        raise ApiError(401, "invalid_api_key", "A valid BladeForge API key is required.")
    prefix = credentials.credentials[:16]
    record = await session.scalar(
        select(ApiKey).where(ApiKey.key_prefix == prefix, ApiKey.status == "active")
    )
    if record is None or (
        record.expires_at is not None and record.expires_at.timestamp() <= time.time()
    ):
        raise ApiError(401, "invalid_api_key", "The API key is invalid, expired, or revoked.")
    if not verify_api_key(credentials.credentials, record.key_hash, settings.api_key_pepper):
        raise ApiError(401, "invalid_api_key", "The API key is invalid, expired, or revoked.")
    recent_requests = int(
        (
            await session.execute(
                text(
                    """
                    select count(*) from usage_events
                    where organization_id = :org_id
                      and event_type = 'api_request'
                      and recorded_at > now() - interval '1 minute'
                      and metadata ->> 'api_key_id' = :key_id
                    """
                ),
                {"org_id": record.organization_id, "key_id": str(record.id)},
            )
        ).scalar_one()
    )
    if recent_requests >= settings.api_key_requests_per_minute:
        raise ApiError(429, "api_key_quota_exceeded", "API key request quota exceeded.")
    await session.execute(
        text("update api_keys set last_used_at = now() where id = :id"),
        {"id": record.id},
    )
    await session.execute(
        text(
            """
            insert into usage_events (organization_id, event_type, metadata)
            values (:org_id, 'api_request', cast(:metadata as jsonb))
            """
        ),
        {
            "org_id": record.organization_id,
            "metadata": __import__("json").dumps({"api_key_id": str(record.id)}),
        },
    )
    await session.commit()
    return Principal(
        user_id=record.created_by,
        email=None,
        organization_id=record.organization_id,
        role=OrgRole.engineer,
        auth_type="api_key",
    )


async def verify_worker_secret(
    settings: Annotated[Settings, Depends(get_settings)],
    worker_secret: Annotated[str | None, Header(alias="X-Worker-Secret")] = None,
) -> None:
    if worker_secret is None or not secrets.compare_digest(worker_secret, settings.worker_secret):
        raise ApiError(401, "invalid_worker_secret", "Worker authentication failed.")
