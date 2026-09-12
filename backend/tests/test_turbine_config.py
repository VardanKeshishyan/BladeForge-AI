"""Validation of the turbine part, multi-defect and asset-import configuration.

The frontend offers a lot of choices here. These tests pin down which combinations the
backend accepts, because the UI is not the security boundary — a caller can post whatever
it likes straight to the API.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.errors import ApiError
from app.schemas.jobs import GenerationConfig, JobCreate
from app.schemas.turbine import (
    DEFECT_PART_MATRIX,
    RENDERER_SUPPORTED_DEFECTS,
    CameraView,
    DefectLayer,
)
from app.services.assets import (
    ENVIRONMENT_ASSET,
    MODEL_ASSET,
    detect_environment_format,
    detect_model_format,
)

BASE_PAYLOAD: dict[str, object] = {
    "name": "Turbine batch",
    "defect_type": "leading_edge_erosion",
    "severity_min": 20,
    "severity_max": 60,
    "image_count": 4,
    "annotation_format": "coco_json",
    "dataset_name": "turbine-batch",
}


def build(config: dict[str, object]) -> JobCreate:
    return JobCreate.model_validate({**BASE_PAYLOAD, "config": config})


# ── Defaults preserve the previous behaviour ──────────────────────────────────


def test_a_payload_without_the_new_fields_still_renders_the_whole_turbine() -> None:
    config = GenerationConfig()
    assert config.turbine_part_id == "all"
    assert config.defect_layers == []
    assert config.generate_all_angles is False
    assert config.model_asset_key is None
    assert config.hdri_asset_key is None


# ── Turbine parts ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("part_id", "defect_id"),
    [
        ("all", "leading_edge_erosion"),
        ("rotor", "leading_edge_erosion"),
        ("blades", "leading_edge_erosion"),
        ("hub", "lightning_strike"),
        ("nacelle", "coating_loss"),
        ("tower", "corrosion"),
        ("foundation", "corrosion"),
    ],
)
def test_every_advertised_turbine_part_is_accepted(part_id: str, defect_id: str) -> None:
    payload = JobCreate.model_validate(
        {**BASE_PAYLOAD, "defect_type": defect_id, "config": {"turbine_part_id": part_id}}
    )
    assert payload.config.turbine_part_id == part_id


def test_primary_defect_cannot_be_hidden_by_part_selection() -> None:
    with pytest.raises(ValidationError):
        build({"turbine_part_id": "tower"})


def test_an_unknown_turbine_part_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build({"turbine_part_id": "gearbox"})


# ── Defect placement ──────────────────────────────────────────────────────────


def test_every_catalogued_defect_can_be_placed_on_each_of_its_own_parts() -> None:
    for defect_id, parts in DEFECT_PART_MATRIX.items():
        for part_id in parts:
            layer = DefectLayer(defect_id=defect_id, part_id=part_id)  # type: ignore[arg-type]
            assert layer.defect_id == defect_id


def test_corrosion_is_refused_on_a_composite_blade() -> None:
    """Rust-coloured marks on a blade shell are runoff staining, not corrosion.

    Accepting this would put a wrong label in the customer's training data.
    """
    with pytest.raises(ValidationError) as failure:
        DefectLayer(defect_id="corrosion", part_id="blades")
    assert "cannot occur on the blades" in str(failure.value)


def test_runoff_staining_is_allowed_on_a_blade() -> None:
    layer = DefectLayer(defect_id="rust_staining", part_id="blades")
    assert layer.part_id == "blades"


def test_leading_edge_erosion_is_refused_on_the_tower() -> None:
    with pytest.raises(ValidationError):
        DefectLayer(defect_id="leading_edge_erosion", part_id="tower")


def test_an_unknown_defect_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DefectLayer(defect_id="gremlins", part_id="blades")  # type: ignore[arg-type]


def test_the_same_defect_cannot_be_listed_twice_on_one_part() -> None:
    with pytest.raises(ValidationError) as failure:
        build(
            {
                "defect_layers": [
                    {"defect_id": "surface_crack", "part_id": "blades"},
                    {"defect_id": "surface_crack", "part_id": "blades"},
                ]
            }
        )
    assert "listed twice" in str(failure.value)


def test_the_same_defect_on_two_different_parts_is_fine() -> None:
    config = build(
        {
            "defect_layers": [
                {"defect_id": "paint_peeling", "part_id": "blades"},
                {"defect_id": "paint_peeling", "part_id": "tower"},
            ]
        }
    ).config
    assert len(config.defect_layers) == 2


def test_a_multi_defect_selection_round_trips_with_its_parameters() -> None:
    config = build(
        {
            "turbine_part_id": "blades",
            "defect_layers": [
                {
                    "defect_id": "lightning_strike",
                    "part_id": "blades",
                    "severity": 80,
                    "coverage": 9,
                    "size_scale": 2.5,
                    "opacity": 70,
                    "rotation_deg": 135.0,
                    "spread": 25,
                    "randomness": 90,
                    "color_hex": "#a855f7",
                    "region_id": "tip-outboard",
                },
                {"defect_id": "delamination", "part_id": "blades"},
            ],
        }
    ).config

    strike = config.defect_layers[0]
    assert strike.severity == 80
    assert strike.size_scale == pytest.approx(2.5)
    assert strike.rotation_deg == pytest.approx(135.0)
    assert strike.color_hex == "#a855f7"
    assert strike.region_id == "tip-outboard"
    assert config.defect_layers[1].severity == 50


@pytest.mark.parametrize(
    "field,value",
    [
        ("severity", 101),
        ("coverage", 0),
        ("size_scale", 0.01),
        ("size_scale", 9.0),
        ("opacity", 0),
        ("rotation_deg", 400.0),
        ("color_hex", "red"),
    ],
)
def test_defect_parameters_outside_their_range_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        DefectLayer.model_validate({"defect_id": "surface_crack", "part_id": "blades", field: value})


def test_a_job_cannot_carry_an_unbounded_number_of_defect_layers() -> None:
    with pytest.raises(ValidationError):
        build(
            {
                "defect_layers": [
                    {"defect_id": "surface_crack", "part_id": part}
                    for part in ["blades", "hub", "nacelle", "tower"]
                ]
                * 4
            }
        )


def test_the_renderer_support_list_only_names_catalogued_defects() -> None:
    assert RENDERER_SUPPORTED_DEFECTS <= set(DEFECT_PART_MATRIX)


# ── Camera and angle generation ───────────────────────────────────────────────


def test_a_camera_view_carries_roll_and_field_of_view() -> None:
    view = CameraView(azimuth_deg=-55, elevation_deg=8, distance_m=220, roll_deg=15, fov_deg=35)
    assert view.roll_deg == pytest.approx(15)
    assert view.fov_deg == pytest.approx(35)


def test_a_camera_view_defaults_to_level_and_a_normal_lens() -> None:
    view = CameraView(azimuth_deg=0, elevation_deg=0, distance_m=100)
    assert view.roll_deg == 0
    assert view.fov_deg == pytest.approx(45)


@pytest.mark.parametrize("field,value", [("roll_deg", 200.0), ("fov_deg", 1.0), ("fov_deg", 200.0)])
def test_a_camera_view_outside_safe_bounds_is_rejected(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        CameraView.model_validate(
            {"azimuth_deg": 0, "elevation_deg": 0, "distance_m": 100, field: value}
        )


def test_all_angle_generation_is_accepted_on_its_own() -> None:
    assert build({"generate_all_angles": True}).config.generate_all_angles is True


def test_all_angle_generation_conflicts_with_a_pinned_camera_view() -> None:
    """One pose and every pose cannot both be true; the API says so rather than guessing."""
    with pytest.raises(ValidationError) as failure:
        build(
            {
                "generate_all_angles": True,
                "camera_view": {"azimuth_deg": 0, "elevation_deg": 5, "distance_m": 120},
            }
        )
    assert "mutually exclusive" in str(failure.value)


# ── Environments ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "environment_id",
    ["DESERT_CLEAR_V1", "MOONLIGHT_HDRI_V1", "LIGHT_SNOW_V1", "SNOW_STORM_V1"],
)
def test_the_new_environments_are_accepted(environment_id: str) -> None:
    assert build({"environment_id": environment_id}).config.environment_id == environment_id


# ── Asset import ──────────────────────────────────────────────────────────────


def test_a_binary_fbx_is_recognised_from_its_magic_bytes() -> None:
    content = b"Kaydara FBX Binary  \x00" + b"\x00" * 64
    assert detect_model_format(content, "turbine.fbx") == "fbx"


def test_an_obj_is_recognised_from_its_geometry_keywords() -> None:
    content = b"# exported from Blender\nmtllib turbine.mtl\nv 1.0 2.0 3.0\nf 1 2 3\n"
    assert detect_model_format(content, "turbine.obj") == "obj"


def test_a_renamed_file_is_refused_rather_than_trusted() -> None:
    """The browser's content type is caller-controlled, so the bytes decide."""
    with pytest.raises(ApiError) as failure:
        detect_model_format(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "turbine.fbx")
    assert failure.value.status_code == 422


