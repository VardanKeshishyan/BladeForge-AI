"""The shipped defect profile versions.

Every profile here is immutable and paired with a Blender implementation keyed by
``renderer_key`` in ``render_engine.v2.defects``. All lengths are millimetres,
areas are square millimetres, angles are degrees, densities are per square
centimetre, and fractions are 0..1 of the stated reference quantity.

Band ranges are drawn from published wind-turbine blade inspection practice for
plausibility, and are deliberately non-overlapping enough that early, moderate,
and severe are independently testable.
"""

from __future__ import annotations

from ..versioning import ReleaseStatus
from .base import CoverageLimits, DefectProfileVersion, bands, spec

FRACTION = "fraction_0_1"
MM = "mm"
MM2 = "mm2"
DEG = "degrees"
COUNT = "count"
PER_CM2 = "per_cm2"
DELTA_E = "delta_e_cie76"

# ---------------------------------------------------------------------------
# Leading-edge erosion: material loss, not decorative bumps.
# ---------------------------------------------------------------------------

LEE_STANDARD_V1 = DefectProfileVersion(
    id="LEE_STANDARD_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Leading-edge erosion (standard)",
    summary=(
        "Rain and particle erosion of the leading edge modelled as real material loss: "
        "coating removal, edge breakup, pitting, exposed substrate, gelcoat chipping, "
        "roughness change, and discoloration."
    ),
    family="erosion",
    renderer_key="lee_material_loss_v1",
    primary_category="leading_edge_erosion",
    emitted_categories=(
        "leading_edge_erosion",
        "erosion_coating_loss",
        "erosion_pitting",
        "gelcoat_chipping",
        "exposed_substrate",
    ),
    feature_flag="defect_lee_standard_v1",
    parameters=(
        spec("span_start_fraction", FRACTION, 0.0, 0.95,
             "Where the eroded region begins, as a fraction of span from the root."),
        spec("affected_span_fraction", FRACTION, 0.005, 0.70,
             "Length of the eroded region as a fraction of total blade span."),
        spec("erosion_length_mm", MM, 50.0, 40000.0,
             "Spanwise length of the eroded region."),
        spec("erosion_width_mm", MM, 1.0, 150.0,
             "Chordwise width of material loss measured back from the leading edge."),
        spec("erosion_depth_mm", MM, 0.02, 6.0,
             "Maximum depth of removed material normal to the original surface."),
        spec("edge_breakup_amplitude_mm", MM, 0.0, 8.0,
             "Amplitude of the ragged, non-straight erosion boundary."),
        spec("pit_density_per_cm2", PER_CM2, 0.0, 25.0,
             "Number of discrete impact pits per square centimetre of eroded area."),
        spec("pit_diameter_mm", MM, 0.2, 14.0, "Mean pit diameter."),
        spec("coating_removal_fraction", FRACTION, 0.0, 1.0,
             "Fraction of the eroded region where the paint or coating layer is gone."),
        spec("substrate_exposure_fraction", FRACTION, 0.0, 1.0,
             "Fraction of the eroded region where bare laminate or fibre is exposed."),
        spec("gelcoat_chip_count", COUNT, 0, 80, "Number of hard-edged gelcoat chips.",
             integral=True),
        spec("roughness_delta", FRACTION, 0.0, 0.65,
             "Increase in surface roughness inside the eroded region."),
        spec("discoloration_strength", FRACTION, 0.0, 1.0,
             "Strength of the darkening and colour shift of the eroded region."),
        spec("defect_coverage_fraction", FRACTION, 0.0005, 0.60,
             "Target fraction of the visible blade area occupied by the defect."),
    ),
    bands=bands(
        early={
            "span_start_fraction": (0.35, 0.85),
            "affected_span_fraction": (0.02, 0.10),
            "erosion_length_mm": (300.0, 3000.0),
            "erosion_width_mm": (3.0, 12.0),
            "erosion_depth_mm": (0.05, 0.40),
            "edge_breakup_amplitude_mm": (0.05, 0.60),
            "pit_density_per_cm2": (0.5, 3.0),
            "pit_diameter_mm": (0.3, 1.5),
            "coating_removal_fraction": (0.02, 0.15),
            "substrate_exposure_fraction": (0.0, 0.04),
            "gelcoat_chip_count": (0, 6),
            "roughness_delta": (0.03, 0.15),
            "discoloration_strength": (0.05, 0.25),
            "defect_coverage_fraction": (0.0010, 0.020),
        },
        moderate={
            "span_start_fraction": (0.25, 0.80),
            "affected_span_fraction": (0.08, 0.28),
            "erosion_length_mm": (2500.0, 9000.0),
            "erosion_width_mm": (12.0, 38.0),
            "erosion_depth_mm": (0.40, 1.60),
            "edge_breakup_amplitude_mm": (0.50, 2.20),
            "pit_density_per_cm2": (3.0, 9.0),
            "pit_diameter_mm": (1.2, 4.5),
            "coating_removal_fraction": (0.15, 0.50),
            "substrate_exposure_fraction": (0.04, 0.25),
            "gelcoat_chip_count": (4, 24),
            "roughness_delta": (0.12, 0.35),
            "discoloration_strength": (0.20, 0.55),
            "defect_coverage_fraction": (0.015, 0.090),
        },
        severe={
            "span_start_fraction": (0.15, 0.70),
            "affected_span_fraction": (0.25, 0.65),
            "erosion_length_mm": (8000.0, 26000.0),
            "erosion_width_mm": (35.0, 95.0),
            "erosion_depth_mm": (1.50, 5.00),
            "edge_breakup_amplitude_mm": (2.00, 6.50),
            "pit_density_per_cm2": (8.0, 20.0),
            "pit_diameter_mm": (4.0, 12.0),
            "coating_removal_fraction": (0.45, 0.92),
            "substrate_exposure_fraction": (0.22, 0.70),
            "gelcoat_chip_count": (20, 70),
            "roughness_delta": (0.30, 0.60),
            "discoloration_strength": (0.50, 0.95),
            "defect_coverage_fraction": (0.070, 0.350),
        },
    ),
    coverage_limits=CoverageLimits(0.00003, 0.45, 32),
    supports_as_secondary=True,
    validated_secondary_profiles=("COATING_FAILURE_STANDARD_V1",),
    notes=(
        "Replaces the legacy implementation that overlaid external ico-spheres. Erosion "
        "is now produced by displacing and removing surface material inside a bounded "
        "leading-edge band, so the silhouette and shading change as real material loss."
    ),
)

