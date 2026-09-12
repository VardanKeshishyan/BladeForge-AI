import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import Principal, current_principal
from app.api.errors import ApiError
from app.core.config import Settings, get_settings
from app.db.models import OrgRole
from app.db.session import get_session
from app.schemas.organizations import ApiKeyCreate
from app.schemas.turbine import DEFECT_PART_MATRIX, RENDERER_SUPPORTED_DEFECTS, DefectId
from app.services.assets import (
    ENVIRONMENT_ASSET,
    MAX_ENVIRONMENT_BYTES,
    MAX_MODEL_BYTES,
    MODEL_ASSET,
    AssetKind,
    AssetService,
    local_asset_path,
)
from app.services.defects import DefectService
from app.services.resources import ResourceService

router = APIRouter(tags=["resources"])


class DefectProfileWrite(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    severity_levels: list[str] = Field(min_length=1, max_length=10)
    surface_parameters: dict[str, object]
    defect_type: DefectId = "leading_edge_erosion"


@router.get("/defect-profiles")
async def list_defect_profiles(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    rows = (
        await session.execute(
            text(
                """
                select id, organization_id, name, defect_type, description, severity_levels,
                       surface_parameters, reference_image_paths, is_system, created_at, updated_at
                from defect_profiles
                where is_system or organization_id = :org_id
                order by is_system desc, created_at
                """
            ),
            {"org_id": principal.organization_id},
        )
    ).mappings()
    return {"items": [dict(row) for row in rows]}


@router.post("/defect-profiles", status_code=201)
async def create_defect_profile(
    payload: DefectProfileWrite,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    if principal.role not in {OrgRole.owner, OrgRole.administrator}:
        raise ApiError(403, "insufficient_role", "Only owners and administrators can manage defect profiles.")
    row = (
        await session.execute(
            text(
                """
                insert into defect_profiles (
                  id, organization_id, created_by, name, defect_type, description,
                  severity_levels, surface_parameters, is_system
                ) values (
                  :id, :org_id, :created_by, :name, :defect_type, :description,
                  :severity_levels, cast(:surface_parameters as jsonb), false
                )
                returning id, organization_id, name, defect_type, description, severity_levels,
                          surface_parameters, reference_image_paths, is_system, created_at, updated_at
                """
            ),
            {
                "id": uuid.uuid4(),
                "org_id": principal.organization_id,
                "created_by": principal.user_id,
                "name": payload.name.strip(),
                "defect_type": payload.defect_type,
                "description": payload.description,
                "severity_levels": payload.severity_levels,
                "surface_parameters": __import__("json").dumps(payload.surface_parameters),
            },
        )
    ).mappings().one()
    await session.commit()
    return dict(row)


@router.patch("/defect-profiles/{profile_id}")
async def update_defect_profile(
    profile_id: uuid.UUID,
    payload: DefectProfileWrite,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    if principal.role not in {OrgRole.owner, OrgRole.administrator}:
        raise ApiError(403, "insufficient_role", "Only owners and administrators can manage defect profiles.")
    row = (
        await session.execute(
            text(
                """
                update defect_profiles
                set name = :name, defect_type = :defect_type, description = :description,
                    severity_levels = :severity_levels,
                    surface_parameters = cast(:surface_parameters as jsonb)
                where id = :id and organization_id = :org_id and not is_system
                returning id, organization_id, name, defect_type, description, severity_levels,
                          surface_parameters, reference_image_paths, is_system, created_at, updated_at
                """
            ),
            {
                "id": profile_id,
                "org_id": principal.organization_id,
                "name": payload.name.strip(),
                "defect_type": payload.defect_type,
                "description": payload.description,
                "severity_levels": payload.severity_levels,
                "surface_parameters": __import__("json").dumps(payload.surface_parameters),
            },
        )
    ).mappings().first()
    if row is None:
        raise ApiError(404, "defect_profile_not_found", "Organization defect profile not found.")
    await session.commit()
    return dict(row)


@router.delete("/defect-profiles/{profile_id}", status_code=204)
async def delete_defect_profile(
    profile_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    if principal.role not in {OrgRole.owner, OrgRole.administrator}:
        raise ApiError(403, "insufficient_role", "Only owners and administrators can manage defect profiles.")
    result = await session.execute(
        text(
            """
            delete from defect_profiles
            where id = :id and organization_id = :org_id and not is_system
            """
        ),
        {"id": profile_id, "org_id": principal.organization_id},
    )
    if getattr(result, "rowcount", 0) == 0:
        raise ApiError(404, "defect_profile_not_found", "Organization defect profile not found.")
    await session.commit()


@router.post("/defect-profiles/{profile_id}/references", status_code=201)
async def upload_defect_reference(
    profile_id: uuid.UUID,
    reference: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    content = await reference.read(10 * 1024 * 1024 + 1)
    return await DefectService(session, settings).add_reference(
        principal,
        profile_id,
        content,
        reference.content_type or "application/octet-stream",
    )


@router.get("/api-keys")
async def list_api_keys(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    if principal.role not in {OrgRole.owner, OrgRole.administrator}:
        raise ApiError(403, "insufficient_role", "Only owners and administrators can view API keys.")
    rows = (
        await session.execute(
            text(
                """
                select id, name, key_prefix, status, expires_at, last_used_at, revoked_at, created_at
                from api_keys where organization_id = :org_id order by created_at desc
                """
            ),
            {"org_id": principal.organization_id},
        )
    ).mappings()
    return {"items": [dict(row) for row in rows]}


@router.post("/api-keys", status_code=201)
async def create_api_key(
    payload: ApiKeyCreate,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await ResourceService(session, settings).create_api_key(principal, payload)


@router.post("/api-keys/{key_id}/revoke")
async def revoke_api_key(
    key_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await ResourceService(session, settings).revoke_api_key(principal, key_id)


@router.get("/usage/summary")
async def usage_summary(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await ResourceService(session, settings).usage_summary(principal)


@router.get("/usage/jobs/{job_id}")
async def job_usage(
    job_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await ResourceService(session, get_settings()).job_usage(principal, job_id)


@router.get("/overview/summary")
async def overview_summary(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return await ResourceService(session, settings).overview_summary(principal)


@router.get("/render-workers")
async def render_worker_status(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return {"items": await ResourceService(session, settings).worker_status(principal)}


@router.get("/capabilities")
async def capabilities(settings: Annotated[Settings, Depends(get_settings)]):
    """What this deployment can actually produce.

    The generation UI drives its enabled and disabled states from this, so a control is
    never shown as working when the renderer behind it cannot deliver.
    """
    engine = settings.render_engine_version
    renderer_defects = sorted(RENDERER_SUPPORTED_DEFECTS) if engine == "v2" else ["leading_edge_erosion"]
    return {
        # Retained exactly as before: existing clients read this key.
        "supported_defects": renderer_defects,
        "annotation_formats": ["coco_json", "yolo_v8"],
        "email_invitations": settings.email_enabled,
        "runpod": settings.runpod_enabled,
        "webhooks": False,
        "billing": False,
        "renderer": {
            "engine": engine,
            "backend": "Blender Cycles" if engine == "v2" else "Blender Eevee (legacy path)",
            "description": (
                "Path-traced rendering with physically based materials, image-based "
                "lighting from the selected environment, and defect geometry driven by "
                "the painted regions."
                if engine == "v2"
                else "The shipped renderer. It produces leading-edge erosion on the built-in "
                "blade with preset lighting, and ignores environment, weather, camera "
                "pose and multi-defect selections."
            ),
            "gpu_required": engine == "v2",
            "relative_cost": 6.0 if engine == "v2" else 1.0,
            "supported_defects": renderer_defects,
            "unsupported_defects": sorted(set(DEFECT_PART_MATRIX) - set(renderer_defects)),
            "supports_environments": engine == "v2",
            "supports_custom_models": engine == "v2",
            # Painting is a viewport feature that always works; the mask is only consumed
            # by the v2 renderer. Advertise it as available so customers can prepare jobs.
            "supports_region_painting": True,
            "supports_all_angles": engine == "v2",
            "fallback": (
                "None. This deployment renders every job on the v2 path."
                if engine == "v2"
                else "Selections beyond the legacy feature set are stored with the job. "
                "Set RENDER_ENGINE_VERSION=v2 on the API and worker, and point the worker "
                "at render_engine/v2/main.py, to produce multi-defect Cycles output."
            ),
        },
        "asset_import": {
            "model_formats": ["fbx", "obj"],
            "environment_formats": ["exr", "hdr"],
            "max_model_mb": MAX_MODEL_BYTES // (1024 * 1024),
            "max_environment_mb": MAX_ENVIRONMENT_BYTES // (1024 * 1024),
        },
    }


class AssetUploadResponse(BaseModel):
    key: str
    kind: str
    format: str
    filename: str
    size_bytes: int
    url: str


async def _upload_asset(
    spec: AssetKind,
    upload: UploadFile,
    licence_confirmed: bool,
    principal: Principal,
    session: AsyncSession,
    settings: Settings,
) -> AssetUploadResponse:
    service = AssetService(session, settings)
    # Read one byte past the limit so an oversized file is refused rather than truncated.
    content = await upload.read(spec.max_bytes + 1)
    record = await service.upload(
        principal,
        spec,
        content,
        upload.filename or "upload",
        licence_confirmed,
    )
    url = await service.signed_url(principal, str(record["key"]))
    return AssetUploadResponse(**record, url=url)  # type: ignore[arg-type]


@router.post("/assets/models", status_code=201)
async def upload_model_asset(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    model: Annotated[UploadFile, File()],
    licence_confirmed: Annotated[bool, Form()] = False,
) -> AssetUploadResponse:
    return await _upload_asset(MODEL_ASSET, model, licence_confirmed, principal, session, settings)


@router.post("/assets/environments", status_code=201)
async def upload_environment_asset(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    environment: Annotated[UploadFile, File()],
    licence_confirmed: Annotated[bool, Form()] = False,
) -> AssetUploadResponse:
    return await _upload_asset(
        ENVIRONMENT_ASSET, environment, licence_confirmed, principal, session, settings
    )


@router.get("/assets/url")
async def asset_signed_url(
    key: str,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    return {"url": await AssetService(session, settings).signed_url(principal, key)}


@router.get("/assets/local/{asset_path:path}", include_in_schema=False)
async def local_asset(asset_path: str, settings: Annotated[Settings, Depends(get_settings)]):
    if settings.environment != "development":
        raise ApiError(404, "asset_not_found", "Asset not found.")
    path = local_asset_path(settings, asset_path)
    if not path.is_file():
        raise ApiError(404, "asset_not_found", "Asset not found.")
    media_type = "application/octet-stream"
    suffix = Path(asset_path).suffix.lower()
    if suffix == ".obj":
        media_type = "text/plain"
    return FileResponse(path, media_type=media_type)
