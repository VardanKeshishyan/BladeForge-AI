"""Blade model versions, their model cards, and the UV layout contract.

Coordinate system (shared with the Blender generator and the web viewport)
-------------------------------------------------------------------------
* Units are metres. ``units_per_metre`` is 1.0 and the Blender scene unit scale is
  set explicitly rather than inherited.
* ``+Z`` is span. The root plane sits at ``z = 0`` and the tip at ``z = length_m``.
* ``-X`` is the leading edge, ``+X`` the trailing edge.
* ``+Y`` is the suction-side surface normal direction at the root.
* ``+Z`` is also world up for the scene, which keeps camera azimuth and elevation
  meaningful.

UV layout contract
------------------
``U`` runs chordwise: 0.0 at the leading edge, 0.5 at the trailing edge going over
the suction side, and back to 1.0 at the leading edge over the pressure side.
``V`` runs spanwise: 0.0 at the root, 1.0 at the tip.

This is what makes painted regions portable. A region mask is stored against a
``uv_layout_checksum``. The checksum is derived from the layout specification, which
is itself fully determined by the generator parameters, so any change to the blade
geometry or its unwrap invalidates saved regions and the customer is told to repaint
rather than being handed a silently misaligned mask.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import RegistryLookupError
from .versioning import (
    INTERNAL_AUTHORSHIP,
    LicenseRecord,
    ReleaseStatus,
    SemanticVersion,
    checksum,
    validate_registry_id,
)

BUILTIN_PROCEDURAL = "builtin_procedural"
CUSTOMER_IMPORT = "customer_import"

# Bumped when the blade generator's geometry or unwrap algorithm changes.
BLADE_GENERATOR_VERSION = "2.0.0"

# Landmarks used for region-mask round-trip validation. If a rasterised UV mask does
# not agree with these positions the unwrap has changed and the mask is unusable.
UV_LANDMARKS: dict[str, tuple[float, float]] = {
    "root_leading_edge": (0.0, 0.0),
    "tip_leading_edge": (0.0, 1.0),
    "root_trailing_edge": (0.5, 0.0),
    "tip_trailing_edge": (0.5, 1.0),
    "midspan_leading_edge": (0.0, 0.5),
    "midspan_trailing_edge": (0.5, 0.5),
    "midspan_pressure_side": (0.75, 0.5),
}


@dataclass(frozen=True)
class BladeSection:
    """A named spanwise region a customer can target damage at."""

    id: str
    display_name: str
    span_start_fraction: float
    span_end_fraction: float
    description: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.span_start_fraction < self.span_end_fraction <= 1.0:
            raise ValueError(f"Section {self.id}: invalid span range.")

    def contains(self, span_fraction: float) -> bool:
        return self.span_start_fraction <= span_fraction <= self.span_end_fraction

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "span_start_fraction": self.span_start_fraction,
            "span_end_fraction": self.span_end_fraction,
            "description": self.description,
        }


@dataclass(frozen=True)
class AirfoilStation:
    """One spanwise design station of the blade's lofted surface."""

    span_fraction: float
    chord_m: float
    twist_deg: float
    thickness_ratio: float
    prebend_m: float

    def as_dict(self) -> dict[str, float]:
        return {
            "span_fraction": self.span_fraction,
            "chord_m": self.chord_m,
            "twist_deg": self.twist_deg,
            "thickness_ratio": self.thickness_ratio,
            "prebend_m": self.prebend_m,
        }


@dataclass(frozen=True)
class UvLayoutSpec:
    """The unwrap contract. Its checksum gates painted-region reuse."""

    uv_set_name: str
    layout_algorithm: str
    u_axis: str
    v_axis: str
    chordwise_samples: int
    spanwise_samples: int
    seam_position: str
    landmarks: dict[str, tuple[float, float]] = field(
        default_factory=lambda: dict(UV_LANDMARKS)
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "uv_set_name": self.uv_set_name,
            "layout_algorithm": self.layout_algorithm,
            "u_axis": self.u_axis,
            "v_axis": self.v_axis,
            "chordwise_samples": self.chordwise_samples,
            "spanwise_samples": self.spanwise_samples,
            "seam_position": self.seam_position,
            "landmarks": {name: list(uv) for name, uv in sorted(self.landmarks.items())},
        }

    @property
    def checksum(self) -> str:
        return checksum(self.as_dict())


