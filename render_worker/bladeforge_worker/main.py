from __future__ import annotations

import asyncio
import json
import signal
import time
from pathlib import Path

import httpx
import structlog

from bladeforge_worker.adapters import LocalBlenderAdapter
from bladeforge_worker.client import WorkerApi
from bladeforge_worker.config import WorkerSettings
from bladeforge_worker.gemini import GeminiEditError, edit_dataset

log = structlog.get_logger()


async def prepare_job(
    api: WorkerApi,
    worker_id,
    settings: WorkerSettings,
    job: dict[str, object],
) -> tuple[Path, Path]:
    job_root = (settings.output_root / str(job["id"])).resolve()
    output_directory = job_root / "dataset"
    job_root.mkdir(parents=True, exist_ok=True)
    config = dict(job.get("config") or {})
    if settings.gemini_enabled:
        config["render_engine"] = "v2"
        config["image_edit_backend"] = "gemini"
    for key_name, path_name in (
        ("model_asset_key", "model_asset_path"),
        ("hdri_asset_key", "hdri_asset_path"),
    ):
        key = config.get(key_name)
        if not key:
            continue
        suffix = Path(str(key)).suffix.lower()
        destination = job_root / "assets" / f"{key_name.removesuffix('_key')}{suffix}"
        await api.download_selected_asset(worker_id, str(job["id"]), str(key), destination)
        config[path_name] = str(destination.resolve())

    job_payload = {
        "id": str(job["id"]),
        "dataset_name": str(job["dataset_name"]),
        "defect_type": str(job.get("defect_type") or "leading_edge_erosion"),
        "image_count": int(job["image_count"]),
        "image_width": int(job["image_width"]),
        "image_height": int(job["image_height"]),
        "severity_min": int(job["severity_min"]),
        "severity_max": int(job["severity_max"]),
        "annotation_format": str(job["annotation_format"]),
        "config": config,
        "seed": settings.base_seed + int(str(job["id"]).replace("-", "")[:8], 16),
        "output_directory": str(output_directory),
    }
    job_file = job_root / "job.json"
    job_file.write_text(json.dumps(job_payload, indent=2), encoding="utf-8")
    return job_file, output_directory


def resolve_engine_path(settings: WorkerSettings, job: dict[str, object]) -> Path:
    """Prefer the job's config.render_engine; otherwise use the worker setting."""
    if settings.gemini_enabled:
        return settings.render_engine_v2_path
    config = job.get("config")
    configured: str | None = None
    if isinstance(config, dict):
        value = config.get("render_engine")
        if value in ("legacy", "v2"):
            configured = str(value)
    engine_version = configured or settings.render_engine_version
    if engine_version == "v2":
        return settings.render_engine_v2_path
    return settings.render_engine_path


def validate_render_output(output_directory: Path, job: dict[str, object]) -> None:
    dataset_name = str(job["dataset_name"])
    required_paths = [
        output_directory / "manifest.json",
        output_directory / f"{dataset_name}.zip",
    ]
    annotation_format = str(job["annotation_format"])
    required_paths.append(
        output_directory
        / "annotations"
        / ("coco.json" if annotation_format == "coco_json" else "data.yaml")
    )
    image_count = int(job["image_count"])
    for index in range(image_count):
        stem = f"sample_{index:06d}"
        required_paths.extend(
            [
                output_directory / "images" / f"{stem}.png",
                output_directory / "masks" / f"{stem}.png",
                output_directory / "masks" / f"{stem}_instances.png",
                output_directory / "metadata" / f"{stem}.json",
            ]
        )
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        preview = "\n".join(missing[:10])
        more = f"\n...and {len(missing) - 10} more missing files" if len(missing) > 10 else ""
        raise RuntimeError(
            "Renderer exited before producing a complete dataset package. "
            f"Missing files:\n{preview}{more}"
        )


