import pytest
from pydantic import ValidationError

from app.schemas.jobs import JobCreate
from app.services.jobs import estimate_dataset_size_bytes


def valid_job(**overrides: object) -> JobCreate:
    payload: dict[str, object] = {
        "name": "Erosion batch",
        "defect_type": "leading_edge_erosion",
        "severity_min": 20,
        "severity_max": 70,
        "image_count": 10,
        "annotation_format": "coco_json",
        "dataset_name": "erosion-dataset",
        "config": {
            "lighting_preset": "overcast",
            "camera_fov": 45,
            "image_width": 512,
            "image_height": 512,
        },
    }
    payload.update(overrides)
    return JobCreate.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("defect_type", "invented_damage"),
        ("annotation_format", "pascal_voc"),
        ("severity_min", -1),
        ("severity_max", 101),
        ("name", "../unsafe"),
        ("dataset_name", "../../escape"),
    ],
)
def test_unsupported_or_unsafe_generation_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        valid_job(**{field: value})


def test_minimum_severity_must_be_below_maximum() -> None:
    with pytest.raises(ValidationError):
        valid_job(severity_min=70, severity_max=70)


def test_size_estimate_scales_with_resolution_masks_and_count() -> None:
    small = valid_job(image_count=2)
    large = valid_job(
        image_count=4,
        config={
            "lighting_preset": "overcast",
            "camera_fov": 45,
            "image_width": 1024,
            "image_height": 1024,
        },
    )
    assert estimate_dataset_size_bytes(large) > estimate_dataset_size_bytes(small) * 4
