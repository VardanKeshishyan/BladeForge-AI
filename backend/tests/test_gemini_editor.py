import base64
import asyncio
import io
import json
import os
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image, ImageChops

from bladeforge_worker.config import WorkerSettings
from bladeforge_worker.gemini import (
    GeminiEditError,
    build_prompt,
    composite_edit,
    decode_mask,
    edit_dataset,
    request_edit,
)
from bladeforge_worker.main import prepare_job, resolve_engine_path
import bladeforge_worker.main as worker


def settings(**kwargs):
    return WorkerSettings(
        _env_file=None, worker_secret="x" * 32, gemini_api_key="test-secret-never-export", **kwargs
    )


def rle(mask):
    counts, previous, count = [], 0, 0
    for x in range(mask.width):
        for y in range(mask.height):
            value = int(mask.getpixel((x, y)) > 0)
            if value != previous:
                counts.append(count)
                count = 0
                previous = value
            count += 1
    counts.append(count)
    return {"size": [mask.height, mask.width], "counts": counts}


def test_mask_orientation_and_exact_pixel_preservation():
    mask = Image.new("L", (40, 30))
    mask.paste(255, (3, 8, 12, 19))
    assert decode_mask(rle(mask), mask.size).tobytes() == mask.tobytes()
    source = Image.new("RGB", mask.size, (120, 140, 160))
    result = composite_edit(source, Image.new("RGB", source.size, "red"), mask)
    outside = ImageChops.invert(mask)
    assert (
        ImageChops.multiply(ImageChops.difference(result, source), outside.convert("RGB")).getbbox()
        is None
    )
    assert result.getpixel((7, 12)) != source.getpixel((7, 12))
    with pytest.raises(GeminiEditError, match="no visible change"):
        composite_edit(source, source, mask)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
async def test_http_failure_is_actionable_and_does_not_expose_key(status):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={"error": "test-secret-never-export"})
        )
    ) as client:
        with pytest.raises(GeminiEditError) as caught:
            await request_edit(
                client,
                settings(),
                Image.new("RGB", (16, 16)),
                Image.new("L", (16, 16), 255),
                "edit",
            )
    assert str(status) in str(caught.value)
    assert "test-secret-never-export" not in str(caught.value)


async def test_no_image_response_fails():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": "cannot edit"}]}}]}
            )
        )
    ) as client:
        with pytest.raises(GeminiEditError, match="no image"):
            await request_edit(
                client,
                settings(),
                Image.new("RGB", (16, 16)),
                Image.new("L", (16, 16), 255),
                "edit",
            )


