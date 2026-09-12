"""Invariants every registry entry must satisfy, whatever else changes.

These are the tests that stop a capability from being advertised before it works, stop a
released category ID from ever being reused, and stop a registry entry from referencing a
feature flag that does not exist.
"""

from __future__ import annotations

import pytest

from bladeforge_core import (
    blades,
    cameras,
    environments,
    flags,
    materials,
    outputs,
    taxonomy,
)
from bladeforge_core.defects import ALL_PROFILES
from bladeforge_core.versioning import REGISTRY_ID, ReleaseStatus, SemanticVersion


def all_versioned_entries() -> list[object]:
    return [
        *blades.ALL_BLADE_MODELS,
        *cameras.ALL_CAMERA_PRESETS,
        *environments.ALL_ENVIRONMENTS,
        *outputs.ALL_OUTPUT_SCHEMAS,
        *ALL_PROFILES,
        *materials.ALL_MATERIALS,
    ]


@pytest.mark.parametrize("entry", all_versioned_entries(), ids=lambda e: e.id)
def test_registry_ids_and_versions_are_well_formed(entry: object) -> None:
    assert REGISTRY_ID.match(entry.id), entry.id
    SemanticVersion.parse(entry.version)
    assert entry.status in ReleaseStatus.ALL


@pytest.mark.parametrize("entry", all_versioned_entries(), ids=lambda e: e.id)
def test_every_entry_has_a_stable_checksum(entry: object) -> None:
    first = entry.checksum
    assert len(first) == 64
    assert first == entry.checksum


def licensed_entries() -> list[object]:
    """Entries that describe an asset. Output schemas are file layouts, not assets."""
    return [
        *blades.ALL_BLADE_MODELS,
        *cameras.ALL_CAMERA_PRESETS,
        *environments.ALL_ENVIRONMENTS,
        *ALL_PROFILES,
        *materials.ALL_MATERIALS,
        taxonomy.ACTIVE_TAXONOMY,
    ]


@pytest.mark.parametrize("entry", licensed_entries(), ids=lambda e: e.id)
def test_every_licensed_entry_has_a_license_record(entry: object) -> None:
    record = entry.license
    assert record.source
    assert record.owner
    assert record.license_name
    assert record.review_status in {"pending", "approved", "rejected", "customer_attested"}


def test_registry_ids_are_globally_unique_per_kind() -> None:
    for group in (
        blades.ALL_BLADE_MODELS,
        cameras.ALL_CAMERA_PRESETS,
        environments.ALL_ENVIRONMENTS,
        outputs.ALL_OUTPUT_SCHEMAS,
        ALL_PROFILES,
        materials.ALL_MATERIALS,
    ):
        ids = [entry.id for entry in group]
        assert len(set(ids)) == len(ids), ids


def flagged_entries() -> list[object]:
    return [
        *blades.ALL_BLADE_MODELS,
        *cameras.ALL_CAMERA_PRESETS,
        *environments.ALL_ENVIRONMENTS,
        *outputs.ALL_OUTPUT_SCHEMAS,
        *ALL_PROFILES,
    ]


@pytest.mark.parametrize("entry", flagged_entries(), ids=lambda e: e.id)
def test_every_flagged_entry_declares_a_known_flag(entry: object) -> None:
    """A registry entry pointing at an undeclared flag would be silently unreachable."""
    assert entry.feature_flag in flags.FLAGS, (
        f"{entry.id} references feature flag {entry.feature_flag!r}, which is not "
        "declared in bladeforge_core.flags.FLAGS."
    )


def test_flag_dependencies_resolve() -> None:
    for key, flag in flags.FLAGS.items():
        for dependency in flag.requires:
            assert dependency in flags.FLAGS, f"{key} requires unknown flag {dependency!r}"


def test_billing_stays_disabled() -> None:
    """Billing is deliberately off until the validation workflow can prove value."""
    assert not flags.is_enabled("billing")


def test_unknown_flag_is_treated_as_disabled() -> None:
    assert not flags.is_enabled("definitely_not_a_real_flag")


def test_flag_can_be_disabled_through_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    assert flags.is_enabled("defect_lee_standard_v1")
    monkeypatch.setenv("BLADEFORGE_FLAG_DEFECT_LEE_STANDARD_V1", "0")
    assert not flags.is_enabled("defect_lee_standard_v1")


