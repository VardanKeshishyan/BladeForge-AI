import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OrgRole(StrEnum):
    owner = "owner"
    administrator = "administrator"
    engineer = "engineer"
    viewer = "viewer"


class JobStatus(StrEnum):
    draft = "draft"
    awaiting_worker = "awaiting_worker"
    queued = "queued"
    rendering = "rendering"
    processing_annotations = "processing_annotations"
    complete = "complete"
    failed = "failed"
    cancelled = "cancelled"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Profile(Base, TimestampMixin):
    __tablename__ = "profiles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str | None] = mapped_column(String(120))
    job_title: Mapped[str | None] = mapped_column(String(120))
    onboarding_role: Mapped[str | None] = mapped_column(String(80))
    selected_use_cases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))


class OrganizationMember(Base, TimestampMixin):
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    role: Mapped[OrgRole] = mapped_column(
        Enum(OrgRole, name="organization_role", create_type=False)
    )
    status: Mapped[str] = mapped_column(String)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GenerationJob(Base, TimestampMixin):
    __tablename__ = "generation_jobs"
    __table_args__ = (UniqueConstraint("organization_id", "idempotency_key"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", create_type=False), index=True
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    defect_type: Mapped[str] = mapped_column(String)
    severity_min: Mapped[int] = mapped_column(SmallInteger)
    severity_max: Mapped[int] = mapped_column(SmallInteger)
    image_count: Mapped[int] = mapped_column(Integer)
    image_width: Mapped[int] = mapped_column(Integer)
    image_height: Mapped[int] = mapped_column(Integer)
    annotation_format: Mapped[str] = mapped_column(String)
    dataset_name: Mapped[str] = mapped_column(String(100))
    estimated_size_bytes: Mapped[int] = mapped_column(BigInteger)
    progress: Mapped[int] = mapped_column(SmallInteger)
    current_stage: Mapped[str] = mapped_column(String)
    attempt_count: Mapped[int] = mapped_column(Integer)
    max_attempts: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String)
    failure_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generation_jobs.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Dataset(Base, TimestampMixin):
    __tablename__ = "datasets"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(100))
    defect_type: Mapped[str] = mapped_column(String)
    image_count: Mapped[int] = mapped_column(Integer)
    annotation_formats: Mapped[list[str]] = mapped_column(ARRAY(Text))
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    archive_storage_path: Mapped[str | None] = mapped_column(Text)
    manifest_storage_path: Mapped[str | None] = mapped_column(Text)
    preview_storage_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(100))
    key_prefix: Mapped[str] = mapped_column(String, unique=True)
    key_hash: Mapped[str] = mapped_column(String, unique=True)
    status: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UsageEvent(Base):
    __tablename__ = "usage_events"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    event_type: Mapped[str] = mapped_column(String)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    gpu_seconds: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    storage_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