async def test_dataset_uses_masks_defect_settings_and_repackages_crops(tmp_path):
    for folder in ("images", "masks", "metadata", "annotations"):
        (tmp_path / folder).mkdir()
    source = Image.new("RGB", (40, 30), "white")
    source.save(tmp_path / "images/sample_000000.png")
    source.crop((0, 0, 20, 20)).save(tmp_path / "images/sample_000000_crop.png")
    regions = []
    for index, defect in enumerate(("surface_crack", "dirt_buildup")):
        mask = Image.new("L", source.size)
        mask.paste(255, (3 + index * 20, 4, 13 + index * 20, 15))
        regions.append(
            {
                "instance_id": str(index),
                "defect_id": defect,
                "region_id": str(index),
                "layer_index": index,
                "severity": 62,
                "segmentation": rle(mask),
            }
        )
    sample = {
        "image": "images/sample_000000.png",
        "metadata": "metadata/sample_000000.json",
        "width": 40,
        "height": 30,
        "instances": regions,
        "crop": {"source_crop_box": [0, 0, 20, 20], "image": "images/sample_000000_crop.png"},
    }
    manifest = {
        "dataset_name": "test",
        "defect_types": [r["defect_id"] for r in regions],
        "samples": [sample],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    metadata = {
        "image_edit_backend": "gemini",
        "camera": {"fov_deg": 40},
        "defect_layers": [
            {"defect_id": r["defect_id"], "severity": 62, "coverage": 30} for r in regions
        ],
    }
    (tmp_path / sample["metadata"]).write_text(json.dumps(metadata))
    (tmp_path / "annotations/coco.json").write_text(
        json.dumps({"info": {}, "annotations": [{"id": 1}]})
    )
    (tmp_path / "README.md").write_text("test")
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        parts = payload["contents"][0]["parts"]
        assert len(parts) == 4
        assert "62" in parts[0]["text"] and "coverage" in parts[0]["text"]
        assert request.headers["x-goog-api-key"] == "test-secret-never-export"
        assert "test-secret-never-export" not in request.content.decode()
        assert regions[len(calls)]["defect_id"] in parts[0]["text"]
        incoming_mask = Image.open(io.BytesIO(base64.b64decode(parts[2]["inlineData"]["data"])))
        assert (
            incoming_mask.tobytes()
            == decode_mask(regions[len(calls)]["segmentation"], source.size).tobytes()
        )
        buffer = io.BytesIO()
        Image.new("RGB", source.size, (40, 30, 20)).save(buffer, format="PNG")
        calls.append(payload)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": base64.b64encode(buffer.getvalue()).decode(),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await edit_dataset(tmp_path, settings(), client=client)
    assert len(calls) == 2
    with Image.open(tmp_path / sample["image"]) as final:
        assert final.getpixel((1, 1)) == (255, 255, 255)
        assert final.getpixel((6, 8)) != (255, 255, 255)
        assert final.getpixel((26, 8)) != (255, 255, 255)
        with Image.open(tmp_path / sample["crop"]["image"]) as crop:
            assert crop.tobytes() == final.crop((0, 0, 20, 20)).tobytes()
    with zipfile.ZipFile(tmp_path / "test.zip") as bundle:
        assert bundle.read(sample["image"]) == (tmp_path / sample["image"]).read_bytes()
        assert "guidance/sample_000000/source.png" in bundle.namelist()
        assert all(
            b"test-secret-never-export" not in bundle.read(name) for name in bundle.namelist()
        )
    assert (
        json.loads((tmp_path / "manifest.json").read_text())["image_edit"]["annotation_semantics"]
        == "edit_region_guidance_unverified"
    )


def test_prompt_distinguishes_region_colour_and_defect_appearance():
    prompt = build_prompt(
        {"weather": {"precipitation": "snow"}},
        {"defect_id": "leading_edge_erosion", "severity": 42},
        {"color_hex": "#ff0000"},
    )
    assert "fine pitting" in prompt and "snow" in prompt and "42" in prompt
    assert "not literal defect paint" in prompt


async def test_prepare_job_selects_gemini_without_serializing_secret(tmp_path):
    cfg = settings(output_root=tmp_path)
    job = {
        "id": "12345678-1111-1111-1111-111111111111",
        "dataset_name": "test",
        "image_count": 1,
        "image_width": 64,
        "image_height": 64,
        "severity_min": 20,
        "severity_max": 80,
        "annotation_format": "coco_json",
        "config": {"render_engine": "legacy"},
    }
    path, _ = await prepare_job(None, None, cfg, job)
    content = path.read_text()
    assert "test-secret-never-export" not in content
    assert json.loads(content)["config"]["image_edit_backend"] == "gemini"
    assert resolve_engine_path(cfg, job) == cfg.render_engine_v2_path


@pytest.mark.skipif(
    not os.getenv("BLADEFORGE_GEMINI_SOURCE_JOB"),
    reason="Optional Blender guidance regression using a saved paint job",
)
@pytest.mark.parametrize("split_regions", [False, True])
def test_saved_painted_job_produces_real_gemini_guidance(tmp_path, split_regions):
    source = Path(os.environ["BLADEFORGE_GEMINI_SOURCE_JOB"])
    job = json.loads(source.read_text(encoding="utf-8"))
    job.update(
        image_count=1, image_width=512, image_height=512, output_directory=str(tmp_path / "dataset")
    )
    job["config"].update(image_edit_backend="gemini", generate_all_angles=False)
    if split_regions:
        job["config"]["region_document"]["strokes"][1]["region_id"] = "blue"
        job["config"]["defect_layers"].append(
            {
                **job["config"]["defect_layers"][1],
                "defect_id": "surface_crack",
                "region_id": "blue",
            }
        )
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")
    repo = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
            "--background",
            "--python",
            str(repo / "render_engine/v2/main.py"),
            "--",
            "--job-file",
            str(job_file),
        ],
        env={**os.environ, "BLADEFORGE_RENDER_ENGINE": "EEVEE"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-5000:] + result.stderr[-2000:]
    output = tmp_path / "dataset"
    manifest = json.loads((output / "manifest.json").read_text())
    instances = manifest["samples"][0]["instances"]
    assert {i["defect_id"] for i in instances} == set(manifest["defect_types"])
    assert all(i["area"] >= 9 and not i.get("fallback_annotation") for i in instances)
    print(f"Guidance render: {output}")


@pytest.mark.parametrize("outcome", ["complete", "failure", "cancel"])
async def test_worker_gemini_lifecycle(monkeypatch, tmp_path, outcome):
    api = AsyncMock()
    api.progress.return_value = {}
    api.cancellation.return_value = False

    class Adapter:
        def __init__(self, *args):
            pass

        async def run(self, path):
            yield {"progress": 99, "stage": "processing_annotations", "message": "Blender done"}

    monkeypatch.setattr(worker, "LocalBlenderAdapter", Adapter)
    monkeypatch.setattr(
        worker, "prepare_job", AsyncMock(return_value=(tmp_path / "job.json", tmp_path))
    )
    monkeypatch.setattr(worker, "validate_render_output", lambda *args: None)

    async def edit(output, cfg, progress):
        await progress(0, 1, "surface_crack")
        if outcome == "failure":
            raise GeminiEditError("quota exhausted")
        if outcome == "cancel":
            raise asyncio.CancelledError

    monkeypatch.setattr(worker, "edit_dataset", edit)
    await worker.run_job(api, "worker", settings(), {"id": "test", "config": {}})
    if outcome == "complete":
        api.complete.assert_awaited_once()
        api.failed.assert_not_awaited()
    else:
        api.complete.assert_not_awaited()
        api.failed.assert_awaited_once()
        assert api.failed.call_args.kwargs["retryable"] is False
    progress = [c.args[2]["progress"] for c in api.progress.call_args_list]
    assert progress == sorted(progress)


@pytest.mark.parametrize(
    "bad",
    [
        {"size": [2, 2], "counts": [-1, 5]},
        {"size": [2, 2], "counts": [1, 2]},
        {"size": [2, 2], "counts": "abcd"},
    ],
)
def test_invalid_rle_is_rejected(bad):
    with pytest.raises(GeminiEditError):
        decode_mask(bad, (2, 2))