def test_an_exr_is_recognised_from_its_magic_bytes() -> None:
    assert detect_environment_format(b"\x76\x2f\x31\x01rest", "sky.exr") == "exr"


def test_a_radiance_hdr_is_recognised_from_its_signature() -> None:
    content = b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 2 +X 2\n"
    assert detect_environment_format(content, "sky.hdr") == "hdr"


def test_an_unreadable_environment_map_is_refused() -> None:
    with pytest.raises(ApiError):
        detect_environment_format(b"just some text", "sky.exr")


def test_the_import_limits_match_what_the_formats_need() -> None:
    assert MODEL_ASSET.extensions == (".fbx", ".obj")
    assert ENVIRONMENT_ASSET.extensions == (".exr", ".hdr")
    # A 4K EXR runs to roughly 100 MB, so the environment limit has to clear that.
    assert ENVIRONMENT_ASSET.max_bytes > 100 * 1024 * 1024


def test_a_region_document_round_trips_through_the_job_config() -> None:
    config = build(
        {
            "region_document": {
                "name": "tip-erosion",
                "blade_model_id": "BF_CUSTOMER_TURBINE",
                "blade_model_version": "1.0.0",
                "uv_layout_checksum": "abcd1234",
                "layers": [
                    {
                        "region_id": "leading_edge_erosion-blades",
                        "layer_index": 1,
                        "display_name": "Leading-edge erosion",
                        "color_key": "leading_edge_erosion",
                        "hex_color": "#22c55e",
                        "defect_profile_id": "LEADING_EDGE_EROSION",
                        "severity_min": 20,
                        "severity_max": 60,
                        "coverage_target": 0.2,
                    }
                ],
                "strokes": [
                    {
                        "region_id": "leading_edge_erosion-blades",
                        "mode": "paint",
                        "radius_uv": 0.03,
                        "points": [[0.4, 0.1], [0.45, 0.12], [0.5, 0.11]],
                    }
                ],
            },
            "render_engine": "v2",
        }
    ).config
    assert config.render_engine == "v2"
    assert config.region_document is not None
    assert len(config.region_document.strokes) == 1
    assert config.region_document.strokes[0].points[0] == [0.4, 0.1]