def test_flag_allowlist_disables_everything_else(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLADEFORGE_FLAGS", "defect_lee_standard_v1")
    assert flags.is_enabled("defect_lee_standard_v1")
    assert not flags.is_enabled("defect_lightning_strike_standard_v1")


def test_render_engine_defaults_to_v2_and_accepts_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RENDER_ENGINE_VERSION", raising=False)
    assert flags.render_engine_version() == flags.RENDER_ENGINE_V2
    monkeypatch.setenv("RENDER_ENGINE_VERSION", "legacy")
    assert flags.render_engine_version() == flags.RENDER_ENGINE_LEGACY
    monkeypatch.setenv("RENDER_ENGINE_VERSION", "nonsense")
    assert flags.render_engine_version() == flags.RENDER_ENGINE_V2


def test_disabling_renderer_v2_falls_back_to_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_ENGINE_VERSION", "v2")
    monkeypatch.setenv("BLADEFORGE_FLAG_RENDERER_V2", "0")
    assert flags.render_engine_version() == flags.RENDER_ENGINE_LEGACY


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

# The released category IDs. A dataset trained against these must never see one of
# them mean something different, so this list is append-only by construction: adding a
# category here is fine, changing or removing an entry is a breaking change.
RELEASED_CATEGORY_IDS: dict[int, str] = {
    1: "leading_edge_erosion",
    2: "lightning_strike_damage",
    3: "surface_crack",
    4: "delamination",
    5: "coating_failure",
    6: "corrosion_rust",
}


def test_released_category_ids_never_change() -> None:
    active = taxonomy.ACTIVE_TAXONOMY
    for category_id, name in RELEASED_CATEGORY_IDS.items():
        assert active.by_id(category_id).name == name, (
            f"Category id {category_id} was released as {name!r} and must keep that "
            "meaning forever. Add a new id instead of repurposing this one."
        )


def test_background_id_is_reserved() -> None:
    assert taxonomy.BACKGROUND_ID == 0
    assert all(category.id != 0 for category in taxonomy.ACTIVE_TAXONOMY.categories)


def test_category_ids_are_unique_and_in_band() -> None:
    active = taxonomy.ACTIVE_TAXONOMY
    ids = [category.id for category in active.categories]
    assert len(set(ids)) == len(ids)
    for category in active.categories:
        if category.structural:
            assert taxonomy.STRUCTURAL_ID_MIN <= category.id <= taxonomy.STRUCTURAL_ID_MAX
        else:
            assert taxonomy.DEFECT_ID_MIN <= category.id <= taxonomy.DEFECT_ID_MAX


def test_taxonomy_checksum_is_stable() -> None:
    assert taxonomy.ACTIVE_TAXONOMY.checksum == taxonomy.ACTIVE_TAXONOMY.checksum


def test_coco_categories_are_valid() -> None:
    categories = taxonomy.ACTIVE_TAXONOMY.coco_categories()
    assert categories
    for entry in categories:
        assert set(entry) >= {"id", "name", "supercategory"}
        assert isinstance(entry["id"], int)
        assert entry["id"] > 0


# ---------------------------------------------------------------------------
# Defect profiles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile", ALL_PROFILES, ids=lambda p: p.id)
def test_profile_declares_ranges_for_every_parameter_in_every_band(profile: object) -> None:
    """A missing band range would mean a parameter silently falls back to a default."""
    names = {spec.name for spec in profile.parameters}
    for band in ("early", "moderate", "severe"):
        assert band in profile.bands, f"{profile.id} has no {band} band."
        assert set(profile.bands[band]) == names, (
            f"{profile.id} band {band} does not cover exactly its declared parameters. "
            f"Missing: {sorted(names - set(profile.bands[band]))}. "
            f"Unexpected: {sorted(set(profile.bands[band]) - names)}."
        )


@pytest.mark.parametrize("profile", ALL_PROFILES, ids=lambda p: p.id)
def test_profile_band_ranges_stay_inside_absolute_limits(profile: object) -> None:
    for band, ranges in profile.bands.items():
        for name, band_range in ranges.items():
            spec = profile.parameter(name)
            assert spec.absolute_min <= band_range.minimum, (profile.id, band, name)
            assert band_range.maximum <= spec.absolute_max, (profile.id, band, name)


@pytest.mark.parametrize("profile", ALL_PROFILES, ids=lambda p: p.id)
def test_profile_primary_category_is_emitted(profile: object) -> None:
    assert profile.primary_category in profile.emitted_categories
    assert profile.primary_category_id in profile.emitted_category_ids


@pytest.mark.parametrize("profile", ALL_PROFILES, ids=lambda p: p.id)
def test_profile_renderer_key_has_a_material_set(profile: object) -> None:
    """Every advertised defect must have materials its Blender implementation can use."""
    assert materials.defect_materials_for_renderer_key(profile.renderer_key)


def test_validated_secondary_profiles_exist_and_support_the_role() -> None:
    from bladeforge_core.defects import get_profile

    for profile in ALL_PROFILES:
        for secondary_id in profile.validated_secondary_profiles:
            secondary = get_profile(secondary_id)
            assert secondary.supports_as_secondary, (
                f"{profile.id} lists {secondary_id} as a validated secondary, but that "
                "profile does not support the secondary role."
            )


def test_corrosion_on_composite_is_labelled_as_staining_not_corrosion() -> None:
    """Fiberglass does not rust. The registry must not claim otherwise."""
    from bladeforge_core.defects import get_profile

    metallic = get_profile("CORROSION_RUST_STANDARD_V1")
    staining = get_profile("CORROSION_RUNOFF_STAINING_V1")
    assert metallic.requires_metallic_context
    assert not staining.requires_metallic_context
    assert "corrosion_rust" == metallic.primary_category
    assert "corrosion_rust" != staining.primary_category
    assert "stain" in staining.primary_category or "runoff" in staining.primary_category


def test_subsurface_delamination_does_not_claim_a_visible_mask() -> None:
    from bladeforge_core.defects import get_profile

    subsurface = get_profile("DELAMINATION_SUBSURFACE_V1")
    surface = get_profile("DELAMINATION_STANDARD_V1")
    assert not subsurface.produces_visible_mask
    assert surface.produces_visible_mask


def test_all_six_requested_defect_families_are_present_and_selectable() -> None:
    from bladeforge_core.defects import primary_selectable_profiles

    required = {
        "LEE_STANDARD_V1",
        "LIGHTNING_STRIKE_STANDARD_V1",
        "SURFACE_CRACK_STANDARD_V1",
        "DELAMINATION_STANDARD_V1",
        "COATING_FAILURE_STANDARD_V1",
        "CORROSION_RUST_STANDARD_V1",
    }
    available = {profile.id for profile in primary_selectable_profiles()}
    assert required <= available, sorted(required - available)


# ---------------------------------------------------------------------------
# Blade models
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", blades.ALL_BLADE_MODELS, ids=lambda m: m.id)
def test_blade_sections_tile_the_span_exactly(model: object) -> None:
    covered = 0.0
    for section in model.sections:
        assert abs(section.span_start_fraction - covered) < 1e-9, model.id
        covered = section.span_end_fraction
    assert abs(covered - 1.0) < 1e-9, model.id


@pytest.mark.parametrize("model", blades.ALL_BLADE_MODELS, ids=lambda m: m.id)
def test_blade_material_slots_resolve(model: object) -> None:
    resolved = materials.materials_for_slots(model.material_slots)
    assert len(resolved) >= len(model.material_slots)


def test_generic_blade_is_realistic_and_paintable() -> None:
    model = blades.BF_GENERIC_BLADE_V1
    assert model.units_per_metre == 1.0
    assert 40.0 <= model.length_m <= 120.0
    assert model.close_up_ready
    assert model.has_metallic_components
    assert blades.supports_region_painting(model)
    assert len(model.stations) >= 10
    # Taper and twist must actually be present, not nominal.
    chords = [station.chord_m for station in model.stations]
    twists = [station.twist_deg for station in model.stations]
    assert max(chords) / min(chords) > 3.0
    assert max(twists) - min(twists) > 8.0


def test_legacy_blade_is_preserved_and_honest_about_its_limits() -> None:
    model = blades.BF_LEGACY_DEV_BLADE_V1
    assert model.status == ReleaseStatus.RELEASED
    assert not model.close_up_ready
    assert model.intended_limitations
    assert not blades.supports_region_painting(model)


def test_uv_layout_checksum_changes_when_the_unwrap_changes() -> None:
    """This checksum is what makes a stale painted region detectable."""
    import dataclasses

    original = blades.BF_GENERIC_BLADE_V1.uv_layout
    changed = dataclasses.replace(original, spanwise_samples=original.spanwise_samples + 1)
    assert changed.checksum != original.checksum


# ---------------------------------------------------------------------------
# Output schemas
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("schema", outputs.ALL_OUTPUT_SCHEMAS, ids=lambda s: s.id)
def test_class_id_masks_stay_single_channel(schema: object) -> None:
    assert schema.mask_channels == 1
    assert schema.mask_bit_depth in {8, 16}


def test_legacy_annotation_format_names_still_resolve() -> None:
    assert outputs.canonical_annotation_format("coco_json") == "coco_instance_segmentation"
    assert outputs.canonical_annotation_format("yolo_v8") == "yolo_detection"
    assert outputs.output_schema_for_legacy_format("coco_json").id == "LEGACY_COCO_OUTPUT_V1"
    assert outputs.output_schema_for_legacy_format("yolo_v8").id == "LEGACY_YOLO_OUTPUT_V1"


def test_crop_policies_cover_whole_damaged_and_both() -> None:
    """The customer must be able to ask for the frame, the damage, or both."""
    assert set(outputs.CropPolicy.ALL) == {"full_frame", "defect_crop", "full_and_crop"}
    whole = outputs.get_output_schema("STANDARD_DETECTION_OUTPUT_V1")
    crop = outputs.get_output_schema("DEFECT_CROP_OUTPUT_V1")
    both = outputs.get_output_schema("FULL_ANALYSIS_OUTPUT_V1")
    assert whole.emits_full_frames and not whole.emits_crops
    assert crop.emits_crops and not crop.emits_full_frames
    assert both.emits_full_frames and both.emits_crops


def test_required_package_files_are_declared() -> None:
    assert set(outputs.REQUIRED_PACKAGE_FILES) == {
        "manifest.json",
        "dataset-config.json",
        "checksums.sha256",
        "README.md",
        "model-card.json",
        "licenses.json",
        "taxonomy.json",
        "validation-report.json",
    }
