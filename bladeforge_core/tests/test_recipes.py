"""Recipe resolution: backward compatibility, reproducibility, and refusal to guess.

The two guarantees these tests defend are:

* a job submitted with the pre-upgrade payload resolves to the behaviour it had before;
* a resolved recipe is reproducible from its seed, on any machine, at any later date.
"""

from __future__ import annotations

import json
import random

import pytest

from bladeforge_core import blades, cameras, environments, outputs, recipes, regions
from bladeforge_core.defects import ALL_PROFILES, get_profile
from bladeforge_core.errors import (
    ParameterValidationError,
    RecipeResolutionError,
    RegionMaskError,
)

MODEL = blades.BF_GENERIC_BLADE_V1


def legacy(**overrides: object) -> recipes.ResolvedRecipe:
    payload: dict = {
        "defect_type": "leading_edge_erosion",
        "severity_min": 20,
        "severity_max": 80,
        "image_count": 10,
        "annotation_format": "coco_json",
        "dataset_name": "Legacy set",
        "seed": 7,
    }
    payload.update(overrides)
    return recipes.resolve_legacy_job(**payload)  # type: ignore[arg-type]


def v2(**overrides: object) -> recipes.RecipeRequest:
    payload: dict = {
        "blade_model_ref": MODEL.id,
        "defects": (recipes.DefectSelection(profile_ref="LEE_STANDARD_V1"),),
        "camera_preset_ref": cameras.DEFAULT_CAMERA_PRESET_ID,
        "environment_ref": environments.DEFAULT_ENVIRONMENT_ID,
        "output_schema_ref": outputs.DEFAULT_OUTPUT_SCHEMA_ID,
        "image_count": 12,
        "image_width": 1024,
        "image_height": 1024,
        "dataset_name": "V2 set",
        "seed": 99,
    }
    payload.update(overrides)
    return recipes.RecipeRequest(**payload)


def painted() -> regions.RegionStrokeDocument:
    le_u, le_v = MODEL.uv_layout.landmarks["midspan_leading_edge"]
    tip_u, tip_v = MODEL.uv_layout.landmarks["tip_leading_edge"]
    return regions.RegionStrokeDocument(
        name="Regions",
        blade_model_id=MODEL.id,
        blade_model_version=MODEL.version,
        uv_set_name=MODEL.uv_layout.uv_set_name,
        uv_layout_checksum=MODEL.uv_layout_checksum,
        mask_width=512,
        mask_height=256,
        layers=(
            regions.RegionLayer(
                region_id="erosion-band", layer_index=1, display_name="Erosion",
                color_key="green", hex_color="#22c55e",
                defect_profile_id="LEE_STANDARD_V1", defect_profile_version="1.0.0",
                severity_min=40.0, severity_max=85.0, coverage_target=0.06,
            ),
            regions.RegionLayer(
                region_id="strike-zone", layer_index=2, display_name="Lightning",
                color_key="red", hex_color="#ef4444",
                defect_profile_id="LIGHTNING_STRIKE_STANDARD_V1",
                defect_profile_version="1.0.0",
                severity_min=70.0, severity_max=95.0, coverage_target=0.03,
            ),
        ),
        strokes=(
            regions.BrushStroke(
                "erosion-band", regions.PAINT, 0.02,
                ((le_u, le_v), (le_u + 0.25, le_v)),
            ),
            regions.BrushStroke("strike-zone", regions.PAINT, 0.04, ((tip_u, tip_v),)),
        ),
    )


# ---------------------------------------------------------------------------
# Legacy compatibility
# ---------------------------------------------------------------------------


def test_legacy_payload_resolves_to_legacy_registry_entries() -> None:
    resolved = legacy()
    assert resolved.blade_model.id == blades.LEGACY_BLADE_MODEL_ID
    assert resolved.camera_preset.id == cameras.LEGACY_CAMERA_PRESET_ID
    assert resolved.output_schema.id == "LEGACY_COCO_OUTPUT_V1"
    assert resolved.defect_profiles[0].id == "LEE_STANDARD_V1"


