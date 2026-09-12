import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def blender_executable() -> Path | None:
    discovered = shutil.which("blender")
    if discovered:
        return Path(discovered)
    installed = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
    return installed if installed.is_file() else None


@pytest.mark.skipif(
    os.getenv("BLADEFORGE_E2E") != "1" or blender_executable() is None,
    reason="Set BLADEFORGE_E2E=1 on a machine with Blender to run the render E2E test.",
)
def test_v2_blender_job_produces_imported_scene_crops_and_instance_coco(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[2]
    defect_parts = {
        "surface_crack": "blades",
        "leading_edge_erosion": "blades",
        "trailing_edge_damage": "blades",
        "corrosion": "tower",
        "rust_staining": "tower",
        "paint_peeling": "nacelle",
        "coating_loss": "blades",
        "scratches": "blades",
        "dents": "tower",
        "lightning_strike": "blades",
        "holes": "blades",
        "chips": "blades",
        "delamination": "blades",
        "oil_stains": "nacelle",
        "dirt_buildup": "tower",
        "ice_buildup": "blades",
        "structural_deformation": "tower",
    }
    output = tmp_path / "dataset"
    job = {
        "id": "00000000-0000-0000-0000-000000000001",
        "dataset_name": "e2e-dataset",
        "defect_type": "leading_edge_erosion",
        "image_count": 4,
        "image_width": 256,
        "image_height": 256,
        "severity_min": 20,
        "severity_max": 60,
        "annotation_format": "coco_json",
        "seed": 42,
        "config": {
            "environment_id": "LIGHT_SNOW_V1",
            "weather_intensity": 0.4,
            "camera_fov": 45,
            "weather": True,
            "turbine_part_id": "all",
            "crop_policy": "full_and_crop",
            "generate_all_angles": True,
            "camera_views": [
                {
                    "target_x_m": 0,
                    "target_y_m": 0,
                    "target_z_m": 70,
                    "azimuth_deg": azimuth,
                    "elevation_deg": 8,
                    "distance_m": 225,
                    "roll_deg": 0,
                    "fov_deg": 45,
                }
                for azimuth in (-90, 0, 90, 180)
            ],
            "model_asset_path": str(repository_root / "public/assets/models/wind-turbine.fbx"),
            "hdri_asset_path": str(repository_root / "public/assets/hdri/desert.hdr"),
            "defect_layers": [
                {
                    "defect_id": defect_id,
                    "part_id": part_id,
                    "severity": 55,
                    "coverage": 5,
                    "size_scale": 2.5,
                    "opacity": 100,
                    "rotation_deg": 15,
                    "spread": 10,
                    "randomness": 20,
                    "color_hex": "#9a3412",
                    "region_id": None,
                }
                for defect_id, part_id in defect_parts.items()
            ],
        },
        "output_directory": str(output),
    }
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")
    engine = repository_root / "render_engine" / "v2" / "main.py"
    environment = {**os.environ, "BLADEFORGE_RENDER_ENGINE": "EEVEE"}
    subprocess.run(
        [
            str(blender_executable()),
            "--background",
            "--python",
            str(engine),
            "--",
            "--job-file",
            str(job_file),
        ],
        check=True,
        timeout=300,
        env=environment,
    )
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["sample_count"] == 4
    assert manifest["renderer"] == "bladeforge_cycles_v2"
    assert manifest["model_source"] == "uploaded"
    assert manifest["hdri_loaded"] is True
    assert set(manifest["defect_types"]) == set(defect_parts)
    sample = manifest["samples"][0]
    assert sample["crop"]["image"] == "images/sample_000000_crop.png"
    delivered_instances = {
        item["defect_id"] for delivered in manifest["samples"] for item in delivered["instances"]
    }
    assert delivered_instances == set(defect_parts)
    assert (output / "images/sample_000000.png").is_file()
    assert (output / "masks/sample_000000.png").is_file()
    assert (output / "masks/sample_000000_instances.png").is_file()
    assert (output / "annotations/coco.json").is_file()
    assert (output / "e2e-dataset.zip").is_file()
    image_module = pytest.importorskip("PIL.Image")
    rgb = image_module.open(output / "images/sample_000000.png").convert("RGB")
    assert max(channel[1] for channel in rgb.getextrema()) > 20
    metadata = json.loads((output / "metadata/sample_000000.json").read_text(encoding="utf-8"))
    assert metadata["weather"]["precipitation"] == "snow"
    coco = json.loads((output / "annotations/coco.json").read_text(encoding="utf-8"))
    assert len(coco["images"]) == 8
    assert all(record["segmentation"]["counts"] for record in coco["annotations"])
    assert all(record["attributes"]["instance_id"] for record in coco["annotations"])
