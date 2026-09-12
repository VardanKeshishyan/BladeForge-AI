from pathlib import Path
from urllib.parse import quote

import httpx

from app.core.config import Settings


class StorageError(Exception):
    pass


class SupabaseStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = f"{settings.supabase_url.rstrip('/')}/storage/v1"
        self.headers = {
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "apikey": settings.supabase_service_role_key,
        }

    async def upload(
        self,
        bucket: str,
        object_path: str,
        local_path: Path,
        content_type: str,
    ) -> None:
        url = f"{self.base_url}/object/{quote(bucket)}/{quote(object_path, safe='/')}"
        headers = {**self.headers, "Content-Type": content_type, "x-upsert": "false"}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, headers=headers, content=local_path.read_bytes())
        if response.status_code >= 300:
            raise StorageError(
                f"Storage upload failed with status {response.status_code}: {response.text[:500]}"
            )

    async def upload_bytes(
        self,
        bucket: str,
        object_path: str,
        content: bytes,
        content_type: str,
    ) -> None:
        url = f"{self.base_url}/object/{quote(bucket)}/{quote(object_path, safe='/')}"
        headers = {**self.headers, "Content-Type": content_type, "x-upsert": "false"}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, content=content)
        if response.status_code >= 300:
            raise StorageError(
                f"Storage upload failed with status {response.status_code}: {response.text[:500]}"
            )

    async def remove(self, bucket: str, object_paths: list[str]) -> None:
        if not object_paths:
            return
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                "DELETE",
                f"{self.base_url}/object/{quote(bucket)}",
                headers={**self.headers, "Content-Type": "application/json"},
                json={"prefixes": object_paths},
            )
        if response.status_code >= 300:
            raise StorageError(f"Storage cleanup failed with status {response.status_code}")

    async def signed_url(self, bucket: str, object_path: str, ttl: int | None = None) -> str:
        expires_in = ttl or self.settings.signed_url_ttl_seconds
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{self.base_url}/object/sign/{quote(bucket)}/{quote(object_path, safe='/')}",
                headers={**self.headers, "Content-Type": "application/json"},
                json={"expiresIn": expires_in},
            )
        if response.status_code >= 300:
            raise StorageError(f"Unable to create signed URL ({response.status_code})")
        signed = response.json().get("signedURL") or response.json().get("signedUrl")
        if not signed:
            raise StorageError("Storage did not return a signed URL")
        if signed.startswith("http"):
            return str(signed)
        return f"{self.settings.supabase_url.rstrip('/')}/storage/v1{signed}"