# ---------------------------------------------------------------------------
# Lightning strike
# ---------------------------------------------------------------------------

LIGHTNING_STRIKE_STANDARD_V1 = DefectProfileVersion(
    id="LIGHTNING_STRIKE_STANDARD_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Lightning strike damage (standard)",
    summary=(
        "A structured strike: attachment entry point, optional puncture, branching burn "
        "and scorch pattern, radial material change, controlled exposed composite, and "
        "optional local delamination. Each part is separately labelled."
    ),
    family="lightning",
    renderer_key="lightning_strike_v1",
    primary_category="lightning_strike_damage",
    emitted_categories=(
        "lightning_strike_damage",
        "lightning_scorch",
        "lightning_puncture",
        "lightning_delamination",
        "exposed_substrate",
    ),
    feature_flag="defect_lightning_strike_standard_v1",
    parameters=(
        spec("strike_span_fraction", FRACTION, 0.30, 1.0,
             "Spanwise attachment position. Strikes concentrate towards the tip."),
        spec("entry_point_diameter_mm", MM, 2.0, 200.0,
             "Diameter of the arc attachment crater."),
        spec("puncture_depth_mm", MM, 0.0, 25.0,
             "Depth of the localised perforation. Zero means no puncture."),
        spec("branch_count", COUNT, 0, 20,
             "Number of burn or scorch branches radiating from the entry point.",
             integral=True),
        spec("branch_reach_mm", MM, 0.0, 1400.0, "Maximum radial reach of a branch."),
        spec("branch_width_mm", MM, 0.3, 30.0, "Mean branch width."),
        spec("burn_intensity", FRACTION, 0.0, 1.0,
             "Strength of the charring and darkening of the burnt material."),
        spec("scorch_radius_mm", MM, 5.0, 700.0,
             "Radius of the contiguous scorch region around the entry point."),
        spec("radial_discoloration_mm", MM, 0.0, 900.0,
             "Radius of the outer heat discoloration halo."),
        spec("exposed_composite_fraction", FRACTION, 0.0, 1.0,
             "Fraction of the damaged region where bare composite is exposed."),
        spec("secondary_delamination_area_mm2", MM2, 0.0, 80000.0,
             "Area of ply separation caused by the pressure pulse. Zero means none."),
        spec("soot_opacity", FRACTION, 0.0, 1.0, "Opacity of deposited soot."),
    ),
    bands=bands(
        early={
            "strike_span_fraction": (0.60, 0.98),
            "entry_point_diameter_mm": (6.0, 22.0),
            "puncture_depth_mm": (0.0, 0.20),
            "branch_count": (2, 4),
            "branch_reach_mm": (30.0, 130.0),
            "branch_width_mm": (0.5, 2.0),
            "burn_intensity": (0.15, 0.35),
            "scorch_radius_mm": (25.0, 85.0),
            "radial_discoloration_mm": (30.0, 120.0),
            "exposed_composite_fraction": (0.0, 0.08),
            "secondary_delamination_area_mm2": (0.0, 400.0),
            "soot_opacity": (0.10, 0.30),
        },
        moderate={
            "strike_span_fraction": (0.55, 0.98),
            "entry_point_diameter_mm": (20.0, 60.0),
            "puncture_depth_mm": (0.20, 2.50),
            "branch_count": (4, 9),
            "branch_reach_mm": (120.0, 380.0),
            "branch_width_mm": (1.5, 6.0),
            "burn_intensity": (0.30, 0.65),
            "scorch_radius_mm": (80.0, 230.0),
            "radial_discoloration_mm": (100.0, 350.0),
            "exposed_composite_fraction": (0.06, 0.30),
            "secondary_delamination_area_mm2": (300.0, 6000.0),
            "soot_opacity": (0.25, 0.60),
        },
        severe={
            "strike_span_fraction": (0.50, 0.99),
            "entry_point_diameter_mm": (55.0, 160.0),
            "puncture_depth_mm": (2.00, 18.00),
            "branch_count": (8, 16),
            "branch_reach_mm": (350.0, 1100.0),
            "branch_width_mm": (5.0, 22.0),
            "burn_intensity": (0.60, 1.00),
            "scorch_radius_mm": (210.0, 620.0),
            "radial_discoloration_mm": (320.0, 850.0),
            "exposed_composite_fraction": (0.25, 0.80),
            "secondary_delamination_area_mm2": (5000.0, 60000.0),
            "soot_opacity": (0.55, 0.95),
        },
    ),
    coverage_limits=CoverageLimits(0.00003, 0.40, 28),
    validated_secondary_profiles=("DELAMINATION_STANDARD_V1",),
    notes=(
        "Severity controls entry-point size, branch reach, burn intensity, substrate "
        "exposure, and secondary damage independently rather than through one texture."
    ),
)

