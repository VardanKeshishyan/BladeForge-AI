"""Non-regression contract tests for behaviour that existed before the v2 upgrade.

These lock in the public surface that current customers and the deployed render
worker depend on: route paths, the accepted legacy job payload, job status names
and transitions, the worker callback payloads, and the dataset package layout.
Anything here breaking means an existing integration breaks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.errors import ApiError
from app.db.models import JobStatus, OrgRole
from app.main import app
from app.schemas.jobs import JobCreate, WorkerCompletion, WorkerFailure, WorkerProgress
from app.services.datasets import classify_dataset_file
from app.services.jobs import LEGAL_TRANSITIONS, estimate_dataset_size_bytes

client = TestClient(app)

# The exact payload documented in README.md for the external API.
LEGACY_JOB_PAYLOAD: dict[str, object] = {
    "name": "Small erosion batch",
    "defect_type": "leading_edge_erosion",
    "severity_min": 20,
    "severity_max": 60,
    "image_count": 2,
    "annotation_format": "coco_json",
    "dataset_name": "small-erosion-batch",
    "config": {
        "lighting_preset": "overcast",
        "camera_fov": 45,
        "image_width": 512,
        "image_height": 512,
    },
}

BASELINE_ROUTES: set[str] = {
    "/health",
    "/ready",
    "/v1/jobs",
    "/v1/jobs/{job_id}",
    "/v1/jobs/{job_id}/events",
    "/v1/jobs/{job_id}/cancel",
    "/v1/jobs/{job_id}/retry",
    "/v1/jobs/{job_id}/duplicate",
    "/v1/external/jobs",
    "/v1/external/jobs/{job_id}",
    "/v1/datasets",
    "/v1/datasets/{dataset_id}",
    "/v1/defect-profiles",
    "/v1/defect-profiles/{profile_id}",
    "/v1/defect-profiles/{profile_id}/references",
    "/v1/api-keys",
    "/v1/api-keys/{key_id}/revoke",
    "/v1/usage/summary",
    "/v1/usage/jobs/{job_id}",
    "/v1/overview/summary",
    "/v1/render-workers",
    "/v1/capabilities",
    "/v1/workers/register",
    "/v1/workers/{worker_id}/heartbeat",
    "/v1/workers/{worker_id}/claim",
    "/v1/workers/{worker_id}/jobs/{job_id}/progress",
    "/v1/workers/{worker_id}/jobs/{job_id}/cancellation",
    "/v1/workers/{worker_id}/jobs/{job_id}/failed",
    "/v1/workers/{worker_id}/jobs/{job_id}/complete",
}

BASELINE_JOB_STATUS_NAMES: set[str] = {
    "draft",
    "awaiting_worker",
    "queued",
    "rendering",
    "processing_annotations",
    "complete",
    "failed",
    "cancelled",
}

BASELINE_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.draft: {JobStatus.awaiting_worker, JobStatus.cancelled},
    JobStatus.awaiting_worker: {JobStatus.queued, JobStatus.cancelled},
    JobStatus.queued: {JobStatus.rendering, JobStatus.cancelled, JobStatus.failed},
    JobStatus.rendering: {
        JobStatus.processing_annotations,
        JobStatus.cancelled,
        JobStatus.failed,
    },
    JobStatus.processing_annotations: {
        JobStatus.complete,
        JobStatus.cancelled,
        JobStatus.failed,
    },
    JobStatus.complete: set(),
    JobStatus.failed: {JobStatus.awaiting_worker},
    JobStatus.cancelled: {JobStatus.awaiting_worker},
}


def test_openapi_still_publishes_every_baseline_route() -> None:
    schema = client.get("/openapi.json").json()
    published = set(schema["paths"])
    missing = BASELINE_ROUTES - published
    assert not missing, f"Existing public routes disappeared: {sorted(missing)}"


def test_openapi_document_is_servable() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "BladeForge AI API"


def test_legacy_job_payload_is_still_accepted_unchanged() -> None:
    payload = JobCreate.model_validate(LEGACY_JOB_PAYLOAD)
    assert payload.defect_type == "leading_edge_erosion"
    assert payload.severity_min == 20
    assert payload.severity_max == 60
    assert payload.image_count == 2
    assert payload.annotation_format == "coco_json"
    assert payload.dataset_name == "small-erosion-batch"
    assert payload.config.lighting_preset == "overcast"
    assert payload.config.camera_fov == 45
    assert payload.config.image_width == 512
    assert payload.config.image_height == 512
    # Fields the legacy payload omits must keep their documented defaults.
    assert payload.config.compression_quality == 92
    assert payload.config.include_masks is True
    assert payload.config.weather is False


def test_legacy_generation_config_defaults_are_unchanged() -> None:
    payload = JobCreate.model_validate(
        {
            "name": "Defaults",
            "defect_type": "leading_edge_erosion",
            "severity_min": 10,
            "severity_max": 90,
            "image_count": 1,
            "annotation_format": "yolo_v8",
            "dataset_name": "defaults",
        }
    )
    assert payload.config.image_width == 1024
    assert payload.config.image_height == 1024
    assert payload.config.camera_fov == 45
    assert payload.config.lighting_preset == "overcast"


@pytest.mark.parametrize("preset", ["overcast", "golden_hour", "midday", "cloudy"])
def test_legacy_lighting_presets_remain_valid(preset: str) -> None:
    payload = JobCreate.model_validate({**LEGACY_JOB_PAYLOAD, "config": {"lighting_preset": preset}})
    assert payload.config.lighting_preset == preset


def test_new_config_fields_are_absent_from_a_legacy_payload() -> None:
    """A request written before these fields existed must behave exactly as it did."""
    payload = JobCreate.model_validate(LEGACY_JOB_PAYLOAD)
    assert payload.config.environment_id is None
    assert payload.config.weather_intensity is None
    assert payload.config.blade_section_id is None
    assert payload.config.camera_view is None
    assert payload.config.crop_policy == "full_frame"


@pytest.mark.parametrize(
    "environment_id",
    [
        "CLEAR_DAY_V1",
        "OVERCAST_DAY_V1",
        "CLOUDY_DAY_V1",
        "GOLDEN_HOUR_V1",
        "NIGHT_MOONLIT_V1",
        "OFFSHORE_HAZE_V1",
        "LIGHT_RAIN_WET_V1",
        "HEAVY_RAIN_STORM_V1",
        "POST_RAIN_WET_V1",
    ],
)
def test_every_advertised_environment_is_accepted(environment_id: str) -> None:
    payload = JobCreate.model_validate(
        {**LEGACY_JOB_PAYLOAD, "config": {"environment_id": environment_id}}
    )
    assert payload.config.environment_id == environment_id


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        JobCreate.model_validate({**LEGACY_JOB_PAYLOAD, "config": {"environment_id": "SUNNY"}})


@pytest.mark.parametrize("policy", ["full_frame", "defect_crop", "full_and_crop"])
def test_crop_policies_are_accepted(policy: str) -> None:
    payload = JobCreate.model_validate({**LEGACY_JOB_PAYLOAD, "config": {"crop_policy": policy}})
    assert payload.config.crop_policy == policy


def test_a_saved_camera_view_round_trips_through_the_schema() -> None:
    payload = JobCreate.model_validate(
        {
            **LEGACY_JOB_PAYLOAD,
            "config": {
                "blade_section_id": "outboard",
                "camera_view": {
                    "target_x_m": 0.0,
                    "target_y_m": 0.0,
                    "target_z_m": 47.5,
                    "azimuth_deg": -55.0,
                    "elevation_deg": 12.0,
                    "distance_m": 18.0,
                },
            },
        }
    )
    assert payload.config.blade_section_id == "outboard"
    view = payload.config.camera_view
    assert view is not None
    assert view.target_z_m == pytest.approx(47.5)
    assert view.distance_m == pytest.approx(18.0)


@pytest.mark.parametrize(
    "field,value",
    [
        ("azimuth_deg", 200.0),
        ("elevation_deg", 95.0),
        ("distance_m", 0.01),
        ("distance_m", 5000.0),
    ],
)
def test_a_camera_view_outside_safe_bounds_is_rejected(field: str, value: float) -> None:
    """The browser cannot talk the renderer into an unreachable or degenerate pose."""
    view = {"azimuth_deg": 0.0, "elevation_deg": 10.0, "distance_m": 20.0, field: value}
    with pytest.raises(ValidationError):
        JobCreate.model_validate({**LEGACY_JOB_PAYLOAD, "config": {"camera_view": view}})


def test_job_status_names_are_unchanged() -> None:
    assert {status.value for status in JobStatus} == BASELINE_JOB_STATUS_NAMES


def test_job_status_transitions_are_preserved() -> None:
    for source, allowed in BASELINE_TRANSITIONS.items():
        assert allowed <= LEGAL_TRANSITIONS[source], (
            f"Transitions out of {source.value} lost a previously legal target."
        )


def test_organization_roles_are_unchanged() -> None:
    assert {role.value for role in OrgRole} == {"owner", "administrator", "engineer", "viewer"}


def test_size_estimate_stays_positive_and_scales_with_image_count() -> None:
    one = estimate_dataset_size_bytes(JobCreate.model_validate(LEGACY_JOB_PAYLOAD))
    many = estimate_dataset_size_bytes(
        JobCreate.model_validate({**LEGACY_JOB_PAYLOAD, "image_count": 20})
    )
    assert one > 0
    assert many > one


def test_worker_callback_payloads_are_unchanged() -> None:
    progress = WorkerProgress.model_validate(
        {"status": "rendering", "progress": 42, "stage": "rendering", "message": "Rendered 1 of 2."}
    )
    assert progress.metadata == {}
    failure = WorkerFailure.model_validate({"code": "renderer_failed", "message": "boom"})
    assert failure.retryable is True
    assert failure.gpu_seconds == 0
    completion = WorkerCompletion.model_validate(
        {
            "output_directory": "/work/job/dataset",
            "manifest_path": "manifest.json",
            "archive_path": "dataset.zip",
            "gpu_seconds": 1.5,
        }
    )
    assert completion.preview_path is None


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("manifest.json", "manifest"),
        ("README.md", "readme"),
        ("images/sample_000000.png", "image"),
        ("masks/sample_000000.png", "mask"),
        ("annotations/coco.json", "annotation"),
        ("annotations/labels/sample_000000.txt", "annotation"),
        ("metadata/sample_000000.json", "metadata"),
    ],
)
def test_baseline_dataset_zip_layout_is_still_classified(relative: str, expected: str) -> None:
    assert classify_dataset_file(Path(relative)) == expected


def test_unexpected_dataset_files_are_still_rejected() -> None:
    with pytest.raises(ApiError) as error:
        classify_dataset_file(Path("unexpected/file.bin"))
    assert error.value.code == "invalid_dataset_package"


def test_capabilities_endpoint_keeps_documented_keys() -> None:
    payload = client.get("/v1/capabilities").json()
    for key in (
        "supported_defects",
        "annotation_formats",
        "email_invitations",
        "runpod",
        "webhooks",
        "billing",
    ):
        assert key in payload, f"/v1/capabilities dropped the {key} field."
    assert "leading_edge_erosion" in payload["supported_defects"]
    assert {"coco_json", "yolo_v8"} <= set(payload["annotation_formats"])
