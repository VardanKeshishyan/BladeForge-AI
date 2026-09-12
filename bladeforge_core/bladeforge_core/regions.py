"""Painted damage regions: colour layers, stroke documents, and the UV permission mask.

How this works end to end
-------------------------
1. In the viewport the customer paints on the blade with a coloured brush. Each colour
   is a *layer*. A layer is bound to one defect profile version, a severity range, and
   a coverage target.
2. The browser records strokes in UV space, not screen space, together with the model
   version and its ``uv_layout_checksum``.
3. The backend rasterises the strokes into one authoritative single-channel mask where
   each pixel holds the *layer index*, not an RGB colour. Both the stroke document and
   the raster are stored privately.
4. Blender loads the raster and generates each defect only where its own layer index
   appears. A defect cannot escape its region.

Colours are interface identifiers only. Stored data keys off stable ``region_id`` and
``defect_profile_version`` values, so re-theming the UI cannot change what gets
generated, and two customers who both use "red" are unaffected by each other.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from .blades import BladeModelVersion, supports_region_painting
from .errors import ParameterValidationError, RegionMaskError
from .versioning import checksum

STROKE_SCHEMA_VERSION = "2.0.0"
MASK_SCHEMA_VERSION = "2.0.0"

REGION_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")

# A single-channel mask can hold this many distinct layers. Index 0 means "not painted".
MAX_REGION_LAYERS = 32
UNPAINTED = 0

DEFAULT_MASK_WIDTH = 2048
DEFAULT_MASK_HEIGHT = 1024
MIN_MASK_SIDE = 256
MAX_MASK_SIDE = 8192

MAX_STROKES = 4000
MAX_POINTS_PER_STROKE = 4000
MAX_TOTAL_POINTS = 250_000

PAINT = "paint"
ERASE = "erase"


@dataclass(frozen=True)
class PaletteEntry:
    """One suggested colour and what it means, so a first-time user needs no manual."""

    color_key: str
    hex_color: str
    display_name: str
    defect_profile_id: str
    what_it_paints: str
    when_to_use: str

    def as_dict(self) -> dict[str, str]:
        return {
            "color_key": self.color_key,
            "hex_color": self.hex_color,
            "display_name": self.display_name,
            "defect_profile_id": self.defect_profile_id,
            "what_it_paints": self.what_it_paints,
            "when_to_use": self.when_to_use,
        }


# The suggested palette. The frontend renders this as an always-visible legend and as
# a first-run walkthrough, which is why every entry carries plain-language guidance.
DEFAULT_PALETTE: tuple[PaletteEntry, ...] = (
    PaletteEntry(
        color_key="green",
        hex_color="#22c55e",
        display_name="Leading-edge erosion",
        defect_profile_id="LEE_STANDARD_V1",
        what_it_paints="Material loss along the leading edge.",
        when_to_use=(
            "Paint a narrow band along the front edge, usually on the outer half of the "
            "blade where rain impact speed is highest."
        ),
    ),
    PaletteEntry(
        color_key="red",
        hex_color="#ef4444",
        display_name="Lightning strike damage",
        defect_profile_id="LIGHTNING_STRIKE_STANDARD_V1",
        what_it_paints="Strike entry point with branching burn and scorch.",
        when_to_use=(
            "Paint a compact patch near the tip or over a lightning receptor. Strikes "
            "attach at a point, so keep the region small."
        ),
    ),
    PaletteEntry(
        color_key="purple",
        hex_color="#a855f7",
        display_name="Surface cracks",
        defect_profile_id="SURFACE_CRACK_STANDARD_V1",
        what_it_paints="Open fissures that follow the blade surface.",
        when_to_use=(
            "Paint along the area where cracks should run. Mid-span and the trailing-edge "
            "bond line are the usual places."
        ),
    ),
    PaletteEntry(
        color_key="blue",
        hex_color="#3b82f6",
        display_name="Delamination",
        defect_profile_id="DELAMINATION_STANDARD_V1",
        what_it_paints="Lifted, blistered, or bubbled composite plies.",
        when_to_use=(
            "Paint a broader area away from the leading edge. Only surface-visible "
            "delamination is labelled."
        ),
    ),
    PaletteEntry(
        color_key="yellow",
        hex_color="#eab308",
        display_name="Coating failure",
        defect_profile_id="COATING_FAILURE_STANDARD_V1",
        what_it_paints="Peeling, flaking, chalking, thinning, and paint loss.",
        when_to_use=(
            "Paint large, loose areas. Coating degradation spreads over wide regions "
            "rather than sitting in one spot."
        ),
    ),
    PaletteEntry(
        color_key="orange",
        hex_color="#f97316",
        display_name="Corrosion and rust",
        defect_profile_id="CORROSION_RUST_STANDARD_V1",
        what_it_paints="Corroding metal hardware and the rust it stains below itself.",
        when_to_use=(
            "Paint over metallic hardware, normally near the root. Composite does not "
            "corrode, so on composite the result is labelled rust staining instead."
        ),
    ),
    PaletteEntry(
        color_key="cyan",
        hex_color="#06b6d4",
        display_name="Rust runoff staining",
        defect_profile_id="CORROSION_RUNOFF_STAINING_V1",
        what_it_paints="Iron-oxide staining on composite below a corroding part.",
        when_to_use="Paint a downward streak from wherever you painted corroding metal.",
    ),
)

REGION_PAINTING_GUIDE: dict[str, Any] = {
    "version": "1.0.0",
    "headline": "Paint where each defect is allowed to appear",
    "steps": [
        {
            "title": "Pick a colour",
            "body": (
                "Each colour is one defect type. Green is leading-edge erosion, red is "
                "lightning damage, purple is cracks, blue is delamination, yellow is "
                "coating failure, orange is corroding metal, cyan is rust staining."
            ),
        },
        {
            "title": "Paint on the blade",
            "body": (
                "Drag on the model to mark where that defect may be generated. Adjust the "
                "brush size, erase to correct, and undo if you overshoot."
            ),
        },
        {
            "title": "Set severity per colour",
            "body": (
                "Every colour gets its own severity range and coverage, so one image can "
                "carry early erosion at the tip and severe coating failure inboard."
            ),
        },
        {
            "title": "Nothing appears outside your paint",
            "body": (
                "The renderer treats your painted mask as a hard permission boundary. Any "
                "unpainted surface stays undamaged."
            ),
        },
    ],
    "notes": [
        "Colours are only labels in this interface. Your saved regions are stored against "
        "stable identifiers, so changing the palette never changes your data.",
        "If you switch to a blade model with a different surface layout, saved regions are "
        "rejected rather than silently misaligned, and you are asked to repaint.",
        "Leaving every colour unpainted lets each defect use its default region for the "
        "blade section you selected.",
    ],
}


@dataclass(frozen=True)
class RegionLayer:
    """One painted colour layer bound to a defect profile."""

    region_id: str
    layer_index: int
    display_name: str
    color_key: str
    hex_color: str
    defect_profile_id: str
    defect_profile_version: str
    severity_min: float
    severity_max: float
    coverage_target: float
    instance_count_min: int = 1
    instance_count_max: int = 1
    parameter_overrides: dict[str, float] = field(default_factory=dict)
    # Free text stays a note. It never changes geometry.
    customer_note: str | None = None

    def __post_init__(self) -> None:
        if not REGION_ID.match(self.region_id):
            raise ParameterValidationError(
                f"region_id {self.region_id!r} must be lowercase letters, digits, hyphen, "
                "or underscore, 2 to 63 characters."
            )
        if not 1 <= self.layer_index <= MAX_REGION_LAYERS:
            raise ParameterValidationError(
                f"layer_index {self.layer_index} must be within 1..{MAX_REGION_LAYERS}. "
                "Index 0 is reserved for unpainted surface."
            )
        if not 0.0 <= self.severity_min <= self.severity_max <= 100.0:
            raise ParameterValidationError(
                f"Layer {self.region_id}: severity range {self.severity_min}-"
                f"{self.severity_max} must be ordered and inside 0..100."
            )
        if not 0.0 < self.coverage_target <= 1.0:
            raise ParameterValidationError(
                f"Layer {self.region_id}: coverage_target must be within 0..1 exclusive of 0."
            )
        if not 1 <= self.instance_count_min <= self.instance_count_max <= 64:
            raise ParameterValidationError(
                f"Layer {self.region_id}: instance count range is invalid."
            )
        if self.customer_note is not None and len(self.customer_note) > 2000:
            raise ParameterValidationError("customer_note is limited to 2000 characters.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "layer_index": self.layer_index,
            "display_name": self.display_name,
            "color_key": self.color_key,
            "hex_color": self.hex_color,
            "defect_profile_id": self.defect_profile_id,
            "defect_profile_version": self.defect_profile_version,
            "severity_min": self.severity_min,
            "severity_max": self.severity_max,
            "coverage_target": self.coverage_target,
            "instance_count_min": self.instance_count_min,
            "instance_count_max": self.instance_count_max,
            "parameter_overrides": dict(sorted(self.parameter_overrides.items())),
            "customer_note": self.customer_note,
        }


@dataclass(frozen=True)
class BrushStroke:
    """One brush gesture recorded in UV space."""

    region_id: str
    mode: str
    radius_uv: float
    points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if self.mode not in {PAINT, ERASE}:
            raise ParameterValidationError(f"Unknown stroke mode {self.mode!r}.")
        if not 0.0005 <= self.radius_uv <= 0.5:
            raise ParameterValidationError(
                f"Brush radius {self.radius_uv} in UV units must be within 0.0005..0.5."
            )
        if not self.points:
            raise ParameterValidationError("A stroke needs at least one point.")
        if len(self.points) > MAX_POINTS_PER_STROKE:
            raise ParameterValidationError(
                f"A stroke may not exceed {MAX_POINTS_PER_STROKE} points."
            )
        for u, v in self.points:
            if not (math.isfinite(u) and math.isfinite(v)):
                raise ParameterValidationError("Stroke points must be finite.")
            if not (-0.001 <= u <= 1.001 and -0.001 <= v <= 1.001):
                raise ParameterValidationError(
                    f"Stroke point ({u}, {v}) is outside the 0..1 UV square."
                )

    def as_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "mode": self.mode,
            "radius_uv": self.radius_uv,
            "points": [[round(u, 6), round(v, 6)] for u, v in self.points],
        }


@dataclass(frozen=True)
class RegionStrokeDocument:
    """The editable source of truth for a painted region set."""

    name: str
    blade_model_id: str
    blade_model_version: str
    uv_set_name: str
    uv_layout_checksum: str
    mask_width: int
    mask_height: int
    layers: tuple[RegionLayer, ...]
    strokes: tuple[BrushStroke, ...]
    schema_version: str = STROKE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.layers:
            raise ParameterValidationError("A painted region needs at least one colour layer.")
        if len(self.layers) > MAX_REGION_LAYERS:
            raise ParameterValidationError(
                f"At most {MAX_REGION_LAYERS} colour layers are supported."
            )
        indices = [layer.layer_index for layer in self.layers]
        if len(set(indices)) != len(indices):
            raise ParameterValidationError("Two colour layers share a layer_index.")
        ids = [layer.region_id for layer in self.layers]
        if len(set(ids)) != len(ids):
            raise ParameterValidationError("Two colour layers share a region_id.")
        if len(self.strokes) > MAX_STROKES:
            raise ParameterValidationError(f"At most {MAX_STROKES} strokes are supported.")
        total_points = sum(len(stroke.points) for stroke in self.strokes)
        if total_points > MAX_TOTAL_POINTS:
            raise ParameterValidationError(
                f"A region document may not exceed {MAX_TOTAL_POINTS} stroke points."
            )
        known = set(ids)
        unknown = {stroke.region_id for stroke in self.strokes} - known
        if unknown:
            raise ParameterValidationError(
                f"Strokes reference undefined layers: {sorted(unknown)}."
            )
        for side, value in (("mask_width", self.mask_width), ("mask_height", self.mask_height)):
            if not MIN_MASK_SIDE <= value <= MAX_MASK_SIDE:
                raise ParameterValidationError(
                    f"{side}={value} must be within {MIN_MASK_SIDE}..{MAX_MASK_SIDE}."
                )

    def layer_by_id(self, region_id: str) -> RegionLayer:
        for layer in self.layers:
            if layer.region_id == region_id:
                return layer
        raise RegionMaskError(f"Unknown region layer {region_id!r}")

    def layer_index_map(self) -> dict[str, int]:
        return {layer.region_id: layer.layer_index for layer in self.layers}

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "blade_model_id": self.blade_model_id,
            "blade_model_version": self.blade_model_version,
            "uv_set_name": self.uv_set_name,
            "uv_layout_checksum": self.uv_layout_checksum,
            "mask_width": self.mask_width,
            "mask_height": self.mask_height,
            "layers": [layer.as_dict() for layer in self.layers],
            "strokes": [stroke.as_dict() for stroke in self.strokes],
        }

    @property
    def checksum(self) -> str:
        return checksum(self.as_dict())


def assert_region_matches_model(
    document: RegionStrokeDocument, model: BladeModelVersion
) -> None:
    """Refuse a saved region whose model or unwrap has changed.

    Reusing a mask across a different UV layout would silently place damage in the
    wrong place, so this fails loudly and asks the customer to repaint instead.
    """
    if not supports_region_painting(model):
        raise RegionMaskError(
            f"{model.id} has no defined UV landmarks, so painted regions are not "
            "supported on it. Choose a model that does, such as BF_GENERIC_BLADE_V1."
        )
    if document.blade_model_id != model.id:
        raise RegionMaskError(
            f"This painted region was made for {document.blade_model_id} but the job uses "
            f"{model.id}. Repaint the region on the selected model."
        )
    if document.uv_set_name != model.uv_layout.uv_set_name:
        raise RegionMaskError(
            f"This painted region uses UV set {document.uv_set_name!r} but "
            f"{model.id} exposes {model.uv_layout.uv_set_name!r}. Repaint the region."
        )
    if document.uv_layout_checksum != model.uv_layout_checksum:
        raise RegionMaskError(
            f"The surface layout of {model.id} version {model.version} has changed since "
            "this region was painted, so the saved strokes no longer line up. Repaint the "
            "region on the current model version."
        )


@dataclass(frozen=True)
class RasterisedRegionMask:
    """The authoritative permission mask handed to Blender."""

    width: int
    height: int
    # Row-major bytes, one byte per pixel holding the layer index. 0 means unpainted.
    data: bytes
    layer_index_map: dict[str, int]
    coverage_by_region: dict[str, float]
    bounding_box_by_region: dict[str, tuple[float, float, float, float]]
    schema_version: str = MASK_SCHEMA_VERSION

    @property
    def total_coverage(self) -> float:
        return sum(self.coverage_by_region.values())

    @property
    def checksum(self) -> str:
        from .versioning import checksum_bytes

        return checksum_bytes(self.data)

    def as_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "width": self.width,
            "height": self.height,
            "checksum_sha256": self.checksum,
            "layer_index_map": dict(sorted(self.layer_index_map.items())),
            "coverage_by_region": {
                k: round(v, 8) for k, v in sorted(self.coverage_by_region.items())
            },
            "bounding_box_by_region": {
                k: [round(x, 6) for x in v]
                for k, v in sorted(self.bounding_box_by_region.items())
            },
            "total_coverage": round(self.total_coverage, 8),
        }


def rasterise_region_mask(document: RegionStrokeDocument) -> RasterisedRegionMask:
    """Turn stroke geometry into a single-channel layer-index mask.

    Strokes are applied in recorded order so that erase gestures and overpainting
    behave the way the customer saw them in the viewport.
    """
    import numpy as np

    width = document.mask_width
    height = document.mask_height
    canvas = np.zeros((height, width), dtype=np.uint8)
    index_map = document.layer_index_map()

    # Pixel grid in UV space, built once and reused for every stamp.
    us = (np.arange(width, dtype=np.float64) + 0.5) / width
    vs = (np.arange(height, dtype=np.float64) + 0.5) / height
    grid_u, grid_v = np.meshgrid(us, vs)

    for stroke in document.strokes:
        value = index_map[stroke.region_id] if stroke.mode == PAINT else UNPAINTED
        radius = stroke.radius_uv
        covered = np.zeros((height, width), dtype=bool)
        points = list(stroke.points)
        for point_index, (u, v) in enumerate(points):
            covered |= ((grid_u - u) ** 2 + (grid_v - v) ** 2) <= radius * radius
            if point_index == 0:
                continue
            # Fill the segment between consecutive samples so a fast drag stays solid.
            previous_u, previous_v = points[point_index - 1]
            segment_length = math.hypot(u - previous_u, v - previous_v)
            steps = int(segment_length / max(radius * 0.5, 1e-6))
            for step in range(1, min(steps, 512)):
                weight = step / steps
                mid_u = previous_u + (u - previous_u) * weight
                mid_v = previous_v + (v - previous_v) * weight
                covered |= ((grid_u - mid_u) ** 2 + (grid_v - mid_v) ** 2) <= radius * radius
        if stroke.mode == PAINT:
            canvas[covered] = value
        else:
            # Erase removes only this layer's pixels, leaving other colours intact.
            erase_target = index_map[stroke.region_id]
            canvas[covered & (canvas == erase_target)] = UNPAINTED

    total_pixels = float(width * height)
    coverage: dict[str, float] = {}
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for region_id, index in index_map.items():
        hit = canvas == index
        count = int(hit.sum())
        coverage[region_id] = count / total_pixels
        if count == 0:
            boxes[region_id] = (0.0, 0.0, 0.0, 0.0)
            continue
        rows = np.flatnonzero(hit.any(axis=1))
        cols = np.flatnonzero(hit.any(axis=0))
        boxes[region_id] = (
            float(cols[0]) / width,
            float(rows[0]) / height,
            float(cols[-1] + 1 - cols[0]) / width,
            float(rows[-1] + 1 - rows[0]) / height,
        )

    return RasterisedRegionMask(
        width=width,
        height=height,
        data=canvas.tobytes(),
        layer_index_map=index_map,
        coverage_by_region=coverage,
        bounding_box_by_region=boxes,
    )


def sample_layer_at_uv(mask: RasterisedRegionMask, u: float, v: float) -> int:
    """Nearest-neighbour lookup of the layer index at a UV coordinate."""
    x = min(max(int(u * mask.width), 0), mask.width - 1)
    y = min(max(int(v * mask.height), 0), mask.height - 1)
    return mask.data[y * mask.width + x]


def verify_uv_landmark_round_trip(
    mask: RasterisedRegionMask,
    model: BladeModelVersion,
    expected: dict[str, str],
) -> dict[str, bool]:
    """Check that named UV landmarks fall inside the layers they are supposed to.

    ``expected`` maps a landmark name from the model's UV layout to a ``region_id``.
    This is the round-trip check that catches a flipped or rotated unwrap, which would
    otherwise produce a plausible-looking but wrongly located mask.
    """
    results: dict[str, bool] = {}
    for landmark, region_id in expected.items():
        if landmark not in model.uv_layout.landmarks:
            raise RegionMaskError(f"{model.id} has no UV landmark named {landmark!r}.")
        if region_id not in mask.layer_index_map:
            raise RegionMaskError(f"Mask has no region layer {region_id!r}.")
        u, v = model.uv_layout.landmarks[landmark]
        results[landmark] = sample_layer_at_uv(mask, u, v) == mask.layer_index_map[region_id]
    return results


def palette_for_profile(profile_id: str) -> PaletteEntry | None:
    for entry in DEFAULT_PALETTE:
        if entry.defect_profile_id == profile_id:
            return entry
    return None


def default_palette_payload() -> dict[str, Any]:
    """What the frontend fetches to render the legend and the first-run walkthrough."""
    return {
        "palette": [entry.as_dict() for entry in DEFAULT_PALETTE],
        "guide": REGION_PAINTING_GUIDE,
        "stroke_schema_version": STROKE_SCHEMA_VERSION,
        "mask_schema_version": MASK_SCHEMA_VERSION,
        "max_layers": MAX_REGION_LAYERS,
        "default_mask_width": DEFAULT_MASK_WIDTH,
        "default_mask_height": DEFAULT_MASK_HEIGHT,
        "unpainted_index": UNPAINTED,
    }
