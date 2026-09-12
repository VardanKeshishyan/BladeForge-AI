import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.core.config import Settings
from app.db.models import GenerationJob, JobStatus
from app.repositories.jobs import JobRepository
from app.schemas.jobs import WorkerFailure, WorkerProgress
from app.services.assets import AssetService
from app.services.datasets import DatasetService
from app.services.jobs import JobService


class WorkerService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.jobs = JobRepository(session)

    async def register(
        self, name: str, organization_id: uuid.UUID | None, capabilities: dict[str, object]
    ) -> dict[str, object]:
        row = (
            await self.session.execute(
                text(
                    """
                    insert into render_workers (
                      id, organization_id, name, adapter_type, status, capabilities, last_seen_at
                    ) values (
                      :id, :organization_id, :name, 'local', 'healthy', cast(:capabilities as jsonb), now()
                    )
                    returning id, organization_id, name, status, capabilities, last_seen_at
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "organization_id": organization_id,
                    "name": name.strip(),
                    "capabilities": __import__("json").dumps(capabilities),
                },
            )
        ).mappings().one()
        await self.session.commit()
        return dict(row)

    async def heartbeat(self, worker_id: uuid.UUID) -> dict[str, object]:
        row = (
            await self.session.execute(
                text(
                    """
                    update render_workers
                    set last_seen_at = now(),
                        status = case when current_job_id is null then 'healthy' else 'busy' end
                    where id = :worker_id
                    returning id, status, current_job_id, last_seen_at
                    """
                ),
                {"worker_id": worker_id},
            )
        ).mappings().first()
        if row is None:
            raise ApiError(404, "worker_not_found", "Render worker is not registered.")
        stale_before = datetime.now(UTC) - timedelta(seconds=self.settings.worker_stale_seconds)
        await self.session.execute(
            text(
                """
                update generation_jobs
                set status = 'awaiting_worker',
                    current_stage = 'awaiting_worker',
                    worker_id = null,
                    locked_at = null,
                    heartbeat_at = null
                where status in ('queued', 'rendering', 'processing_annotations')
                  and heartbeat_at is not null
                  and heartbeat_at < :stale_before
                """
            ),
            {"stale_before": stale_before},
        )
        await self.session.commit()
        return dict(row)

    async def claim(self, worker_id: uuid.UUID) -> dict[str, object] | None:
        row = (
            await self.session.execute(
                text(
                    """
                    with worker as (
                      select id, organization_id from render_workers where id = :worker_id
                    ),
                    picked as (
                      select j.id
                      from generation_jobs j, worker w
                      where j.status = 'awaiting_worker'
                        and (w.organization_id is null or j.organization_id = w.organization_id)
                      order by j.created_at asc
                      for update skip locked
                      limit 1
                    ),
                    claimed as (
                      update generation_jobs j
                      set status = 'queued',
                          current_stage = 'queued',
                          progress = greatest(progress, 1),
                          worker_id = :worker_id,
                          locked_at = now(),
                          heartbeat_at = now(),
                          attempt_count = attempt_count + 1
                      from picked
                      where j.id = picked.id
                      returning j.*
                    )
                    update render_workers rw
                    set status = 'busy',
                        current_job_id = (select id from claimed),
                        last_seen_at = now()
                    where rw.id = :worker_id
                      and exists (select 1 from claimed)
                    returning (select row_to_json(claimed) from claimed)
                    """
                ),
                {"worker_id": worker_id},
            )
        ).first()
        await self.session.commit()
        if row is None or row[0] is None:
            return None
        return dict(row[0])

    async def _owned_job(
        self, worker_id: uuid.UUID, job_id: uuid.UUID, *, lock: bool = True
    ) -> GenerationJob:
        statement = select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.worker_id == worker_id,
        )
        if lock:
            statement = statement.with_for_update()
        job = await self.session.scalar(statement)
        if job is None:
            raise ApiError(404, "worker_job_not_found", "This job is not assigned to the worker.")
        return job

    async def progress(
        self, worker_id: uuid.UUID, job_id: uuid.UUID, payload: WorkerProgress
    ) -> dict[str, object]:
        job = await self._owned_job(worker_id, job_id)
        if job.cancellation_requested_at is not None:
            return {"cancel_requested": True, "status": job.status.value}
        target = JobStatus(payload.status)
        service = JobService(self.session, self.settings)
        if job.status != target:
            await service.transition(
                job,
                target,
                stage=payload.stage,
                message=payload.message,
                progress=payload.progress,
                metadata=payload.metadata,
            )
        else:
            if payload.progress < job.progress:
                raise ApiError(409, "progress_regression", "Job progress cannot move backwards.")
            job.progress = payload.progress
            job.current_stage = payload.stage
            self.jobs.add_event(
                job,
                "progress",
                payload.message,
                metadata={"progress": payload.progress, **payload.metadata},
            )
        job.heartbeat_at = datetime.now(UTC)
        await self.session.execute(
            text("update render_workers set last_seen_at = now() where id = :worker_id"),
            {"worker_id": worker_id},
        )
        await self.session.commit()
        return {"cancel_requested": False, "status": job.status.value, "progress": job.progress}

    async def cancellation_status(self, worker_id: uuid.UUID, job_id: uuid.UUID) -> dict[str, object]:
        job = await self._owned_job(worker_id, job_id, lock=False)
        return {"cancel_requested": job.cancellation_requested_at is not None}

    async def asset_url(
        self, worker_id: uuid.UUID, job_id: uuid.UUID, key: str
    ) -> str:
        """Return a short-lived URL only for an asset owned by the claimed job's tenant."""
        job = await self._owned_job(worker_id, job_id, lock=False)
        selected = {
            str(job.config.get("model_asset_key") or ""),
            str(job.config.get("hdri_asset_key") or ""),
        }
        if key not in selected or not key:
            raise ApiError(404, "asset_not_selected", "This asset is not selected by the job.")
        return await AssetService(self.session, self.settings).signed_url_for_organization(
            job.organization_id, key
        )

    async def failed(
        self, worker_id: uuid.UUID, job_id: uuid.UUID, payload: WorkerFailure
    ) -> dict[str, object]:
        job = await self._owned_job(worker_id, job_id)
        service = JobService(self.session, self.settings)
        job.failure_code = payload.code
        job.failure_message = payload.message
        cancelled = payload.code == "cancelled_by_user"
        retry = payload.retryable and not cancelled and job.attempt_count < job.max_attempts
        await service.transition(
            job,
            JobStatus.cancelled if cancelled else JobStatus.failed,
            stage="cancelled" if cancelled else "failed",
            message=payload.message,
            metadata={"code": payload.code, "retryable": retry},
        )
        await self.session.execute(
            text(
                """
                update render_workers set status = 'healthy', current_job_id = null, last_seen_at = now()
                where id = :worker_id
                """
            ),
            {"worker_id": worker_id},
        )
        if not cancelled:
            await self.session.execute(
                text(
                    """
                    insert into usage_events (
                      organization_id, job_id, event_type, gpu_seconds, metadata
                    ) values (:org_id, :job_id, 'gpu_failure', :gpu_seconds, '{}'::jsonb)
                    """
                ),
                {
                    "org_id": job.organization_id,
                    "job_id": job.id,
                    "gpu_seconds": payload.gpu_seconds,
                },
            )
        await self.session.commit()
        if retry:
            await service.retry(
                __import__("app.api.dependencies", fromlist=["Principal"]).Principal(
                    user_id=job.created_by,
                    email=None,
                    organization_id=job.organization_id,
                    role=__import__("app.db.models", fromlist=["OrgRole"]).OrgRole.engineer,
                ),
                job.id,
            )
        return {"status": job.status.value, "retry_scheduled": retry}

    async def complete(
        self, worker_id: uuid.UUID, job_id: uuid.UUID, output_directory: str, gpu_seconds: float
    ) -> dict[str, object]:
        job = await self._owned_job(worker_id, job_id)
        if job.status not in {
            JobStatus.queued,
            JobStatus.rendering,
            JobStatus.processing_annotations,
        }:
            raise ApiError(409, "job_not_finalizable", "Job must be claimed by a worker first.")
        job.status = JobStatus.processing_annotations
        job.current_stage = "processing_annotations"
        job.progress = max(job.progress, 90)
        root = Path(self.settings.worker_output_root).resolve()
        directory = Path(output_directory).resolve()
        if root != directory and root not in directory.parents:
            raise ApiError(422, "unsafe_output_path", "Worker output is outside the configured root.")
        await self.session.commit()
        dataset = await DatasetService(self.session, self.settings).finalize_local_package(
            job, directory, gpu_seconds
        )
        await self.session.execute(
            text(
                """
                update render_workers set status = 'healthy', current_job_id = null, last_seen_at = now()
                where id = :worker_id
                """
            ),
            {"worker_id": worker_id},
        )
        await self.session.commit()
        return {"job_id": job.id, "dataset_id": dataset.id, "status": "complete"}
