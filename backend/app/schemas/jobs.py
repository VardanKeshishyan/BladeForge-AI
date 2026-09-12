import math
import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.turbine import (
    DEFECT_PART_MATRIX,
    CameraView,
    DefectId,
    DefectLayer,
    TurbinePartId,
)

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{1,99}$")

__all__ = [
    "BladeSectionId",
    "BrushStroke",
    "CameraView",
    "DefectLayer",
    "EnvironmentId",
    "GenerationConfig",
    "JobCreate",
    "JobList",
    "JobRead",
    "RegionDocument",
    "RegionLayerSpec",
    "TurbinePartId",
    "WorkerCompletion",
    "WorkerFailure",
    "WorkerProgress",
]


EnvironmentId = Literal[
    "CLEAR_DAY_V1",
    "OVERCAST_DAY_V1",
    "CLOUDY_DAY_V1",
    "GOLDEN_HOUR_V1",
    "NIGHT_MOONLIT_V1",
    "OFFSHORE_HAZE_V1",
    "LIGHT_RAIN_WET_V1",
    "HEAVY_RAIN_STORM_V1",
    "POST_RAIN_WET_V1",
    # Captured environments backed by a real HDRI.
    "DESERT_CLEAR_V1",
    "MOONLIGHT_HDRI_V1",
    # Winter conditions.
    "LIGHT_SNOW_V1",
    "SNOW_STORM_V1",
]

BladeSectionId = Literal["root_transition", "inboard", "midspan", "outboard", "tip"]

#: Which renderer produces the deliverable. ``legacy`` is the shipped renderer;
#: ``v2`` is the photorealistic Cycles path and is selected per deployment.
RenderEngineVersion = Literal["legacy", "v2"]


class RegionLayerSpec(BaseModel):
    """One coloured paint layer bound to a defect profile."""

    region_id: str = Field(min_length=2, max_length=63, pattern=r"^[a-z0-9][a-z0-9_-]{1,62}$")
    layer_index: int = Field(ge=1, le=32)
    display_name: str = Field(min_length=1, max_length=100)
    color_key: str = Field(min_length=1, max_length=64)
    hex_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    defect_profile_id: str = Field(min_length=2, max_length=80)
    defect_profile_version: str = Field(default="1.0.0", max_length=32)
    severity_min: float = Field(ge=0.0, le=100.0)
    severity_max: float = Field(ge=0.0, le=100.0)
    coverage_target: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_severity_order(self) -> "RegionLayerSpec":
        if self.severity_min > self.severity_max:
            raise ValueError("severity_min must be <= severity_max")
        return self


class BrushStroke(BaseModel):
    """One brush gesture bound to one exact model surface."""

    region_id: str = Field(min_length=2, max_length=63)
    mode: Literal["paint", "erase"]
    radius_uv: float = Field(ge=0.0005, le=0.5)
    points: list[list[float]] = Field(min_length=1, max_length=4000)
    # Optional only for backward compatibility with jobs saved before stroke schema 3.
    # New browser jobs always provide all five fields.
    surface_id: str | None = Field(default=None, min_length=1, max_length=200)
    surface_part_id: str | None = Field(default=None, min_length=1, max_length=80)
    face_indices: list[int] = Field(default_factory=list, max_length=4000)
    local_points: list[list[float]] = Field(default_factory=list, max_length=4000)
    local_normals: list[list[float]] = Field(default_factory=list, max_length=4000)
    world_points: list[list[float]] = Field(default_factory=list, max_length=4000)
    world_normals: list[list[float]] = Field(default_factory=list, max_length=4000)

    @model_validator(mode="after")
    def validate_points(self) -> "BrushStroke":
        for point in self.points:
            if len(point) != 2:
                raise ValueError("each stroke point must be [u, v]")
            u, v = point
            if not (-0.001 <= u <= 1.001 and -0.001 <= v <= 1.001):
                raise ValueError("stroke points must lie inside the 0..1 UV square")
        for face_index in self.face_indices:
            if face_index < 0:
                raise ValueError("face_indices cannot contain negative triangle indices")
        for field_name, vectors in (
            ("local_points", self.local_points),
            ("local_normals", self.local_normals),
            ("world_points", self.world_points),
            ("world_normals", self.world_normals),
        ):
            for vector in vectors:
                if len(vector) != 3:
                    raise ValueError(f"each {field_name} entry must be [x, y, z]")
                if not all(math.isfinite(value) for value in vector):
                    raise ValueError(f"{field_name} entries must be finite")
        for field_name, values in (
            ("face_indices", self.face_indices),
            ("local_points", self.local_points),
            ("local_normals", self.local_normals),
            ("world_points", self.world_points),
            ("world_normals", self.world_normals),
        ):
            if values and len(values) != len(self.points):
                raise ValueError(f"{field_name} must have one entry per stroke point")
        if self.surface_id is None and any(
            (self.face_indices, self.local_points, self.local_normals)
        ):
            raise ValueError("surface_id is required when exact-surface hit data is present")
        return self