@dataclass(frozen=True)
class BladeModelVersion:
    id: str
    version: str
    status: str
    title: str
    summary: str
    source: str
    generator_version: str
    length_m: float
    root_diameter_m: float
    max_chord_m: float
    tip_chord_m: float
    stations: tuple[AirfoilStation, ...]
    sections: tuple[BladeSection, ...]
    uv_layout: UvLayoutSpec
    material_slots: tuple[str, ...]
    feature_flag: str
    units_per_metre: float = 1.0
    up_axis: str = "+Z"
    span_axis: str = "+Z"
    leading_edge_axis: str = "-X"
    trailing_edge_axis: str = "+X"
    # Approximate evaluated triangle count of the render artifact.
    triangle_budget: int = 0
    has_metallic_components: bool = False
    metallic_component_names: tuple[str, ...] = ()
    close_up_ready: bool = True
    preview_glb_path: str | None = None
    license: LicenseRecord = INTERNAL_AUTHORSHIP
    intended_limitations: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        validate_registry_id(self.id)
        SemanticVersion.parse(self.version)
        if self.status not in ReleaseStatus.ALL:
            raise ValueError(f"Unknown release status {self.status!r}")
        if self.source not in {BUILTIN_PROCEDURAL, CUSTOMER_IMPORT}:
            raise ValueError(f"{self.id}: unknown source {self.source!r}")
        if self.length_m <= 0:
            raise ValueError(f"{self.id}: length must be positive.")
        if not self.stations:
            raise ValueError(f"{self.id}: at least one airfoil station is required.")
        fractions = [station.span_fraction for station in self.stations]
        if fractions != sorted(fractions):
            raise ValueError(f"{self.id}: stations must be ordered from root to tip.")
        if not self.sections:
            raise ValueError(f"{self.id}: at least one named section is required.")
        # Sections must tile the span exactly, so every point belongs to one section.
        covered = 0.0
        for section in self.sections:
            if abs(section.span_start_fraction - covered) > 1e-9:
                raise ValueError(f"{self.id}: sections leave a gap or overlap at {covered}.")
            covered = section.span_end_fraction
        if abs(covered - 1.0) > 1e-9:
            raise ValueError(f"{self.id}: sections must reach the tip, stopped at {covered}.")
        if self.has_metallic_components and not self.metallic_component_names:
            raise ValueError(f"{self.id}: metallic components declared but not named.")

    @property
    def is_selectable(self) -> bool:
        return self.status == ReleaseStatus.RELEASED

    @property
    def uv_layout_checksum(self) -> str:
        return self.uv_layout.checksum

    def section(self, section_id: str) -> BladeSection:
        for section in self.sections:
            if section.id == section_id:
                return section
        raise RegistryLookupError(f"{self.id} has no section {section_id!r}")

    def section_ids(self) -> tuple[str, ...]:
        return tuple(section.id for section in self.sections)

    def chord_at(self, span_fraction: float) -> float:
        """Linear interpolation of chord between design stations, in metres."""
        clamped = max(0.0, min(1.0, span_fraction))
        previous = self.stations[0]
        for station in self.stations:
            if station.span_fraction >= clamped:
                if station.span_fraction == previous.span_fraction:
                    return station.chord_m
                weight = (clamped - previous.span_fraction) / (
                    station.span_fraction - previous.span_fraction
                )
                return previous.chord_m + weight * (station.chord_m - previous.chord_m)
            previous = station
        return self.stations[-1].chord_m

    def twist_at(self, span_fraction: float) -> float:
        clamped = max(0.0, min(1.0, span_fraction))
        previous = self.stations[0]
        for station in self.stations:
            if station.span_fraction >= clamped:
                if station.span_fraction == previous.span_fraction:
                    return station.twist_deg
                weight = (clamped - previous.span_fraction) / (
                    station.span_fraction - previous.span_fraction
                )
                return previous.twist_deg + weight * (station.twist_deg - previous.twist_deg)
            previous = station
        return self.stations[-1].twist_deg

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "status": self.status,
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "generator_version": self.generator_version,
            "length_m": self.length_m,
            "root_diameter_m": self.root_diameter_m,
            "max_chord_m": self.max_chord_m,
            "tip_chord_m": self.tip_chord_m,
            "units_per_metre": self.units_per_metre,
            "up_axis": self.up_axis,
            "span_axis": self.span_axis,
            "leading_edge_axis": self.leading_edge_axis,
            "trailing_edge_axis": self.trailing_edge_axis,
            "stations": [station.as_dict() for station in self.stations],
            "sections": [section.as_dict() for section in self.sections],
            "uv_layout": self.uv_layout.as_dict(),
            "uv_layout_checksum": self.uv_layout_checksum,
            "material_slots": list(self.material_slots),
            "triangle_budget": self.triangle_budget,
            "has_metallic_components": self.has_metallic_components,
            "metallic_component_names": list(self.metallic_component_names),
            "close_up_ready": self.close_up_ready,
            "preview_glb_path": self.preview_glb_path,
            "feature_flag": self.feature_flag,
            "license": self.license.as_dict(),
            "intended_limitations": list(self.intended_limitations),
            "notes": self.notes,
        }

    @property
    def checksum(self) -> str:
        return checksum(self.as_dict())

    def model_card(self) -> dict[str, Any]:
        """The model card shipped inside every dataset package."""
        return {
            "model_id": self.id,
            "model_version": self.version,
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "generator_version": self.generator_version,
            "dimensions": {
                "length_m": self.length_m,
                "root_diameter_m": self.root_diameter_m,
                "max_chord_m": self.max_chord_m,
                "tip_chord_m": self.tip_chord_m,
            },
            "coordinate_system": {
                "units": "metres",
                "units_per_metre": self.units_per_metre,
                "up_axis": self.up_axis,
                "span_axis": self.span_axis,
                "leading_edge_axis": self.leading_edge_axis,
                "trailing_edge_axis": self.trailing_edge_axis,
                "root_plane": "z = 0",
                "tip_plane": f"z = {self.length_m}",
            },
            "uv_set": self.uv_layout.as_dict(),
            "uv_layout_checksum": self.uv_layout_checksum,
            "materials": list(self.material_slots),
            "named_sections": [section.as_dict() for section in self.sections],
            "metallic_components": list(self.metallic_component_names),
            "triangle_budget": self.triangle_budget,
            "intended_limitations": list(self.intended_limitations),
            "license": self.license.as_dict(),
            "checksum": self.checksum,
        }

    def public_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "length_m": self.length_m,
            "sections": [section.as_dict() for section in self.sections],
            "uv_layout_checksum": self.uv_layout_checksum,
            "has_metallic_components": self.has_metallic_components,
            "preview_glb_path": self.preview_glb_path,
            "checksum": self.checksum,
        }