# ---------------------------------------------------------------------------
# Surface cracking
# ---------------------------------------------------------------------------

SURFACE_CRACK_STANDARD_V1 = DefectProfileVersion(
    id="SURFACE_CRACK_STANDARD_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Surface crack (standard)",
    summary=(
        "Curve-driven fissures with controlled length, opening, depth, branching, "
        "direction, and edge roughness. Cracks are projected onto the blade surface and "
        "never float above it."
    ),
    family="crack",
    renderer_key="surface_crack_v1",
    primary_category="surface_crack",
    emitted_categories=("surface_crack", "exposed_substrate"),
    feature_flag="defect_surface_crack_standard_v1",
    parameters=(
        spec("crack_count", COUNT, 1, 12, "Number of independent primary cracks.",
             integral=True),
        spec("crack_length_mm", MM, 5.0, 2200.0, "Arc length of the primary crack."),
        spec("crack_opening_mm", MM, 0.05, 12.0, "Width of the crack opening at its widest."),
        spec("crack_depth_mm", MM, 0.05, 18.0, "Depth of the fissure into the laminate."),
        spec("branch_count", COUNT, 0, 10, "Number of secondary branches.", integral=True),
        spec("branch_angle_deg", DEG, 5.0, 80.0, "Angle a branch leaves the primary crack."),
        spec("direction_deg", DEG, 0.0, 180.0,
             "Crack direction relative to the spanwise axis. 0 is spanwise, 90 chordwise."),
        spec("edge_roughness", FRACTION, 0.0, 1.0, "Irregularity of the crack edges."),
        spec("opening_taper", FRACTION, 0.0, 1.0,
             "How strongly the opening narrows towards the crack tips."),
        spec("max_surface_deviation_mm", MM, 0.0, 0.50,
             "Hard invariant: how far crack geometry may sit off the blade surface. "
             "Kept near zero so cracks conform to the surface."),
        spec("span_start_fraction", FRACTION, 0.0, 0.95,
             "Spanwise position where the crack begins."),
    ),
    bands=bands(
        early={
            "crack_count": (1, 2),
            "crack_length_mm": (20.0, 120.0),
            "crack_opening_mm": (0.08, 0.60),
            "crack_depth_mm": (0.10, 0.80),
            "branch_count": (0, 1),
            "branch_angle_deg": (10.0, 35.0),
            "direction_deg": (0.0, 180.0),
            "edge_roughness": (0.10, 0.35),
            "opening_taper": (0.20, 0.50),
            "max_surface_deviation_mm": (0.0, 0.02),
            "span_start_fraction": (0.10, 0.90),
        },
        moderate={
            "crack_count": (1, 4),
            "crack_length_mm": (110.0, 460.0),
            "crack_opening_mm": (0.50, 2.60),
            "crack_depth_mm": (0.70, 3.20),
            "branch_count": (1, 3),
            "branch_angle_deg": (15.0, 50.0),
            "direction_deg": (0.0, 180.0),
            "edge_roughness": (0.30, 0.60),
            "opening_taper": (0.30, 0.70),
            "max_surface_deviation_mm": (0.0, 0.03),
            "span_start_fraction": (0.10, 0.90),
        },
        severe={
            "crack_count": (2, 8),
            "crack_length_mm": (440.0, 1800.0),
            "crack_opening_mm": (2.40, 9.00),
            "crack_depth_mm": (3.00, 14.00),
            "branch_count": (3, 8),
            "branch_angle_deg": (20.0, 70.0),
            "direction_deg": (0.0, 180.0),
            "edge_roughness": (0.55, 0.95),
            "opening_taper": (0.40, 0.90),
            "max_surface_deviation_mm": (0.0, 0.05),
            "span_start_fraction": (0.05, 0.90),
        },
    ),
    coverage_limits=CoverageLimits(0.00002, 0.25, 24),
    supports_as_secondary=True,
    notes=(
        "The parametric curve control points are retained in per-image metadata so the "
        "underlying crack representation survives alongside the rasterised mask."
    ),
)

