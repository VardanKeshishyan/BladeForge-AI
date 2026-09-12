"""Output schema versions: what a dataset contains and how it is labelled.

Three policies exist because each is a real choice with training consequences, and
each has to be recorded explicitly rather than assumed:

``CropPolicy``
    Whether the customer receives the whole frame, a crop tightened around the
    damage, or both.

``AnnotationPolicy``
    Whether the exported boxes and polygons describe the defect's intrinsic
    geometry, only the part actually visible after rain and occlusion, or both.

``MotionBlurMaskPolicy``
    When motion blur is on, whether the mask means "pixels the defect visibly
    covers" or "the sharp underlying geometry". Both are defensible; guessing is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ParameterValidationError, RegistryLookupError
from .versioning import ReleaseStatus, SemanticVersion, checksum, validate_registry_id


class CropPolicy:
    FULL_FRAME = "full_frame"
    DEFECT_CROP = "defect_crop"
    FULL_AND_CROP = "full_and_crop"
    ALL = (FULL_FRAME, DEFECT_CROP, FULL_AND_CROP)

    LABELS = {
        FULL_FRAME: "Whole image only",
        DEFECT_CROP: "Cropped to the damaged area only",
        FULL_AND_CROP: "Both the whole image and the damaged-area crop",
    }


class AnnotationPolicy:
    VISIBLE_ONLY = "visible_only"
    INTRINSIC_ONLY = "intrinsic_only"
    BOTH = "both"
    ALL = (VISIBLE_ONLY, INTRINSIC_ONLY, BOTH)

    LABELS = {
        VISIBLE_ONLY: "Label only what the camera can actually see",
        INTRINSIC_ONLY: "Label the full defect geometry, including occluded parts",
        BOTH: "Export both visible and intrinsic annotation sets",
    }


class MotionBlurMaskPolicy:
    VISIBLE_COVERAGE = "visible_coverage"
    SHARP_GEOMETRY = "sharp_geometry"
    ALL = (VISIBLE_COVERAGE, SHARP_GEOMETRY)


class OcclusionPolicy:
    """What to do when weather or geometry hides the defect."""

    REJECT = "reject_occluded"
    ALLOW = "allow_occluded"
    HARD_NEGATIVE = "hard_negative"
    ALL = (REJECT, ALLOW, HARD_NEGATIVE)


class AnnotationFormat:
    # Legacy names, still accepted so existing payloads and datasets keep working.
    COCO_JSON = "coco_json"
    YOLO_V8 = "yolo_v8"
    # Explicit v2 names.
    COCO_INSTANCE_SEGMENTATION = "coco_instance_segmentation"
    YOLO_DETECTION = "yolo_detection"
    YOLO_SEGMENTATION = "yolo_segmentation"

    ALL = (
        COCO_JSON,
        YOLO_V8,
        COCO_INSTANCE_SEGMENTATION,
        YOLO_DETECTION,
        YOLO_SEGMENTATION,
    )

    LEGACY_ALIASES = {
        COCO_JSON: COCO_INSTANCE_SEGMENTATION,
        YOLO_V8: YOLO_DETECTION,
    }

    LABELS = {
        COCO_JSON: "COCO JSON",
        YOLO_V8: "YOLO v8",
        COCO_INSTANCE_SEGMENTATION: "COCO instance segmentation",
        YOLO_DETECTION: "YOLO detection",
        YOLO_SEGMENTATION: "YOLO segmentation",
    }


def canonical_annotation_format(value: str) -> str:
    """Resolve a legacy alias to its canonical v2 format name."""
    if value not in AnnotationFormat.ALL:
        raise ParameterValidationError(f"Unknown annotation format {value!r}.")
    return AnnotationFormat.LEGACY_ALIASES.get(value, value)


# ---------------------------------------------------------------------------
# Package layout
# ---------------------------------------------------------------------------

SPLIT = "train"

IMAGE_DIR = f"images/{SPLIT}"
VISIBLE_MASK_DIR = f"masks/visible/{SPLIT}"
INTRINSIC_MASK_DIR = f"masks/intrinsic/{SPLIT}"
SEMANTIC_MASK_DIR = f"masks/semantic/{SPLIT}"
CROP_IMAGE_DIR = f"crops/images/{SPLIT}"
CROP_VISIBLE_MASK_DIR = f"crops/masks/visible/{SPLIT}"
METADATA_DIR = f"metadata/{SPLIT}"
# YOLO detection labels sit at the package root so its data.yaml can point at the
# canonical images directory without duplicating a single image file.
YOLO_DETECTION_LABEL_DIR = f"labels/{SPLIT}"
YOLO_DETECTION_DIR = "annotations/yolo_detection"
# YOLO segmentation needs its own root because Ultralytics derives the label path by
# substituting "images" with "labels", which the detection labels already occupy.
YOLO_SEGMENTATION_DIR = "annotations/yolo_segmentation"
YOLO_SEGMENTATION_IMAGE_DIR = f"{YOLO_SEGMENTATION_DIR}/images/{SPLIT}"
YOLO_SEGMENTATION_LABEL_DIR = f"{YOLO_SEGMENTATION_DIR}/labels/{SPLIT}"

COCO_LEGACY_FILE = "annotations/coco.json"
COCO_V2_FILE = "annotations/coco_instance_segmentation.json"
COCO_INTRINSIC_FILE = "annotations/coco_instance_segmentation_intrinsic.json"

MANIFEST_FILE = "manifest.json"
DATASET_CONFIG_FILE = "dataset-config.json"
CHECKSUMS_FILE = "checksums.sha256"
README_FILE = "README.md"
MODEL_CARD_FILE = "model-card.json"
LICENSES_FILE = "licenses.json"
TAXONOMY_FILE = "taxonomy.json"
VALIDATION_REPORT_FILE = "validation-report.json"

REQUIRED_PACKAGE_FILES: tuple[str, ...] = (
    MANIFEST_FILE,
    DATASET_CONFIG_FILE,
    CHECKSUMS_FILE,
    README_FILE,
    MODEL_CARD_FILE,
    LICENSES_FILE,
    TAXONOMY_FILE,
    VALIDATION_REPORT_FILE,
)


@dataclass(frozen=True)
class OutputSchemaVersion:
    id: str
    version: str
    status: str
    title: str
    summary: str
    annotation_formats: tuple[str, ...]
    crop_policy: str
    annotation_policy: str
    motion_blur_mask_policy: str
    occlusion_policy: str
    feature_flag: str
    include_visible_masks: bool = True
    include_intrinsic_masks: bool = True
    include_semantic_mask: bool = False
    include_per_image_metadata: bool = True
    crop_padding_fraction: float = 0.18
    crop_min_side_px: int = 64
    # A sample whose defect is visible below this fraction of its intrinsic area is
    # treated as occluded and handled by the occlusion policy.
    min_visibility_fraction: float = 0.15
    image_format: str = "PNG"
    mask_format: str = "PNG"
    mask_channels: int = 1
    mask_bit_depth: int = 8

    def __post_init__(self) -> None:
        validate_registry_id(self.id)
        SemanticVersion.parse(self.version)
        if self.status not in ReleaseStatus.ALL:
            raise ValueError(f"Unknown release status {self.status!r}")
        if not self.annotation_formats:
            raise ValueError(f"{self.id}: at least one annotation format is required.")
        for value in self.annotation_formats:
            canonical_annotation_format(value)
        if self.crop_policy not in CropPolicy.ALL:
            raise ValueError(f"{self.id}: unknown crop policy {self.crop_policy!r}")
        if self.annotation_policy not in AnnotationPolicy.ALL:
            raise ValueError(f"{self.id}: unknown annotation policy {self.annotation_policy!r}")
        if self.motion_blur_mask_policy not in MotionBlurMaskPolicy.ALL:
            raise ValueError(f"{self.id}: unknown motion blur mask policy.")
        if self.occlusion_policy not in OcclusionPolicy.ALL:
            raise ValueError(f"{self.id}: unknown occlusion policy.")
        if self.mask_channels != 1:
            raise ValueError(
                f"{self.id}: class-ID masks must stay single-channel so category IDs "
                "remain exact."
            )
        if self.mask_bit_depth not in {8, 16}:
            raise ValueError(f"{self.id}: mask bit depth must be 8 or 16.")
        if not 0.0 <= self.crop_padding_fraction <= 2.0:
            raise ValueError(f"{self.id}: crop padding fraction is implausible.")

    @property
    def is_selectable(self) -> bool:
        return self.status == ReleaseStatus.RELEASED

    @property
    def canonical_formats(self) -> tuple[str, ...]:
        seen: list[str] = []
        for value in self.annotation_formats:
            canonical = canonical_annotation_format(value)
            if canonical not in seen:
                seen.append(canonical)
        return tuple(seen)

    @property
    def emits_crops(self) -> bool:
        return self.crop_policy in {CropPolicy.DEFECT_CROP, CropPolicy.FULL_AND_CROP}

    @property
    def emits_full_frames(self) -> bool:
        return self.crop_policy in {CropPolicy.FULL_FRAME, CropPolicy.FULL_AND_CROP}

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "status": self.status,
            "title": self.title,
            "summary": self.summary,
            "annotation_formats": list(self.annotation_formats),
            "canonical_annotation_formats": list(self.canonical_formats),
            "crop_policy": self.crop_policy,
            "annotation_policy": self.annotation_policy,
            "motion_blur_mask_policy": self.motion_blur_mask_policy,
            "occlusion_policy": self.occlusion_policy,
            "include_visible_masks": self.include_visible_masks,
            "include_intrinsic_masks": self.include_intrinsic_masks,
            "include_semantic_mask": self.include_semantic_mask,
            "include_per_image_metadata": self.include_per_image_metadata,
            "crop_padding_fraction": self.crop_padding_fraction,
            "crop_min_side_px": self.crop_min_side_px,
            "min_visibility_fraction": self.min_visibility_fraction,
            "image_format": self.image_format,
            "mask_format": self.mask_format,
            "mask_channels": self.mask_channels,
            "mask_bit_depth": self.mask_bit_depth,
            "feature_flag": self.feature_flag,
        }

    @property
    def checksum(self) -> str:
        return checksum(self.as_dict())

    def public_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "summary": self.summary,
            "annotation_formats": list(self.annotation_formats),
            "crop_policy": self.crop_policy,
            "annotation_policy": self.annotation_policy,
            "checksum": self.checksum,
        }

    def with_overrides(
        self,
        *,
        annotation_formats: tuple[str, ...] | None = None,
        crop_policy: str | None = None,
        annotation_policy: str | None = None,
        occlusion_policy: str | None = None,
        motion_blur_mask_policy: str | None = None,
        include_semantic_mask: bool | None = None,
    ) -> OutputSchemaVersion:
        """Derive a job-specific schema. The base version id is retained in the manifest."""
        from dataclasses import replace

        changes: dict[str, Any] = {}
        if annotation_formats is not None:
            changes["annotation_formats"] = tuple(annotation_formats)
        if crop_policy is not None:
            changes["crop_policy"] = crop_policy
        if annotation_policy is not None:
            changes["annotation_policy"] = annotation_policy
        if occlusion_policy is not None:
            changes["occlusion_policy"] = occlusion_policy
        if motion_blur_mask_policy is not None:
            changes["motion_blur_mask_policy"] = motion_blur_mask_policy
        if include_semantic_mask is not None:
            changes["include_semantic_mask"] = include_semantic_mask
        return replace(self, **changes)


LEGACY_COCO_OUTPUT_V1 = OutputSchemaVersion(
    id="LEGACY_COCO_OUTPUT_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Legacy COCO output (compatibility)",
    summary=(
        "Reproduces the pre-v2 package: full-frame images, one mask per image, and "
        "annotations/coco.json. Selected automatically for jobs submitted with the "
        "legacy payload."
    ),
    annotation_formats=(AnnotationFormat.COCO_JSON,),
    crop_policy=CropPolicy.FULL_FRAME,
    annotation_policy=AnnotationPolicy.VISIBLE_ONLY,
    motion_blur_mask_policy=MotionBlurMaskPolicy.VISIBLE_COVERAGE,
    occlusion_policy=OcclusionPolicy.REJECT,
    include_intrinsic_masks=False,
    feature_flag="output_legacy_coco_v1",
)

LEGACY_YOLO_OUTPUT_V1 = OutputSchemaVersion(
    id="LEGACY_YOLO_OUTPUT_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Legacy YOLO output (compatibility)",
    summary="Reproduces the pre-v2 YOLO v8 detection package layout.",
    annotation_formats=(AnnotationFormat.YOLO_V8,),
    crop_policy=CropPolicy.FULL_FRAME,
    annotation_policy=AnnotationPolicy.VISIBLE_ONLY,
    motion_blur_mask_policy=MotionBlurMaskPolicy.VISIBLE_COVERAGE,
    occlusion_policy=OcclusionPolicy.REJECT,
    include_intrinsic_masks=False,
    feature_flag="output_legacy_yolo_v1",
)

STANDARD_DETECTION_OUTPUT_V1 = OutputSchemaVersion(
    id="STANDARD_DETECTION_OUTPUT_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Standard detection and segmentation",
    summary=(
        "Full-frame images with single-channel class-ID masks, COCO instance "
        "segmentation, and YOLO detection labels. The general-purpose default."
    ),
    annotation_formats=(
        AnnotationFormat.COCO_INSTANCE_SEGMENTATION,
        AnnotationFormat.YOLO_DETECTION,
    ),
    crop_policy=CropPolicy.FULL_FRAME,
    annotation_policy=AnnotationPolicy.VISIBLE_ONLY,
    motion_blur_mask_policy=MotionBlurMaskPolicy.VISIBLE_COVERAGE,
    occlusion_policy=OcclusionPolicy.REJECT,
    feature_flag="output_standard_detection_v1",
)

FULL_ANALYSIS_OUTPUT_V1 = OutputSchemaVersion(
    id="FULL_ANALYSIS_OUTPUT_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Full analysis package",
    summary=(
        "Everything: full frames plus damage crops, visible and intrinsic masks, a "
        "combined semantic mask, COCO instance segmentation for both annotation "
        "policies, and both YOLO formats."
    ),
    annotation_formats=(
        AnnotationFormat.COCO_INSTANCE_SEGMENTATION,
        AnnotationFormat.YOLO_DETECTION,
        AnnotationFormat.YOLO_SEGMENTATION,
    ),
    crop_policy=CropPolicy.FULL_AND_CROP,
    annotation_policy=AnnotationPolicy.BOTH,
    motion_blur_mask_policy=MotionBlurMaskPolicy.SHARP_GEOMETRY,
    occlusion_policy=OcclusionPolicy.ALLOW,
    include_semantic_mask=True,
    feature_flag="output_full_analysis_v1",
)

DEFECT_CROP_OUTPUT_V1 = OutputSchemaVersion(
    id="DEFECT_CROP_OUTPUT_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Damaged-area crops only",
    summary=(
        "Only the region around each defect, tightly cropped with padding. Useful for "
        "classifier and severity-grading training where the whole blade is not needed."
    ),
    annotation_formats=(
        AnnotationFormat.COCO_INSTANCE_SEGMENTATION,
        AnnotationFormat.YOLO_DETECTION,
    ),
    crop_policy=CropPolicy.DEFECT_CROP,
    annotation_policy=AnnotationPolicy.VISIBLE_ONLY,
    motion_blur_mask_policy=MotionBlurMaskPolicy.VISIBLE_COVERAGE,
    occlusion_policy=OcclusionPolicy.REJECT,
    feature_flag="output_defect_crop_v1",
)

HARD_NEGATIVE_OUTPUT_V1 = OutputSchemaVersion(
    id="HARD_NEGATIVE_OUTPUT_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Hard negatives and occluded samples",
    summary=(
        "Deliberately keeps samples where weather or geometry hides the defect, marked "
        "as hard negatives. Empty visible masks are expected here, not a failure."
    ),
    annotation_formats=(AnnotationFormat.COCO_INSTANCE_SEGMENTATION,),
    crop_policy=CropPolicy.FULL_FRAME,
    annotation_policy=AnnotationPolicy.BOTH,
    motion_blur_mask_policy=MotionBlurMaskPolicy.VISIBLE_COVERAGE,
    occlusion_policy=OcclusionPolicy.HARD_NEGATIVE,
    min_visibility_fraction=0.0,
    feature_flag="output_hard_negative_v1",
)

ALL_OUTPUT_SCHEMAS: tuple[OutputSchemaVersion, ...] = (
    LEGACY_COCO_OUTPUT_V1,
    LEGACY_YOLO_OUTPUT_V1,
    STANDARD_DETECTION_OUTPUT_V1,
    FULL_ANALYSIS_OUTPUT_V1,
    DEFECT_CROP_OUTPUT_V1,
    HARD_NEGATIVE_OUTPUT_V1,
)

DEFAULT_OUTPUT_SCHEMA_ID = STANDARD_DETECTION_OUTPUT_V1.id

_BY_ID = {schema.id: schema for schema in ALL_OUTPUT_SCHEMAS}


def get_output_schema(reference: str) -> OutputSchemaVersion:
    key = reference.strip()
    if "@" in key:
        key = key.split("@", 1)[0]
    try:
        return _BY_ID[key]
    except KeyError as exc:
        raise RegistryLookupError(f"Unknown output schema {reference!r}") from exc


def list_output_schemas() -> tuple[OutputSchemaVersion, ...]:
    return tuple(schema for schema in ALL_OUTPUT_SCHEMAS if schema.is_selectable)


def output_schema_for_legacy_format(annotation_format: str) -> OutputSchemaVersion:
    """The compatibility schema a pre-upgrade job resolves to."""
    if annotation_format == AnnotationFormat.COCO_JSON:
        return LEGACY_COCO_OUTPUT_V1
    if annotation_format == AnnotationFormat.YOLO_V8:
        return LEGACY_YOLO_OUTPUT_V1
    raise RegistryLookupError(
        f"{annotation_format!r} is not a legacy annotation format."
    )


def registry_checksum() -> str:
    return checksum([schema.as_dict() for schema in ALL_OUTPUT_SCHEMAS])