def test_legacy_payload_is_preserved_verbatim_in_the_snapshot() -> None:
    """The original request has to survive so a legacy job can be re-run exactly."""
    resolved = legacy()
    stored = resolved.request.legacy_payload
    assert stored is not None
    assert stored["defect_type"] == "leading_edge_erosion"
    assert stored["annotation_format"] == "coco_json"
    assert stored["severity_min"] == 20
    assert stored["severity_max"] == 80


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        ("overcast", "OVERCAST_DAY_V1"),
        ("golden_hour", "GOLDEN_HOUR_V1"),
        ("midday", "CLEAR_DAY_V1"),
        ("cloudy", "CLOUDY_DAY_V1"),
    ],
)
def test_every_legacy_lighting_preset_maps_to_an_environment(
    preset: str, expected: str
) -> None:
    assert legacy(config={"lighting_preset": preset}).environment.id == expected


@pytest.mark.parametrize(
    ("annotation_format", "expected"),
    [("coco_json", "LEGACY_COCO_OUTPUT_V1"), ("yolo_v8", "LEGACY_YOLO_OUTPUT_V1")],
)
def test_both_legacy_annotation_formats_resolve(
    annotation_format: str, expected: str
) -> None:
    assert legacy(annotation_format=annotation_format).output_schema.id == expected


def test_legacy_compatibility_path_does_not_invent_weather() -> None:
    """The old renderer had no weather model, so the mapped scene stays at its mildest."""
    resolved = legacy(config={"lighting_preset": "overcast"})
    assert resolved.request.weather_intensity == 0.0
    sample = resolved.resolve_sample(0)
    assert not sample.environment.has_active_precipitation
    assert not sample.sensor.motion_blur_enabled


def test_legacy_resolution_and_severity_are_honoured() -> None:
    resolved = legacy(config={"image_width": 800, "image_height": 600})
    assert resolved.request.image_width == 800
    assert resolved.request.image_height == 600
    for index in range(resolved.request.image_count):
        severity = resolved.resolve_sample(index).defects[0].severity
        assert 20.0 <= severity <= 80.0


def test_legacy_camera_fov_is_now_actually_correct() -> None:
    """The pre-upgrade focal-length formula produced roughly half the requested angle."""
    resolved = legacy(config={"camera_fov": 45})
    camera = resolved.resolve_sample(0).camera
    assert abs(camera.blender_angle_deg - 45.0) < 0.01
    legacy_focal = cameras.legacy_focal_length_mm_from_fov(45.0)
    assert abs(camera.focal_length_mm - legacy_focal) > 5.0, (
        "The corrected focal length should differ noticeably from the buggy one."
    )


def test_legacy_path_does_not_depend_on_v2_assets() -> None:
    """A legacy job must resolve even with every v2-only capability switched off."""
    resolved = legacy()
    assert resolved.blade_model.source == blades.BUILTIN_PROCEDURAL
    assert resolved.region_mask is None
    assert resolved.request.camera_view is None


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


def test_same_seed_gives_an_identical_checksum_and_plan() -> None:
    a, b = legacy(seed=42), legacy(seed=42)
    assert a.checksum == b.checksum
    assert a.resolve_sample(3).as_dict() == b.resolve_sample(3).as_dict()


def test_different_seed_gives_a_different_plan() -> None:
    a, b = legacy(seed=42), legacy(seed=43)
    assert a.checksum != b.checksum
    assert a.resolve_sample(0).as_dict() != b.resolve_sample(0).as_dict()


def test_per_sample_seeds_are_unique_and_uncorrelated() -> None:
    resolved = legacy(image_count=64)
    seeds = [resolved.resolve_sample(i).seed for i in range(64)]
    assert len(set(seeds)) == 64
    # Hashed derivation, so consecutive seeds must not be consecutive integers.
    deltas = {seeds[i + 1] - seeds[i] for i in range(len(seeds) - 1)}
    assert len(deltas) > 1


def test_sample_index_outside_the_job_is_rejected() -> None:
    resolved = legacy(image_count=4)
    with pytest.raises(RecipeResolutionError, match="outside"):
        resolved.resolve_sample(4)
    with pytest.raises(RecipeResolutionError, match="outside"):
        resolved.resolve_sample(-1)


