import math
import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import Principal
from app.api.errors import ApiError
from app.core.config import Settings
from app.db.models import GenerationJob, JobStatus, OrgRole
from app.repositories.jobs import JobRepository
from app.schemas.jobs import JobCreate

LEGAL_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.draft: {JobStatus.awaiting_worker, JobStatus.cancelled},
    JobStatus.awaiting_worker: {JobStatus.queued, JobStatus.cancelled},
    JobStatus.queued: {JobStatus.rendering, JobStatus.cancelled, JobStatus.failed},
    JobStatus.rendering: {
        JobStatus.processing_annotations,
        JobStatus.cancelled,
        JobStatus.failed,
    },
    JobStatus.processing_annotations: {
        JobStatus.complete,
        JobStatus.cancelled,
        JobStatus.failed,
    },
    JobStatus.complete: set(),
    JobStatus.failed: {JobStatus.awaiting_worker},
    JobStatus.cancelled: {JobStatus.awaiting_worker},
}


def estimate_dataset_size_bytes(payload: JobCreate) -> int:
    pixels = payload.config.image_width * payload.config.image_height
    quality_factor = 0.12 + (payload.config.compression_quality - 50) / 500
    rgb_bytes = int(pixels * 3 * quality_factor)
    mask_bytes = int(pixels * 0.075)
    metadata_bytes = 4_096
    annotation_bytes = 3_072 if payload.annotation_format == "coco_json" else 1_024
    per_image = rgb_bytes + mask_bytes + metadata_bytes + annotation_bytes
    return math.ceil(payload.image_count * per_image * 1.04)


class JobService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repository = JobRepository(session)

    async def create(
        self, principal: Principal, payload: JobCreate, idempotency_key: str
    ) -> GenerationJob:
        if principal.role == OrgRole.viewer:
            raise ApiError(403, "insufficient_role", "Viewers cannot create generation jobs.")
        if payload.image_count > self.settings.max_image_count:
            raise ApiError(
                422,
                "image_count_limit",
                f"Image count cannot exceed {self.settings.max_image_count}.",
            )
        existing = await self.repository.by_idempotency_key(
            principal.organization_id, idempotency_key
        )
        if existing is not None:
            return existing

        config = payload.config.model_dump()
        now = datetime.now(UTC)
        job = GenerationJob(
            id=uuid.uuid4(),
            organization_id=principal.organization_id,
            created_by=principal.user_id,
            name=payload.name,
            description=payload.description,
            status=JobStatus.awaiting_worker,
            config=config,
            defect_type=payload.defect_type,
            severity_min=payload.severity_min,
            severity_max=payload.severity_max,
            image_count=payload.image_count,
            image_width=payload.config.image_width,
            image_height=payload.config.image_height,
            annotation_format=payload.annotation_format,
            dataset_name=payload.dataset_name,
            estimated_size_bytes=estimate_dataset_size_bytes(payload),
            progress=0,
            current_stage="awaiting_worker",
            attempt_count=0,
            max_attempts=3,
            idempotency_key=idempotency_key,
            submitted_at=now,
        )
        self.repository.add(job)
        self.repository.add_event(
            job,
            "submitted",
            "Job validated and is waiting for a healthy render worker.",
            created_by=principal.user_id,
        )
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            duplicate = await self.repository.by_idempotency_key(
                principal.organization_id, idempotency_key
            )
            if duplicate is None:
                raise
            return duplicate
        await self.session.refresh(job)
        return job

    async def transition(
        self,
        job: GenerationJob,
        target: JobStatus,
        *,
        stage: str,
        message: str,
        actor: uuid.UUID | None = None,
        progress: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if target not in LEGAL_TRANSITIONS[job.status]:
            raise ApiError(
                409,
                "illegal_job_transition",
                f"Cannot move a job from {job.status.value} to {target.value}.",
            )
        job.status = target
        job.current_stage = stage
        if progress is not None:
            job.progress = progress
        now = datetime.now(UTC)
        if target == JobStatus.rendering and job.started_at is None:
            job.started_at = now
        if target in {JobStatus.complete, JobStatus.failed, JobStatus.cancelled}:
            job.completed_at = now
        self.repository.add_event(
            job,
            target.value,
            message,
            created_by=actor,
            metadata=metadata,
        )

    async def cancel(self, principal: Principal, job_id: uuid.UUID) -> GenerationJob:
        job = await self.repository.get(principal.organization_id, job_id, lock=True)
        if job is None:
            raise ApiError(404, "job_not_found", "Generation job not found.")
        if job.status in {JobStatus.complete, JobStatus.failed, JobStatus.cancelled}:
            raise ApiError(409, "job_not_cancellable", "This job can no longer be cancelled.")
        job.cancellation_requested_at = datetime.now(UTC)
        if job.status in {JobStatus.draft, JobStatus.awaiting_worker, JobStatus.queued}:
            await self.transition(
                job,
                JobStatus.cancelled,
                stage="cancelled",
                message="Job cancelled by a user.",
                actor=principal.user_id,
                progress=job.progress,
            )
        else:
            self.repository.add_event(
                job,
                "cancellation_requested",
                "Cancellation requested; the worker will stop at the next safe checkpoint.",
                created_by=principal.user_id,
            )
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def retry(self, principal: Principal, job_id: uuid.UUID) -> GenerationJob:
        job = await self.repository.get(principal.organization_id, job_id, lock=True)
        if job is None:
            raise ApiError(404, "job_not_found", "Generation job not found.")
        if job.status not in {JobStatus.failed, JobStatus.cancelled}:
            raise ApiError(409, "job_not_retryable", "Only failed or cancelled jobs can be retried.")
        if job.attempt_count >= job.max_attempts:
            raise ApiError(409, "attempt_limit_reached", "This job reached its maximum attempts.")
        job.failure_code = None
        job.failure_message = None
        job.cancellation_requested_at = None
        job.worker_id = None
        job.locked_at = None
        job.heartbeat_at = None
        job.completed_at = None
        await self.transition(
            job,
            JobStatus.awaiting_worker,
            stage="awaiting_worker",
            message="Job returned to the worker queue for another attempt.",
            actor=principal.user_id,
            progress=0,
        )
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def duplicate(
        self, principal: Principal, job_id: uuid.UUID, idempotency_key: str
    ) -> GenerationJob:
        source = await self.repository.get(principal.organization_id, job_id)
        if source is None:
            raise ApiError(404, "job_not_found", "Generation job not found.")
        # Validating rather than constructing re-checks the stored configuration against
        # the current schema, so a copy of an old job cannot carry forward a value the
        # API no longer accepts.
        payload = JobCreate.model_validate(
            {
                "name": f"{source.name} copy"[:100],
                "description": source.description,
                "defect_type": source.defect_type,
                "severity_min": source.severity_min,
                "severity_max": source.severity_max,
                "image_count": source.image_count,
                "annotation_format": source.annotation_format,
                "dataset_name": f"{source.dataset_name} copy"[:100],
                "config": source.config,
            }
        )
        return await self.create(principal, payload, idempotency_key)