# ---------------------------------------------------------------------------
# Delamination
# ---------------------------------------------------------------------------

DELAMINATION_STANDARD_V1 = DefectProfileVersion(
    id="DELAMINATION_STANDARD_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Delamination, surface visible (standard)",
    summary=(
        "Lifted, blistered, bubbled, or locally distorted composite plies with real "
        "geometry, altered normals, self-shadowing, edge transitions, and optional "
        "exposed laminate. Only the surface-visible signature is labelled."
    ),
    family="delamination",
    renderer_key="delamination_surface_v1",
    primary_category="delamination",
    emitted_categories=("delamination", "exposed_substrate"),
    feature_flag="defect_delamination_standard_v1",
    parameters=(
        spec("blister_count", COUNT, 1, 30, "Number of lifted or blistered areas.",
             integral=True),
        spec("blister_diameter_mm", MM, 8.0, 900.0, "Mean blister diameter."),
        spec("lift_height_mm", MM, 0.1, 30.0,
             "How far the separated ply lifts off the substrate."),
        spec("edge_transition_mm", MM, 0.5, 60.0,
             "Width of the transition from lifted to bonded material."),
        spec("separated_area_mm2", MM2, 50.0, 600000.0, "Total separated ply area."),
        spec("distortion_amplitude_mm", MM, 0.05, 25.0,
             "Amplitude of the local surface distortion."),
        spec("exposed_laminate_fraction", FRACTION, 0.0, 1.0,
             "Fraction of the separated area where laminate is exposed."),
        spec("surface_visibility", FRACTION, 0.30, 1.0,
             "How strongly the damage reads on the outer surface. Values below 0.30 are "
             "not honestly labellable and belong to the subsurface profile."),
        spec("span_start_fraction", FRACTION, 0.0, 0.95, "Spanwise position."),
        spec("chord_position_fraction", FRACTION, 0.0, 1.0,
             "Chordwise position, 0 at the leading edge and 1 at the trailing edge."),
    ),
    bands=bands(
        early={
            "blister_count": (1, 3),
            "blister_diameter_mm": (15.0, 60.0),
            "lift_height_mm": (0.20, 1.00),
            "edge_transition_mm": (1.0, 6.0),
            "separated_area_mm2": (200.0, 3000.0),
            "distortion_amplitude_mm": (0.10, 0.80),
            "exposed_laminate_fraction": (0.0, 0.03),
            "surface_visibility": (0.35, 0.55),
            "span_start_fraction": (0.10, 0.90),
            "chord_position_fraction": (0.10, 0.85),
        },
        moderate={
            "blister_count": (2, 8),
            "blister_diameter_mm": (55.0, 210.0),
            "lift_height_mm": (0.90, 4.20),
            "edge_transition_mm": (4.0, 18.0),
            "separated_area_mm2": (2500.0, 30000.0),
            "distortion_amplitude_mm": (0.70, 3.50),
            "exposed_laminate_fraction": (0.02, 0.18),
            "surface_visibility": (0.50, 0.78),
            "span_start_fraction": (0.10, 0.90),
            "chord_position_fraction": (0.10, 0.85),
        },
        severe={
            "blister_count": (4, 18),
            "blister_diameter_mm": (200.0, 750.0),
            "lift_height_mm": (4.00, 16.00),
            "edge_transition_mm": (15.0, 50.0),
            "separated_area_mm2": (25000.0, 400000.0),
            "distortion_amplitude_mm": (3.00, 14.00),
            "exposed_laminate_fraction": (0.15, 0.60),
            "surface_visibility": (0.72, 1.00),
            "span_start_fraction": (0.05, 0.95),
            "chord_position_fraction": (0.05, 0.90),
        },
    ),
    coverage_limits=CoverageLimits(0.00003, 0.45, 30),
    supports_as_secondary=True,
    # Coating over a lifted ply commonly fails with it. Lightning is deliberately not
    # listed: a strike causes delamination, so the pairing belongs on the strike
    # profile as primary, not on this one.
    validated_secondary_profiles=("COATING_FAILURE_STANDARD_V1",),
    notes=(
        "Distinguished from DELAMINATION_SUBSURFACE_V1, which models damage with no "
        "reliable RGB signature and therefore emits no visible mask."
    ),
)