def test_checksum_ignores_how_many_sample_plans_are_embedded() -> None:
    """Embedded plans are derivable, so they must not perturb the recipe identity."""
    import dataclasses

    resolved = legacy(seed=5)
    stripped = dataclasses.replace(resolved, sample_plans=())
    assert stripped.checksum == resolved.checksum


def test_only_a_bounded_number_of_plans_is_embedded() -> None:
    resolved = legacy(image_count=5000)
    assert len(resolved.sample_plans) == recipes.EMBEDDED_SAMPLE_PLAN_LIMIT
    assert resolved.request.image_count == 5000


def test_snapshot_is_json_serialisable_and_carries_its_checksum() -> None:
    resolved = legacy()
    snapshot = resolved.snapshot()
    encoded = json.dumps(snapshot, sort_keys=True)
    assert json.loads(encoded)["checksum_sha256"] == resolved.checksum
    assert snapshot["sample_plans_total"] == resolved.request.image_count


def test_snapshot_records_every_registry_checksum() -> None:
    """Without these, a dataset cannot be traced back to the registries that made it."""
    checksums = legacy().registry_checksums()
    assert set(checksums) == {
        "blade_models",
        "cameras",
        "defects",
        "environments",
        "materials",
        "outputs",
        "taxonomy",
    }
    assert all(len(value) == 64 for value in checksums.values())


def test_snapshot_stays_small_enough_for_a_database_column() -> None:
    encoded = json.dumps(legacy(image_count=20_000).snapshot())
    assert len(encoded) < 400_000, len(encoded)


# ---------------------------------------------------------------------------
# v2 resolution
# ---------------------------------------------------------------------------


def test_v2_multi_defect_with_painted_regions_resolves() -> None:
    resolved = recipes.resolve_recipe(
        v2(
            section_ids=("outboard", "tip"),
            defects=(
                recipes.DefectSelection(
                    profile_ref="LIGHTNING_STRIKE_STANDARD_V1",
                    severity_min=70.0,
                    severity_max=95.0,
                    region_id="strike-zone",
                ),
                recipes.DefectSelection(
                    profile_ref="DELAMINATION_STANDARD_V1",
                    role=recipes.SECONDARY,
                    severity_min=30.0,
                    severity_max=60.0,
                ),
            ),
            environment_ref="HEAVY_RAIN_STORM_V1",
            output_schema_ref="FULL_ANALYSIS_OUTPUT_V1",
            region_document=painted(),
            weather_intensity=0.85,
        )
    )
    assert [section.id for section in resolved.sections] == ["outboard", "tip"]
    assert resolved.region_mask is not None
    sample = resolved.resolve_sample(0)
    roles = {defect.role for defect in sample.defects}
    assert roles == {recipes.PRIMARY, recipes.SECONDARY}
    primary = next(d for d in sample.defects if d.role == recipes.PRIMARY)
    assert primary.region_id == "strike-zone"


def test_defect_stays_bound_to_its_painted_region_across_every_sample() -> None:
    resolved = recipes.resolve_recipe(
        v2(
            defects=(
                recipes.DefectSelection(
                    profile_ref="LEE_STANDARD_V1", region_id="erosion-band"
                ),
            ),
            region_document=painted(),
            image_count=20,
        )
    )
    for index in range(20):
        for defect in resolved.resolve_sample(index).defects:
            assert defect.region_id == "erosion-band"


def test_selected_sections_drive_the_camera_target() -> None:
    """Choosing which part of the blade to photograph has to actually aim the camera."""
    tip = recipes.resolve_recipe(v2(section_ids=("tip",)))
    root = recipes.resolve_recipe(v2(section_ids=("root_transition",)))
    tip_target = tip.resolve_sample(0).camera.target_m[2]
    root_target = root.resolve_sample(0).camera.target_m[2]
    assert tip_target > root_target
    assert tip_target > MODEL.length_m * 0.8
    assert root_target < MODEL.length_m * 0.2


def test_instance_counts_produce_multiple_defect_instances() -> None:
    resolved = recipes.resolve_recipe(
        v2(
            defects=(
                recipes.DefectSelection(
                    profile_ref="SURFACE_CRACK_STANDARD_V1",
                    instance_count_min=3,
                    instance_count_max=3,
                ),
            )
        )
    )
    sample = resolved.resolve_sample(0)
    assert len(sample.defects) == 3
    assert {d.instance_index for d in sample.defects} == {0, 1, 2}


