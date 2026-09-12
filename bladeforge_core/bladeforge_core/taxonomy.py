"""Versioned label taxonomy with permanently stable category IDs.

Contract
--------
A category ID that has shipped is never reused for a different meaning and never
renumbered. Downstream customers train models against these integers; changing
one silently corrupts every model they already trained.

Adding a new category is allowed: append it with the next free ID and bump the
taxonomy minor version. ``tests/test_taxonomy_stability.py`` pins the shipped
ID-to-name mapping so an accidental renumber fails the build.

ID bands
--------
``0``          background. Always exactly zero in a class-ID mask.
``1``-``99``   defect classes. These are the trainable targets.
``100``-``199`` reserved for future defect classes.
``200``-``249`` structural context (blade surface, metallic hardware). Emitted only
               in the optional combined semantic mask, never as a defect instance.
``250``-``255`` reserved sentinels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import RegistryLookupError
from .versioning import INTERNAL_AUTHORSHIP, LicenseRecord, checksum

BACKGROUND_ID = 0
DEFECT_ID_MIN = 1
DEFECT_ID_MAX = 99
STRUCTURAL_ID_MIN = 200
STRUCTURAL_ID_MAX = 249


@dataclass(frozen=True)
class Category:
    """One trainable or structural label."""

    id: int
    name: str
    supercategory: str
    display_name: str
    description: str
    # False when the class describes damage that cannot honestly be delineated in
    # an RGB image. Such classes are recorded in metadata but never exported as a
    # visible segmentation target.
    annotatable_from_rgb: bool = True
    # True for context classes that describe the part rather than a defect.
    structural: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "supercategory": self.supercategory,
            "display_name": self.display_name,
            "description": self.description,
            "annotatable_from_rgb": self.annotatable_from_rgb,
            "structural": self.structural,
        }


# ---------------------------------------------------------------------------
# Shipped categories. Append only. Never renumber.
# ---------------------------------------------------------------------------

_CATEGORIES: tuple[Category, ...] = (
    Category(
        id=1,
        name="leading_edge_erosion",
        supercategory="erosion",
        display_name="Leading-edge erosion",
        description=(
            "Material loss along the leading edge: coating removal, edge breakup, "
            "pitting, and exposed substrate caused by rain and particle impact."
        ),
    ),
    Category(
        id=2,
        name="lightning_strike_damage",
        supercategory="lightning",
        display_name="Lightning strike damage",
        description="The strike entry region where the arc attached to the blade.",
    ),
    Category(
        id=3,
        name="surface_crack",
        supercategory="crack",
        display_name="Surface crack",
        description="An open fissure in the gelcoat or laminate that follows the surface.",
    ),
    Category(
        id=4,
        name="delamination",
        supercategory="delamination",
        display_name="Delamination (surface visible)",
        description=(
            "Composite plies that have separated enough to lift, blister, or distort "
            "the outer surface so the damage is visible in an RGB image."
        ),
    ),
    Category(
        id=5,
        name="coating_failure",
        supercategory="coating",
        display_name="Coating failure",
        description="Degradation of the paint or coating layer without deep structural loss.",
    ),
    Category(
        id=6,
        name="corrosion_rust",
        supercategory="corrosion",
        display_name="Corrosion or rust",
        description=(
            "Oxidation of a metallic component. Parent class for actual metallic "
            "corrosion and for rust runoff staining on adjacent composite."
        ),
    ),
    Category(
        id=7,
        name="lightning_scorch",
        supercategory="lightning",
        display_name="Lightning scorch or burn",
        description="Radial burn, soot, and discoloration branching away from the entry point.",
    ),
    Category(
        id=8,
        name="lightning_puncture",
        supercategory="lightning",
        display_name="Lightning puncture",
        description="A through-thickness or deep localised perforation at the attachment point.",
    ),
    Category(
        id=9,
        name="lightning_delamination",
        supercategory="lightning",
        display_name="Lightning-induced delamination",
        description="Ply separation caused by the pressure pulse around a strike.",
    ),
    Category(
        id=10,
        name="exposed_substrate",
        supercategory="substrate",
        display_name="Exposed substrate",
        description=(
            "Bare composite, laminate, or fibre visible because the coating above it "
            "is gone. Shared by several defect families."
        ),
    ),
    Category(
        id=11,
        name="coating_peeling",
        supercategory="coating",
        display_name="Coating peeling",
        description="Coating lifting from the substrate with a raised, curling edge.",
    ),
    Category(
        id=12,
        name="coating_flaking",
        supercategory="coating",
        display_name="Coating flaking",
        description="Coating breaking away in discrete flakes leaving hard-edged islands.",
    ),
    Category(
        id=13,
        name="coating_chalking",
        supercategory="coating",
        display_name="Coating chalking",
        description="Powdery, whitened, UV-degraded coating surface with raised diffuse response.",
    ),
    Category(
        id=14,
        name="coating_thinning",
        supercategory="coating",
        display_name="Coating thinning",
        description="Reduced coating thickness showing the substrate colour through it.",
    ),
    Category(
        id=15,
        name="coating_discoloration",
        supercategory="coating",
        display_name="Coating discoloration",
        description="Colour shift from UV, heat, or contamination with the coating still intact.",
    ),
    Category(
        id=16,
        name="corrosion_metallic",
        supercategory="corrosion",
        display_name="Metallic corrosion",
        description=(
            "Oxidation, pitting, and scale on a genuinely metallic part: attachment "
            "hardware, fasteners, lightning-protection components, or metallic inserts."
        ),
    ),
    Category(
        id=17,
        name="corrosion_staining",
        supercategory="corrosion",
        display_name="Rust runoff staining",
        description=(
            "Iron-oxide staining deposited on a composite surface by water running off "
            "a corroding metallic part. The composite itself has not corroded."
        ),
    ),
    Category(
        id=18,
        name="delamination_subsurface",
        supercategory="delamination",
        display_name="Delamination (subsurface only)",
        description=(
            "Ply separation with no reliable outer-surface signature. Recorded in "
            "metadata for physical realism, never exported as an RGB segmentation target."
        ),
        annotatable_from_rgb=False,
    ),
    Category(
        id=19,
        name="erosion_pitting",
        supercategory="erosion",
        display_name="Erosion pitting",
        description="Discrete impact pits within an eroded region.",
    ),
    Category(
        id=20,
        name="erosion_coating_loss",
        supercategory="erosion",
        display_name="Erosion coating loss",
        description="The area where erosion has removed the coating but not the laminate.",
    ),
    Category(
        id=21,
        name="gelcoat_chipping",
        supercategory="erosion",
        display_name="Gelcoat chipping",
        description="Hard-edged gelcoat chips at the leading edge.",
    ),
    Category(
        id=22,
        name="surface_contamination",
        supercategory="background_variation",
        display_name="Surface contamination",
        description=(
            "Dirt, salt, insect residue, and streaking. Treated as background variation "
            "unless the job explicitly requests it as a labelled class."
        ),
    ),
    Category(
        id=200,
        name="blade_surface",
        supercategory="structure",
        display_name="Blade surface",
        description="Undamaged blade surface. Structural context for the semantic mask.",
        structural=True,
    ),
    Category(
        id=201,
        name="blade_metallic_component",
        supercategory="structure",
        display_name="Blade metallic component",
        description=(
            "Metallic hardware on the blade: root fasteners, lightning receptors, and "
            "metallic inserts. Provides the physical context corrosion requires."
        ),
        structural=True,
    ),
)


@dataclass(frozen=True)
class TaxonomyVersion:
    id: str
    version: str
    categories: tuple[Category, ...]
    license: LicenseRecord = INTERNAL_AUTHORSHIP
    _by_id: dict[int, Category] = field(default_factory=dict, repr=False, compare=False)
    _by_name: dict[str, Category] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        seen_ids: set[int] = set()
        seen_names: set[str] = set()
        for category in self.categories:
            if category.id in seen_ids:
                raise ValueError(f"Duplicate category id {category.id}")
            if category.name in seen_names:
                raise ValueError(f"Duplicate category name {category.name!r}")
            if category.id == BACKGROUND_ID:
                raise ValueError("Category id 0 is reserved for background")
            if category.structural:
                if not STRUCTURAL_ID_MIN <= category.id <= STRUCTURAL_ID_MAX:
                    raise ValueError(
                        f"Structural category {category.name!r} must use id "
                        f"{STRUCTURAL_ID_MIN}-{STRUCTURAL_ID_MAX}"
                    )
            elif not DEFECT_ID_MIN <= category.id <= DEFECT_ID_MAX:
                raise ValueError(
                    f"Defect category {category.name!r} must use id "
                    f"{DEFECT_ID_MIN}-{DEFECT_ID_MAX}"
                )
            seen_ids.add(category.id)
            seen_names.add(category.name)
        self._by_id.update({category.id: category for category in self.categories})
        self._by_name.update({category.name: category for category in self.categories})

    def by_id(self, category_id: int) -> Category:
        try:
            return self._by_id[category_id]
        except KeyError as exc:
            raise RegistryLookupError(f"Unknown category id {category_id}") from exc

    def by_name(self, name: str) -> Category:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise RegistryLookupError(f"Unknown category name {name!r}") from exc

    def defect_categories(self) -> tuple[Category, ...]:
        return tuple(c for c in self.categories if not c.structural)

    def annotatable_categories(self) -> tuple[Category, ...]:
        return tuple(c for c in self.defect_categories() if c.annotatable_from_rgb)

    def id_map(self) -> dict[int, str]:
        return {category.id: category.name for category in self.categories}

    def as_dict(self) -> dict[str, Any]:
        return {
            "taxonomy_id": self.id,
            "taxonomy_version": self.version,
            "background_id": BACKGROUND_ID,
            "categories": [category.as_dict() for category in self.categories],
        }

    @property
    def checksum(self) -> str:
        return checksum(self.as_dict())

    def coco_categories(self, names: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        """COCO ``categories`` entries, restricted to annotatable defect classes."""
        selected = self.annotatable_categories()
        if names is not None:
            wanted = set(names)
            selected = tuple(c for c in selected if c.name in wanted)
        return [
            {"id": c.id, "name": c.name, "supercategory": c.supercategory} for c in selected
        ]


TAXONOMY_V1 = TaxonomyVersion(
    id="BLADEFORGE_DEFECT_TAXONOMY",
    version="1.0.0",
    categories=_CATEGORIES,
)

ACTIVE_TAXONOMY = TAXONOMY_V1

_TAXONOMIES: dict[str, TaxonomyVersion] = {
    f"{TAXONOMY_V1.id}@{TAXONOMY_V1.version}": TAXONOMY_V1,
}


def get_taxonomy(reference: str | None = None) -> TaxonomyVersion:
    if reference is None:
        return ACTIVE_TAXONOMY
    try:
        return _TAXONOMIES[reference]
    except KeyError as exc:
        raise RegistryLookupError(f"Unknown taxonomy reference {reference!r}") from exc


def category_id(name: str) -> int:
    return ACTIVE_TAXONOMY.by_name(name).id


def category_name(identifier: int) -> str:
    return ACTIVE_TAXONOMY.by_id(identifier).name