# ---------------------------------------------------------------------------
# The improved built-in blade
# ---------------------------------------------------------------------------

GENERIC_UV_LAYOUT_V1 = UvLayoutSpec(
    uv_set_name="BF_UV",
    layout_algorithm="chordwise_arclength_spanwise_linear_v1",
    u_axis="chordwise_arclength_leading_edge_seam",
    v_axis="spanwise_root_to_tip_linear",
    chordwise_samples=96,
    spanwise_samples=64,
    seam_position="leading_edge",
)

BF_GENERIC_BLADE_V1 = BladeModelVersion(
    id="BF_GENERIC_BLADE_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="BladeForge generic utility-scale blade",
    summary=(
        "Procedurally generated tapered and twisted airfoil-based blade at realistic "
        "utility scale, with named root, tip, leading edge, trailing edge, and spanwise "
        "sections, a stable unwrap, and metallic root hardware that gives corrosion an "
        "honest physical context."
    ),
    source=BUILTIN_PROCEDURAL,
    generator_version=BLADE_GENERATOR_VERSION,
    length_m=62.0,
    root_diameter_m=3.40,
    max_chord_m=4.20,
    tip_chord_m=0.55,
    stations=(
        AirfoilStation(0.000, 3.400, 14.0, 1.000, 0.000),
        AirfoilStation(0.035, 3.420, 13.6, 0.880, 0.002),
        AirfoilStation(0.080, 3.700, 12.8, 0.620, 0.010),
        AirfoilStation(0.150, 4.120, 11.2, 0.400, 0.038),
        AirfoilStation(0.220, 4.200, 9.10, 0.320, 0.082),
        AirfoilStation(0.300, 3.940, 6.80, 0.272, 0.152),
        AirfoilStation(0.400, 3.420, 4.60, 0.238, 0.286),
        AirfoilStation(0.500, 2.900, 3.10, 0.212, 0.470),
        AirfoilStation(0.600, 2.400, 1.90, 0.192, 0.732),
        AirfoilStation(0.700, 1.920, 0.95, 0.178, 1.108),
        AirfoilStation(0.800, 1.460, 0.10, 0.166, 1.640),
        AirfoilStation(0.900, 1.020, -0.80, 0.156, 2.360),
        AirfoilStation(0.960, 0.760, -1.30, 0.150, 2.860),
        AirfoilStation(1.000, 0.550, -1.50, 0.146, 3.200),
    ),
    sections=(
        BladeSection(
            "root_transition", "Root transition", 0.00, 0.15,
            "Cylindrical root and the transition into the first airfoil. Carries the "
            "metallic attachment hardware.",
        ),
        BladeSection(
            "inboard", "Inboard", 0.15, 0.35,
            "Maximum chord region. Thick sections, high structural loading.",
        ),
        BladeSection(
            "midspan", "Mid-span", 0.35, 0.65,
            "The long tapering mid-section where cracks and delamination are common.",
        ),
        BladeSection(
            "outboard", "Outboard", 0.65, 0.88,
            "High relative velocity. The dominant region for leading-edge erosion.",
        ),
        BladeSection(
            "tip", "Tip", 0.88, 1.00,
            "Tip region. Highest erosion rate and the usual lightning attachment zone.",
        ),
    ),
    uv_layout=GENERIC_UV_LAYOUT_V1,
    material_slots=(
        "GELCOAT_WHITE_V1",
        "PAINT_COATING_OFF_WHITE_V1",
        "COMPOSITE_SUBSTRATE_GFRP_V1",
        "LAMINATE_FIBERGLASS_EXPOSED_V1",
        "CARBON_LAMINATE_V1",
        "METAL_GALVANISED_STEEL_V1",
    ),
    feature_flag="blade_bf_generic_blade_v1",
    triangle_budget=248_000,
    has_metallic_components=True,
    metallic_component_names=(
        "BF_RootFlangeBolts",
        "BF_TipLightningReceptor",
        "BF_MidspanLightningReceptor",
    ),
    preview_glb_path="blade-models/BF_GENERIC_BLADE_V1/1.0.0/preview.glb",
    intended_limitations=(
        "A generic research blade, not a reproduction of any manufacturer's proprietary "
        "aerodynamic design.",
        "The internal spar and shear web are not modelled. Only the outer surface, its "
        "materials, and the metallic hardware are represented.",
        "Airfoil sections are a smooth analytic family, not measured airfoil coordinates.",
        "Root bolt hardware is representative rather than dimensionally certified.",
    ),
    notes=(
        "The blade is generated at render time from these parameters, so no mesh binary "
        "needs to be redistributed and the checksum fully determines the geometry."
    ),
)

