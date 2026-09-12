from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import httpx

from bladeforge_worker.config import WorkerSettings


class WorkerApi:
    def __init__(self, settings: WorkerSettings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            base_url=settings.api_url.rstrip("/"),
            timeout=settings.request_timeout_seconds,
            headers={"X-Worker-Secret": settings.worker_secret},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return dict(response.json())

    async def register(self) -> uuid.UUID:
        if self.settings.render_engine_version == "v2":
            defect_types = [
                "leading_edge_erosion",
                "surface_crack",
                "delamination",
                "lightning_strike",
                "coating_loss",
                "paint_peeling",
                "corrosion",
                "rust_staining",
                "dirt_buildup",
                "scratches",
                "chips",
                "dents",
                "holes",
                "oil_stains",
                "ice_buildup",
                "trailing_edge_damage",
                "structural_deformation",
            ]
            engine_label = "blender_cycles_v2"
        else:
            defect_types = ["leading_edge_erosion"]
            engine_label = "blender"
        payload: dict[str, object] = {
            "name": self.settings.worker_name,
            "capabilities": {
                "defect_types": defect_types,
                "annotation_formats": ["coco_json", "yolo_v8"],
                "engine": engine_label,
                "render_engine_version": self.settings.render_engine_version,
            },
        }
        if self.settings.worker_organization_id:
            payload["organization_id"] = self.settings.worker_organization_id
        data = await self._request("POST", "/v1/workers/register", json=payload)
        return uuid.UUID(str(data["id"]))

    async def heartbeat(self, worker_id: uuid.UUID) -> dict[str, Any]:
        return await self._request("POST", f"/v1/workers/{worker_id}/heartbeat")

    async def claim(self, worker_id: uuid.UUID) -> dict[str, Any] | None:
        data = await self._request("POST", f"/v1/workers/{worker_id}/claim")
        return data.get("job")

    async def progress(
        self, worker_id: uuid.UUID, job_id: str, payload: dict[str, object]
    ) -> dict[str, Any]:
        status = str(payload["stage"])
        lifecycle_status = (
            "processing_annotations" if status == "processing_annotations" else "rendering"
        )
        return await self._request(
            "POST",
            f"/v1/workers/{worker_id}/jobs/{job_id}/progress",
            json={
                **payload,
                "status": lifecycle_status,
            },
        )

    async def cancellation(self, worker_id: uuid.UUID, job_id: str) -> bool:
        data = await self._request(
            "GET", f"/v1/workers/{worker_id}/jobs/{job_id}/cancellation"
        )
        return bool(data["cancel_requested"])

    async def download_selected_asset(
        self, worker_id: uuid.UUID, job_id: str, key: str, destination: Path
    ) -> None:
        data = await self._request(
            "GET",
            f"/v1/workers/{worker_id}/jobs/{job_id}/assets/url",
            params={"key": key},
        )
        url = httpx.URL(str(data["url"]))
        if url.host in {"127.0.0.1", "localhost"}:
            api_origin = httpx.URL(self.settings.api_url)
            url = url.copy_with(
                scheme=api_origin.scheme,
                host=api_origin.host,
                port=api_origin.port,
            )
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as downloader:
            response = await downloader.get(url)
            response.raise_for_status()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)

    async def complete(
        self,
        worker_id: uuid.UUID,
        job_id: str,
        output_directory: str,
        gpu_seconds: float,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/workers/{worker_id}/jobs/{job_id}/complete",
            json={"output_directory": output_directory, "gpu_seconds": gpu_seconds},
        )

    async def failed(
        self,
        worker_id: uuid.UUID,
        job_id: str,
        code: str,
        message: str,
        gpu_seconds: float,
        retryable: bool,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/v1/workers/{worker_id}/jobs/{job_id}/failed",
            json={
                "code": code,
                "message": message,
                "gpu_seconds": gpu_seconds,
                "retryable": retryable,
            },
        )