def test_presence_probability_produces_a_mixed_dataset() -> None:
    resolved = recipes.resolve_recipe(
        v2(
            defects=(
                recipes.DefectSelection(profile_ref="LEE_STANDARD_V1"),
                recipes.DefectSelection(
                    profile_ref="COATING_FAILURE_STANDARD_V1",
                    role=recipes.SECONDARY,
                    presence_probability=0.5,
                ),
            ),
            image_count=60,
        )
    )
    counts = [len(resolved.resolve_sample(i).defects) for i in range(60)]
    assert min(counts) == 1
    assert max(counts) == 2


def test_weather_intensity_randomization_varies_per_sample() -> None:
    resolved = recipes.resolve_recipe(
        v2(
            environment_ref="HEAVY_RAIN_STORM_V1",
            output_schema_ref="FULL_ANALYSIS_OUTPUT_V1",
            randomization=recipes.RandomizationSpec(weather_intensity_range=(0.0, 1.0)),
            image_count=20,
        )
    )
    rates = {
        round(resolved.resolve_sample(i).environment.weather["precipitation_rate_mm_h"], 3)
        for i in range(20)
    }
    assert len(rates) > 5


def test_every_randomized_parameter_is_recorded_per_sample() -> None:
    sample = recipes.resolve_recipe(v2()).resolve_sample(0)
    recorded = sample.as_dict()
    assert set(recorded["sensor"]) >= {
        "exposure_ev_offset",
        "iso_scale",
        "jpeg_quality",
        "lens_distortion_enabled",
        "chromatic_aberration",
        "sensor_noise_enabled",
        "motion_blur_enabled",
        "motion_blur_shutter",
        "motion_blur_mask_policy",
    }
    assert set(recorded["surface"]) == {
        "dirt_amount",
        "manufacturing_variation",
        "surface_contamination",
        "wetness",
    }
    assert recorded["camera"]["focal_length_mm"] > 0
    assert recorded["environment"]["weather"]


def test_motion_blur_mask_policy_comes_from_the_output_schema() -> None:
    """When blur is on, the mask's meaning must be stated, never assumed."""
    sharp = recipes.resolve_recipe(
        v2(output_schema_ref="FULL_ANALYSIS_OUTPUT_V1", environment_ref="HEAVY_RAIN_STORM_V1")
    )
    visible = recipes.resolve_recipe(v2(output_schema_ref="STANDARD_DETECTION_OUTPUT_V1"))
    assert sharp.resolve_sample(0).sensor.motion_blur_mask_policy == (
        outputs.MotionBlurMaskPolicy.SHARP_GEOMETRY
    )
    assert visible.resolve_sample(0).sensor.motion_blur_mask_policy == (
        outputs.MotionBlurMaskPolicy.VISIBLE_COVERAGE
    )


def test_crop_choice_flows_through_to_the_resolved_schema() -> None:
    """Whole image, damaged part, or both: the customer's choice must be recorded."""
    for policy in outputs.CropPolicy.ALL:
        resolved = recipes.resolve_recipe(
            v2(output_schema_ref="FULL_ANALYSIS_OUTPUT_V1", crop_policy=policy)
        )
        assert resolved.output_schema.crop_policy == policy
        assert resolved.snapshot()["output_schema"]["crop_policy"] == policy


def test_size_estimate_scales_with_pixels_and_count() -> None:
    small = recipes.resolve_recipe(v2(image_count=10, image_width=512, image_height=512))
    large = recipes.resolve_recipe(v2(image_count=100, image_width=1024, image_height=1024))
    assert small.estimated_total_bytes() > 0
    assert large.estimated_total_bytes() > small.estimated_total_bytes() * 30


def test_random_seed_policy_produces_a_seed_and_records_it() -> None:
    resolved = recipes.resolve_recipe(
        v2(seed=None, seed_policy=recipes.SEED_POLICY_RANDOM)
    )
    assert resolved.master_seed > 0
    assert resolved.request.seed == resolved.master_seed


