"""Region painting: colour layers, UV alignment, and the permission mask.

The behaviour under test is that a customer's painted colours become a hard boundary the
renderer cannot escape, and that a stale region is refused rather than silently
misaligned.
"""

from __future__ import annotations

import dataclasses

import pytest

from bladeforge_core import blades, regions
from bladeforge_core.errors import ParameterValidationError, RegionMaskError

MODEL = blades.BF_GENERIC_BLADE_V1


def layer(region_id: str, index: int, profile_id: str, color_key: str) -> regions.RegionLayer:
    entry = regions.palette_for_profile(profile_id)
    assert entry is not None, profile_id
    return regions.RegionLayer(
        region_id=region_id,
        layer_index=index,
        display_name=entry.display_name,
        color_key=color_key,
        hex_color=entry.hex_color,
        defect_profile_id=profile_id,
        defect_profile_version="1.0.0",
        severity_min=30.0,
        severity_max=80.0,
        coverage_target=0.05,
    )


def document(
    *,
    uv_layout_checksum: str | None = None,
    model_id: str | None = None,
    uv_set_name: str | None = None,
) -> regions.RegionStrokeDocument:
    le_u, le_v = MODEL.uv_layout.landmarks["midspan_leading_edge"]
    tip_u, tip_v = MODEL.uv_layout.landmarks["tip_leading_edge"]
    return regions.RegionStrokeDocument(
        name="Test regions",
        blade_model_id=model_id or MODEL.id,
        blade_model_version=MODEL.version,
        uv_set_name=uv_set_name or MODEL.uv_layout.uv_set_name,
        uv_layout_checksum=uv_layout_checksum or MODEL.uv_layout_checksum,
        mask_width=512,
        mask_height=256,
        layers=(
            layer("erosion", 1, "LEE_STANDARD_V1", "green"),
            layer("strike", 2, "LIGHTNING_STRIKE_STANDARD_V1", "red"),
        ),
        strokes=(
            regions.BrushStroke(
                "erosion", regions.PAINT, 0.02,
                ((le_u, le_v), (le_u + 0.2, le_v), (le_u + 0.35, le_v)),
            ),
            regions.BrushStroke("strike", regions.PAINT, 0.04, ((tip_u, tip_v),)),
        ),
    )


# ---------------------------------------------------------------------------
# Palette and onboarding
# ---------------------------------------------------------------------------


def test_palette_covers_every_selectable_defect_family() -> None:
    """A first-time user must be able to see what each colour means without being told."""
    from bladeforge_core.defects import primary_selectable_profiles

    painted = {entry.defect_profile_id for entry in regions.DEFAULT_PALETTE}
    for profile in primary_selectable_profiles():
        assert profile.id in painted, (
            f"{profile.id} is selectable but has no palette colour, so a customer would "
            "have no way to paint a region for it."
        )


def test_palette_colours_and_ids_are_unique() -> None:
    keys = [entry.color_key for entry in regions.DEFAULT_PALETTE]
    hexes = [entry.hex_color for entry in regions.DEFAULT_PALETTE]
    assert len(set(keys)) == len(keys)
    assert len(set(hexes)) == len(hexes)


def test_every_palette_entry_explains_itself() -> None:
    for entry in regions.DEFAULT_PALETTE:
        assert entry.display_name
        assert entry.what_it_paints.endswith(".")
        assert len(entry.when_to_use) > 40, (
            f"{entry.color_key} needs real placement guidance, not a stub."
        )


def test_onboarding_payload_is_self_contained() -> None:
    payload = regions.default_palette_payload()
    assert payload["palette"]
    assert len(payload["guide"]["steps"]) >= 3
    assert payload["guide"]["notes"]
    assert payload["unpainted_index"] == regions.UNPAINTED
    assert payload["max_layers"] == regions.MAX_REGION_LAYERS


def test_the_documented_colour_convention_holds() -> None:
    """The prompt's convention: red lightning, blue delamination, yellow coating, green erosion."""
    expected = {
        "red": "LIGHTNING_STRIKE_STANDARD_V1",
        "blue": "DELAMINATION_STANDARD_V1",
        "yellow": "COATING_FAILURE_STANDARD_V1",
        "green": "LEE_STANDARD_V1",
    }
    actual = {e.color_key: e.defect_profile_id for e in regions.DEFAULT_PALETTE}
    for color, profile_id in expected.items():
        assert actual[color] == profile_id


# ---------------------------------------------------------------------------
# Rasterisation
# ---------------------------------------------------------------------------


def test_mask_is_single_channel_with_only_declared_layer_indices() -> None:
    mask = regions.rasterise_region_mask(document())
    assert len(mask.data) == mask.width * mask.height
    present = set(mask.data)
    allowed = {regions.UNPAINTED, *mask.layer_index_map.values()}
    assert present <= allowed, sorted(present - allowed)


