import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import Principal
from app.api.errors import ApiError
from app.core.config import Settings
from app.db.models import OrgRole
from app.storage.supabase import StorageError, SupabaseStorage

ALLOWED_REFERENCE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


class DefectService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.storage = SupabaseStorage(settings)

    async def add_reference(
        self,
        principal: Principal,
        profile_id: uuid.UUID,
        content: bytes,
        content_type: str,
    ) -> dict[str, object]:
        if principal.role not in {OrgRole.owner, OrgRole.administrator}:
            raise ApiError(
                403,
                "insufficient_role",
                "Only owners and administrators can upload defect references.",
            )
        if content_type not in ALLOWED_REFERENCE_TYPES:
            raise ApiError(422, "unsupported_image_type", "Reference must be PNG or JPEG.")
        if not content or len(content) > 10 * 1024 * 1024:
            raise ApiError(422, "reference_size_limit", "Reference must be between 1 byte and 10 MB.")
        exists = (
            await self.session.execute(
                text(
                    """
                    select 1 from defect_profiles
                    where id = :profile_id and organization_id = :org_id and not is_system
                    """
                ),
                {"profile_id": profile_id, "org_id": principal.organization_id},
            )
        ).scalar_one_or_none()
        if exists is None:
            raise ApiError(404, "defect_profile_not_found", "Organization defect profile not found.")
        object_path = (
            f"{principal.organization_id}/{profile_id}/"
            f"{uuid.uuid4()}{ALLOWED_REFERENCE_TYPES[content_type]}"
        )
        try:
            await self.storage.upload_bytes(
                self.settings.defect_reference_bucket,
                object_path,
                content,
                content_type,
            )
            row = (
                await self.session.execute(
                    text(
                        """
                        update defect_profiles
                        set reference_image_paths = array_append(reference_image_paths, :path)
                        where id = :profile_id and organization_id = :org_id
                        returning id, reference_image_paths
                        """
                    ),
                    {
                        "path": object_path,
                        "profile_id": profile_id,
                        "org_id": principal.organization_id,
                    },
                )
            ).mappings().one()
            await self.session.commit()
            return dict(row)
        except Exception:
            await self.session.rollback()
            try:
                await self.storage.remove(self.settings.defect_reference_bucket, [object_path])
            except StorageError:
                pass
            raise
