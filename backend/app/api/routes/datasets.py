import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import Principal, api_key_principal, current_principal
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.services.datasets import DatasetService

router = APIRouter(prefix="/datasets", tags=["datasets"])
external_router = APIRouter(prefix="/external/datasets", tags=["external-api"])


@router.get("")
async def list_datasets(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return await DatasetService(session, settings).list(principal, page, page_size)


@external_router.get("")
async def external_list_datasets(
    principal: Annotated[Principal, Depends(api_key_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return await DatasetService(session, settings).list(principal, page, page_size)


@router.get("/{dataset_id}")
async def dataset_detail(
    dataset_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await DatasetService(session, settings).detail(principal, dataset_id)


@router.post("/{dataset_id}/download")
async def dataset_download(
    dataset_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return {"url": await DatasetService(session, settings).signed_archive(principal, dataset_id)}


@external_router.post("/{dataset_id}/download")
async def external_dataset_download(
    dataset_id: uuid.UUID,
    principal: Annotated[Principal, Depends(api_key_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return {"url": await DatasetService(session, settings).signed_archive(principal, dataset_id)}


@router.post("/{dataset_id}/files/{file_id}/download")
async def dataset_file_download(
    dataset_id: uuid.UUID,
    file_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return {
        "url": await DatasetService(session, settings).signed_file(
            principal, dataset_id, file_id
        )
    }


@router.post("/{dataset_id}/preview")
async def dataset_preview(
    dataset_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    dataset = await DatasetService(session, settings).get(principal, dataset_id)
    if not dataset.preview_storage_path:
        return {"url": None}
    return {
        "url": await DatasetService(session, settings).storage.signed_url(
            settings.dataset_bucket, dataset.preview_storage_path
        )
    }