async def run_job(
    api: WorkerApi,
    worker_id,
    settings: WorkerSettings,
    job: dict[str, object],
) -> None:
    job_id = str(job["id"])
    job_file, output_directory = await prepare_job(api, worker_id, settings, job)
    engine_path = resolve_engine_path(settings, job)
    adapter = LocalBlenderAdapter(settings.blender_executable, engine_path)
    started = time.monotonic()
    try:
        async for progress in adapter.run(job_file):
            if settings.gemini_enabled:
                progress = {**progress, "progress": max(1, int(progress["progress"]) * 70 // 100)}
            result = await api.progress(worker_id, job_id, progress)
            if result.get("cancel_requested") or await api.cancellation(worker_id, job_id):
                await adapter.cancel()
                raise asyncio.CancelledError
        validate_render_output(output_directory, job)
        if settings.gemini_enabled:
            async def edit_progress(done, total, defect):
                await api.progress(worker_id, job_id, {
                    "progress": 70 + int(28 * done / max(total, 1)),
                    "stage": "processing_annotations",
                    "message": f"Gemini is editing {defect.replace('_', ' ')} ({done + 1}/{total} regions).",
                    "metadata": {"image_edit_backend": "gemini"},
                })

            edit_task = asyncio.create_task(edit_dataset(output_directory, settings, progress=edit_progress))
            try:
                while not edit_task.done():
                    await asyncio.wait({edit_task}, timeout=5)
                    await api.heartbeat(worker_id)
                    if await api.cancellation(worker_id, job_id):
                        raise asyncio.CancelledError
                await edit_task
            finally:
                if not edit_task.done():
                    edit_task.cancel()
                await asyncio.gather(edit_task, return_exceptions=True)
            validate_render_output(output_directory, job)
        gpu_seconds = time.monotonic() - started
        await api.complete(worker_id, job_id, str(output_directory), gpu_seconds)
        await log.ainfo("job_complete", job_id=job_id, gpu_seconds=gpu_seconds)
    except asyncio.CancelledError:
        gpu_seconds = time.monotonic() - started
        await api.failed(
            worker_id,
            job_id,
            "cancelled_by_user",
            "Worker stopped after a user cancellation request.",
            gpu_seconds,
            retryable=False,
        )
    except Exception as exc:
        gpu_seconds = time.monotonic() - started
        await log.aexception("job_failed", job_id=job_id)
        await api.failed(
            worker_id,
            job_id,
            "gemini_edit_failed" if isinstance(exc, GeminiEditError) else "renderer_failed",
            str(exc)[:1000],
            gpu_seconds,
            retryable=not settings.gemini_enabled,
        )


async def serve() -> None:
    settings = WorkerSettings()  # type: ignore[call-arg]
    settings.output_root.mkdir(parents=True, exist_ok=True)
    api = WorkerApi(settings)
    while True:
        try:
            worker_id = await api.register()
            break
        except (httpx.HTTPError, OSError) as exc:
            await log.awarning(
                "worker_registration_retry",
                error=str(exc),
                retry_in_seconds=settings.poll_seconds,
            )
            await asyncio.sleep(settings.poll_seconds)
    await log.ainfo("worker_registered", worker_id=str(worker_id))
    try:
        while True:
            try:
                await api.heartbeat(worker_id)
                job = await api.claim(worker_id)
                if job is not None:
                    await run_job(api, worker_id, settings, job)
                else:
                    await asyncio.sleep(settings.poll_seconds)
            except (httpx.HTTPError, OSError) as exc:
                await log.awarning(
                    "worker_api_temporarily_unavailable",
                    error=str(exc),
                    retry_in_seconds=settings.poll_seconds,
                )
                await asyncio.sleep(settings.poll_seconds)
    finally:
        await api.close()


def main() -> None:
    signal.signal(signal.SIGTERM, lambda *_: raise_signal_exit())
    asyncio.run(serve())


def raise_signal_exit() -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    main()
