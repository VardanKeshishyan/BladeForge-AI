"""The immutable defect-profile version type.

A profile is not a label in a dropdown. Before the backend reports a profile as
available it must have:

* a real renderer implementation keyed by ``renderer_key``;
* every parameter declared with an explicit physical unit and hard bounds;
* explicit per-band parameter ranges for early, moderate, and severe;
* the taxonomy categories it emits, so masks and annotations are structured;
* coverage limits used to reject renders whose mask is empty or implausible;
* a feature flag, so it stays hidden until its acceptance tests pass.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from ..errors import ParameterValidationError, RegistryLookupError
from ..severity import (
    SEVERITY_BANDS,
    BandRange,
    ParameterSpec,
    band_for_severity,
    band_position,
)
from ..taxonomy import ACTIVE_TAXONOMY
from ..versioning import (
    INTERNAL_AUTHORSHIP,
    LicenseRecord,
    ReleaseStatus,
    SemanticVersion,
    checksum,
    validate_registry_id,
)

# Bumped when the JSON contract between the resolver and the Blender renderer changes.
RENDERER_SCHEMA_VERSION = "2.0.0"


@dataclass(frozen=True)
class ResolvedDefect:
    """A concrete, physically-valued defect instance for one rendered sample."""

    profile_id: str
    profile_version: str
    family: str
    renderer_key: str
    renderer_schema_version: str
    severity: float
    severity_band: str
    primary_category_id: int
    primary_category_name: str
    emitted_category_ids: tuple[int, ...]
    parameters: dict[str, float]
    parameter_units: dict[str, str]
    role: str = "primary"
    region_id: str | None = None
    instance_index: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "family": self.family,
            "renderer_key": self.renderer_key,
            "renderer_schema_version": self.renderer_schema_version,
            "role": self.role,
            "region_id": self.region_id,
            "instance_index": self.instance_index,
            "severity": round(self.severity, 4),
            "severity_band": self.severity_band,
            "primary_category_id": self.primary_category_id,
            "primary_category_name": self.primary_category_name,
            "emitted_category_ids": list(self.emitted_category_ids),
            "parameters": {k: _round(v) for k, v in sorted(self.parameters.items())},
            "parameter_units": dict(sorted(self.parameter_units.items())),
        }


def _round(value: float) -> float | int:
    if isinstance(value, bool):
        return int(value)
    if float(value).is_integer():
        return int(value)
    return round(float(value), 6)


@dataclass(frozen=True)
class CoverageLimits:
    """Plausibility bounds on the fraction of the image a defect mask may occupy.

    A render whose mask falls outside these bounds is rejected: an empty mask is a
    silently broken label, and a mask covering most of the frame usually means the
    defect escaped its region or the camera clipped into the blade.
    """

    minimum_pixel_fraction: float = 0.00002
    maximum_pixel_fraction: float = 0.60
    minimum_pixels: int = 24

    def as_dict(self) -> dict[str, Any]:
        return {
            "minimum_pixel_fraction": self.minimum_pixel_fraction,
            "maximum_pixel_fraction": self.maximum_pixel_fraction,
            "minimum_pixels": self.minimum_pixels,
        }


@dataclass(frozen=True)
class DefectProfileVersion:
    id: str
    version: str
    status: str
    title: str
    summary: str
    family: str
    renderer_key: str
    primary_category: str
    emitted_categories: tuple[str, ...]
    parameters: tuple[ParameterSpec, ...]
    bands: dict[str, dict[str, BandRange]]
    feature_flag: str
    coverage_limits: CoverageLimits = field(default_factory=CoverageLimits)
    renderer_schema_version: str = RENDERER_SCHEMA_VERSION
    # Real corrosion needs a metallic part. Profiles that set this refuse to place
    # damage on bare composite and fall back to a staining category instead.
    requires_metallic_context: bool = False
    # False for damage that has no honest RGB signature. The renderer records it in
    # metadata but emits no visible mask, and the validator does not treat the empty
    # visible mask as a failure. Never pretend an invisible defect is labellable.
    produces_visible_mask: bool = True
    supports_as_primary: bool = True
    supports_as_secondary: bool = False
    # Secondary profiles whose interaction with this one is implemented and tested.
    validated_secondary_profiles: tuple[str, ...] = ()
    license: LicenseRecord = INTERNAL_AUTHORSHIP
    notes: str = ""
    _spec_by_name: dict[str, ParameterSpec] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        validate_registry_id(self.id)
        SemanticVersion.parse(self.version)
        if self.status not in ReleaseStatus.ALL:
            raise ValueError(f"Unknown release status {self.status!r}")
        ACTIVE_TAXONOMY.by_name(self.primary_category)
        if self.primary_category not in self.emitted_categories:
            raise ValueError(
                f"{self.id}: primary category {self.primary_category!r} must also be "
                "listed in emitted_categories."
            )
        for name in self.emitted_categories:
            ACTIVE_TAXONOMY.by_name(name)
        if not self.parameters:
            raise ValueError(f"{self.id}: a profile must declare at least one parameter.")
        self._spec_by_name.update({spec.name: spec for spec in self.parameters})
        if len(self._spec_by_name) != len(self.parameters):
            raise ValueError(f"{self.id}: duplicate parameter name.")
        missing_bands = set(SEVERITY_BANDS) - set(self.bands)
        if missing_bands:
            raise ValueError(f"{self.id}: missing severity bands {sorted(missing_bands)}.")
        for band, ranges in self.bands.items():
            if band not in SEVERITY_BANDS:
                raise ValueError(f"{self.id}: unknown severity band {band!r}.")
            unknown = set(ranges) - set(self._spec_by_name)
            if unknown:
                raise ValueError(f"{self.id}: band {band} declares unknown {sorted(unknown)}.")
            undeclared = set(self._spec_by_name) - set(ranges)
            if undeclared:
                raise ValueError(
                    f"{self.id}: band {band} does not declare a range for "
                    f"{sorted(undeclared)}. Every band must cover every parameter."
                )
            for name, band_range in ranges.items():
                spec = self._spec_by_name[name]
                if band_range.minimum < spec.absolute_min or band_range.maximum > spec.absolute_max:
                    raise ValueError(
                        f"{self.id}: band {band} range for {name} "
                        f"({band_range.minimum}-{band_range.maximum}) escapes the "
                        f"absolute limits {spec.absolute_min}-{spec.absolute_max}."
                    )

    # -- identity ----------------------------------------------------------
    @property
    def is_selectable(self) -> bool:
        return self.status == ReleaseStatus.RELEASED

    @property
    def primary_category_id(self) -> int:
        return ACTIVE_TAXONOMY.by_name(self.primary_category).id

    @property
    def emitted_category_ids(self) -> tuple[int, ...]:
        return tuple(ACTIVE_TAXONOMY.by_name(name).id for name in self.emitted_categories)

    @property
    def annotatable_category_ids(self) -> tuple[int, ...]:
        return tuple(
            ACTIVE_TAXONOMY.by_name(name).id
            for name in self.emitted_categories
            if ACTIVE_TAXONOMY.by_name(name).annotatable_from_rgb
        )

    def parameter(self, name: str) -> ParameterSpec:
        try:
            return self._spec_by_name[name]
        except KeyError as exc:
            raise RegistryLookupError(f"{self.id} has no parameter {name!r}") from exc

    # -- resolution --------------------------------------------------------
    def resolve(
        self,
        severity: float,
        rng: random.Random,
        *,
        role: str = "primary",
        region_id: str | None = None,
        instance_index: int = 0,
        overrides: dict[str, float] | None = None,
    ) -> ResolvedDefect:
        """Turn a severity score into concrete physical parameters.

        ``overrides`` is for advanced API customers supplying a structured
        configuration. Each override is validated against the parameter's absolute
        limits; anything outside them raises rather than being clamped.
        """
        band = band_for_severity(severity)
        position = band_position(severity)
        ranges = self.bands[band]
        values: dict[str, float] = {}
        for spec in self.parameters:
            raw = ranges[spec.name].sample(rng, position)
            values[spec.name] = spec.validate(raw)
        for name, value in (overrides or {}).items():
            spec = self.parameter(name)
            values[name] = spec.validate(float(value))
        if self.requires_metallic_context and not values.get("metallic_context_present", 1):
            raise ParameterValidationError(
                f"{self.id} models corrosion of a metallic part and cannot be placed on "
                "bare composite. Select a metallic component or use rust runoff staining."
            )
        return ResolvedDefect(
            profile_id=self.id,
            profile_version=self.version,
            family=self.family,
            renderer_key=self.renderer_key,
            renderer_schema_version=self.renderer_schema_version,
            severity=severity,
            severity_band=band,
            primary_category_id=self.primary_category_id,
            primary_category_name=self.primary_category,
            emitted_category_ids=self.emitted_category_ids,
            parameters=values,
            parameter_units={spec.name: spec.unit for spec in self.parameters},
            role=role,
            region_id=region_id,
            instance_index=instance_index,
        )

    def band_table(self) -> dict[str, dict[str, dict[str, float]]]:
        return {
            band: {name: rng.as_dict() for name, rng in sorted(ranges.items())}
            for band, ranges in sorted(self.bands.items())
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "status": self.status,
            "title": self.title,
            "summary": self.summary,
            "family": self.family,
            "renderer_key": self.renderer_key,
            "renderer_schema_version": self.renderer_schema_version,
            "primary_category": self.primary_category,
            "primary_category_id": self.primary_category_id,
            "emitted_categories": list(self.emitted_categories),
            "emitted_category_ids": list(self.emitted_category_ids),
            "parameters": [spec.as_dict() for spec in self.parameters],
            "bands": self.band_table(),
            "coverage_limits": self.coverage_limits.as_dict(),
            "requires_metallic_context": self.requires_metallic_context,
            "produces_visible_mask": self.produces_visible_mask,
            "supports_as_primary": self.supports_as_primary,
            "supports_as_secondary": self.supports_as_secondary,
            "validated_secondary_profiles": list(self.validated_secondary_profiles),
            "feature_flag": self.feature_flag,
            "license": self.license.as_dict(),
            "notes": self.notes,
        }

    @property
    def checksum(self) -> str:
        return checksum(self.as_dict())

    def public_summary(self) -> dict[str, Any]:
        """The customer-facing view: understandable controls, no renderer internals."""
        return {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "summary": self.summary,
            "family": self.family,
            "severity_levels": list(SEVERITY_BANDS),
            "primary_category": self.primary_category,
            "emitted_categories": list(self.emitted_categories),
            "requires_metallic_context": self.requires_metallic_context,
            "produces_visible_mask": self.produces_visible_mask,
            "supports_as_primary": self.supports_as_primary,
            "supports_as_secondary": self.supports_as_secondary,
            "validated_secondary_profiles": list(self.validated_secondary_profiles),
            "checksum": self.checksum,
        }


def spec(
    name: str,
    unit: str,
    absolute_min: float,
    absolute_max: float,
    description: str,
    *,
    integral: bool = False,
) -> ParameterSpec:
    return ParameterSpec(
        name=name,
        unit=unit,
        absolute_min=absolute_min,
        absolute_max=absolute_max,
        description=description,
        integral=integral,
    )


def bands(
    early: dict[str, tuple[float, float]],
    moderate: dict[str, tuple[float, float]],
    severe: dict[str, tuple[float, float]],
) -> dict[str, dict[str, BandRange]]:
    return {
        "early": {k: BandRange(*v) for k, v in early.items()},
        "moderate": {k: BandRange(*v) for k, v in moderate.items()},
        "severe": {k: BandRange(*v) for k, v in severe.items()},
    }
