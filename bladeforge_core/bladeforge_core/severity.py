"""Severity bands and the mapping from a 0-100 severity score to real parameters.

The customer-facing control is a 0-100 severity range. Every defect profile
declares, per severity band, an explicit physical range for each of its
parameters in a named unit. Sampling is deterministic for a given seed, which is
what makes ``deterministic seed`` tests meaningful.

Band boundaries are fixed so that a severity value always maps to the same band
across releases:

``early``     0 to 33 inclusive
``moderate``  34 to 66 inclusive
``severe``    67 to 100 inclusive
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from .errors import ParameterValidationError

EARLY = "early"
MODERATE = "moderate"
SEVERE = "severe"

SEVERITY_BANDS: tuple[str, ...] = (EARLY, MODERATE, SEVERE)

BAND_BOUNDS: dict[str, tuple[int, int]] = {
    EARLY: (0, 33),
    MODERATE: (34, 66),
    SEVERE: (67, 100),
}


def band_for_severity(severity: float) -> str:
    """Map a 0-100 severity score onto a named band."""
    if not 0.0 <= severity <= 100.0:
        raise ParameterValidationError(f"Severity {severity} is outside 0-100.")
    for band, (low, high) in BAND_BOUNDS.items():
        if low <= severity <= high:
            return band
    # severity == 100 lands in severe via the loop; this is unreachable defensively.
    return SEVERE


def band_position(severity: float) -> float:
    """Position of ``severity`` inside its own band, normalised to 0..1."""
    band = band_for_severity(severity)
    low, high = BAND_BOUNDS[band]
    if high == low:
        return 0.0
    return (severity - low) / (high - low)


@dataclass(frozen=True)
class ParameterSpec:
    """One physically meaningful defect parameter.

    ``unit`` is always explicit. ``absolute_min``/``absolute_max`` are the hard
    validation limits across every band: a customer-supplied or profile-derived
    value outside them is rejected rather than clamped silently.
    """

    name: str
    unit: str
    absolute_min: float
    absolute_max: float
    description: str
    integral: bool = False

    def __post_init__(self) -> None:
        if self.absolute_min > self.absolute_max:
            raise ValueError(f"{self.name}: absolute_min exceeds absolute_max")

    def validate(self, value: float) -> float:
        if not self.absolute_min <= value <= self.absolute_max:
            raise ParameterValidationError(
                f"{self.name}={value} {self.unit} is outside the allowed range "
                f"{self.absolute_min}-{self.absolute_max} {self.unit}."
            )
        return round(value) if self.integral else value

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "unit": self.unit,
            "absolute_min": self.absolute_min,
            "absolute_max": self.absolute_max,
            "description": self.description,
            "integral": self.integral,
        }


@dataclass(frozen=True)
class BandRange:
    """The range a single parameter may take inside one severity band."""

    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        if self.minimum > self.maximum:
            raise ValueError(f"Band range {self.minimum}-{self.maximum} is inverted")

    def sample(self, rng: random.Random, position: float | None = None) -> float:
        """Draw a value.

        When ``position`` is given the value is interpolated deterministically from
        the severity's position inside its band, then jittered by a bounded amount
        so that two images at the same severity are not identical. When it is
        ``None`` the value is drawn uniformly from the band.
        """
        if position is None:
            return rng.uniform(self.minimum, self.maximum)
        span = self.maximum - self.minimum
        centre = self.minimum + span * max(0.0, min(1.0, position))
        jitter = span * 0.15
        return max(self.minimum, min(self.maximum, rng.uniform(centre - jitter, centre + jitter)))

    def as_dict(self) -> dict[str, float]:
        return {"min": self.minimum, "max": self.maximum}


def as_band_range(value: BandRange | tuple[float, float] | list[float]) -> BandRange:
    if isinstance(value, BandRange):
        return value
    minimum, maximum = value
    return BandRange(float(minimum), float(maximum))


def severity_label(severity: float) -> str:
    return band_for_severity(severity)


def sample_severity(
    rng: random.Random, severity_min: float, severity_max: float
) -> float:
    """Draw a severity score from the customer's requested range."""
    if severity_min > severity_max:
        raise ParameterValidationError("severity_min must not exceed severity_max.")
    if not (0.0 <= severity_min and severity_max <= 100.0):
        raise ParameterValidationError("Severity range must stay inside 0-100.")
    return rng.uniform(severity_min, severity_max)