def test_rasterisation_is_deterministic() -> None:
    doc = document()
    assert regions.rasterise_region_mask(doc).checksum == (
        regions.rasterise_region_mask(doc).checksum
    )


def test_painted_layers_have_coverage_and_bounding_boxes() -> None:
    mask = regions.rasterise_region_mask(document())
    for region_id in ("erosion", "strike"):
        assert mask.coverage_by_region[region_id] > 0.0
        x, y, w, h = mask.bounding_box_by_region[region_id]
        assert w > 0.0 and h > 0.0
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def test_a_bigger_brush_paints_more() -> None:
    le_u, le_v = MODEL.uv_layout.landmarks["midspan_leading_edge"]
    base = document()
    small = dataclasses.replace(
        base,
        strokes=(regions.BrushStroke("erosion", regions.PAINT, 0.01, ((le_u, le_v),)),),
    )
    large = dataclasses.replace(
        base,
        strokes=(regions.BrushStroke("erosion", regions.PAINT, 0.05, ((le_u, le_v),)),),
    )
    small_coverage = regions.rasterise_region_mask(small).coverage_by_region["erosion"]
    large_coverage = regions.rasterise_region_mask(large).coverage_by_region["erosion"]
    assert large_coverage > small_coverage * 4


def test_a_dragged_stroke_is_continuous() -> None:
    """A fast drag must not leave gaps between sampled points."""
    import numpy as np

    base = document()
    dragged = dataclasses.replace(
        base,
        strokes=(
            regions.BrushStroke("erosion", regions.PAINT, 0.01, ((0.05, 0.5), (0.85, 0.5))),
        ),
    )
    mask = regions.rasterise_region_mask(dragged)
    canvas = np.frombuffer(mask.data, dtype=np.uint8).reshape(mask.height, mask.width)
    row = canvas[mask.height // 2]
    painted_columns = np.flatnonzero(row == 1)
    assert painted_columns.size > 0
    # Contiguous: no unpainted gap inside the stroke's extent.
    assert painted_columns.size == painted_columns[-1] - painted_columns[0] + 1


def test_erase_removes_only_its_own_layer() -> None:
    """Erasing green must not damage the red the customer painted next to it."""
    tip_u, tip_v = MODEL.uv_layout.landmarks["tip_leading_edge"]
    base = document()
    before = regions.rasterise_region_mask(base)
    erased = dataclasses.replace(
        base,
        strokes=base.strokes
        + (regions.BrushStroke("erosion", regions.ERASE, 0.06, ((tip_u, tip_v),)),),
    )
    after = regions.rasterise_region_mask(erased)
    assert after.coverage_by_region["strike"] == before.coverage_by_region["strike"]


def test_overpainting_replaces_the_earlier_layer() -> None:
    le_u, le_v = MODEL.uv_layout.landmarks["midspan_leading_edge"]
    base = document()
    over = dataclasses.replace(
        base,
        strokes=(
            regions.BrushStroke("erosion", regions.PAINT, 0.04, ((le_u, le_v),)),
            regions.BrushStroke("strike", regions.PAINT, 0.04, ((le_u, le_v),)),
        ),
    )
    mask = regions.rasterise_region_mask(over)
    assert mask.coverage_by_region["erosion"] == 0.0
    assert mask.coverage_by_region["strike"] > 0.0


# ---------------------------------------------------------------------------
# UV alignment
# ---------------------------------------------------------------------------


def test_uv_landmark_round_trip_confirms_alignment() -> None:
    """The check that catches a flipped or rotated unwrap."""
    mask = regions.rasterise_region_mask(document())
    result = regions.verify_uv_landmark_round_trip(
        mask, MODEL,
        {"midspan_leading_edge": "erosion", "tip_leading_edge": "strike"},
    )
    assert all(result.values()), result


def test_uv_landmark_round_trip_detects_a_swapped_mapping() -> None:
    mask = regions.rasterise_region_mask(document())
    result = regions.verify_uv_landmark_round_trip(
        mask, MODEL,
        {"midspan_leading_edge": "strike", "tip_leading_edge": "erosion"},
    )
    assert not any(result.values()), result


def test_sampling_outside_the_painted_area_returns_unpainted() -> None:
    mask = regions.rasterise_region_mask(document())
    u, v = MODEL.uv_layout.landmarks["midspan_pressure_side"]
    assert regions.sample_layer_at_uv(mask, u, v) == regions.UNPAINTED


def test_unknown_landmark_is_rejected() -> None:
    mask = regions.rasterise_region_mask(document())
    with pytest.raises(RegionMaskError, match="no UV landmark"):
        regions.verify_uv_landmark_round_trip(mask, MODEL, {"nope": "erosion"})


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def test_matching_model_is_accepted() -> None:
    regions.assert_region_matches_model(document(), MODEL)


def test_changed_uv_checksum_is_rejected_with_a_repaint_instruction() -> None:
    with pytest.raises(RegionMaskError, match="[Rr]epaint"):
        regions.assert_region_matches_model(document(uv_layout_checksum="0" * 64), MODEL)


def test_different_model_is_rejected() -> None:
    with pytest.raises(RegionMaskError, match="[Rr]epaint"):
        regions.assert_region_matches_model(document(model_id="SOMETHING_ELSE_V1"), MODEL)


def test_different_uv_set_is_rejected() -> None:
    with pytest.raises(RegionMaskError, match="[Rr]epaint"):
        regions.assert_region_matches_model(document(uv_set_name="OtherUV"), MODEL)


def test_model_without_uv_landmarks_cannot_be_painted() -> None:
    with pytest.raises(RegionMaskError, match="painted regions are not supported"):
        regions.assert_region_matches_model(document(), blades.BF_LEGACY_DEV_BLADE_V1)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_duplicate_layer_index_is_rejected() -> None:
    with pytest.raises(ParameterValidationError, match="layer_index"):
        dataclasses.replace(
            document(),
            layers=(
                layer("first", 1, "LEE_STANDARD_V1", "green"),
                layer("second", 1, "DELAMINATION_STANDARD_V1", "blue"),
            ),
            strokes=(),
        )


def test_duplicate_region_id_is_rejected() -> None:
    with pytest.raises(ParameterValidationError, match="region_id"):
        dataclasses.replace(
            document(),
            layers=(
                layer("same", 1, "LEE_STANDARD_V1", "green"),
                layer("same", 2, "DELAMINATION_STANDARD_V1", "blue"),
            ),
            strokes=(),
        )


def test_stroke_referencing_an_undefined_layer_is_rejected() -> None:
    with pytest.raises(ParameterValidationError, match="undefined layers"):
        dataclasses.replace(
            document(),
            strokes=(regions.BrushStroke("ghost", regions.PAINT, 0.02, ((0.1, 0.1),)),),
        )


def test_layer_index_zero_is_reserved_for_unpainted() -> None:
    with pytest.raises(ParameterValidationError, match="reserved for unpainted"):
        layer("unpainted-clash", 0, "LEE_STANDARD_V1", "green")


@pytest.mark.parametrize("point", [(-0.2, 0.5), (0.5, 1.4), (float("nan"), 0.5)])
def test_stroke_points_outside_the_uv_square_are_rejected(point: tuple) -> None:
    with pytest.raises(ParameterValidationError):
        regions.BrushStroke("erosion", regions.PAINT, 0.02, (point,))


@pytest.mark.parametrize("radius", [0.0, 0.00001, 0.9])
def test_implausible_brush_radius_is_rejected(radius: float) -> None:
    with pytest.raises(ParameterValidationError, match="[Bb]rush radius"):
        regions.BrushStroke("erosion", regions.PAINT, radius, ((0.5, 0.5),))


def test_unknown_stroke_mode_is_rejected() -> None:
    with pytest.raises(ParameterValidationError, match="stroke mode"):
        regions.BrushStroke("erosion", "smudge", 0.02, ((0.5, 0.5),))


def test_free_text_is_stored_as_a_note_and_length_limited() -> None:
    """A note never changes geometry, but it must not be unbounded either."""
    entry = layer("erosion", 1, "LEE_STANDARD_V1", "green")
    noted = dataclasses.replace(entry, customer_note="Focus on the outer third.")
    assert noted.as_dict()["customer_note"] == "Focus on the outer third."
    with pytest.raises(ParameterValidationError, match="2000 characters"):
        dataclasses.replace(entry, customer_note="x" * 2001)


def test_region_id_format_is_enforced() -> None:
    with pytest.raises(ParameterValidationError, match="region_id"):
        layer("Not Valid!", 1, "LEE_STANDARD_V1", "green")


def test_mask_dimensions_are_bounded() -> None:
    with pytest.raises(ParameterValidationError, match="mask_width"):
        dataclasses.replace(document(), mask_width=64)
    with pytest.raises(ParameterValidationError, match="mask_height"):
        dataclasses.replace(document(), mask_height=99999)


def test_document_checksum_changes_when_strokes_change() -> None:
    base = document()
    extra = dataclasses.replace(
        base,
        strokes=base.strokes
        + (regions.BrushStroke("erosion", regions.PAINT, 0.02, ((0.3, 0.3),)),),
    )
    assert base.checksum != extra.checksum


def test_stored_data_keys_off_stable_ids_not_colours() -> None:
    """Re-theming the interface must not change what gets generated."""
    base = document()
    recoloured = dataclasses.replace(
        base,
        layers=tuple(
            dataclasses.replace(entry, hex_color="#000000", color_key="black")
            for entry in base.layers
        ),
    )
    original_mask = regions.rasterise_region_mask(base)
    recoloured_mask = regions.rasterise_region_mask(recoloured)
    assert original_mask.checksum == recoloured_mask.checksum
    assert original_mask.layer_index_map == recoloured_mask.layer_index_map
