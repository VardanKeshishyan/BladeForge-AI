import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import Principal
from app.api.errors import ApiError
from app.auth.api_keys import generate_api_key, hash_api_key
from app.core.config import Settings
from app.db.models import OrgRole
from app.schemas.organizations import ApiKeyCreate


class ResourceService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def create_api_key(
        self, principal: Principal, payload: ApiKeyCreate
    ) -> dict[str, object]:
        if principal.role not in {OrgRole.owner, OrgRole.administrator}:
            raise ApiError(403, "insufficient_role", "Only owners and administrators can create API keys.")
        raw_key, prefix = generate_api_key()
        row = (
            await self.session.execute(
                text(
                    """
                    insert into api_keys (
                      id, organization_id, created_by, name, key_prefix, key_hash, expires_at
                    ) values (
                      :id, :org_id, :created_by, :name, :prefix, :key_hash, :expires_at
                    )
                    returning id, name, key_prefix, status, expires_at, last_used_at, created_at
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "org_id": principal.organization_id,
                    "created_by": principal.user_id,
                    "name": payload.name.strip(),
                    "prefix": prefix,
                    "key_hash": hash_api_key(raw_key, self.settings.api_key_pepper),
                    "expires_at": payload.expires_at,
                },
            )
        ).mappings().one()
        await self.session.commit()
        return {**dict(row), "key": raw_key}

    async def revoke_api_key(
        self, principal: Principal, key_id: uuid.UUID
    ) -> dict[str, object]:
        if principal.role not in {OrgRole.owner, OrgRole.administrator}:
            raise ApiError(403, "insufficient_role", "Only owners and administrators can revoke API keys.")
        row = (
            await self.session.execute(
                text(
                    """
                    update api_keys
                    set status = 'revoked', revoked_at = now(), revoked_by = :user_id
                    where id = :key_id and organization_id = :org_id and status = 'active'
                    returning id, name, key_prefix, status, expires_at, last_used_at, created_at
                    """
                ),
                {
                    "user_id": principal.user_id,
                    "key_id": key_id,
                    "org_id": principal.organization_id,
                },
            )
        ).mappings().first()
        if row is None:
            raise ApiError(404, "api_key_not_found", "Active API key not found.")
        await self.session.commit()
        return dict(row)

    async def usage_summary(self, principal: Principal) -> dict[str, object]:
        row = (
            await self.session.execute(
                text(
                    """
                    select
                      coalesce(sum(image_count), 0)::bigint as image_count,
                      coalesce(sum(gpu_seconds) filter (where event_type = 'gpu_success'), 0)::float as successful_gpu_seconds,
                      coalesce(sum(gpu_seconds) filter (where event_type = 'gpu_failure'), 0)::float as failed_gpu_seconds,
                      count(*) filter (where event_type = 'render_attempt')::bigint as render_attempts,
                      coalesce(sum(storage_bytes), 0)::bigint as storage_bytes,
                      count(*) filter (where event_type = 'dataset_download')::bigint as dataset_downloads
                    from usage_events
                    where organization_id = :org_id
                    """
                ),
                {"org_id": principal.organization_id},
            )
        ).mappings().one()
        return {**dict(row), "billing_available": False}

    async def job_usage(
        self, principal: Principal, job_id: uuid.UUID
    ) -> dict[str, object]:
        job_exists = (
            await self.session.execute(
                text(
                    """
                    select 1 from generation_jobs
                    where id = :job_id and organization_id = :org_id
                    """
                ),
                {"job_id": job_id, "org_id": principal.organization_id},
            )
        ).scalar_one_or_none()
        if job_exists is None:
            raise ApiError(404, "job_not_found", "Generation job not found.")
        row = (
            await self.session.execute(
                text(
                    """
                    select
                      coalesce(sum(image_count), 0)::bigint as image_count,
                      coalesce(sum(gpu_seconds) filter (
                        where event_type = 'gpu_success'
                      ), 0)::float as successful_gpu_seconds,
                      coalesce(sum(gpu_seconds) filter (
                        where event_type = 'gpu_failure'
                      ), 0)::float as failed_gpu_seconds,
                      count(*) filter (
                        where event_type = 'render_attempt'
                      )::bigint as render_attempts,
                      coalesce(sum(storage_bytes), 0)::bigint as storage_bytes
                    from usage_events
                    where job_id = :job_id and organization_id = :org_id
                    """
                ),
                {"job_id": job_id, "org_id": principal.organization_id},
            )
        ).mappings().one()
        return dict(row)

    async def overview_summary(self, principal: Principal) -> dict[str, object]:
        row = (
            await self.session.execute(
                text(
                    """
                    select
                      (select count(*) from generation_jobs where organization_id = :org_id) as total_jobs,
                      (select count(*) from generation_jobs where organization_id = :org_id and status in ('awaiting_worker','queued','rendering','processing_annotations')) as active_jobs,
                      (select count(*) from generation_jobs where organization_id = :org_id and status = 'complete') as completed_jobs,
                      (select count(*) from datasets where organization_id = :org_id and status = 'available') as total_datasets,
                      (select coalesce(sum(image_count), 0) from datasets where organization_id = :org_id and status = 'available') as total_images,
                      (select coalesce(sum(gpu_seconds), 0)::float from usage_events where organization_id = :org_id) as gpu_seconds,
                      (select coalesce(sum(file_size_bytes), 0) from datasets where organization_id = :org_id and status = 'available') as storage_bytes
                    """
                ),
                {"org_id": principal.organization_id},
            )
        ).mappings().one()
        return dict(row)

    async def worker_status(self, principal: Principal) -> list[dict[str, object]]:
        rows = (
            await self.session.execute(
                text(
                    """
                    select id, name, adapter_type, status, capabilities, current_job_id,
                           last_seen_at, registered_at
                    from render_workers
                    where organization_id = :org_id or organization_id is null
                    order by name
                    """
                ),
                {"org_id": principal.organization_id},
            )
        ).mappings()
        return [dict(row) for row in rows]