def test_an_exact_surface_region_stroke_round_trips() -> None:
    config = build(
        {
            "region_document": {
                "name": "one-blade-only",
                "blade_model_id": "BF_CUSTOMER_TURBINE",
                "blade_model_version": "1.0.0",
                "uv_layout_checksum": "abcd1234",
                "schema_version": "3.0.0",
                "layers": [
                    {
                        "region_id": "red",
                        "layer_index": 1,
                        "display_name": "Red",
                        "color_key": "red",
                        "hex_color": "#e11d48",
                        "defect_profile_id": "LIGHTNING_STRIKE",
                        "severity_min": 20,
                        "severity_max": 60,
                        "coverage_target": 0.2,
                    }
                ],
                "strokes": [
                    {
                        "region_id": "red",
                        "mode": "paint",
                        "radius_uv": 0.03,
                        "points": [[0.4, 0.1], [0.45, 0.12]],
                        "surface_id": "blades:1",
                        "surface_part_id": "blades",
                        "face_indices": [100, 101],
                        "local_points": [[1.0, 2.0, 3.0], [1.1, 2.1, 3.1]],
                        "local_normals": [[0.0, 0.0, 1.0], [0.0, 0.1, 0.99]],
                    }
                ],
            }
        }
    ).config
    stroke = config.region_document.strokes[0]  # type: ignore[union-attr]
    assert stroke.surface_id == "blades:1"
    assert stroke.face_indices == [100, 101]
    assert stroke.local_points[1] == [1.1, 2.1, 3.1]


def test_schema_three_rejects_an_ambiguous_uv_only_stroke() -> None:
    with pytest.raises(ValidationError):
        build(
            {
                "region_document": {
                    "name": "ambiguous",
                    "blade_model_id": "BF_CUSTOMER_TURBINE",
                    "blade_model_version": "1.0.0",
                    "uv_layout_checksum": "abcd1234",
                    "schema_version": "3.0.0",
                    "layers": [
                        {
                            "region_id": "red",
                            "layer_index": 1,
                            "display_name": "Red",
                            "color_key": "red",
                            "hex_color": "#e11d48",
                            "defect_profile_id": "LIGHTNING_STRIKE",
                            "severity_min": 20,
                            "severity_max": 60,
                            "coverage_target": 0.2,
                        }
                    ],
                    "strokes": [
                        {
                            "region_id": "red",
                            "mode": "paint",
                            "radius_uv": 0.03,
                            "points": [[0.4, 0.1]],
                        }
                    ],
                }
            }
        )


def test_a_stroke_referencing_an_unknown_region_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build(
            {
                "region_document": {
                    "name": "bad",
                    "blade_model_id": "BF_CUSTOMER_TURBINE",
                    "blade_model_version": "1.0.0",
                    "uv_layout_checksum": "abcd1234",
                    "layers": [
                        {
                            "region_id": "leading_edge_erosion-blades",
                            "layer_index": 1,
                            "display_name": "LEE",
                            "color_key": "lee",
                            "hex_color": "#22c55e",
                            "defect_profile_id": "LEE",
                            "severity_min": 10,
                            "severity_max": 50,
                            "coverage_target": 0.1,
                        }
                    ],
                    "strokes": [
                        {
                            "region_id": "not-a-real-layer",
                            "mode": "paint",
                            "radius_uv": 0.02,
                            "points": [[0.5, 0.5]],
                        }
                    ],
                }
            }
        )


def test_render_engine_v2_is_accepted() -> None:
    assert build({"render_engine": "v2"}).config.render_engine == "v2"