class RegionDocument(BaseModel):
    """Editable painted-region source of truth, stored on the job config."""

    name: str = Field(min_length=1, max_length=120)
    blade_model_id: str = Field(min_length=1, max_length=80)
    blade_model_version: str = Field(min_length=1, max_length=32)
    uv_set_name: str = Field(default="UVMap", max_length=64)
    uv_layout_checksum: str = Field(min_length=4, max_length=128)
    mask_width: int = Field(default=1024, ge=256, le=8192)
    mask_height: int = Field(default=512, ge=256, le=8192)
    layers: list[RegionLayerSpec] = Field(min_length=1, max_length=32)
    strokes: list[BrushStroke] = Field(default_factory=list, max_length=4000)
    # Omitted means a legacy UV-only document; the browser explicitly submits 3.0.0.
    schema_version: str = Field(default="2.0.0", max_length=16)

    @model_validator(mode="after")
    def validate_stroke_regions(self) -> "RegionDocument":
        known = {layer.region_id for layer in self.layers}
        for stroke in self.strokes:
            if stroke.region_id not in known:
                raise ValueError(
                    f"stroke references unknown region_id {stroke.region_id!r}; "
                    "paint only onto declared layers"
                )
        if self.schema_version.startswith("3."):
            for stroke in self.strokes:
                if not stroke.surface_id or not stroke.surface_part_id:
                    raise ValueError(
                        "stroke schema 3 requires surface_id and surface_part_id"
                    )
                if not all(
                    (stroke.face_indices, stroke.local_points, stroke.local_normals)
                ):
                    raise ValueError(
                        "stroke schema 3 requires face_indices, local_points, and "
                        "local_normals for every stroke point"
                    )
        if self.schema_version.startswith("4."):
            for stroke in self.strokes:
                if not stroke.surface_id or not stroke.surface_part_id:
                    raise ValueError("stroke schema 4 requires exact surface identity")
                if not all(
                    (
                        stroke.face_indices,
                        stroke.local_points,
                        stroke.local_normals,
                        stroke.world_points,
                        stroke.world_normals,
                    )
                ):
                    raise ValueError(
                        "stroke schema 4 requires face, local, and normalized-world hit data"
                    )
        return self


class GenerationConfig(BaseModel):
    lighting_preset: Literal["overcast", "golden_hour", "midday", "cloudy"] = "overcast"
    camera_fov: int = Field(default=45, ge=5, le=120)
    weather: bool = False
    image_width: int = Field(default=1024, ge=256, le=4096)
    image_height: int = Field(default=1024, ge=256, le=4096)
    compression_quality: int = Field(default=92, ge=50, le=100)
    include_masks: Literal[True] = True

    # Everything below is optional so that a request written against the previous
    # schema still validates and renders exactly as it did before.

    environment_id: EnvironmentId | None = None
    weather_intensity: float | None = Field(default=None, ge=0.0, le=1.0)
    blade_section_id: BladeSectionId | None = None
    camera_view: CameraView | None = None

    # Whether the deliverable holds whole frames, tight crops around the damage, or both.
    crop_policy: Literal["full_frame", "defect_crop", "full_and_crop"] = "full_frame"
    crop_padding_fraction: float = Field(default=0.18, ge=0.0, le=1.0)

    # Which part of the turbine is rendered. ``all`` keeps the previous whole-model
    # behaviour, so an existing payload is unaffected.
    turbine_part_id: TurbinePartId = "all"

    #: Additional defects beyond ``JobCreate.defect_type``. The top-level field stays the
    #: primary defect so that every existing request, dashboard filter and dataset name
    #: continues to mean what it always did.
    defect_layers: list[DefectLayer] = Field(default_factory=list, max_length=17)

    #: Spread the image count over distinct viewpoints instead of reusing one angle.
    generate_all_angles: bool = False
    #: Exact plan shown by the browser. External API clients may omit it and let the
    #: renderer construct the same deterministic plan from the selected part bounds.
    camera_views: list[CameraView] = Field(default_factory=list, max_length=10000)

    #: Customer-supplied assets, referenced by storage key. Null selects the bundled asset.
    model_asset_key: str | None = Field(default=None, max_length=400)
    hdri_asset_key: str | None = Field(default=None, max_length=400)

    render_engine: RenderEngineVersion | None = None

    #: Painted UV regions that constrain where each defect may appear. Null means each
    #: defect uses its default placement on the selected part.
    region_document: RegionDocument | None = None

    @model_validator(mode="after")
    def validate_defect_layers(self) -> "GenerationConfig":
        seen: set[tuple[str, str]] = set()
        for layer in self.defect_layers:
            key = (layer.defect_id, layer.part_id)
            if key in seen:
                raise ValueError(
                    f"{layer.defect_id} is listed twice for the {layer.part_id}; "
                    "combine them into one layer"
                )
            seen.add(key)
            selected = self.turbine_part_id
            visible_parts = {"blades", "hub"} if selected == "rotor" else {selected}
            if selected != "all" and layer.part_id not in visible_parts:
                raise ValueError(
                    f"{layer.defect_id} is placed on {layer.part_id}, which is hidden by "
                    f"the selected {selected} render"
                )
        return self

    @model_validator(mode="after")
    def validate_camera_view_matches_manual_framing(self) -> "GenerationConfig":
        if self.generate_all_angles and self.camera_view is not None:
            raise ValueError(
                "a saved camera view and generate_all_angles are mutually exclusive; "
                "all-angle generation replaces the single saved pose"
            )
        if not self.generate_all_angles and self.camera_views:
            raise ValueError("camera_views requires generate_all_angles")
        return self


