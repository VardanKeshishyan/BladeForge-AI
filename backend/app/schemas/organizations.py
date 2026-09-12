import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class OnboardingRequest(BaseModel):
    organization_name: str = Field(min_length=2, max_length=100)
    organization_slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2, max_length=63)
    onboarding_role: str = Field(min_length=1, max_length=80)
    job_title: str | None = Field(default=None, max_length=120)
    selected_use_cases: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("organization_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()


class ProfileUpdate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    job_title: str | None = Field(default=None, max_length=120)


class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)


class InvitationCreate(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: Literal["administrator", "engineer", "viewer"]


class InvitationAccept(BaseModel):
    token: str = Field(min_length=32, max_length=500)


class MemberRoleUpdate(BaseModel):
    role: Literal["administrator", "engineer", "viewer"]


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    expires_at: datetime | None = None


class AccountDelete(BaseModel):
    confirmation: Literal["DELETE MY ACCOUNT"]


class OrganizationRead(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