def test_category_ids_are_collected_from_the_selected_profiles() -> None:
    resolved = recipes.resolve_recipe(
        v2(defects=(recipes.DefectSelection(profile_ref="CORROSION_RUST_STANDARD_V1"),))
    )
    profile = get_profile("CORROSION_RUST_STANDARD_V1")
    assert set(resolved.category_ids) == set(profile.emitted_category_ids)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_corrosion_on_a_model_without_metal_is_refused_with_an_alternative() -> None:
    with pytest.raises(RecipeResolutionError, match="rust runoff staining"):
        recipes.resolve_recipe(
            v2(
                blade_model_ref=blades.LEGACY_BLADE_MODEL_ID,
                defects=(
                    recipes.DefectSelection(profile_ref="CORROSION_RUST_STANDARD_V1"),
                ),
            )
        )


def test_unknown_blade_section_lists_the_valid_ones() -> None:
    with pytest.raises(RecipeResolutionError, match="Available sections"):
        recipes.resolve_recipe(v2(section_ids=("nonexistent",)))


def test_two_primary_defects_are_refused() -> None:
    with pytest.raises(ParameterValidationError, match="Exactly one primary"):
        v2(
            defects=(
                recipes.DefectSelection(profile_ref="LEE_STANDARD_V1"),
                recipes.DefectSelection(profile_ref="SURFACE_CRACK_STANDARD_V1"),
            )
        )


def test_no_defect_at_all_is_refused() -> None:
    with pytest.raises(ParameterValidationError, match="at least one defect"):
        v2(defects=())


def test_unvalidated_defect_combination_is_refused() -> None:
    with pytest.raises(ParameterValidationError, match="not a validated combination"):
        recipes.resolve_recipe(
            v2(
                defects=(
                    recipes.DefectSelection(profile_ref="LEE_STANDARD_V1"),
                    recipes.DefectSelection(
                        profile_ref="CORROSION_RUNOFF_STAINING_V1",
                        role=recipes.SECONDARY,
                    ),
                )
            )
        )


def test_a_profile_that_is_not_a_valid_secondary_is_refused() -> None:
    with pytest.raises(RecipeResolutionError, match="not supported as secondary"):
        recipes.resolve_recipe(
            v2(
                defects=(
                    recipes.DefectSelection(profile_ref="LEE_STANDARD_V1"),
                    recipes.DefectSelection(
                        profile_ref="LIGHTNING_STRIKE_STANDARD_V1",
                        role=recipes.SECONDARY,
                    ),
                )
            )
        )


def test_subsurface_only_profile_cannot_be_the_primary_defect() -> None:
    with pytest.raises(RecipeResolutionError, match="cannot be used as the primary"):
        recipes.resolve_recipe(
            v2(defects=(recipes.DefectSelection(profile_ref="DELAMINATION_SUBSURFACE_V1"),))
        )


def test_fixed_seed_without_a_seed_is_refused() -> None:
    with pytest.raises(ParameterValidationError, match="reproducible"):
        recipes.resolve_recipe(v2(seed=None))


def test_region_reference_without_a_region_document_is_refused() -> None:
    with pytest.raises(RegionMaskError, match="no painted region set"):
        recipes.resolve_recipe(
            v2(
                defects=(
                    recipes.DefectSelection(
                        profile_ref="LEE_STANDARD_V1", region_id="erosion-band"
                    ),
                )
            )
        )


def test_defect_pointing_at_a_missing_layer_lists_the_available_ones() -> None:
    with pytest.raises(RegionMaskError, match="Available layers"):
        recipes.resolve_recipe(
            v2(
                defects=(
                    recipes.DefectSelection(
                        profile_ref="LEE_STANDARD_V1", region_id="does-not-exist"
                    ),
                ),
                region_document=painted(),
            )
        )


def test_region_bound_to_a_different_profile_is_refused() -> None:
    with pytest.raises(RegionMaskError, match="is bound to"):
        recipes.resolve_recipe(
            v2(
                defects=(
                    recipes.DefectSelection(
                        profile_ref="COATING_FAILURE_STANDARD_V1",
                        region_id="erosion-band",
                    ),
                ),
                region_document=painted(),
            )
        )


