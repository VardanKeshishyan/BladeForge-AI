import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GenerationJob, JobEvent, JobStatus


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, organization_id: uuid.UUID, job_id: uuid.UUID, *, lock: bool = False) -> GenerationJob | None:
        statement = select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.organization_id == organization_id,
        )
        if lock:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def list(
        self,
        organization_id: uuid.UUID,
        *,
        status: JobStatus | None,
        search: str | None,
        sort: str,
        page: int,
        page_size: int,
    ) -> tuple[Sequence[GenerationJob], int]:
        filters = [GenerationJob.organization_id == organization_id]
        if status is not None:
            filters.append(GenerationJob.status == status)
        if search:
            escaped = search.replace("%", r"\%").replace("_", r"\_")
            filters.append(
                or_(
                    GenerationJob.name.ilike(f"%{escaped}%", escape="\\"),
                    GenerationJob.dataset_name.ilike(f"%{escaped}%", escape="\\"),
                )
            )
        total = int(
            await self.session.scalar(select(func.count()).select_from(GenerationJob).where(*filters))
            or 0
        )
        order_by: dict[str, ColumnElement[Any]] = {
            "created_at": GenerationJob.created_at.desc(),
            "name": GenerationJob.name.asc(),
            "status": GenerationJob.status.asc(),
            "progress": GenerationJob.progress.desc(),
        }
        order = order_by[sort]
        statement: Select[tuple[GenerationJob]] = (
            select(GenerationJob)
            .where(*filters)
            .order_by(order, GenerationJob.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return (await self.session.scalars(statement)).all(), total

    async def by_idempotency_key(
        self, organization_id: uuid.UUID, key: str
    ) -> GenerationJob | None:
        return await self.session.scalar(
            select(GenerationJob).where(
                GenerationJob.organization_id == organization_id,
                GenerationJob.idempotency_key == key,
            )
        )

    def add(self, job: GenerationJob) -> None:
        self.session.add(job)

    def add_event(
        self,
        job: GenerationJob,
        event_type: str,
        message: str,
        *,
        created_by: uuid.UUID | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.session.add(
            JobEvent(
                job_id=job.id,
                organization_id=job.organization_id,
                event_type=event_type,
                message=message,
                metadata_=metadata or {},
                created_by=created_by,
            )
        )
