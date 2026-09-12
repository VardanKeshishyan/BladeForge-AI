import json
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.api.errors import ApiError
from app.db.models import GenerationJob, JobStatus
from app.services.datasets import validate_package


def make_job() -> GenerationJob:
    return GenerationJob(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        created_by=uuid.uuid4(),
        name="Test",
        status=JobStatus.processing_annotations,
        config={},
        defect_type="leading_edge_erosion",
        severity_min=10,
        severity_max=70,
        image_count=1,
        image_width=256,
        image_height=256,
        annotation_format="coco_json",
        dataset_name="test-dataset",
        estimated_size_bytes=10,
        progress=95,
        current_stage="processing_annotations",
        attempt_count=1,
        max_attempts=3,
        idempotency_key="test-package-idempotency",
        submitted_at=datetime.now(UTC),
    )


def test_package_requires_real_image_mask_metadata_and_annotations(tmp_path: Path) -> None:
    for directory in ("images", "masks", "metadata", "annotations"):
        (tmp_path / directory).mkdir()
    (tmp_path / "images/sample.png").write_bytes(b"image")
    (tmp_path / "masks/sample.png").write_bytes(b"mask")
    (tmp_path / "metadata/sample.json").write_text("{}", encoding="utf-8")
    (tmp_path / "annotations/coco.json").write_text("{}", encoding="utf-8")
    manifest = {
        "samples": [
            {
                "image": "images/sample.png",
                "mask": "masks/sample.png",
                "metadata": "metadata/sample.json",
            }
        ]
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with zipfile.ZipFile(tmp_path / "test-dataset.zip", "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
    assert validate_package(tmp_path, make_job()) == manifest
    (tmp_path / "masks/sample.png").unlink()
    with pytest.raises(ApiError) as error:
        validate_package(tmp_path, make_job())
    assert error.value.code == "invalid_dataset_package"