DELAMINATION_SUBSURFACE_V1 = DefectProfileVersion(
    id="DELAMINATION_SUBSURFACE_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Delamination, subsurface only",
    summary=(
        "Ply separation that does not deform the outer surface. Physically real and "
        "recorded in metadata, but deliberately not exported as an RGB segmentation "
        "target because it cannot be delineated honestly from an image."
    ),
    family="delamination",
    renderer_key="delamination_subsurface_v1",
    primary_category="delamination_subsurface",
    emitted_categories=("delamination_subsurface",),
    feature_flag="defect_delamination_subsurface_v1",
    produces_visible_mask=False,
    supports_as_primary=False,
    supports_as_secondary=True,
    parameters=(
        spec("separated_area_mm2", MM2, 50.0, 600000.0, "Total separated ply area."),
        spec("depth_below_surface_mm", MM, 0.5, 60.0,
             "Depth of the separation below the outer surface."),
        spec("ply_count_affected", COUNT, 1, 40, "Number of plies separated.", integral=True),
        spec("surface_visibility", FRACTION, 0.0, 0.29,
             "Capped below the labelling threshold by construction."),
        spec("span_start_fraction", FRACTION, 0.0, 0.95, "Spanwise position."),
        spec("chord_position_fraction", FRACTION, 0.0, 1.0, "Chordwise position."),
    ),
    bands=bands(
        early={
            "separated_area_mm2": (200.0, 3000.0),
            "depth_below_surface_mm": (0.5, 4.0),
            "ply_count_affected": (1, 3),
            "surface_visibility": (0.0, 0.08),
            "span_start_fraction": (0.10, 0.90),
            "chord_position_fraction": (0.10, 0.85),
        },
        moderate={
            "separated_area_mm2": (2500.0, 30000.0),
            "depth_below_surface_mm": (3.0, 14.0),
            "ply_count_affected": (2, 10),
            "surface_visibility": (0.05, 0.18),
            "span_start_fraction": (0.10, 0.90),
            "chord_position_fraction": (0.10, 0.85),
        },
        severe={
            "separated_area_mm2": (25000.0, 400000.0),
            "depth_below_surface_mm": (10.0, 45.0),
            "ply_count_affected": (8, 30),
            "surface_visibility": (0.15, 0.29),
            "span_start_fraction": (0.05, 0.95),
            "chord_position_fraction": (0.05, 0.90),
        },
    ),
    coverage_limits=CoverageLimits(0.0, 1.0, 0),
    notes=(
        "Used for honest hard negatives and for structured combinations where a visible "
        "defect coexists with subsurface damage. Never produces a visible mask."
    ),
)