class JobCreate(BaseModel):
    name: str
    description: str | None = Field(default=None, max_length=1000)
    defect_type: DefectId
    severity_min: int = Field(ge=0, le=99)
    severity_max: int = Field(ge=1, le=100)
    image_count: int = Field(ge=1)
    annotation_format: Literal["coco_json", "yolo_v8"]
    dataset_name: str
    config: GenerationConfig = Field(default_factory=GenerationConfig)

    @field_validator("name", "dataset_name")
    @classmethod
    def validate_safe_name(cls, value: str) -> str:
        normalized = value.strip()
        if not SAFE_NAME.fullmatch(normalized):
            raise ValueError("must be 2-100 characters using letters, numbers, spaces, . _ or -")
        return normalized

    @model_validator(mode="after")
    def validate_severity(self) -> "JobCreate":
        if self.severity_min >= self.severity_max:
            raise ValueError("severity_min must be below severity_max")
        if self.config.generate_all_angles and self.config.camera_views:
            if len(self.config.camera_views) != self.image_count:
                raise ValueError("camera_views must contain exactly one pose per requested image")
        primary_layers = [
            layer for layer in self.config.defect_layers if layer.defect_id == self.defect_type
        ]
        if not primary_layers and self.config.turbine_part_id != "all":
            selected_parts = (
                {"blades", "hub"}
                if self.config.turbine_part_id == "rotor"
                else {self.config.turbine_part_id}
            )
            if not (selected_parts & set(DEFECT_PART_MATRIX[self.defect_type])):
                raise ValueError(
                    f"primary defect {self.defect_type} cannot occur on the selected "
                    f"{self.config.turbine_part_id} render"
                )
        return self


class JobRead(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    organization_id: uuid.UUID
    created_by: uuid.UUID
    name: str
    description: str | None
    status: str
    config: dict[str, Any]
    defect_type: str
    severity_min: int
    severity_max: int
    image_count: int
    image_width: int
    image_height: int
    annotation_format: str
    dataset_name: str
    estimated_size_bytes: int
    progress: int
    current_stage: str
    attempt_count: int
    max_attempts: int
    worker_id: uuid.UUID | None
    cancellation_requested_at: datetime | None
    failure_code: str | None
    failure_message: str | None
    started_at: datetime | None
    submitted_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobList(BaseModel):
    items: list[JobRead]
    page: int
    page_size: int
    total: int
    pages: int


class WorkerProgress(BaseModel):
    status: Literal["rendering", "processing_annotations"]
    progress: int = Field(ge=0, le=99)
    stage: str = Field(min_length=2, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkerFailure(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    message: str = Field(min_length=1, max_length=1000)
    retryable: bool = True
    gpu_seconds: float = Field(default=0, ge=0)


class WorkerCompletion(BaseModel):
    output_directory: str
    manifest_path: str
    archive_path: str
    preview_path: str | None = None
    gpu_seconds: float = Field(ge=0)
