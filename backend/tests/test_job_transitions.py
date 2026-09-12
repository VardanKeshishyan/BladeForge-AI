import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.api.errors import ApiError
from app.core.config import get_settings
from app.db.models import GenerationJob, JobStatus
from app.services.jobs import JobService


class EventRecorder:
    def __init__(self) -> None:
        self.events: list[str] = []

    def add_event(self, job: GenerationJob, event_type: str, message: str, **kwargs: object) -> None:
        self.events.append(event_type)


def job_with_status(status: JobStatus) -> GenerationJob:
    return GenerationJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        name="Test job",
        status=status,
        config={},
        defect_type="leading_edge_erosion",
        severity_min=10,
        severity_max=80,
        image_count=2,
        image_width=512,
        image_height=512,
        annotation_format="coco_json",
        dataset_name="test-data",
        estimated_size_bytes=100,
        progress=0,
        current_stage=status.value,
        attempt_count=0,
        max_attempts=3,
        idempotency_key="test-idempotency-key",
        submitted_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_legal_worker_transition_records_event() -> None:
    service = JobService(AsyncMock(), get_settings())
    recorder = EventRecorder()
    service.repository = recorder  # type: ignore[assignment]
    job = job_with_status(JobStatus.queued)
    await service.transition(
        job,
        JobStatus.rendering,
        stage="rendering_sample_1",
        message="Rendering began.",
        progress=1,
    )
    assert job.status == JobStatus.rendering
    assert job.started_at is not None
    assert recorder.events == ["rendering"]


@pytest.mark.asyncio
async def test_illegal_transition_is_rejected() -> None:
    service = JobService(AsyncMock(), get_settings())
    job = job_with_status(JobStatus.complete)
    with pytest.raises(ApiError) as error:
        await service.transition(
            job,
            JobStatus.rendering,
            stage="rendering",
            message="Invalid.",
        )
    assert error.value.code == "illegal_job_transition"