def test_a_region_layer_with_no_paint_is_refused() -> None:
    import dataclasses

    document = painted()
    empty = dataclasses.replace(document, strokes=document.strokes[:1])
    with pytest.raises(RegionMaskError, match="no painted area"):
        recipes.resolve_recipe(
            v2(
                defects=(
                    recipes.DefectSelection(
                        profile_ref="LEE_STANDARD_V1", region_id="erosion-band"
                    ),
                ),
                region_document=empty,
            )
        )


def test_stale_painted_region_is_refused_at_submission() -> None:
    import dataclasses

    stale = dataclasses.replace(painted(), uv_layout_checksum="0" * 64)
    with pytest.raises(RegionMaskError, match="[Rr]epaint"):
        recipes.resolve_recipe(
            v2(
                defects=(
                    recipes.DefectSelection(
                        profile_ref="LEE_STANDARD_V1", region_id="erosion-band"
                    ),
                ),
                region_document=stale,
            )
        )


def test_unknown_weather_parameter_override_is_refused() -> None:
    with pytest.raises(ParameterValidationError, match="no weather parameter"):
        recipes.resolve_recipe(v2(weather_overrides={"not_real": 1.0}))


@pytest.mark.parametrize("count", [0, recipes.MAX_IMAGE_COUNT + 1])
def test_implausible_image_count_is_refused(count: int) -> None:
    with pytest.raises(ParameterValidationError, match="image_count"):
        v2(image_count=count)


@pytest.mark.parametrize(("width", "height"), [(64, 1024), (1024, 99999)])
def test_out_of_range_resolution_is_refused(width: int, height: int) -> None:
    with pytest.raises(ParameterValidationError, match="image_(width|height)"):
        v2(image_width=width, image_height=height)


def test_disabled_capability_is_refused_rather_than_silently_substituted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLADEFORGE_FLAG_ENVIRONMENT_HEAVY_RAIN_STORM_V1", "0")
    with pytest.raises(RecipeResolutionError, match="not available on this deployment"):
        recipes.resolve_recipe(v2(environment_ref="HEAVY_RAIN_STORM_V1"))


def test_disabling_region_painting_refuses_a_painted_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BLADEFORGE_FLAG_REGION_PAINTING", "0")
    with pytest.raises(RecipeResolutionError, match="not available on this deployment"):
        recipes.resolve_recipe(v2(region_document=painted()))


# ---------------------------------------------------------------------------
# Camera views
# ---------------------------------------------------------------------------


def test_a_saved_camera_view_is_clamped_into_the_preset_envelope() -> None:
    """The browser never gets to dictate an arbitrary transform."""
    preset = cameras.get_camera_preset(cameras.DEFAULT_CAMERA_PRESET_ID)
    wild = cameras.CameraViewRequest(
        target_m=(0.0, 0.0, 30.0),
        azimuth_deg=1234.0,
        elevation_deg=89.0,
        distance_m=9_999.0,
    )
    resolved = recipes.resolve_recipe(v2(camera_view=wild))
    camera = resolved.resolve_sample(0).camera
    assert preset.pose.distance_m_min <= camera.distance_m <= preset.pose.distance_m_max
    assert preset.pose.elevation_deg_min <= camera.elevation_deg <= preset.pose.elevation_deg_max
    assert -180.0 <= camera.azimuth_deg <= 180.0


def saved_view() -> cameras.CameraViewRequest:
    return cameras.CameraViewRequest(
        target_m=(0.0, 0.0, 25.0), azimuth_deg=42.0, elevation_deg=8.0, distance_m=14.0
    )


def test_a_saved_camera_view_is_exact_when_the_air_is_still() -> None:
    resolved = recipes.resolve_recipe(
        v2(
            camera_view=saved_view(),
            image_count=6,
            weather_overrides={"camera_stability": 1.0},
        )
    )
    poses = {
        (
            round(resolved.resolve_sample(i).camera.distance_m, 6),
            round(resolved.resolve_sample(i).camera.azimuth_deg, 6),
            round(resolved.resolve_sample(i).camera.elevation_deg, 6),
        )
        for i in range(6)
    }
    assert poses == {(14.0, 42.0, 8.0)}


