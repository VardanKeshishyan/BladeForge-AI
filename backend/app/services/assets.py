"""Customer asset import: 3D turbine models and environment maps.

Uploads are validated on their actual bytes rather than on the browser-declared content
type, which a client controls and can therefore lie about. Files land in a private bucket
under the organisation's own prefix and are only ever handed back through short-lived
signed URLs, so one organisation cannot reach another's assets.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import Principal
from app.api.errors import ApiError
from app.core.config import Settings
from app.db.models import OrgRole
from app.storage.supabase import StorageError, SupabaseStorage

#: Uploads are capped well below what a browser can comfortably load anyway. A 4K EXR is
#: around 100 MB, which is why environment maps get more headroom than meshes.
MAX_MODEL_BYTES = 96 * 1024 * 1024
MAX_ENVIRONMENT_BYTES = 160 * 1024 * 1024


@dataclass(frozen=True)
class AssetKind:
    kind: str
    extensions: tuple[str, ...]
    max_bytes: int


MODEL_ASSET = AssetKind("model", (".fbx", ".obj"), MAX_MODEL_BYTES)
ENVIRONMENT_ASSET = AssetKind("environment", (".exr", ".hdr"), MAX_ENVIRONMENT_BYTES)


def local_asset_root(settings: Settings) -> Path:
    """Local development fallback for customer assets when the Supabase bucket is absent."""
    return Path(settings.worker_output_root).resolve().parent / "customer-assets"


def local_asset_path(settings: Settings, key: str) -> Path:
    root = local_asset_root(settings)
    candidate = (root / key).resolve()
    if root not in candidate.parents:
        raise ApiError(404, "asset_not_found", "Asset not found.")
    return candidate


def local_asset_url(settings: Settings, key: str) -> str:
    return f"http://127.0.0.1:{settings.api_port}/v1/assets/local/{key}"


def detect_model_format(content: bytes, filename: str) -> str:
    """Identify an FBX or OBJ from its content.

    Binary FBX opens with a fixed magic string. ASCII FBX and OBJ are text, so they are
    recognised from the keywords that must appear near the top of a valid file.
    """
    if content.startswith(b"Kaydara FBX Binary"):
        return "fbx"

    head = content[:8192]
    try:
        text_head = head.decode("utf-8", errors="ignore")
    except Exception:  # pragma: no cover - decode with errors="ignore" cannot raise
        text_head = ""

    lowered = text_head.lower()
    if "fbx" in lowered and ("fbxheaderextension" in lowered.replace(" ", "")):
        return "fbx"

    # An OBJ is a plain list of vertices, faces, normals and groups.
    obj_markers = ("v ", "vt ", "vn ", "f ", "o ", "g ", "mtllib ", "usemtl ")
    lines = [line.strip() for line in text_head.splitlines() if line.strip()]
    meaningful = [line for line in lines if not line.startswith("#")]
    if meaningful and any(line.startswith(obj_markers) for line in meaningful[:200]):
        return "obj"

    raise ApiError(
        422,
        "unsupported_model_format",
        f"{filename} is not a readable FBX or OBJ file. "
        "Export the model as binary FBX or Wavefront OBJ and try again.",
    )


def detect_environment_format(content: bytes, filename: str) -> str:
    """Identify an OpenEXR or Radiance HDR from its magic bytes."""
    if content.startswith(b"\x76\x2f\x31\x01"):
        return "exr"
    if content.startswith(b"#?RADIANCE") or content.startswith(b"#?RGBE"):
        return "hdr"
    raise ApiError(
        422,
        "unsupported_environment_format",
        f"{filename} is not a readable EXR or Radiance HDR file. "
        "Environment maps must be a 32-bit equirectangular EXR or HDR.",
    )


def _reject_traversal(filename: str) -> str:
    """Strip any path a client tried to smuggle in through the filename."""
    cleaned = filename.replace("\\", "/").split("/")[-1].strip()
    if not cleaned or cleaned in {".", ".."}:
        raise ApiError(422, "invalid_filename", "The upload must have a file name.")
    if len(cleaned) > 180:
        cleaned = cleaned[-180:]
    return cleaned


class AssetService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.storage = SupabaseStorage(settings)

    def _require_upload_role(self, principal: Principal) -> None:
        if principal.role == OrgRole.viewer:
            raise ApiError(
                403,
                "insufficient_role",
                "Viewers cannot upload assets. Ask an owner or administrator.",
            )

    async def upload(
        self,
        principal: Principal,
        spec: AssetKind,
        content: bytes,
        filename: str,
        licence_confirmed: bool,
    ) -> dict[str, object]:
        self._require_upload_role(principal)

        if not licence_confirmed:
            raise ApiError(
                422,
                "licence_not_confirmed",
                "Confirm that your organisation holds the rights to use this asset. "
                "BladeForge does not claim ownership of files you upload.",
            )

        safe_name = _reject_traversal(filename)
        extension = "." + safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
        if extension not in spec.extensions:
            raise ApiError(
                422,
                "unsupported_extension",
                f"Expected one of {', '.join(spec.extensions)} but received '{extension or 'no extension'}'.",
            )

        if not content:
            raise ApiError(422, "empty_upload", "The uploaded file is empty.")
        if len(content) > spec.max_bytes:
            raise ApiError(
                422,
                "asset_size_limit",
                f"{safe_name} is {len(content) // (1024 * 1024)} MB. "
                f"The limit for a {spec.kind} is {spec.max_bytes // (1024 * 1024)} MB.",
            )

        detected = (
            detect_model_format(content, safe_name)
            if spec.kind == "model"
            else detect_environment_format(content, safe_name)
        )
        if not extension.endswith(detected):
            raise ApiError(
                422,
                "content_does_not_match_extension",
                f"{safe_name} is named '{extension}' but its contents are {detected.upper()}. "
                "Rename the file to match its real format.",
            )

        object_path = f"{principal.organization_id}/{spec.kind}s/{uuid.uuid4()}{extension}"
        try:
            await self.storage.upload_bytes(
                self.settings.customer_asset_bucket,
                object_path,
                content,
                "application/octet-stream",
            )
        except StorageError as error:
            message = str(error)
            if self.settings.environment == "development" and (
                "Bucket not found" in message or "NoSuchBucket" in message
            ):
                path = local_asset_path(self.settings, object_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            else:
                raise ApiError(502, "asset_upload_failed", message) from error

        return {
            "key": object_path,
            "kind": spec.kind,
            "format": detected,
            "filename": safe_name,
            "size_bytes": len(content),
        }

    async def signed_url(self, principal: Principal, key: str, expires_in: int = 900) -> str:
        """Hand back a short-lived URL, but only for a key inside the caller's own prefix."""
        return await self.signed_url_for_organization(
            principal.organization_id, key, expires_in=expires_in
        )

    async def signed_url_for_organization(
        self, organization_id: uuid.UUID, key: str, *, expires_in: int = 900
    ) -> str:
        """Resolve an asset for a trusted worker while preserving tenant isolation."""
        prefix = f"{organization_id}/"
        if not key.startswith(prefix) or ".." in key:
            raise ApiError(404, "asset_not_found", "Asset not found in this organization.")
        if local_asset_path(self.settings, key).is_file():
            return local_asset_url(self.settings, key)
        try:
            return await self.storage.signed_url(
                self.settings.customer_asset_bucket, key, expires_in
            )
        except StorageError as error:
            raise ApiError(502, "asset_url_failed", str(error)) from error
