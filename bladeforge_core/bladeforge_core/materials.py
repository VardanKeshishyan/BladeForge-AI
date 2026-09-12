"""Physically based material versions for blade surfaces and their damage states.

Values are authored for Blender's Principled BSDF. Base colours are linear sRGB in
0..1. Nothing here references a downloaded texture: every material is procedural,
so the license registry can honestly record internal authorship. Customer-supplied
textures arrive through the model-import pipeline with their own license record.
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

GELCOAT = "gelcoat"
PAINT = "paint_coating"
COMPOSITE = "composite_substrate"
LAMINATE = "laminate"
METAL = "metal"
OXIDE = "oxide"
CONTAMINATION = "contamination"
MODIFIER = "modifier"


@dataclass(frozen=True)
class MaterialVersion:
    id: str
    version: str
    status: str
    title: str
    category: str
    base_color: tuple[float, float, float]
    roughness: float
    metallic: float = 0.0
    specular_ior_level: float = 0.5
    ior: float = 1.47
    # Clearcoat layer, which is what makes an intact gelcoat read as glossy.
    coat_weight: float = 0.0
    coat_roughness: float = 0.05
    sheen_weight: float = 0.0
    subsurface_weight: float = 0.0
    transmission_weight: float = 0.0
    emission_strength: float = 0.0
    normal_strength: float = 1.0
    # Procedural detail: micro-surface noise scale in millimetres and its amplitude.
    micro_detail_scale_mm: float = 4.0
    micro_detail_strength: float = 0.05
    # How much wetness lowers roughness and raises specular response for this material.
    wetness_roughness_response: float = 0.55
    wetness_specular_response: float = 0.35
    license: LicenseRecord = INTERNAL_AUTHORSHIP
    notes: str = ""
    _unused: tuple[()] = field(default=(), repr=False, compare=False)

    def __post_init__(self) -> None:
        validate_registry_id(self.id)
        SemanticVersion.parse(self.version)
        if self.status not in ReleaseStatus.ALL:
            raise ValueError(f"Unknown release status {self.status!r}")
        for name, value in (
            ("roughness", self.roughness),
            ("metallic", self.metallic),
            ("coat_weight", self.coat_weight),
            ("coat_roughness", self.coat_roughness),
            ("sheen_weight", self.sheen_weight),
            ("subsurface_weight", self.subsurface_weight),
            ("transmission_weight", self.transmission_weight),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{self.id}: {name}={value} must be within 0..1")
        if any(not 0.0 <= channel <= 1.0 for channel in self.base_color):
            raise ValueError(f"{self.id}: base_color channels must be within 0..1")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "status": self.status,
            "title": self.title,
            "category": self.category,
            "base_color": list(self.base_color),
            "roughness": self.roughness,
            "metallic": self.metallic,
            "specular_ior_level": self.specular_ior_level,
            "ior": self.ior,
            "coat_weight": self.coat_weight,
            "coat_roughness": self.coat_roughness,
            "sheen_weight": self.sheen_weight,
            "subsurface_weight": self.subsurface_weight,
            "transmission_weight": self.transmission_weight,
            "emission_strength": self.emission_strength,
            "normal_strength": self.normal_strength,
            "micro_detail_scale_mm": self.micro_detail_scale_mm,
            "micro_detail_strength": self.micro_detail_strength,
            "wetness_roughness_response": self.wetness_roughness_response,
            "wetness_specular_response": self.wetness_specular_response,
            "license": self.license.as_dict(),
            "notes": self.notes,
        }

    @property
    def checksum(self) -> str:
        return checksum(self.as_dict())

    def wet(self, wetness: float) -> dict[str, float]:
        """Material response under a given surface wetness, 0..1.

        Wet surfaces get smoother and more specular. This is the single place that
        relation is defined, so a wet-weather test can assert that the blade material
        actually responds rather than only the preset label changing.
        """
        amount = max(0.0, min(1.0, wetness))
        return {
            "roughness": max(
                0.02, self.roughness * (1.0 - self.wetness_roughness_response * amount)
            ),
            "specular_ior_level": min(
                1.0, self.specular_ior_level + self.wetness_specular_response * amount
            ),
            "coat_weight": min(1.0, self.coat_weight + 0.45 * amount),
            "coat_roughness": max(0.01, self.coat_roughness * (1.0 - 0.6 * amount)),
        }


GELCOAT_WHITE_V1 = MaterialVersion(
    id="GELCOAT_WHITE_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Intact white gelcoat",
    category=GELCOAT,
    base_color=(0.780, 0.795, 0.800),
    roughness=0.24,
    specular_ior_level=0.52,
    coat_weight=0.55,
    coat_roughness=0.06,
    micro_detail_scale_mm=6.0,
    micro_detail_strength=0.035,
    wetness_roughness_response=0.62,
    notes="Factory gelcoat with a clear top layer. The baseline undamaged surface.",
)

PAINT_COATING_OFF_WHITE_V1 = MaterialVersion(
    id="PAINT_COATING_OFF_WHITE_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Off-white painted coating",
    category=PAINT,
    base_color=(0.822, 0.826, 0.815),
    roughness=0.34,
    specular_ior_level=0.48,
    coat_weight=0.22,
    coat_roughness=0.12,
    micro_detail_scale_mm=3.0,
    micro_detail_strength=0.05,
    notes="Service-applied coating layer. Coating-failure modes act on this material.",
)

COMPOSITE_SUBSTRATE_GFRP_V1 = MaterialVersion(
    id="COMPOSITE_SUBSTRATE_GFRP_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Glass-fibre composite substrate",
    category=COMPOSITE,
    base_color=(0.402, 0.392, 0.360),
    roughness=0.62,
    specular_ior_level=0.42,
    ior=1.54,
    micro_detail_scale_mm=1.6,
    micro_detail_strength=0.16,
    wetness_roughness_response=0.40,
    notes="What is revealed once coating and gelcoat are gone.",
)

LAMINATE_FIBERGLASS_EXPOSED_V1 = MaterialVersion(
    id="LAMINATE_FIBERGLASS_EXPOSED_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Exposed fibreglass laminate",
    category=LAMINATE,
    base_color=(0.508, 0.478, 0.398),
    roughness=0.74,
    specular_ior_level=0.38,
    ior=1.55,
    sheen_weight=0.18,
    micro_detail_scale_mm=0.9,
    micro_detail_strength=0.28,
    notes="Directional weave visible where the laminate is torn or delaminated.",
)

CARBON_LAMINATE_V1 = MaterialVersion(
    id="CARBON_LAMINATE_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Carbon spar laminate",
    category=LAMINATE,
    base_color=(0.052, 0.054, 0.058),
    roughness=0.41,
    specular_ior_level=0.58,
    ior=1.62,
    micro_detail_scale_mm=1.1,
    micro_detail_strength=0.20,
    notes="Carbon spar cap material exposed by deep damage.",
)

ERODED_COMPOSITE_V1 = MaterialVersion(
    id="ERODED_COMPOSITE_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Eroded composite surface",
    category=COMPOSITE,
    base_color=(0.222, 0.221, 0.209),
    roughness=0.88,
    specular_ior_level=0.30,
    micro_detail_scale_mm=0.7,
    micro_detail_strength=0.42,
    wetness_roughness_response=0.30,
    notes="The rough, darkened surface left where erosion has removed material.",
)

CHARRED_COMPOSITE_V1 = MaterialVersion(
    id="CHARRED_COMPOSITE_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Charred composite",
    category=COMPOSITE,
    base_color=(0.038, 0.032, 0.029),
    roughness=0.93,
    specular_ior_level=0.22,
    micro_detail_scale_mm=1.4,
    micro_detail_strength=0.36,
    notes="Burnt material at a lightning attachment point.",
)

SOOT_DEPOSIT_V1 = MaterialVersion(
    id="SOOT_DEPOSIT_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Soot deposit",
    category=CONTAMINATION,
    base_color=(0.062, 0.058, 0.055),
    roughness=0.97,
    specular_ior_level=0.12,
    micro_detail_scale_mm=8.0,
    micro_detail_strength=0.22,
    notes="Loose soot around a strike. Washes off, so it varies between inspections.",
)

METAL_GALVANISED_STEEL_V1 = MaterialVersion(
    id="METAL_GALVANISED_STEEL_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Galvanised steel hardware",
    category=METAL,
    base_color=(0.560, 0.572, 0.585),
    roughness=0.38,
    metallic=1.0,
    specular_ior_level=0.60,
    micro_detail_scale_mm=2.2,
    micro_detail_strength=0.12,
    notes="Root fasteners and lightning receptors. The only honest context for corrosion.",
)

RUST_OXIDE_V1 = MaterialVersion(
    id="RUST_OXIDE_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Iron-oxide corrosion product",
    category=OXIDE,
    base_color=(0.318, 0.128, 0.048),
    roughness=0.90,
    metallic=0.0,
    specular_ior_level=0.26,
    micro_detail_scale_mm=1.0,
    micro_detail_strength=0.45,
    notes="Rust scale on metal. Non-metallic once oxidised, which is why metallic is 0.",
)

RUST_STAIN_OVERLAY_V1 = MaterialVersion(
    id="RUST_STAIN_OVERLAY_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Rust runoff stain overlay",
    category=CONTAMINATION,
    base_color=(0.392, 0.196, 0.098),
    roughness=0.70,
    specular_ior_level=0.34,
    micro_detail_scale_mm=12.0,
    micro_detail_strength=0.30,
    notes=(
        "A stain deposited on composite. Applied as an overlay, never as a change to the "
        "composite's own material class, because fibreglass does not corrode."
    ),
)

DIRT_OVERLAY_V1 = MaterialVersion(
    id="DIRT_OVERLAY_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Environmental dirt and salt",
    category=CONTAMINATION,
    base_color=(0.352, 0.330, 0.288),
    roughness=0.82,
    specular_ior_level=0.28,
    micro_detail_scale_mm=18.0,
    micro_detail_strength=0.20,
    notes="Background variation. Labelled only when the job requests contamination.",
)

INSECT_RESIDUE_V1 = MaterialVersion(
    id="INSECT_RESIDUE_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Insect residue",
    category=CONTAMINATION,
    base_color=(0.238, 0.208, 0.162),
    roughness=0.78,
    specular_ior_level=0.32,
    micro_detail_scale_mm=2.5,
    micro_detail_strength=0.30,
    notes="Small dark spots concentrated near the leading edge. Background variation.",
)

MANUFACTURING_VARIATION_V1 = MaterialVersion(
    id="MANUFACTURING_VARIATION_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Manufacturing variation modifier",
    category=MODIFIER,
    base_color=(0.500, 0.500, 0.500),
    roughness=0.30,
    micro_detail_scale_mm=120.0,
    micro_detail_strength=0.06,
    notes=(
        "Low-frequency modulation of gelcoat colour, roughness, and mould-seam visibility "
        "so that every blade is not identical."
    ),
)

WEAR_PATINA_V1 = MaterialVersion(
    id="WEAR_PATINA_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="General service wear",
    category=MODIFIER,
    base_color=(0.640, 0.638, 0.622),
    roughness=0.46,
    micro_detail_scale_mm=40.0,
    micro_detail_strength=0.10,
    notes="Uniform ageing of an in-service blade, distinct from a localised defect.",
)

WET_SURFACE_MODIFIER_V1 = MaterialVersion(
    id="WET_SURFACE_MODIFIER_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Wet surface modifier",
    category=MODIFIER,
    base_color=(0.500, 0.500, 0.505),
    roughness=0.06,
    specular_ior_level=0.85,
    ior=1.333,
    coat_weight=0.90,
    coat_roughness=0.03,
    transmission_weight=0.08,
    notes=(
        "Water film applied by the wet-weather presets. Drives the roughness drop and "
        "reflection increase that make rain presets measurably different."
    ),
)

ALL_MATERIALS: tuple[MaterialVersion, ...] = (
    GELCOAT_WHITE_V1,
    PAINT_COATING_OFF_WHITE_V1,
    COMPOSITE_SUBSTRATE_GFRP_V1,
    LAMINATE_FIBERGLASS_EXPOSED_V1,
    CARBON_LAMINATE_V1,
    ERODED_COMPOSITE_V1,
    CHARRED_COMPOSITE_V1,
    SOOT_DEPOSIT_V1,
    METAL_GALVANISED_STEEL_V1,
    RUST_OXIDE_V1,
    RUST_STAIN_OVERLAY_V1,
    DIRT_OVERLAY_V1,
    INSECT_RESIDUE_V1,
    MANUFACTURING_VARIATION_V1,
    WEAR_PATINA_V1,
    WET_SURFACE_MODIFIER_V1,
)

_BY_ID = {material.id: material for material in ALL_MATERIALS}


def get_material(material_id: str) -> MaterialVersion:
    try:
        return _BY_ID[material_id.strip()]
    except KeyError as exc:
        raise RegistryLookupError(f"Unknown material {material_id!r}") from exc


def list_materials(category: str | None = None) -> tuple[MaterialVersion, ...]:
    selected = tuple(m for m in ALL_MATERIALS if m.status == ReleaseStatus.RELEASED)
    if category is None:
        return selected
    return tuple(m for m in selected if m.category == category)


def materials_for_slots(slots: tuple[str, ...]) -> tuple[MaterialVersion, ...]:
    """Resolve a blade model's material slots, plus the overlays every render may use.

    The overlays are always included because dirt, manufacturing variation, wear, and
    the wet-surface modifier are driven per sample by domain randomization and weather
    rather than being declared by the model, and the manifest has to record the exact
    version of each one that was available to the render.
    """
    resolved: list[MaterialVersion] = [get_material(slot) for slot in slots]
    always_available = (
        DIRT_OVERLAY_V1,
        MANUFACTURING_VARIATION_V1,
        WEAR_PATINA_V1,
        WET_SURFACE_MODIFIER_V1,
    )
    for material in always_available:
        if material not in resolved:
            resolved.append(material)
    return tuple(resolved)


def defect_materials_for_renderer_key(renderer_key: str) -> tuple[MaterialVersion, ...]:
    """The materials a defect implementation is allowed to introduce."""
    mapping: dict[str, tuple[MaterialVersion, ...]] = {
        "lee_material_loss_v1": (
            ERODED_COMPOSITE_V1,
            LAMINATE_FIBERGLASS_EXPOSED_V1,
            COMPOSITE_SUBSTRATE_GFRP_V1,
        ),
        "lightning_strike_v1": (
            CHARRED_COMPOSITE_V1,
            SOOT_DEPOSIT_V1,
            LAMINATE_FIBERGLASS_EXPOSED_V1,
            CARBON_LAMINATE_V1,
        ),
        "surface_crack_v1": (COMPOSITE_SUBSTRATE_GFRP_V1, LAMINATE_FIBERGLASS_EXPOSED_V1),
        "delamination_surface_v1": (
            LAMINATE_FIBERGLASS_EXPOSED_V1,
            COMPOSITE_SUBSTRATE_GFRP_V1,
        ),
        "delamination_subsurface_v1": (COMPOSITE_SUBSTRATE_GFRP_V1,),
        "coating_failure_v1": (
            PAINT_COATING_OFF_WHITE_V1,
            GELCOAT_WHITE_V1,
            COMPOSITE_SUBSTRATE_GFRP_V1,
            WEAR_PATINA_V1,
        ),
        "corrosion_metallic_v1": (RUST_OXIDE_V1, METAL_GALVANISED_STEEL_V1),
        "corrosion_staining_v1": (RUST_STAIN_OVERLAY_V1,),
    }
    try:
        return mapping[renderer_key]
    except KeyError as exc:
        raise RegistryLookupError(
            f"No material set is defined for renderer key {renderer_key!r}"
        ) from exc


def registry_checksum() -> str:
    return checksum([material.as_dict() for material in ALL_MATERIALS])