# ---------------------------------------------------------------------------
# The preserved legacy blade
# ---------------------------------------------------------------------------

LEGACY_UV_LAYOUT_V1 = UvLayoutSpec(
    uv_set_name="UVMap",
    layout_algorithm="legacy_ring_loft_v1",
    u_axis="ring_index_linear",
    v_axis="section_index_linear",
    chordwise_samples=32,
    spanwise_samples=36,
    seam_position="ring_index_zero",
    landmarks={},
)

BF_LEGACY_DEV_BLADE_V1 = BladeModelVersion(
    id="BF_LEGACY_DEV_BLADE_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Legacy development blade segment",
    summary=(
        "The original procedural 7 m elliptical blade segment. Preserved unchanged so "
        "pre-upgrade jobs keep rendering identically. Not intended for new work."
    ),
    source=BUILTIN_PROCEDURAL,
    generator_version="1.0.0",
    length_m=7.0,
    root_diameter_m=1.15,
    max_chord_m=1.15,
    tip_chord_m=0.828,
    stations=(
        AirfoilStation(0.0, 1.150, -5.0, 0.191, 0.0),
        AirfoilStation(1.0, 0.828, 6.0, 0.191, 0.0),
    ),
    sections=(
        BladeSection(
            "full_segment", "Full segment", 0.0, 1.0,
            "The whole legacy segment. It has no separately named sections.",
        ),
    ),
    uv_layout=LEGACY_UV_LAYOUT_V1,
    material_slots=("GELCOAT_WHITE_V1", "ERODED_COMPOSITE_V1"),
    feature_flag="blade_bf_legacy_dev_blade_v1",
    triangle_budget=2_240,
    close_up_ready=False,
    preview_glb_path="blade-models/BF_LEGACY_DEV_BLADE_V1/1.0.0/preview.glb",
    intended_limitations=(
        "An elliptical cross-section approximation, not a real airfoil.",
        "A 7 m segment rather than a full blade, so absolute scale is not realistic.",
        "The unwrap has no defined landmarks, so painted regions are not supported on it.",
        "Topology is too coarse for close-up renders.",
    ),
    notes=(
        "Retained purely for backward compatibility with RENDER_ENGINE_VERSION=legacy and "
        "for reproducing datasets generated before the v2 renderer."
    ),
)