# ---------------------------------------------------------------------------
# Coating failure
# ---------------------------------------------------------------------------

COATING_FAILURE_STANDARD_V1 = DefectProfileVersion(
    id="COATING_FAILURE_STANDARD_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Coating failure (standard)",
    summary=(
        "Degradation of the coating layer across five structured modes: peeling, flaking, "
        "chalking, thinning, and discoloration, with paint loss and optional exposed "
        "substrate. Modes share a parent taxonomy but carry their own category IDs."
    ),
    family="coating",
    renderer_key="coating_failure_v1",
    primary_category="coating_failure",
    emitted_categories=(
        "coating_failure",
        "coating_peeling",
        "coating_flaking",
        "coating_chalking",
        "coating_thinning",
        "coating_discoloration",
        "exposed_substrate",
    ),
    feature_flag="defect_coating_failure_standard_v1",
    parameters=(
        spec("patch_count", COUNT, 1, 40, "Number of affected coating patches.", integral=True),
        spec("patch_area_mm2", MM2, 20.0, 250000.0, "Mean area of one affected patch."),
        spec("peel_edge_lift_mm", MM, 0.0, 12.0, "How far a peeling edge lifts off."),
        spec("flake_size_mm", MM, 0.5, 80.0, "Mean size of an individual flake."),
        spec("chalk_whitening", FRACTION, 0.0, 1.0, "Strength of chalky whitening."),
        spec("thinning_fraction", FRACTION, 0.0, 1.0, "Fraction of coating thickness lost."),
        spec("discoloration_delta_e", DELTA_E, 0.0, 60.0,
             "Colour shift of the coating in CIE76 delta-E units."),
        spec("paint_loss_fraction", FRACTION, 0.0, 1.0,
             "Fraction of the affected area with no paint remaining."),
        spec("substrate_exposure_fraction", FRACTION, 0.0, 1.0,
             "Fraction of the affected area showing bare substrate."),
        spec("mode_peeling_weight", FRACTION, 0.0, 1.0, "Relative weight of the peeling mode."),
        spec("mode_flaking_weight", FRACTION, 0.0, 1.0, "Relative weight of the flaking mode."),
        spec("mode_chalking_weight", FRACTION, 0.0, 1.0, "Relative weight of the chalking mode."),
        spec("mode_thinning_weight", FRACTION, 0.0, 1.0, "Relative weight of the thinning mode."),
        spec("mode_discoloration_weight", FRACTION, 0.0, 1.0,
             "Relative weight of the discoloration mode."),
        spec("span_start_fraction", FRACTION, 0.0, 0.95, "Spanwise position."),
    ),
    bands=bands(
        early={
            "patch_count": (1, 4),
            "patch_area_mm2": (100.0, 2500.0),
            "peel_edge_lift_mm": (0.0, 0.40),
            "flake_size_mm": (0.5, 4.0),
            "chalk_whitening": (0.05, 0.30),
            "thinning_fraction": (0.02, 0.20),
            "discoloration_delta_e": (1.0, 8.0),
            "paint_loss_fraction": (0.0, 0.08),
            "substrate_exposure_fraction": (0.0, 0.03),
            "mode_peeling_weight": (0.0, 0.25),
            "mode_flaking_weight": (0.0, 0.25),
            "mode_chalking_weight": (0.20, 0.70),
            "mode_thinning_weight": (0.20, 0.70),
            "mode_discoloration_weight": (0.30, 0.90),
            "span_start_fraction": (0.05, 0.90),
        },
        moderate={
            "patch_count": (3, 14),
            "patch_area_mm2": (2000.0, 30000.0),
            "peel_edge_lift_mm": (0.30, 3.00),
            "flake_size_mm": (3.0, 20.0),
            "chalk_whitening": (0.25, 0.60),
            "thinning_fraction": (0.18, 0.55),
            "discoloration_delta_e": (7.0, 25.0),
            "paint_loss_fraction": (0.06, 0.35),
            "substrate_exposure_fraction": (0.02, 0.18),
            "mode_peeling_weight": (0.20, 0.65),
            "mode_flaking_weight": (0.20, 0.65),
            "mode_chalking_weight": (0.25, 0.75),
            "mode_thinning_weight": (0.25, 0.75),
            "mode_discoloration_weight": (0.30, 0.90),
            "span_start_fraction": (0.05, 0.90),
        },
        severe={
            "patch_count": (10, 34),
            "patch_area_mm2": (25000.0, 200000.0),
            "peel_edge_lift_mm": (2.50, 10.00),
            "flake_size_mm": (15.0, 65.0),
            "chalk_whitening": (0.50, 0.95),
            "thinning_fraction": (0.50, 0.95),
            "discoloration_delta_e": (22.0, 52.0),
            "paint_loss_fraction": (0.30, 0.90),
            "substrate_exposure_fraction": (0.15, 0.70),
            "mode_peeling_weight": (0.45, 1.00),
            "mode_flaking_weight": (0.45, 1.00),
            "mode_chalking_weight": (0.30, 0.90),
            "mode_thinning_weight": (0.40, 0.95),
            "mode_discoloration_weight": (0.35, 0.95),
            "span_start_fraction": (0.05, 0.90),
        },
    ),
    coverage_limits=CoverageLimits(0.00003, 0.50, 30),
    supports_as_secondary=True,
    validated_secondary_profiles=("LEE_STANDARD_V1",),
)

