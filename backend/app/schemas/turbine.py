"""Turbine parts, defect types and camera framing shared by the job schemas.

Kept separate from ``jobs`` so the same definitions can be reused by the worker payload
and by tests without importing the whole request model.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

TurbinePartId = Literal[
    "all",
    "rotor",
    "blades",
    "hub",
    "nacelle",
    "tower",
    "foundation",
]

DefectId = Literal[
    "surface_crack",
    "leading_edge_erosion",
    "trailing_edge_damage",
    "corrosion",
    "rust_staining",
    "paint_peeling",
    "coating_loss",
    "scratches",
    "dents",
    "lightning_strike",
    "holes",
    "chips",
    "delamination",
    "oil_stains",
    "dirt_buildup",
    "ice_buildup",
    "structural_deformation",
]

#: Which parts each defect can physically occur on.
#:
#: This is enforced rather than advisory. Corrosion is an electrochemical attack on metal,
#: so a request to corrode a composite blade shell is rejected: the honest label for
#: rust-coloured marks on a blade is runoff staining, and a dataset that calls it
#: corrosion teaches a detector something untrue.
DEFECT_PART_MATRIX: dict[str, frozenset[str]] = {
    "surface_crack": frozenset({"blades", "hub", "nacelle", "tower"}),
    "leading_edge_erosion": frozenset({"blades"}),
    "trailing_edge_damage": frozenset({"blades"}),
    "corrosion": frozenset({"tower", "nacelle", "hub", "foundation"}),
    "rust_staining": frozenset({"blades", "hub", "nacelle", "tower", "foundation"}),
    "paint_peeling": frozenset({"blades", "hub", "nacelle", "tower", "foundation"}),
    "coating_loss": frozenset({"blades", "hub", "nacelle", "tower"}),
    "scratches": frozenset({"blades", "hub", "nacelle", "tower"}),
    "dents": frozenset({"nacelle", "tower", "hub", "foundation"}),
    "lightning_strike": frozenset({"blades", "hub"}),
    "holes": frozenset({"blades", "nacelle", "hub"}),
    "chips": frozenset({"blades", "hub", "nacelle", "tower"}),
    "delamination": frozenset({"blades", "hub"}),
    "oil_stains": frozenset({"nacelle", "hub", "tower", "blades"}),
    "dirt_buildup": frozenset({"blades", "hub", "nacelle", "tower", "foundation"}),
    "ice_buildup": frozenset({"blades", "hub", "nacelle"}),
    "structural_deformation": frozenset({"blades", "tower", "nacelle"}),
}

#: Defects the v2 Cycles renderer can currently produce. Anything outside this set is
#: accepted by the schema but reported as unavailable, so the UI can grey it out with a
#: reason rather than promising output that will never arrive.
RENDERER_SUPPORTED_DEFECTS: frozenset[str] = frozenset(
    {
        "leading_edge_erosion",
        "surface_crack",
        "delamination",
        "lightning_strike",
        "coating_loss",
        "paint_peeling",
        "corrosion",
        "rust_staining",
        "dirt_buildup",
        "scratches",
        "chips",
        "dents",
        "holes",
        "oil_stains",
        "ice_buildup",
        "trailing_edge_damage",
        "structural_deformation",
    }
)


class DefectLayer(BaseModel):
    """One selected defect, placed on one part, with its generation parameters."""

    defect_id: DefectId
    part_id: TurbinePartId
    severity: int = Field(default=50, ge=0, le=100)
    coverage: int = Field(default=20, ge=1, le=100)
    size_scale: float = Field(default=1.0, ge=0.1, le=5.0)
    opacity: int = Field(default=100, ge=1, le=100)
    rotation_deg: float = Field(default=0.0, ge=0.0, le=360.0)
    spread: int = Field(default=40, ge=0, le=100)
    randomness: int = Field(default=50, ge=0, le=100)
    color_hex: str = Field(default="#ef4444", pattern=r"^#[0-9a-fA-F]{6}$")
    #: Painted region this layer is confined to. Null means the whole selected part.
    region_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_part_is_physically_plausible(self) -> "DefectLayer":
        allowed = DEFECT_PART_MATRIX.get(self.defect_id, frozenset())
        if self.part_id in ("all", "rotor"):
            raise ValueError(
                f"{self.part_id} is a camera/model grouping, not a physical defect surface; "
                f"choose one of {', '.join(sorted(allowed))}"
            )
        if self.part_id not in allowed:
            raise ValueError(
                f"{self.defect_id} cannot occur on the {self.part_id}; "
                f"valid parts are {', '.join(sorted(allowed))}"
            )
        return self


class CameraView(BaseModel):
    """A saved viewport angle, expressed as a bounded orbit rather than a raw matrix.

    The browser never sends a transformation matrix, because there is no reliable way to
    validate one. These values map directly onto the renderer's camera model.
    """

    target_x_m: float = Field(default=0.0, ge=-500.0, le=500.0)
    target_y_m: float = Field(default=0.0, ge=-500.0, le=500.0)
    target_z_m: float = Field(default=0.0, ge=-500.0, le=500.0)
    azimuth_deg: float = Field(ge=-180.0, le=180.0)
    elevation_deg: float = Field(ge=-89.5, le=89.5)
    distance_m: float = Field(ge=0.35, le=4000.0)
    roll_deg: float = Field(default=0.0, ge=-180.0, le=180.0)
    fov_deg: float = Field(default=45.0, ge=5.0, le=120.0)
