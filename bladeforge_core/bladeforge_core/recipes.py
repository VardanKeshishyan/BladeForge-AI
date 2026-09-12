"""Generation recipes: request in, immutable resolved configuration out.

A ``RecipeRequest`` is what a customer asks for, expressed in registry references.
``resolve_recipe`` turns it into a ``ResolvedRecipe``: every registry entry pinned to a
version and checksum, every policy stated explicitly, and a deterministic per-sample
plan. The resolved snapshot plus its SHA-256 is stored with the job, so a dataset can be
reproduced byte-for-byte later even after the registries move on.

Two entry points exist on purpose:

``RecipeRequest.for_legacy_job``
    Builds a request from the pre-upgrade job payload. Jobs submitted before this
    upgrade, and jobs still submitted with the old fields, keep working unchanged.

``RecipeRequest`` directly
    The v2 path, with multi-defect selection, painted regions, camera presets,
    environments, weather, and output policies.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field, replace
from typing import Any

from . import blades, cameras, environments, materials, outputs, taxonomy
from .defects import (
    assert_combination_supported,
    get_profile,
    profile_for_legacy_defect_type,
)
from .defects.base import DefectProfileVersion, ResolvedDefect
from .errors import (
    ParameterValidationError,
    RecipeResolutionError,
    RegionMaskError,
)
from .flags import is_enabled, render_engine_version
from .regions import (
    RasterisedRegionMask,
    RegionStrokeDocument,
    assert_region_matches_model,
    rasterise_region_mask,
)
from .severity import band_for_severity, sample_severity
from .versioning import checksum

RECIPE_SCHEMA_VERSION = "2.0.0"

PRIMARY = "primary"
SECONDARY = "secondary"

SEED_POLICY_FIXED = "fixed"
SEED_POLICY_RANDOM = "random"
SEED_POLICIES = (SEED_POLICY_FIXED, SEED_POLICY_RANDOM)

MAX_IMAGE_COUNT = 20_000
MIN_RESOLUTION = 256
MAX_RESOLUTION = 4096

# How many resolved samples are embedded in the stored snapshot. The rest are
# regenerated deterministically from the master seed, which keeps a 10k-image job's
# configuration row small without giving up reproducibility.
EMBEDDED_SAMPLE_PLAN_LIMIT = 8


def derive_sample_seed(master_seed: int, index: int, purpose: str = "sample") -> int:
    """Deterministically derive a per-sample seed.

    Hashing rather than ``master_seed + index`` keeps neighbouring samples from
    producing correlated draws, and is stable across processes and platforms.
    """
    digest = hashlib.sha256(f"{master_seed}:{purpose}:{index}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


@dataclass(frozen=True)
class DefectSelection:
    """One defect the customer wants, with its severity and placement constraints."""

    profile_ref: str
    role: str = PRIMARY
    severity_min: float = 30.0
    severity_max: float = 70.0
    coverage_target: float | None = None
    instance_count_min: int = 1
    instance_count_max: int = 1
    # When set, this defect may only appear inside the named painted region layer.
    region_id: str | None = None
    # Restricts the defect to these named blade sections. Empty means the job's sections.
    section_ids: tuple[str, ...] = ()
    parameter_overrides: dict[str, float] = field(default_factory=dict)
    # Probability the defect appears at all, for building mixed datasets.
    presence_probability: float = 1.0

    def __post_init__(self) -> None:
        if self.role not in {PRIMARY, SECONDARY}:
            raise ParameterValidationError(f"Unknown defect role {self.role!r}.")
        if not 0.0 <= self.severity_min <= self.severity_max <= 100.0:
            raise ParameterValidationError(
                f"{self.profile_ref}: severity range {self.severity_min}-"
                f"{self.severity_max} must be ordered and inside 0..100."
            )
        if not 1 <= self.instance_count_min <= self.instance_count_max <= 64:
            raise ParameterValidationError(
                f"{self.profile_ref}: instance count range is invalid."
            )
        if self.coverage_target is not None and not 0.0 < self.coverage_target <= 1.0:
            raise ParameterValidationError(
                f"{self.profile_ref}: coverage target must be within 0..1."
            )
        if not 0.0 < self.presence_probability <= 1.0:
            raise ParameterValidationError(
                f"{self.profile_ref}: presence probability must be within 0..1."
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_ref": self.profile_ref,
            "role": self.role,
            "severity_min": self.severity_min,
            "severity_max": self.severity_max,
            "coverage_target": self.coverage_target,
            "instance_count_min": self.instance_count_min,
            "instance_count_max": self.instance_count_max,
            "region_id": self.region_id,
            "section_ids": list(self.section_ids),
            "parameter_overrides": dict(sorted(self.parameter_overrides.items())),
            "presence_probability": self.presence_probability,
        }


@dataclass(frozen=True)
class RandomizationSpec:
    """Bounded domain randomization. Every field is recorded per image when sampled."""

    distance_m_range: tuple[float, float] | None = None
    azimuth_deg_range: tuple[float, float] | None = None
    elevation_deg_range: tuple[float, float] | None = None
    weather_intensity_range: tuple[float, float] | None = None
    exposure_ev_range: tuple[float, float] = (-0.4, 0.4)
    dirt_amount_range: tuple[float, float] = (0.0, 0.35)
    manufacturing_variation_range: tuple[float, float] = (0.0, 0.4)
    surface_contamination_range: tuple[float, float] = (0.0, 0.2)
    jpeg_quality_range: tuple[int, int] = (88, 98)
    lens_distortion_enabled: bool = True
    chromatic_aberration_range: tuple[float, float] = (0.0, 0.35)
    sensor_noise_enabled: bool = True
    motion_blur_allowed: bool = True

    def __post_init__(self) -> None:
        for name in (
            "distance_m_range",
            "azimuth_deg_range",
            "elevation_deg_range",
            "weather_intensity_range",
            "exposure_ev_range",
            "dirt_amount_range",
            "manufacturing_variation_range",
            "surface_contamination_range",
            "chromatic_aberration_range",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            low, high = value
            if low > high:
                raise ParameterValidationError(f"{name} is inverted: {low} > {high}.")
        low_q, high_q = self.jpeg_quality_range
        if not 40 <= low_q <= high_q <= 100:
            raise ParameterValidationError("jpeg_quality_range must be inside 40..100.")
        if self.weather_intensity_range is not None:
            low, high = self.weather_intensity_range
            if not 0.0 <= low <= high <= 1.0:
                raise ParameterValidationError(
                    "weather_intensity_range must be inside 0..1."
                )

    def as_dict(self) -> dict[str, Any]:
        def pair(value: tuple[float, float] | tuple[int, int] | None) -> list[Any] | None:
            return None if value is None else [value[0], value[1]]

        return {
            "distance_m_range": pair(self.distance_m_range),
            "azimuth_deg_range": pair(self.azimuth_deg_range),
            "elevation_deg_range": pair(self.elevation_deg_range),
            "weather_intensity_range": pair(self.weather_intensity_range),
            "exposure_ev_range": pair(self.exposure_ev_range),
            "dirt_amount_range": pair(self.dirt_amount_range),
            "manufacturing_variation_range": pair(self.manufacturing_variation_range),
            "surface_contamination_range": pair(self.surface_contamination_range),
            "jpeg_quality_range": pair(self.jpeg_quality_range),
            "lens_distortion_enabled": self.lens_distortion_enabled,
            "chromatic_aberration_range": pair(self.chromatic_aberration_range),
            "sensor_noise_enabled": self.sensor_noise_enabled,
            "motion_blur_allowed": self.motion_blur_allowed,
        }


@dataclass(frozen=True)
class QualitySpec:
    """Render quality. Bounded so a customer cannot request an unaffordable job."""

    cycles_samples: int = 192
    cycles_max_bounces: int = 8
    denoise: bool = True
    use_gpu: bool = True
    film_transparent: bool = False
    preview_samples: int = 24

    def __post_init__(self) -> None:
        if not 16 <= self.cycles_samples <= 4096:
            raise ParameterValidationError("cycles_samples must be within 16..4096.")
        if not 2 <= self.cycles_max_bounces <= 32:
            raise ParameterValidationError("cycles_max_bounces must be within 2..32.")
        if not 4 <= self.preview_samples <= 256:
            raise ParameterValidationError("preview_samples must be within 4..256.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycles_samples": self.cycles_samples,
            "cycles_max_bounces": self.cycles_max_bounces,
            "denoise": self.denoise,
            "use_gpu": self.use_gpu,
            "film_transparent": self.film_transparent,
            "preview_samples": self.preview_samples,
        }


@dataclass(frozen=True)
class RecipeRequest:
    """What the customer asked for, in registry references rather than resolved values."""

    blade_model_ref: str
    defects: tuple[DefectSelection, ...]
    camera_preset_ref: str
    environment_ref: str
    output_schema_ref: str
    image_count: int
    image_width: int
    image_height: int
    dataset_name: str
    section_ids: tuple[str, ...] = ()
    camera_view: cameras.CameraViewRequest | None = None
    requested_fov_deg: float | None = None
    weather_intensity: float = 0.5
    weather_overrides: dict[str, float] = field(default_factory=dict)
    annotation_formats: tuple[str, ...] = ()
    crop_policy: str | None = None
    annotation_policy: str | None = None
    occlusion_policy: str | None = None
    include_semantic_mask: bool | None = None
    seed: int | None = None
    seed_policy: str = SEED_POLICY_FIXED
    region_document: RegionStrokeDocument | None = None
    randomization: RandomizationSpec = field(default_factory=RandomizationSpec)
    quality: QualitySpec = field(default_factory=QualitySpec)
    customer_notes: str | None = None
    is_preview: bool = False
    # The untouched original payload when this came through the compatibility path.
    legacy_payload: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.defects:
            raise ParameterValidationError("A recipe needs at least one defect selection.")
        primaries = [d for d in self.defects if d.role == PRIMARY]
        if len(primaries) != 1:
            raise ParameterValidationError(
                "Exactly one primary defect profile is required; secondary damage is "
                f"optional. Got {len(primaries)} primaries."
            )
        if not 1 <= self.image_count <= MAX_IMAGE_COUNT:
            raise ParameterValidationError(
                f"image_count must be within 1..{MAX_IMAGE_COUNT}."
            )
        for name, value in (("image_width", self.image_width), ("image_height", self.image_height)):
            if not MIN_RESOLUTION <= value <= MAX_RESOLUTION:
                raise ParameterValidationError(
                    f"{name}={value} must be within {MIN_RESOLUTION}..{MAX_RESOLUTION}."
                )
        if self.seed_policy not in SEED_POLICIES:
            raise ParameterValidationError(f"Unknown seed policy {self.seed_policy!r}.")
        if not 0.0 <= self.weather_intensity <= 1.0:
            raise ParameterValidationError("weather_intensity must be within 0..1.")
        if self.customer_notes is not None and len(self.customer_notes) > 4000:
            raise ParameterValidationError("customer_notes is limited to 4000 characters.")

    @property
    def primary_defect(self) -> DefectSelection:
        return next(d for d in self.defects if d.role == PRIMARY)

    def as_dict(self) -> dict[str, Any]:
        return {
            "blade_model_ref": self.blade_model_ref,
            "section_ids": list(self.section_ids),
            "defects": [d.as_dict() for d in self.defects],
            "camera_preset_ref": self.camera_preset_ref,
            "camera_view": None if self.camera_view is None else self.camera_view.as_dict(),
            "requested_fov_deg": self.requested_fov_deg,
            "environment_ref": self.environment_ref,
            "weather_intensity": self.weather_intensity,
            "weather_overrides": dict(sorted(self.weather_overrides.items())),
            "output_schema_ref": self.output_schema_ref,
            "annotation_formats": list(self.annotation_formats),
            "crop_policy": self.crop_policy,
            "annotation_policy": self.annotation_policy,
            "occlusion_policy": self.occlusion_policy,
            "include_semantic_mask": self.include_semantic_mask,
            "image_count": self.image_count,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "dataset_name": self.dataset_name,
            "seed": self.seed,
            "seed_policy": self.seed_policy,
            "region_document_checksum": (
                None if self.region_document is None else self.region_document.checksum
            ),
            "randomization": self.randomization.as_dict(),
            "quality": self.quality.as_dict(),
            "customer_notes": self.customer_notes,
            "is_preview": self.is_preview,
            "legacy_payload": self.legacy_payload,
        }

    # -- compatibility ----------------------------------------------------
    @classmethod
    def for_legacy_job(
        cls,
        *,
        defect_type: str,
        severity_min: int,
        severity_max: int,
        image_count: int,
        annotation_format: str,
        dataset_name: str,
        config: dict[str, Any] | None = None,
        seed: int | None = None,
    ) -> RecipeRequest:
        """Build a request from the pre-upgrade job payload.

        Every legacy field keeps its original meaning. The legacy development blade,
        the legacy square camera, and the legacy output schema are selected so that a
        job submitted with the old payload resolves to the behaviour it had before,
        while still flowing through the versioned pipeline.
        """
        settings = dict(config or {})
        profile = profile_for_legacy_defect_type(defect_type)
        lighting_preset = str(settings.get("lighting_preset", "overcast"))
        environment = environments.environment_for_legacy_lighting_preset(lighting_preset)
        schema = outputs.output_schema_for_legacy_format(annotation_format)
        width = int(settings.get("image_width", 1024))
        height = int(settings.get("image_height", 1024))
        fov = settings.get("camera_fov")
        return cls(
            blade_model_ref=blades.LEGACY_BLADE_MODEL_ID,
            defects=(
                DefectSelection(
                    profile_ref=profile.id,
                    role=PRIMARY,
                    severity_min=float(severity_min),
                    severity_max=float(severity_max),
                ),
            ),
            camera_preset_ref=cameras.LEGACY_CAMERA_PRESET_ID,
            environment_ref=environment.id,
            output_schema_ref=schema.id,
            image_count=image_count,
            image_width=width,
            image_height=height,
            dataset_name=dataset_name,
            requested_fov_deg=None if fov is None else float(fov),
            # The legacy renderer had no weather model, so the compatibility path pins
            # the mildest sample of the mapped environment rather than inventing rain.
            weather_intensity=0.0,
            annotation_formats=(annotation_format,),
            seed=seed,
            quality=QualitySpec(cycles_samples=128, preview_samples=16),
            legacy_payload={
                "defect_type": defect_type,
                "severity_min": severity_min,
                "severity_max": severity_max,
                "image_count": image_count,
                "annotation_format": annotation_format,
                "dataset_name": dataset_name,
                "config": settings,
            },
        )


@dataclass(frozen=True)
class SensorEffects:
    """Per-sample sensor and post-processing state.

    Recorded because these are the effects that can silently misalign a mask, so the
    mask pipeline has to apply exactly the same values.
    """

    exposure_ev_offset: float
    iso_scale: float
    jpeg_quality: int
    lens_distortion_enabled: bool
    chromatic_aberration: float
    sensor_noise_enabled: bool
    motion_blur_enabled: bool
    motion_blur_shutter: float
    motion_blur_mask_policy: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "exposure_ev_offset": round(self.exposure_ev_offset, 5),
            "iso_scale": round(self.iso_scale, 5),
            "jpeg_quality": self.jpeg_quality,
            "lens_distortion_enabled": self.lens_distortion_enabled,
            "chromatic_aberration": round(self.chromatic_aberration, 5),
            "sensor_noise_enabled": self.sensor_noise_enabled,
            "motion_blur_enabled": self.motion_blur_enabled,
            "motion_blur_shutter": round(self.motion_blur_shutter, 5),
            "motion_blur_mask_policy": self.motion_blur_mask_policy,
        }


@dataclass(frozen=True)
class SurfaceVariation:
    """Per-sample blade surface state, separate from the defects themselves."""

    dirt_amount: float
    manufacturing_variation: float
    surface_contamination: float
    wetness: float

    def as_dict(self) -> dict[str, float]:
        return {
            "dirt_amount": round(self.dirt_amount, 5),
            "manufacturing_variation": round(self.manufacturing_variation, 5),
            "surface_contamination": round(self.surface_contamination, 5),
            "wetness": round(self.wetness, 5),
        }


@dataclass(frozen=True)
class ResolvedSample:
    """Everything needed to render one image, with nothing left to chance."""

    index: int
    seed: int
    defects: tuple[ResolvedDefect, ...]
    camera: cameras.ResolvedCamera
    environment: environments.ResolvedEnvironment
    sensor: SensorEffects
    surface: SurfaceVariation
    target_section_ids: tuple[str, ...]
    is_hard_negative: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "seed": self.seed,
            "defects": [d.as_dict() for d in self.defects],
            "camera": self.camera.as_dict(),
            "environment": self.environment.as_dict(),
            "sensor": self.sensor.as_dict(),
            "surface": self.surface.as_dict(),
            "target_section_ids": list(self.target_section_ids),
            "is_hard_negative": self.is_hard_negative,
        }


@dataclass(frozen=True)
class ResolvedRecipe:
    """The immutable, checksummed configuration stored with a job."""

    schema_version: str
    render_engine_version: str
    request: RecipeRequest
    master_seed: int
    blade_model: blades.BladeModelVersion
    sections: tuple[blades.BladeSection, ...]
    defect_profiles: tuple[DefectProfileVersion, ...]
    material_versions: tuple[materials.MaterialVersion, ...]
    camera_preset: cameras.CameraSensorPreset
    environment: environments.EnvironmentVersion
    output_schema: outputs.OutputSchemaVersion
    taxonomy_version: taxonomy.TaxonomyVersion
    region_mask: RasterisedRegionMask | None
    sample_plans: tuple[ResolvedSample, ...]

    # -- per-sample resolution -------------------------------------------
    def resolve_sample(self, index: int) -> ResolvedSample:
        """Deterministically produce the plan for one sample.

        Called by the renderer for every image. Because the seed derives from the
        master seed and the index, the same job always yields the same sample, whether
        it is rendered now or re-rendered on another machine a year later.
        """
        if not 0 <= index < self.request.image_count:
            raise RecipeResolutionError(
                f"Sample index {index} is outside 0..{self.request.image_count - 1}."
            )
        return _resolve_sample(self, index)

    def iter_sample_plans(self) -> list[ResolvedSample]:
        return [self.resolve_sample(index) for index in range(self.request.image_count)]

    # -- serialisation ---------------------------------------------------
    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "render_engine_version": self.render_engine_version,
            "master_seed": self.master_seed,
            "request": self.request.as_dict(),
            "blade_model": self.blade_model.as_dict(),
            "section_ids": [section.id for section in self.sections],
            "defect_profiles": [profile.as_dict() for profile in self.defect_profiles],
            "materials": [material.as_dict() for material in self.material_versions],
            "camera_preset": self.camera_preset.as_dict(),
            "environment": self.environment.as_dict(),
            "output_schema": self.output_schema.as_dict(),
            "taxonomy": self.taxonomy_version.as_dict(),
            "region_mask": (
                None if self.region_mask is None else self.region_mask.as_metadata()
            ),
            "registry_checksums": self.registry_checksums(),
            "sample_plans": [plan.as_dict() for plan in self.sample_plans],
            "sample_plans_embedded": len(self.sample_plans),
            "sample_plans_total": self.request.image_count,
        }

    def registry_checksums(self) -> dict[str, str]:
        from .defects import registry_checksum as defect_registry_checksum

        return {
            "blade_models": blades.registry_checksum(),
            "cameras": cameras.registry_checksum(),
            "defects": defect_registry_checksum(),
            "environments": environments.registry_checksum(),
            "materials": materials.registry_checksum(),
            "outputs": outputs.registry_checksum(),
            "taxonomy": self.taxonomy_version.checksum,
        }

    @property
    def checksum(self) -> str:
        """SHA-256 of the resolved configuration, excluding the embedded sample preview.

        The embedded plans are derivable from the master seed, so leaving them out
        keeps the checksum stable regardless of how many are stored.
        """
        payload = self.as_dict()
        payload.pop("sample_plans", None)
        payload.pop("sample_plans_embedded", None)
        return checksum(payload)

    def snapshot(self) -> dict[str, Any]:
        """What gets written to the job row and the dataset manifest."""
        payload = self.as_dict()
        payload["checksum_sha256"] = self.checksum
        return payload

    # -- convenience for the product surface ------------------------------
    @property
    def category_ids(self) -> tuple[int, ...]:
        ids: list[int] = []
        for profile in self.defect_profiles:
            for category_id in profile.emitted_category_ids:
                if category_id not in ids:
                    ids.append(category_id)
        return tuple(sorted(ids))

    @property
    def annotatable_category_ids(self) -> tuple[int, ...]:
        ids: list[int] = []
        for profile in self.defect_profiles:
            for category_id in profile.annotatable_category_ids:
                if category_id not in ids:
                    ids.append(category_id)
        return tuple(sorted(ids))

    def estimated_bytes_per_image(self) -> int:
        """Used for the pre-submission size estimate shown to the customer."""
        pixels = self.request.image_width * self.request.image_height
        # An RGB PNG of a rendered blade compresses to roughly 0.9 bytes per pixel.
        total = pixels * 0.9
        if self.output_schema.include_visible_masks:
            # A class-ID mask is single-channel and mostly one value, so it is tiny.
            total += pixels * 0.02
        if self.output_schema.include_intrinsic_masks:
            total += pixels * 0.02
        if self.output_schema.include_semantic_mask:
            total += pixels * 0.02
        if self.output_schema.emits_crops:
            total += pixels * 0.12
        # Per-image metadata JSON.
        total += 3_500
        return int(total)

    def estimated_total_bytes(self) -> int:
        return self.estimated_bytes_per_image() * self.request.image_count


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def _resolve_sections(
    model: blades.BladeModelVersion, section_ids: tuple[str, ...]
) -> tuple[blades.BladeSection, ...]:
    if not section_ids:
        return model.sections
    known = {section.id: section for section in model.sections}
    unknown = [value for value in section_ids if value not in known]
    if unknown:
        raise RecipeResolutionError(
            f"{model.id} has no blade section named {unknown[0]!r}. Available sections: "
            f"{', '.join(sorted(known))}."
        )
    ordered = [
        section for section in model.sections if section.id in set(section_ids)
    ]
    return tuple(ordered)


def _resolve_sample(recipe: ResolvedRecipe, index: int) -> ResolvedSample:
    request = recipe.request
    rng = random.Random(derive_sample_seed(recipe.master_seed, index))
    schema = recipe.output_schema
    randomization = request.randomization

    # --- environment and weather ---------------------------------------
    if randomization.weather_intensity_range is not None:
        low, high = randomization.weather_intensity_range
        intensity = rng.uniform(low, high)
    else:
        intensity = request.weather_intensity
    resolved_environment = environments.resolve_environment(
        recipe.environment,
        rng,
        intensity=intensity,
        overrides=request.weather_overrides or None,
    )

    # --- camera ---------------------------------------------------------
    weather = resolved_environment.weather
    motion_blur = (
        randomization.motion_blur_allowed and resolved_environment.motion_blur_enabled
    )
    exposure_low, exposure_high = randomization.exposure_ev_range
    exposure_offset = rng.uniform(exposure_low, exposure_high)
    iso_scale = weather["sensor_noise_iso_scale"]
    resolved_camera = cameras.resolve_camera(
        recipe.camera_preset,
        rng,
        target_m=_section_target(recipe),
        view=request.camera_view,
        distance_m_range=randomization.distance_m_range,
        azimuth_deg_range=randomization.azimuth_deg_range,
        elevation_deg_range=randomization.elevation_deg_range,
        requested_fov_deg=request.requested_fov_deg,
        exposure_ev_offset=exposure_offset + resolved_environment.exposure_ev,
        iso_scale=iso_scale,
        camera_stability=weather["camera_stability"],
        motion_blur_enabled=motion_blur,
        motion_blur_shutter=weather["motion_blur_shutter"],
        resolution=(request.image_width, request.image_height),
    )

    # --- sensor and surface --------------------------------------------
    jpeg_low, jpeg_high = randomization.jpeg_quality_range
    aberration_low, aberration_high = randomization.chromatic_aberration_range
    sensor = SensorEffects(
        exposure_ev_offset=exposure_offset,
        iso_scale=iso_scale,
        jpeg_quality=rng.randint(jpeg_low, jpeg_high),
        lens_distortion_enabled=(
            randomization.lens_distortion_enabled
            and recipe.camera_preset.distortion.enabled
        ),
        chromatic_aberration=rng.uniform(aberration_low, aberration_high),
        sensor_noise_enabled=randomization.sensor_noise_enabled,
        motion_blur_enabled=motion_blur,
        motion_blur_shutter=weather["motion_blur_shutter"],
        motion_blur_mask_policy=schema.motion_blur_mask_policy,
    )
    dirt_low, dirt_high = randomization.dirt_amount_range
    manufacturing_low, manufacturing_high = randomization.manufacturing_variation_range
    contamination_low, contamination_high = randomization.surface_contamination_range
    surface = SurfaceVariation(
        dirt_amount=rng.uniform(dirt_low, dirt_high),
        manufacturing_variation=rng.uniform(manufacturing_low, manufacturing_high),
        surface_contamination=rng.uniform(contamination_low, contamination_high),
        wetness=resolved_environment.wetness,
    )

    # --- defects --------------------------------------------------------
    profiles = {profile.id: profile for profile in recipe.defect_profiles}
    resolved_defects: list[ResolvedDefect] = []
    for selection in request.defects:
        profile = profiles[get_profile(selection.profile_ref).id]
        if selection.presence_probability < 1.0 and rng.random() > selection.presence_probability:
            continue
        instances = rng.randint(selection.instance_count_min, selection.instance_count_max)
        for instance_index in range(instances):
            severity = sample_severity(rng, selection.severity_min, selection.severity_max)
            overrides = dict(selection.parameter_overrides)
            if profile.requires_metallic_context:
                overrides.setdefault(
                    "metallic_context_present",
                    1.0 if recipe.blade_model.has_metallic_components else 0.0,
                )
            resolved_defects.append(
                profile.resolve(
                    severity,
                    rng,
                    role=selection.role,
                    region_id=selection.region_id,
                    instance_index=instance_index,
                    overrides=overrides or None,
                )
            )

    is_hard_negative = not any(
        profiles[d.profile_id].produces_visible_mask for d in resolved_defects
    )
    if schema.occlusion_policy == outputs.OcclusionPolicy.HARD_NEGATIVE:
        is_hard_negative = True

    return ResolvedSample(
        index=index,
        seed=derive_sample_seed(recipe.master_seed, index),
        defects=tuple(resolved_defects),
        camera=resolved_camera,
        environment=resolved_environment,
        sensor=sensor,
        surface=surface,
        target_section_ids=tuple(section.id for section in recipe.sections),
        is_hard_negative=is_hard_negative,
    )


def _section_target(recipe: ResolvedRecipe) -> tuple[float, float, float]:
    """Aim the camera at the middle of the selected sections along the span."""
    if not recipe.sections:
        return (0.0, 0.0, recipe.blade_model.length_m * 0.5)
    start = min(section.span_start_fraction for section in recipe.sections)
    end = max(section.span_end_fraction for section in recipe.sections)
    span_fraction = (start + end) * 0.5
    return (0.0, 0.0, recipe.blade_model.length_m * span_fraction)


def resolve_recipe(request: RecipeRequest) -> ResolvedRecipe:
    """Resolve a request into an immutable, checksummed, reproducible configuration.

    Everything that can be rejected is rejected here, in the backend, before a job is
    ever queued: disabled capabilities, unsupported defect combinations, painted
    regions that no longer match the model, defects pointing at region layers that do
    not exist, and metallic-context violations.
    """
    # --- blade model ---------------------------------------------------
    model = blades.get_blade_model(request.blade_model_ref)
    if not is_enabled(model.feature_flag):
        raise RecipeResolutionError(
            f"Blade model {model.id} is not available on this deployment."
        )
    sections = _resolve_sections(model, request.section_ids)

    # --- defect profiles ------------------------------------------------
    resolved_profiles: list[DefectProfileVersion] = []
    for selection in request.defects:
        profile = get_profile(selection.profile_ref)
        if not is_enabled(profile.feature_flag):
            raise RecipeResolutionError(
                f"Defect profile {profile.id} is not available on this deployment."
            )
        if selection.role == PRIMARY and not profile.supports_as_primary:
            raise RecipeResolutionError(
                f"{profile.id} cannot be used as the primary defect."
            )
        if selection.role == SECONDARY and not profile.supports_as_secondary:
            raise RecipeResolutionError(
                f"{profile.id} is not supported as secondary damage."
            )
        if selection.section_ids:
            _resolve_sections(model, selection.section_ids)
        if profile.requires_metallic_context and not model.has_metallic_components:
            raise RecipeResolutionError(
                f"{profile.title} models corrosion of a metallic part, but {model.id} "
                "declares no metallic components. Choose a model with metal hardware, "
                "or select rust runoff staining instead, which is honest about staining "
                "composite rather than claiming the composite corroded."
            )
        resolved_profiles.append(profile)

    primary = get_profile(request.primary_defect.profile_ref)
    secondaries = tuple(
        get_profile(d.profile_ref).id for d in request.defects if d.role == SECONDARY
    )
    if secondaries:
        if not is_enabled("defect_multi"):
            raise RecipeResolutionError(
                "Multiple defects per image are not available on this deployment."
            )
        assert_combination_supported(primary.id, secondaries)

    # --- painted region --------------------------------------------------
    region_mask: RasterisedRegionMask | None = None
    if request.region_document is not None:
        if not is_enabled("region_painting"):
            raise RecipeResolutionError(
                "Region painting is not available on this deployment."
            )
        document = request.region_document
        if len(document.layers) > 1 and not is_enabled("region_multi_layer"):
            raise RecipeResolutionError(
                "Multiple coloured region layers are not available on this deployment."
            )
        assert_region_matches_model(document, model)
        region_mask = rasterise_region_mask(document)
        empty = [
            region_id
            for region_id, coverage in region_mask.coverage_by_region.items()
            if coverage <= 0.0
        ]
        if empty:
            raise RegionMaskError(
                "These painted layers have no painted area, so nothing could be "
                f"generated in them: {', '.join(sorted(empty))}. Paint them or remove them."
            )
        known_regions = set(region_mask.layer_index_map)
        for selection in request.defects:
            if selection.region_id is None:
                continue
            if selection.region_id not in known_regions:
                raise RegionMaskError(
                    f"Defect {selection.profile_ref} is assigned to painted region "
                    f"{selection.region_id!r}, which does not exist in the saved region "
                    f"set. Available layers: {', '.join(sorted(known_regions))}."
                )
            layer = document.layer_by_id(selection.region_id)
            if get_profile(layer.defect_profile_id).id != get_profile(selection.profile_ref).id:
                raise RegionMaskError(
                    f"Painted layer {layer.region_id!r} is bound to "
                    f"{layer.defect_profile_id} but the job assigns "
                    f"{selection.profile_ref} to it."
                )
    else:
        assigned = [d.region_id for d in request.defects if d.region_id is not None]
        if assigned:
            raise RegionMaskError(
                "Defects reference painted regions but no painted region set was "
                "supplied with the job."
            )

    # --- camera ----------------------------------------------------------
    camera_preset = cameras.get_camera_preset(request.camera_preset_ref)
    if not is_enabled(camera_preset.feature_flag):
        raise RecipeResolutionError(
            f"Camera preset {camera_preset.id} is not available on this deployment."
        )
    if request.camera_view is not None:
        if not is_enabled("camera_saved_views"):
            raise RecipeResolutionError(
                "Saved camera views are not available on this deployment."
            )
        # Validated eagerly so a bad view fails at submission, not mid-render.
        cameras.validate_camera_view(camera_preset, request.camera_view)

    # --- environment -----------------------------------------------------
    environment = environments.get_environment(request.environment_ref)
    if not is_enabled(environment.feature_flag):
        raise RecipeResolutionError(
            f"Environment {environment.id} is not available on this deployment."
        )
    for name in request.weather_overrides:
        if name not in environment.weather.field_names():
            raise ParameterValidationError(
                f"{environment.id} has no weather parameter {name!r}."
            )

    # --- output schema ---------------------------------------------------
    schema = outputs.get_output_schema(request.output_schema_ref)
    if not is_enabled(schema.feature_flag):
        raise RecipeResolutionError(
            f"Output schema {schema.id} is not available on this deployment."
        )
    schema = schema.with_overrides(
        annotation_formats=request.annotation_formats or None,
        crop_policy=request.crop_policy,
        annotation_policy=request.annotation_policy,
        occlusion_policy=request.occlusion_policy,
        include_semantic_mask=request.include_semantic_mask,
    )
    if (
        outputs.AnnotationFormat.YOLO_SEGMENTATION in schema.canonical_formats
        and not is_enabled("annotation_yolo_segmentation")
    ):
        raise RecipeResolutionError(
            "YOLO segmentation output is not available on this deployment."
        )
    # A subsurface-only defect has no honest visible mask, so a schema that labels only
    # visible pixels would produce an empty dataset. Fail at submission with a reason.
    if schema.annotation_policy == outputs.AnnotationPolicy.VISIBLE_ONLY and not any(
        profile.produces_visible_mask for profile in resolved_profiles
    ):
        raise RecipeResolutionError(
            "Every selected defect is subsurface only, which has no visible signature "
            "in an RGB image. Choose an output schema that exports intrinsic "
            "annotations, or add a surface-visible defect."
        )

    # --- materials -------------------------------------------------------
    material_versions = materials.materials_for_slots(model.material_slots)

    # --- seed ------------------------------------------------------------
    if request.seed_policy == SEED_POLICY_FIXED:
        if request.seed is None:
            raise ParameterValidationError(
                "A fixed seed policy requires an explicit seed so the dataset is "
                "reproducible."
            )
        master_seed = int(request.seed)
    else:
        master_seed = int(request.seed) if request.seed is not None else random.SystemRandom().randrange(2**32)
    if not 0 <= master_seed < 2**63:
        raise ParameterValidationError("Seed must fit in an unsigned 63-bit integer.")

    recipe = ResolvedRecipe(
        schema_version=RECIPE_SCHEMA_VERSION,
        render_engine_version=render_engine_version(),
        request=replace(request, seed=master_seed),
        master_seed=master_seed,
        blade_model=model,
        sections=sections,
        defect_profiles=tuple(resolved_profiles),
        material_versions=material_versions,
        camera_preset=camera_preset,
        environment=environment,
        output_schema=schema,
        taxonomy_version=taxonomy.ACTIVE_TAXONOMY,
        region_mask=region_mask,
        sample_plans=(),
    )
    # Embed a bounded preview of resolved samples so the job row shows real values
    # without carrying a plan for every image in a 20,000-image job.
    embedded = min(request.image_count, EMBEDDED_SAMPLE_PLAN_LIMIT)
    plans = tuple(_resolve_sample(recipe, index) for index in range(embedded))
    return replace(recipe, sample_plans=plans)


def resolve_legacy_job(
    *,
    defect_type: str,
    severity_min: int,
    severity_max: int,
    image_count: int,
    annotation_format: str,
    dataset_name: str,
    config: dict[str, Any] | None = None,
    seed: int | None = None,
) -> ResolvedRecipe:
    """One call for the compatibility path used by jobs submitted with the old payload."""
    request = RecipeRequest.for_legacy_job(
        defect_type=defect_type,
        severity_min=severity_min,
        severity_max=severity_max,
        image_count=image_count,
        annotation_format=annotation_format,
        dataset_name=dataset_name,
        config=config,
        seed=seed if seed is not None else 0,
    )
    return resolve_recipe(request)


def default_request(
    *,
    dataset_name: str,
    profile_id: str,
    image_count: int = 50,
    seed: int = 1,
) -> RecipeRequest:
    """A sensible v2 request, used by tests and by the frontend's initial state."""
    return RecipeRequest(
        blade_model_ref=blades.BF_GENERIC_BLADE_V1.id,
        defects=(DefectSelection(profile_ref=profile_id),),
        camera_preset_ref=cameras.DEFAULT_CAMERA_PRESET_ID,
        environment_ref=environments.DEFAULT_ENVIRONMENT_ID,
        output_schema_ref=outputs.DEFAULT_OUTPUT_SCHEMA_ID,
        image_count=image_count,
        image_width=1024,
        image_height=1024,
        dataset_name=dataset_name,
        seed=seed,
    )


def severity_summary(request: RecipeRequest) -> dict[str, str]:
    """Human-readable severity bands, for the pre-submission summary panel."""
    return {
        selection.profile_ref: (
            f"{band_for_severity(selection.severity_min)} to "
            f"{band_for_severity(selection.severity_max)}"
        )
        for selection in request.defects
    }