# ---------------------------------------------------------------------------
# Corrosion and rust. Physically contextual.
# ---------------------------------------------------------------------------

CORROSION_RUST_STANDARD_V1 = DefectProfileVersion(
    id="CORROSION_RUST_STANDARD_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Corrosion and rust on metallic components (standard)",
    summary=(
        "Oxidation, pitting, and scale on genuinely metallic parts: root attachment "
        "hardware, fasteners, lightning-protection receptors, and exposed metallic "
        "inserts, plus the rust runoff staining they deposit on adjacent composite. "
        "The metallic source and the stain are labelled separately."
    ),
    family="corrosion",
    renderer_key="corrosion_metallic_v1",
    primary_category="corrosion_rust",
    emitted_categories=("corrosion_rust", "corrosion_metallic", "corrosion_staining"),
    feature_flag="defect_corrosion_rust_standard_v1",
    requires_metallic_context=True,
    parameters=(
        spec("metallic_context_present", FRACTION, 1.0, 1.0,
             "Invariant: this profile only applies where a metallic component exists."),
        spec("component_count", COUNT, 1, 12, "Number of affected metallic components.",
             integral=True),
        spec("corroded_area_mm2", MM2, 10.0, 120000.0,
             "Total corroded area on the metallic surfaces."),
        spec("pit_depth_mm", MM, 0.02, 12.0, "Depth of corrosion pitting into the metal."),
        spec("scale_thickness_mm", MM, 0.0, 8.0, "Thickness of built-up oxide scale."),
        spec("rust_color_shift", FRACTION, 0.0, 1.0,
             "Strength of the iron-oxide colour shift of the metal surface."),
        spec("runoff_length_mm", MM, 0.0, 2500.0,
             "Length of the stain streak running off onto the composite."),
        spec("runoff_width_mm", MM, 0.0, 400.0, "Width of the runoff stain."),
        spec("stain_opacity", FRACTION, 0.0, 1.0, "Opacity of the deposited stain."),
        spec("span_start_fraction", FRACTION, 0.0, 0.95,
             "Spanwise position of the metallic component."),
    ),
    bands=bands(
        early={
            "metallic_context_present": (1.0, 1.0),
            "component_count": (1, 2),
            "corroded_area_mm2": (30.0, 600.0),
            "pit_depth_mm": (0.02, 0.20),
            "scale_thickness_mm": (0.0, 0.15),
            "rust_color_shift": (0.10, 0.35),
            "runoff_length_mm": (0.0, 120.0),
            "runoff_width_mm": (0.0, 25.0),
            "stain_opacity": (0.05, 0.25),
            "span_start_fraction": (0.0, 0.35),
        },
        moderate={
            "metallic_context_present": (1.0, 1.0),
            "component_count": (1, 5),
            "corroded_area_mm2": (500.0, 9000.0),
            "pit_depth_mm": (0.18, 1.60),
            "scale_thickness_mm": (0.10, 1.20),
            "rust_color_shift": (0.30, 0.65),
            "runoff_length_mm": (100.0, 700.0),
            "runoff_width_mm": (20.0, 110.0),
            "stain_opacity": (0.20, 0.55),
            "span_start_fraction": (0.0, 0.45),
        },
        severe={
            "metallic_context_present": (1.0, 1.0),
            "component_count": (3, 10),
            "corroded_area_mm2": (8000.0, 90000.0),
            "pit_depth_mm": (1.50, 9.00),
            "scale_thickness_mm": (1.00, 6.00),
            "rust_color_shift": (0.60, 1.00),
            "runoff_length_mm": (600.0, 2200.0),
            "runoff_width_mm": (90.0, 330.0),
            "stain_opacity": (0.50, 0.95),
            "span_start_fraction": (0.0, 0.55),
        },
    ),
    coverage_limits=CoverageLimits(0.00002, 0.35, 24),
    validated_secondary_profiles=("CORROSION_RUNOFF_STAINING_V1",),
    notes=(
        "Fibreglass does not rust. When the visible mark sits on composite rather than "
        "metal it is labelled corrosion_staining, never corrosion_metallic."
    ),
)

