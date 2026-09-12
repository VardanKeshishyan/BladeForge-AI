import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.api.dependencies import Principal
from app.api.errors import ApiError
from app.core.config import get_settings
from app.db.models import GenerationJob, JobStatus, OrgRole
from app.schemas.jobs import JobCreate
from app.services.jobs import JobService


def principal(role: OrgRole = OrgRole.engineer) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        email="engineer@example.com",
        organization_id=uuid.uuid4(),
        role=role,
    )


def payload() -> JobCreate:
    return JobCreate.model_validate(
        {
            "name": "Service test",
            "defect_type": "leading_edge_erosion",
            "severity_min": 10,
            "severity_max": 70,
            "image_count": 2,
            "annotation_format": "coco_json",
            "dataset_name": "service-test-data",
        }
    )


def job(owner: Principal, status: JobStatus) -> GenerationJob:
    return GenerationJob(
        id=uuid.uuid4(),
        organization_id=owner.organization_id,
        created_by=owner.user_id,
        name="Existing job",
        status=status,
        config={},
        defect_type="leading_edge_erosion",
        severity_min=10,
        severity_max=70,
        image_count=2,
        image_width=512,
        image_height=512,
        annotation_format="coco_json",
        dataset_name="existing-data",
        estimated_size_bytes=100,
        progress=0,
        current_stage=status.value,
        attempt_count=1,
        max_attempts=3,
        idempotency_key="existing-idempotency-key",
        submitted_at=datetime.now(UTC),
    )


class FakeRepository:
    def __init__(self, existing: GenerationJob | None) -> None:
        self.existing = existing
        self.events: list[str] = []

    async def by_idempotency_key(
        self, organization_id: uuid.UUID, key: str
    ) -> GenerationJob | None:
        return self.existing

    async def get(
        self, organization_id: uuid.UUID, job_id: uuid.UUID, *, lock: bool = False
    ) -> GenerationJob | None:
        if self.existing is not None and self.existing.organization_id == organization_id:
            return self.existing
        return None

    def add(self, value: GenerationJob) -> None:
        self.existing = value

    def add_event(
        self, value: GenerationJob, event_type: str, message: str, **kwargs: object
    ) -> None:
        self.events.append(event_type)


@pytest.mark.asyncio
async def test_idempotent_create_returns_original_job() -> None:
    actor = principal()
    existing = job(actor, JobStatus.awaiting_worker)
    service = JobService(AsyncMock(), get_settings())
    service.repository = FakeRepository(existing)  # type: ignore[assignment]
    created = await service.create(actor, payload(), "same-request-key")
    assert created is existing


@pytest.mark.asyncio
async def test_viewer_cannot_create_job() -> None:
    actor = principal(OrgRole.viewer)
    service = JobService(AsyncMock(), get_settings())
    with pytest.raises(ApiError) as error:
        await service.create(actor, payload(), "viewer-request-key")
    assert error.value.code == "insufficient_role"


@pytest.mark.asyncio
async def test_cross_organization_job_is_reported_not_found() -> None:
    owner = principal()
    outsider = principal()
    service = JobService(AsyncMock(), get_settings())
    service.repository = FakeRepository(job(owner, JobStatus.queued))  # type: ignore[assignment]
    with pytest.raises(ApiError) as error:
        await service.cancel(outsider, service.repository.existing.id)  # type: ignore[union-attr]
    assert error.value.code == "job_not_found"


@pytest.mark.asyncio
async def test_cancel_and_retry_follow_legal_transitions() -> None:
    actor = principal()
    existing = job(actor, JobStatus.queued)
    session = AsyncMock()
    repository = FakeRepository(existing)
    service = JobService(session, get_settings())
    service.repository = repository  # type: ignore[assignment]
    cancelled = await service.cancel(actor, existing.id)
    assert cancelled.status == JobStatus.cancelled
    retried = await service.retry(actor, existing.id)
    assert retried.status == JobStatus.awaiting_worker
    assert repository.events == ["cancelled", "awaiting_worker"]

