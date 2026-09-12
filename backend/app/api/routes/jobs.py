import math
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import Principal, api_key_principal, current_principal
from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.db.models import JobStatus
from app.db.session import get_session
from app.repositories.jobs import JobRepository
from app.schemas.jobs import JobCreate, JobList, JobRead
from app.services.jobs import JobService

router = APIRouter(prefix="/jobs", tags=["jobs"])
external_router = APIRouter(prefix="/external/jobs", tags=["external-api"])


async def create_job_operation(
    payload: JobCreate,
    idempotency_key: str,
    principal: Principal,
    session: AsyncSession,
    settings: Settings,
):
    return await JobService(session, settings).create(principal, payload, idempotency_key)


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
):
    return await create_job_operation(payload, idempotency_key, principal, session, settings)


@external_router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def external_create_job(
    payload: JobCreate,
    principal: Annotated[Principal, Depends(api_key_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
):
    return await create_job_operation(payload, idempotency_key, principal, session, settings)


@router.get("", response_model=JobList)
async def list_jobs(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    sort: Literal["created_at", "name", "status", "progress"] = "created_at",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
):
    items, total = await JobRepository(session).list(
        principal.organization_id,
        status=status_filter,
        search=search,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return JobList(
        items=[JobRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        pages=math.ceil(total / page_size),
    )


async def get_job_or_404(
    session: AsyncSession, principal: Principal, job_id: uuid.UUID
):
    job = await JobRepository(session).get(principal.organization_id, job_id)
    if job is None:
        raise ApiError(404, "job_not_found", "Generation job not found.")
    return job


@router.get("/{job_id}", response_model=JobRead)
async def get_job(
    job_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await get_job_or_404(session, principal, job_id)


@external_router.get("/{job_id}", response_model=JobRead)
async def external_get_job(
    job_id: uuid.UUID,
    principal: Annotated[Principal, Depends(api_key_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await get_job_or_404(session, principal, job_id)


@router.get("/{job_id}/events")
async def job_events(
    job_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    await get_job_or_404(session, principal, job_id)
    rows = (
        await session.execute(
            text(
                """
                select id, event_type, message, metadata, created_by, created_at
                from job_events
                where job_id = :job_id and organization_id = :org_id
                order by created_at
                """
            ),
            {"job_id": job_id, "org_id": principal.organization_id},
        )
    ).mappings()
    return {"items": [dict(row) for row in rows]}


@router.post("/{job_id}/cancel", response_model=JobRead)
async def cancel_job(
    job_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await JobService(session, settings).cancel(principal, job_id)


@router.post("/{job_id}/retry", response_model=JobRead)
async def retry_job(
    job_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await JobService(session, settings).retry(principal, job_id)


@router.post("/{job_id}/duplicate", response_model=JobRead, status_code=201)
async def duplicate_job(
    job_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)],
):
    return await JobService(session, settings).duplicate(principal, job_id, idempotency_key)