def test_a_saved_camera_view_only_drifts_by_the_declared_wind_jitter() -> None:
    """Wind moves a hovering drone slightly. It must not wander off the saved shot."""
    resolved = recipes.resolve_recipe(v2(camera_view=saved_view(), image_count=12))
    for index in range(12):
        camera = resolved.resolve_sample(index).camera
        assert abs(camera.distance_m - 14.0) < 0.5
        assert abs(camera.azimuth_deg - 42.0) < 2.0
        assert abs(camera.elevation_deg - 8.0) < 2.0


def test_a_non_finite_camera_view_is_refused() -> None:
    preset = cameras.get_camera_preset(cameras.DEFAULT_CAMERA_PRESET_ID)
    with pytest.raises(ParameterValidationError):
        cameras.validate_camera_view(
            preset,
            cameras.CameraViewRequest(
                target_m=(0.0, float("nan"), 0.0),
                azimuth_deg=0.0,
                elevation_deg=0.0,
                distance_m=10.0,
            ),
        )


# ---------------------------------------------------------------------------
# Every advertised defect must resolve
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "profile", [p for p in ALL_PROFILES if p.supports_as_primary], ids=lambda p: p.id
)
def test_every_primary_profile_resolves_with_in_range_parameters(profile: object) -> None:
    resolved = recipes.resolve_recipe(
        v2(
            defects=(
                recipes.DefectSelection(
                    profile_ref=profile.id, severity_min=5.0, severity_max=95.0
                ),
            ),
            image_count=12,
        )
    )
    for index in range(12):
        for defect in resolved.resolve_sample(index).defects:
            assert defect.parameters
            assert defect.severity_band in {"early", "moderate", "severe"}
            for name, value in defect.parameters.items():
                spec = profile.parameter(name)
                assert spec.absolute_min <= value <= spec.absolute_max, (name, value)


@pytest.mark.parametrize(
    "band_bounds", [(0.0, 33.0), (34.0, 66.0), (67.0, 100.0)],
    ids=["early", "moderate", "severe"],
)
def test_severity_bands_are_independently_selectable(band_bounds: tuple) -> None:
    low, high = band_bounds
    resolved = recipes.resolve_recipe(
        v2(
            defects=(
                recipes.DefectSelection(
                    profile_ref="LEE_STANDARD_V1", severity_min=low, severity_max=high
                ),
            ),
            image_count=8,
        )
    )
    bands = {resolved.resolve_sample(i).defects[0].severity_band for i in range(8)}
    assert len(bands) == 1, bands


def test_severity_ranges_map_to_increasing_erosion_depth() -> None:
    """Severity has to move the physical parameters, not just a label."""
    depths = []
    for low, high in ((0.0, 20.0), (40.0, 60.0), (85.0, 100.0)):
        resolved = recipes.resolve_recipe(
            v2(
                defects=(
                    recipes.DefectSelection(
                        profile_ref="LEE_STANDARD_V1", severity_min=low, severity_max=high
                    ),
                ),
                image_count=16,
            )
        )
        samples = [resolved.resolve_sample(i).defects[0] for i in range(16)]
        depths.append(
            sum(d.parameters["erosion_depth_mm"] for d in samples) / len(samples)
        )
    assert depths[0] < depths[1] < depths[2], depths


def test_physical_parameters_carry_explicit_units() -> None:
    sample = recipes.resolve_recipe(v2()).resolve_sample(0)
    defect = sample.defects[0]
    assert defect.parameter_units
    assert set(defect.parameter_units) == set(defect.parameters)
    assert any(unit == "mm" for unit in defect.parameter_units.values()), (
        "erosion geometry must be recorded in millimetres, not unitless numbers"
    )


def test_random_module_state_does_not_leak_into_resolution() -> None:
    """Resolution must not depend on global RNG state, or reruns would drift."""
    random.seed(1)
    first = recipes.resolve_recipe(v2()).resolve_sample(0).as_dict()
    random.seed(999)
    [random.random() for _ in range(50)]
    second = recipes.resolve_recipe(v2()).resolve_sample(0).as_dict()
    assert first == second
