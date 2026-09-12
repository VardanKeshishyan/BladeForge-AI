import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import verify_worker_secret
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.schemas.jobs import WorkerFailure, WorkerProgress
from app.services.workers import WorkerService

router = APIRouter(
    prefix="/workers",
    tags=["render-workers"],
    dependencies=[Depends(verify_worker_secret)],
)


class WorkerRegistration(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    organization_id: uuid.UUID | None = None
    capabilities: dict[str, object] = Field(default_factory=dict)


class CompletionPayload(BaseModel):
    output_directory: str = Field(min_length=1, max_length=1000)
    gpu_seconds: float = Field(ge=0)


@router.post("/register", status_code=201)
async def register_worker(
    payload: WorkerRegistration,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await WorkerService(session, settings).register(
        payload.name, payload.organization_id, payload.capabilities
    )


@router.post("/{worker_id}/heartbeat")
async def heartbeat(
    worker_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await WorkerService(session, settings).heartbeat(worker_id)


@router.post("/{worker_id}/claim")
async def claim_job(
    worker_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return {"job": await WorkerService(session, settings).claim(worker_id)}


@router.post("/{worker_id}/jobs/{job_id}/progress")
async def report_progress(
    worker_id: uuid.UUID,
    job_id: uuid.UUID,
    payload: WorkerProgress,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await WorkerService(session, settings).progress(worker_id, job_id, payload)


@router.get("/{worker_id}/jobs/{job_id}/cancellation")
async def cancellation_status(
    worker_id: uuid.UUID,
    job_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await WorkerService(session, settings).cancellation_status(worker_id, job_id)


@router.get("/{worker_id}/jobs/{job_id}/assets/url")
async def selected_asset_url(
    worker_id: uuid.UUID,
    job_id: uuid.UUID,
    key: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return {"url": await WorkerService(session, settings).asset_url(worker_id, job_id, key)}


@router.post("/{worker_id}/jobs/{job_id}/failed")
async def report_failure(
    worker_id: uuid.UUID,
    job_id: uuid.UUID,
    payload: WorkerFailure,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await WorkerService(session, settings).failed(worker_id, job_id, payload)


@router.post("/{worker_id}/jobs/{job_id}/complete")
async def complete_job(
    worker_id: uuid.UUID,
    job_id: uuid.UUID,
    payload: CompletionPayload,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await WorkerService(session, settings).complete(
        worker_id, job_id, payload.output_directory, payload.gpu_seconds
    )