ALL_BLADE_MODELS: tuple[BladeModelVersion, ...] = (
    BF_GENERIC_BLADE_V1,
    BF_LEGACY_DEV_BLADE_V1,
)

DEFAULT_BLADE_MODEL_ID = BF_GENERIC_BLADE_V1.id
LEGACY_BLADE_MODEL_ID = BF_LEGACY_DEV_BLADE_V1.id

_BY_ID = {model.id: model for model in ALL_BLADE_MODELS}
_BY_REFERENCE = {f"{m.id}@{m.version}": m for m in ALL_BLADE_MODELS}


def get_blade_model(reference: str) -> BladeModelVersion:
    key = reference.strip()
    if "@" in key:
        try:
            return _BY_REFERENCE[key]
        except KeyError as exc:
            raise RegistryLookupError(f"Unknown blade model version {reference!r}") from exc
    try:
        return _BY_ID[key]
    except KeyError as exc:
        raise RegistryLookupError(f"Unknown blade model {reference!r}") from exc


def list_blade_models() -> tuple[BladeModelVersion, ...]:
    return tuple(model for model in ALL_BLADE_MODELS if model.is_selectable)


def registry_checksum() -> str:
    return checksum([model.as_dict() for model in ALL_BLADE_MODELS])


def supports_region_painting(model: BladeModelVersion) -> bool:
    """Painting needs defined UV landmarks so alignment can be verified."""
    return bool(model.uv_layout.landmarks)