CORROSION_RUNOFF_STAINING_V1 = DefectProfileVersion(
    id="CORROSION_RUNOFF_STAINING_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Rust runoff staining on composite",
    summary=(
        "Iron-oxide staining deposited on a composite surface by water draining off a "
        "corroding metallic part. Labelled as staining because the composite itself has "
        "not corroded."
    ),
    family="corrosion",
    renderer_key="corrosion_staining_v1",
    primary_category="corrosion_staining",
    emitted_categories=("corrosion_staining",),
    feature_flag="defect_corrosion_runoff_staining_v1",
    parameters=(
        spec("stain_area_mm2", MM2, 20.0, 400000.0, "Total stained composite area."),
        spec("streak_count", COUNT, 1, 24, "Number of distinct runoff streaks.", integral=True),
        spec("runoff_length_mm", MM, 10.0, 2500.0, "Length of the longest streak."),
        spec("runoff_width_mm", MM, 2.0, 400.0, "Mean streak width."),
        spec("stain_opacity", FRACTION, 0.0, 1.0, "Opacity of the stain."),
        spec("edge_diffusion_mm", MM, 0.5, 80.0, "Softness of the stain boundary."),
        spec("span_start_fraction", FRACTION, 0.0, 0.95, "Spanwise position."),
        spec("chord_position_fraction", FRACTION, 0.0, 1.0, "Chordwise position."),
    ),
    bands=bands(
        early={
            "stain_area_mm2": (100.0, 2000.0),
            "streak_count": (1, 3),
            "runoff_length_mm": (30.0, 200.0),
            "runoff_width_mm": (3.0, 25.0),
            "stain_opacity": (0.05, 0.25),
            "edge_diffusion_mm": (0.5, 8.0),
            "span_start_fraction": (0.0, 0.60),
            "chord_position_fraction": (0.05, 0.90),
        },
        moderate={
            "stain_area_mm2": (1800.0, 30000.0),
            "streak_count": (2, 9),
            "runoff_length_mm": (180.0, 900.0),
            "runoff_width_mm": (20.0, 120.0),
            "stain_opacity": (0.20, 0.55),
            "edge_diffusion_mm": (6.0, 30.0),
            "span_start_fraction": (0.0, 0.70),
            "chord_position_fraction": (0.05, 0.90),
        },
        severe={
            "stain_area_mm2": (25000.0, 300000.0),
            "streak_count": (6, 20),
            "runoff_length_mm": (800.0, 2200.0),
            "runoff_width_mm": (100.0, 340.0),
            "stain_opacity": (0.50, 0.95),
            "edge_diffusion_mm": (25.0, 70.0),
            "span_start_fraction": (0.0, 0.80),
            "chord_position_fraction": (0.05, 0.90),
        },
    ),
    coverage_limits=CoverageLimits(0.00002, 0.45, 24),
    supports_as_secondary=True,
    # Staining is the downstream effect of corroding metal, so the validated pairing
    # lives on CORROSION_RUST_STANDARD_V1 with this profile as the secondary.
    validated_secondary_profiles=(),
)

ALL_PROFILES: tuple[DefectProfileVersion, ...] = (
    LEE_STANDARD_V1,
    LIGHTNING_STRIKE_STANDARD_V1,
    SURFACE_CRACK_STANDARD_V1,
    DELAMINATION_STANDARD_V1,
    DELAMINATION_SUBSURFACE_V1,
    COATING_FAILURE_STANDARD_V1,
    CORROSION_RUST_STANDARD_V1,
    CORROSION_RUNOFF_STAINING_V1,
)
