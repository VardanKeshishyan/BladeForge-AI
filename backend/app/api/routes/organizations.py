import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    AuthenticatedUser,
    Principal,
    current_principal,
    current_user,
)
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.schemas.organizations import (
    AccountDelete,
    InvitationAccept,
    InvitationCreate,
    MemberRoleUpdate,
    OnboardingRequest,
    OrganizationUpdate,
    ProfileUpdate,
)
from app.services.organizations import OrganizationService

router = APIRouter(tags=["account-and-organization"])


@router.post("/onboarding")
async def complete_onboarding(
    payload: OnboardingRequest,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await OrganizationService(session, settings).onboarding(user, payload)


@router.get("/me")
async def get_me(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await OrganizationService(session, settings).me(principal)


@router.patch("/me/profile")
async def update_profile(
    payload: ProfileUpdate,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await OrganizationService(session, settings).update_profile(principal, payload)


@router.patch("/organization")
async def update_organization(
    payload: OrganizationUpdate,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await OrganizationService(session, settings).update_organization(
        principal, payload.name
    )


@router.get("/organization")
async def get_organization(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await OrganizationService(session, settings).organization(principal)


@router.get("/team")
async def list_team(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return {"items": await OrganizationService(session, settings).team(principal)}


@router.patch("/team/{member_id}")
async def update_member_role(
    member_id: uuid.UUID,
    payload: MemberRoleUpdate,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await OrganizationService(session, settings).update_member_role(
        principal, member_id, payload.role
    )


@router.delete("/team/{member_id}", status_code=204)
async def remove_member(
    member_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    await OrganizationService(session, settings).remove_member(principal, member_id)


@router.post("/invitations", status_code=201)
async def create_invitation(
    payload: InvitationCreate,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await OrganizationService(session, settings).invite(principal, payload)


@router.get("/invitations")
async def list_invitations(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return {"items": await OrganizationService(session, settings).invitations(principal)}


@router.post("/invitations/{invitation_id}/revoke")
async def revoke_invitation(
    invitation_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await OrganizationService(session, settings).revoke_invitation(
        principal, invitation_id
    )


@router.post("/invitations/accept")
async def accept_invitation(
    payload: InvitationAccept,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await OrganizationService(session, settings).accept_invitation(user, payload.token)


@router.delete("/me")
async def delete_account(
    payload: AccountDelete,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    await OrganizationService(session, settings).delete_account(principal)
    return {"message": "Account deleted."}


@router.get("/me/password")
async def password_change_capability(
    principal: Annotated[Principal, Depends(current_principal)],
):
    return {
        "provider": "supabase_auth",
        "supported": True,
        "message": "Use the authenticated Supabase session to update the password.",
    }
