"""Camera and drone-sensor presets, with correct field-of-view mathematics.

Why this module exists
---------------------
The legacy renderer computed ``lens = 36 / tan(fov / 2)``. That is wrong: the
correct relation for a sensor of size ``s`` is

    focal = s / (2 * tan(fov / 2))

so with a 36 mm sensor the divisor is 18, not 36. The legacy expression produced
a focal length twice as long as intended, which rendered a field of view roughly
half of what the customer asked for. ``tests/test_camera_calibration.py`` pins the
corrected relation numerically and documents the legacy error so it cannot return.

Blender specifics
-----------------
``camera.data.angle`` is the field of view measured across the sensor dimension
selected by ``camera.data.sensor_fit``. With ``AUTO`` it follows the larger render
dimension, which silently changes meaning when a customer switches from landscape
to portrait. Every preset therefore pins ``sensor_fit`` explicitly and stores the
convention it was authored against.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from .errors import ParameterValidationError, RegistryLookupError
from .versioning import (
    INTERNAL_AUTHORSHIP,
    LicenseRecord,
    ReleaseStatus,
    SemanticVersion,
    checksum,
    validate_registry_id,
)

HORIZONTAL = "horizontal"
VERTICAL = "vertical"
DIAGONAL = "diagonal"


def focal_length_mm_from_fov(fov_degrees: float, sensor_mm: float) -> float:
    """Focal length that yields ``fov_degrees`` across a sensor of ``sensor_mm``."""
    if not 0.0 < fov_degrees < 180.0:
        raise ParameterValidationError(f"Field of view {fov_degrees} must be within 0-180 degrees.")
    if sensor_mm <= 0:
        raise ParameterValidationError("Sensor size must be positive.")
    return sensor_mm / (2.0 * math.tan(math.radians(fov_degrees) / 2.0))


def fov_degrees_from_focal_length(focal_mm: float, sensor_mm: float) -> float:
    """Inverse of :func:`focal_length_mm_from_fov`."""
    if focal_mm <= 0 or sensor_mm <= 0:
        raise ParameterValidationError("Focal length and sensor size must be positive.")
    return math.degrees(2.0 * math.atan(sensor_mm / (2.0 * focal_mm)))


def legacy_focal_length_mm_from_fov(fov_degrees: float) -> float:
    """The historical, incorrect expression. Retained only so tests can prove the fix."""
    return 36.0 / math.tan(math.radians(fov_degrees) / 2.0)


def diagonal_mm(sensor_width_mm: float, sensor_height_mm: float) -> float:
    return math.hypot(sensor_width_mm, sensor_height_mm)


@dataclass(frozen=True)
class DistortionCoefficients:
    """Brown-Conrady radial and tangential distortion.

    The same coefficients are applied to the RGB render and, with nearest-neighbour
    class-ID resampling, to the masks, so a distorted image and its label stay
    pixel-aligned.
    """

    k1: float = 0.0
    k2: float = 0.0
    k3: float = 0.0
    p1: float = 0.0
    p2: float = 0.0

    @property
    def enabled(self) -> bool:
        return any(abs(value) > 1e-12 for value in (self.k1, self.k2, self.k3, self.p1, self.p2))

    def as_dict(self) -> dict[str, float]:
        return {"k1": self.k1, "k2": self.k2, "k3": self.k3, "p1": self.p1, "p2": self.p2}


@dataclass(frozen=True)
class PoseRange:
    """Safe camera placement envelope relative to the blade being inspected."""

    distance_m_min: float
    distance_m_max: float
    azimuth_deg_min: float = -180.0
    azimuth_deg_max: float = 180.0
    elevation_deg_min: float = -60.0
    elevation_deg_max: float = 60.0
    roll_deg_min: float = -6.0
    roll_deg_max: float = 6.0

    def __post_init__(self) -> None:
        if self.distance_m_min <= 0 or self.distance_m_min > self.distance_m_max:
            raise ValueError("Invalid camera distance range.")
        if self.elevation_deg_min < -89.0 or self.elevation_deg_max > 89.0:
            raise ValueError("Elevation must stay strictly between -89 and 89 degrees.")

    def as_dict(self) -> dict[str, float]:
        return {
            "distance_m_min": self.distance_m_min,
            "distance_m_max": self.distance_m_max,
            "azimuth_deg_min": self.azimuth_deg_min,
            "azimuth_deg_max": self.azimuth_deg_max,
            "elevation_deg_min": self.elevation_deg_min,
            "elevation_deg_max": self.elevation_deg_max,
            "roll_deg_min": self.roll_deg_min,
            "roll_deg_max": self.roll_deg_max,
        }

    def clamp(self, *, distance_m: float, azimuth_deg: float, elevation_deg: float,
              roll_deg: float = 0.0) -> tuple[float, float, float, float]:
        return (
            min(max(distance_m, self.distance_m_min), self.distance_m_max),
            min(max(azimuth_deg, self.azimuth_deg_min), self.azimuth_deg_max),
            min(max(elevation_deg, self.elevation_deg_min), self.elevation_deg_max),
            min(max(roll_deg, self.roll_deg_min), self.roll_deg_max),
        )


@dataclass(frozen=True)
class CameraSensorPreset:
    id: str
    version: str
    status: str
    title: str
    summary: str
    sensor_width_mm: float
    sensor_height_mm: float
    focal_length_mm: float
    sensor_fit: str
    fov_convention: str
    resolution_x: int
    resolution_y: int
    pose: PoseRange
    feature_flag: str
    distortion: DistortionCoefficients = field(default_factory=DistortionCoefficients)
    exposure_ev_min: float = -1.0
    exposure_ev_max: float = 1.0
    shutter_speed_s: float = 1.0 / 500.0
    iso_min: int = 100
    iso_max: int = 400
    # Read noise floor and shot-noise scale used by the sensor-noise model.
    read_noise_sigma: float = 0.0025
    shot_noise_scale: float = 0.010
    chromatic_aberration_px: float = 0.0
    jpeg_quality: int = 92
    # True when this preset lets the customer choose the field of view directly, which
    # is how the legacy square preset preserved the existing camera_fov control.
    fov_is_customer_selectable: bool = False
    fov_deg_min: float = 20.0
    fov_deg_max: float = 90.0
    license: LicenseRecord = INTERNAL_AUTHORSHIP
    notes: str = ""

    def __post_init__(self) -> None:
        validate_registry_id(self.id)
        SemanticVersion.parse(self.version)
        if self.status not in ReleaseStatus.ALL:
            raise ValueError(f"Unknown release status {self.status!r}")
        if self.sensor_fit not in {"HORIZONTAL", "VERTICAL", "AUTO"}:
            raise ValueError(f"{self.id}: sensor_fit must be HORIZONTAL, VERTICAL, or AUTO.")
        if self.fov_convention not in {HORIZONTAL, VERTICAL, DIAGONAL}:
            raise ValueError(f"{self.id}: unknown fov convention {self.fov_convention!r}")
        if self.sensor_fit == "AUTO" and self.resolution_x != self.resolution_y:
            raise ValueError(
                f"{self.id}: sensor_fit AUTO is only unambiguous on a square render. "
                "Pin HORIZONTAL or VERTICAL instead."
            )
        if self.resolution_x < 64 or self.resolution_y < 64:
            raise ValueError(f"{self.id}: resolution is implausibly small.")

    @property
    def is_selectable(self) -> bool:
        return self.status == ReleaseStatus.RELEASED

    @property
    def fit_sensor_mm(self) -> float:
        """The sensor dimension Blender's ``camera.data.angle`` actually measures."""
        if self.sensor_fit == "HORIZONTAL":
            return self.sensor_width_mm
        if self.sensor_fit == "VERTICAL":
            return self.sensor_height_mm
        return max(self.sensor_width_mm, self.sensor_height_mm)

    @property
    def aspect_ratio(self) -> float:
        return self.resolution_x / self.resolution_y

    def horizontal_fov_deg(self) -> float:
        return fov_degrees_from_focal_length(self.focal_length_mm, self.sensor_width_mm)

    def vertical_fov_deg(self) -> float:
        return fov_degrees_from_focal_length(self.focal_length_mm, self.sensor_height_mm)

    def diagonal_fov_deg(self) -> float:
        return fov_degrees_from_focal_length(
            self.focal_length_mm, diagonal_mm(self.sensor_width_mm, self.sensor_height_mm)
        )

    def blender_angle_deg(self, focal_mm: float | None = None) -> float:
        """The value Blender will report as ``camera.data.angle`` in degrees."""
        return fov_degrees_from_focal_length(focal_mm or self.focal_length_mm, self.fit_sensor_mm)

    def focal_length_for_requested_fov(self, fov_degrees: float) -> float:
        """Focal length for a customer-requested field of view under this convention."""
        if not self.fov_is_customer_selectable:
            raise ParameterValidationError(
                f"{self.id} has a fixed lens. Choose a different preset to change the "
                "field of view."
            )
        if not self.fov_deg_min <= fov_degrees <= self.fov_deg_max:
            raise ParameterValidationError(
                f"Field of view {fov_degrees} is outside {self.fov_deg_min}-{self.fov_deg_max} "
                f"for {self.id}."
            )
        if self.fov_convention == HORIZONTAL:
            reference = self.sensor_width_mm
        elif self.fov_convention == VERTICAL:
            reference = self.sensor_height_mm
        else:
            reference = diagonal_mm(self.sensor_width_mm, self.sensor_height_mm)
        return focal_length_mm_from_fov(fov_degrees, reference)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "status": self.status,
            "title": self.title,
            "summary": self.summary,
            "sensor_width_mm": self.sensor_width_mm,
            "sensor_height_mm": self.sensor_height_mm,
            "focal_length_mm": self.focal_length_mm,
            "sensor_fit": self.sensor_fit,
            "fov_convention": self.fov_convention,
            "resolution_x": self.resolution_x,
            "resolution_y": self.resolution_y,
            "aspect_ratio": round(self.aspect_ratio, 6),
            "horizontal_fov_deg": round(self.horizontal_fov_deg(), 4),
            "vertical_fov_deg": round(self.vertical_fov_deg(), 4),
            "diagonal_fov_deg": round(self.diagonal_fov_deg(), 4),
            "blender_angle_deg": round(self.blender_angle_deg(), 4),
            "distortion": self.distortion.as_dict(),
            "exposure_ev_min": self.exposure_ev_min,
            "exposure_ev_max": self.exposure_ev_max,
            "shutter_speed_s": self.shutter_speed_s,
            "iso_min": self.iso_min,
            "iso_max": self.iso_max,
            "read_noise_sigma": self.read_noise_sigma,
            "shot_noise_scale": self.shot_noise_scale,
            "chromatic_aberration_px": self.chromatic_aberration_px,
            "jpeg_quality": self.jpeg_quality,
            "fov_is_customer_selectable": self.fov_is_customer_selectable,
            "fov_deg_min": self.fov_deg_min,
            "fov_deg_max": self.fov_deg_max,
            "pose": self.pose.as_dict(),
            "feature_flag": self.feature_flag,
            "license": self.license.as_dict(),
            "notes": self.notes,
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
            "resolution_x": self.resolution_x,
            "resolution_y": self.resolution_y,
            "horizontal_fov_deg": round(self.horizontal_fov_deg(), 2),
            "distortion_enabled": self.distortion.enabled,
            "fov_is_customer_selectable": self.fov_is_customer_selectable,
            "fov_deg_min": self.fov_deg_min,
            "fov_deg_max": self.fov_deg_max,
            "distance_m_min": self.pose.distance_m_min,
            "distance_m_max": self.pose.distance_m_max,
            "checksum": self.checksum,
        }


@dataclass(frozen=True)
class ResolvedCamera:
    """Everything needed to place a camera and to reproduce the shot later."""

    preset_id: str
    preset_version: str
    focal_length_mm: float
    sensor_width_mm: float
    sensor_height_mm: float
    sensor_fit: str
    blender_angle_deg: float
    resolution_x: int
    resolution_y: int
    target_m: tuple[float, float, float]
    azimuth_deg: float
    elevation_deg: float
    roll_deg: float
    distance_m: float
    location_m: tuple[float, float, float]
    exposure_ev: float
    iso: int
    shutter_speed_s: float
    distortion: DistortionCoefficients
    chromatic_aberration_px: float
    jpeg_quality: int
    motion_blur_enabled: bool
    motion_blur_shutter: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "preset_id": self.preset_id,
            "preset_version": self.preset_version,
            "focal_length_mm": round(self.focal_length_mm, 6),
            "sensor_width_mm": self.sensor_width_mm,
            "sensor_height_mm": self.sensor_height_mm,
            "sensor_fit": self.sensor_fit,
            "blender_angle_deg": round(self.blender_angle_deg, 6),
            "resolution_x": self.resolution_x,
            "resolution_y": self.resolution_y,
            "target_m": [round(v, 6) for v in self.target_m],
            "azimuth_deg": round(self.azimuth_deg, 6),
            "elevation_deg": round(self.elevation_deg, 6),
            "roll_deg": round(self.roll_deg, 6),
            "distance_m": round(self.distance_m, 6),
            "location_m": [round(v, 6) for v in self.location_m],
            "exposure_ev": round(self.exposure_ev, 6),
            "iso": self.iso,
            "shutter_speed_s": self.shutter_speed_s,
            "distortion": self.distortion.as_dict(),
            "chromatic_aberration_px": self.chromatic_aberration_px,
            "jpeg_quality": self.jpeg_quality,
            "motion_blur_enabled": self.motion_blur_enabled,
            "motion_blur_shutter": round(self.motion_blur_shutter, 6),
        }


def spherical_to_cartesian(
    target: tuple[float, float, float], azimuth_deg: float, elevation_deg: float, distance_m: float
) -> tuple[float, float, float]:
    """Convert an orbit pose into a world location. Z is up, matching Blender."""
    azimuth = math.radians(azimuth_deg)
    elevation = math.radians(elevation_deg)
    horizontal = distance_m * math.cos(elevation)
    return (
        target[0] + horizontal * math.cos(azimuth),
        target[1] + horizontal * math.sin(azimuth),
        target[2] + distance_m * math.sin(elevation),
    )


def cartesian_to_spherical(
    target: tuple[float, float, float], location: tuple[float, float, float]
) -> tuple[float, float, float]:
    """Recover azimuth, elevation, and distance. Inverse of the above."""
    dx = location[0] - target[0]
    dy = location[1] - target[1]
    dz = location[2] - target[2]
    distance = math.sqrt(dx * dx + dy * dy + dz * dz)
    if distance < 1e-9:
        return (0.0, 0.0, 0.0)
    azimuth = math.degrees(math.atan2(dy, dx))
    elevation = math.degrees(math.asin(max(-1.0, min(1.0, dz / distance))))
    return (azimuth, elevation, distance)


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

GENERIC_SQUARE_1024_V1 = CameraSensorPreset(
    id="GENERIC_SQUARE_1024_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Generic square 1024 (compatibility)",
    summary=(
        "Square-format virtual camera on a 36 mm sensor with a customer-selectable field "
        "of view. Reproduces the framing of pre-v2 jobs, now with the corrected focal "
        "length relation."
    ),
    sensor_width_mm=36.0,
    sensor_height_mm=36.0,
    focal_length_mm=focal_length_mm_from_fov(45.0, 36.0),
    sensor_fit="AUTO",
    fov_convention=HORIZONTAL,
    resolution_x=1024,
    resolution_y=1024,
    pose=PoseRange(distance_m_min=3.0, distance_m_max=40.0,
                   elevation_deg_min=-25.0, elevation_deg_max=25.0),
    feature_flag="camera_generic_square_1024_v1",
    fov_is_customer_selectable=True,
    fov_deg_min=20.0,
    fov_deg_max=90.0,
    iso_min=100,
    iso_max=200,
    read_noise_sigma=0.0015,
    shot_noise_scale=0.006,
    notes=(
        "The legacy renderer used focal = 36 / tan(fov/2), which halved the actual field "
        "of view. This preset uses focal = 18 / tan(fov/2) for a 36 mm sensor."
    ),
)

DRONE_WIDE_20MP_V1 = CameraSensorPreset(
    id="DRONE_WIDE_20MP_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Drone wide 20 MP (4/3 inch)",
    summary=(
        "Wide survey camera typical of a 4/3-inch 20 MP inspection drone payload. Used for "
        "whole-blade sweeps where the defect occupies a small part of the frame."
    ),
    sensor_width_mm=17.3,
    sensor_height_mm=13.0,
    focal_length_mm=12.29,
    sensor_fit="HORIZONTAL",
    fov_convention=HORIZONTAL,
    resolution_x=5280,
    resolution_y=3956,
    pose=PoseRange(distance_m_min=4.0, distance_m_max=60.0,
                   elevation_deg_min=-40.0, elevation_deg_max=40.0),
    feature_flag="camera_drone_wide_20mp_v1",
    distortion=DistortionCoefficients(k1=-0.052, k2=0.0135, k3=-0.0021, p1=0.0004, p2=-0.0003),
    exposure_ev_min=-1.3,
    exposure_ev_max=1.3,
    shutter_speed_s=1.0 / 800.0,
    iso_min=100,
    iso_max=800,
    read_noise_sigma=0.0030,
    shot_noise_scale=0.012,
    chromatic_aberration_px=0.45,
    jpeg_quality=90,
)

DRONE_TELE_12MP_V1 = CameraSensorPreset(
    id="DRONE_TELE_12MP_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Drone telephoto 12 MP (1/2 inch)",
    summary=(
        "Standard-angle 1/2-inch payload used at moderate standoff. A reasonable default "
        "for defect-level detail on a full-span blade."
    ),
    sensor_width_mm=6.4,
    sensor_height_mm=4.8,
    focal_length_mm=12.7,
    sensor_fit="HORIZONTAL",
    fov_convention=HORIZONTAL,
    resolution_x=4000,
    resolution_y=3000,
    pose=PoseRange(distance_m_min=2.5, distance_m_max=35.0,
                   elevation_deg_min=-35.0, elevation_deg_max=35.0),
    feature_flag="camera_drone_tele_12mp_v1",
    distortion=DistortionCoefficients(k1=-0.028, k2=0.0061, p1=0.0002, p2=0.0002),
    exposure_ev_min=-1.0,
    exposure_ev_max=1.0,
    shutter_speed_s=1.0 / 1000.0,
    iso_min=100,
    iso_max=1600,
    read_noise_sigma=0.0042,
    shot_noise_scale=0.018,
    chromatic_aberration_px=0.30,
    jpeg_quality=92,
)

DRONE_ZOOM_INSPECTION_V1 = CameraSensorPreset(
    id="DRONE_ZOOM_INSPECTION_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Drone zoom inspection (long standoff)",
    summary=(
        "Long-focal inspection camera flown at a safe standoff. Narrow field of view, "
        "shallow perspective, and low geometric distortion."
    ),
    sensor_width_mm=6.4,
    sensor_height_mm=4.8,
    focal_length_mm=56.0,
    sensor_fit="HORIZONTAL",
    fov_convention=HORIZONTAL,
    resolution_x=1920,
    resolution_y=1440,
    pose=PoseRange(distance_m_min=12.0, distance_m_max=120.0,
                   elevation_deg_min=-30.0, elevation_deg_max=30.0),
    feature_flag="camera_drone_zoom_inspection_v1",
    distortion=DistortionCoefficients(k1=-0.006, k2=0.0009),
    exposure_ev_min=-0.8,
    exposure_ev_max=0.8,
    shutter_speed_s=1.0 / 1600.0,
    iso_min=100,
    iso_max=3200,
    read_noise_sigma=0.0050,
    shot_noise_scale=0.022,
    chromatic_aberration_px=0.18,
    jpeg_quality=94,
)

HANDHELD_FULLFRAME_V1 = CameraSensorPreset(
    id="HANDHELD_FULLFRAME_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Handheld full-frame reference",
    summary=(
        "Ground or platform-based full-frame reference camera. Used for close-range "
        "verification imagery and for calibration comparisons."
    ),
    sensor_width_mm=36.0,
    sensor_height_mm=24.0,
    focal_length_mm=50.0,
    sensor_fit="HORIZONTAL",
    fov_convention=HORIZONTAL,
    resolution_x=6000,
    resolution_y=4000,
    pose=PoseRange(distance_m_min=0.5, distance_m_max=25.0,
                   elevation_deg_min=-45.0, elevation_deg_max=45.0),
    feature_flag="camera_handheld_fullframe_v1",
    distortion=DistortionCoefficients(k1=-0.012, k2=0.0022),
    exposure_ev_min=-1.5,
    exposure_ev_max=1.5,
    shutter_speed_s=1.0 / 250.0,
    iso_min=100,
    iso_max=6400,
    read_noise_sigma=0.0020,
    shot_noise_scale=0.009,
    chromatic_aberration_px=0.22,
    jpeg_quality=96,
)

ALL_CAMERA_PRESETS: tuple[CameraSensorPreset, ...] = (
    GENERIC_SQUARE_1024_V1,
    DRONE_WIDE_20MP_V1,
    DRONE_TELE_12MP_V1,
    DRONE_ZOOM_INSPECTION_V1,
    HANDHELD_FULLFRAME_V1,
)

DEFAULT_CAMERA_PRESET_ID = DRONE_TELE_12MP_V1.id
LEGACY_CAMERA_PRESET_ID = GENERIC_SQUARE_1024_V1.id

_BY_ID = {preset.id: preset for preset in ALL_CAMERA_PRESETS}
_BY_REFERENCE = {f"{p.id}@{p.version}": p for p in ALL_CAMERA_PRESETS}


def get_camera_preset(reference: str) -> CameraSensorPreset:
    key = reference.strip()
    if "@" in key:
        try:
            return _BY_REFERENCE[key]
        except KeyError as exc:
            raise RegistryLookupError(f"Unknown camera preset version {reference!r}") from exc
    try:
        return _BY_ID[key]
    except KeyError as exc:
        raise RegistryLookupError(f"Unknown camera preset {reference!r}") from exc


def list_camera_presets() -> tuple[CameraSensorPreset, ...]:
    return tuple(p for p in ALL_CAMERA_PRESETS if p.is_selectable)


def registry_checksum() -> str:
    return checksum([preset.as_dict() for preset in ALL_CAMERA_PRESETS])


@dataclass(frozen=True)
class CameraViewRequest:
    """A camera view saved from the browser, before validation.

    The browser never gets to hand the renderer a raw transformation matrix. It sends
    an orbit description, which the backend clamps into the preset's safe envelope.
    """

    target_m: tuple[float, float, float]
    azimuth_deg: float
    elevation_deg: float
    distance_m: float
    roll_deg: float = 0.0
    fov_deg: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_m": list(self.target_m),
            "azimuth_deg": self.azimuth_deg,
            "elevation_deg": self.elevation_deg,
            "distance_m": self.distance_m,
            "roll_deg": self.roll_deg,
            "fov_deg": self.fov_deg,
        }


def validate_camera_view(
    preset: CameraSensorPreset,
    view: CameraViewRequest,
    *,
    target_bounds_m: float = 200.0,
) -> CameraViewRequest:
    """Clamp and sanity-check a browser-supplied view against the preset envelope."""
    for axis, value in zip("xyz", view.target_m, strict=True):
        if not math.isfinite(value) or abs(value) > target_bounds_m:
            raise ParameterValidationError(
                f"Camera target {axis}={value} is not a finite value inside "
                f"+/-{target_bounds_m} m."
            )
    for name, value in (
        ("azimuth_deg", view.azimuth_deg),
        ("elevation_deg", view.elevation_deg),
        ("distance_m", view.distance_m),
        ("roll_deg", view.roll_deg),
    ):
        if not math.isfinite(value):
            raise ParameterValidationError(f"Camera {name} must be a finite number.")
    distance, azimuth, elevation, roll = preset.pose.clamp(
        distance_m=view.distance_m,
        azimuth_deg=((view.azimuth_deg + 180.0) % 360.0) - 180.0,
        elevation_deg=view.elevation_deg,
        roll_deg=view.roll_deg,
    )
    fov = view.fov_deg
    if fov is not None:
        if not preset.fov_is_customer_selectable:
            fov = None
        else:
            fov = min(max(fov, preset.fov_deg_min), preset.fov_deg_max)
    return CameraViewRequest(
        target_m=(view.target_m[0], view.target_m[1], view.target_m[2]),
        azimuth_deg=azimuth,
        elevation_deg=elevation,
        distance_m=distance,
        roll_deg=roll,
        fov_deg=fov,
    )


def resolve_camera(
    preset: CameraSensorPreset,
    rng: random.Random,
    *,
    target_m: tuple[float, float, float] = (0.0, 0.0, 0.0),
    view: CameraViewRequest | None = None,
    distance_m_range: tuple[float, float] | None = None,
    azimuth_deg_range: tuple[float, float] | None = None,
    elevation_deg_range: tuple[float, float] | None = None,
    requested_fov_deg: float | None = None,
    exposure_ev_offset: float = 0.0,
    iso_scale: float = 1.0,
    camera_stability: float = 1.0,
    motion_blur_enabled: bool = False,
    motion_blur_shutter: float = 0.5,
    resolution: tuple[int, int] | None = None,
) -> ResolvedCamera:
    """Produce a fully specified camera for one sample.

    A saved ``view`` pins the pose exactly. Otherwise the pose is sampled from the
    requested ranges, clamped into the preset's safe envelope.
    ``camera_stability`` below 1 adds bounded pose jitter, which is how wind and
    storm presets destabilise the shot.
    """
    if view is not None:
        validated = validate_camera_view(preset, view)
        target = validated.target_m
        azimuth = validated.azimuth_deg
        elevation = validated.elevation_deg
        distance = validated.distance_m
        roll = validated.roll_deg
        fov = validated.fov_deg if validated.fov_deg is not None else requested_fov_deg
    else:
        low_d, high_d = distance_m_range or (preset.pose.distance_m_min, preset.pose.distance_m_max)
        low_a, high_a = azimuth_deg_range or (
            preset.pose.azimuth_deg_min, preset.pose.azimuth_deg_max
        )
        low_e, high_e = elevation_deg_range or (
            preset.pose.elevation_deg_min, preset.pose.elevation_deg_max
        )
        distance, azimuth, elevation, roll = preset.pose.clamp(
            distance_m=rng.uniform(low_d, high_d),
            azimuth_deg=rng.uniform(low_a, high_a),
            elevation_deg=rng.uniform(low_e, high_e),
            roll_deg=0.0,
        )
        target = target_m
        fov = requested_fov_deg

    instability = max(0.0, 1.0 - max(0.0, min(1.0, camera_stability)))
    if instability > 0.0:
        azimuth += rng.uniform(-4.0, 4.0) * instability
        elevation += rng.uniform(-3.0, 3.0) * instability
        distance *= 1.0 + rng.uniform(-0.05, 0.05) * instability
        roll += rng.uniform(-5.0, 5.0) * instability
        distance, azimuth, elevation, roll = preset.pose.clamp(
            distance_m=distance, azimuth_deg=azimuth, elevation_deg=elevation, roll_deg=roll
        )

    focal = (
        preset.focal_length_for_requested_fov(fov)
        if fov is not None and preset.fov_is_customer_selectable
        else preset.focal_length_mm
    )
    resolution_x, resolution_y = resolution or (preset.resolution_x, preset.resolution_y)
    exposure = min(
        max(
            rng.uniform(preset.exposure_ev_min, preset.exposure_ev_max) + exposure_ev_offset,
            preset.exposure_ev_min - 3.0,
        ),
        preset.exposure_ev_max + 6.0,
    )
    iso = int(
        min(
            max(round(rng.uniform(preset.iso_min, preset.iso_max) * max(0.05, iso_scale)), 50),
            25600,
        )
    )
    return ResolvedCamera(
        preset_id=preset.id,
        preset_version=preset.version,
        focal_length_mm=focal,
        sensor_width_mm=preset.sensor_width_mm,
        sensor_height_mm=preset.sensor_height_mm,
        sensor_fit=preset.sensor_fit,
        blender_angle_deg=preset.blender_angle_deg(focal),
        resolution_x=resolution_x,
        resolution_y=resolution_y,
        target_m=(target[0], target[1], target[2]),
        azimuth_deg=azimuth,
        elevation_deg=elevation,
        roll_deg=roll,
        distance_m=distance,
        location_m=spherical_to_cartesian(target, azimuth, elevation, distance),
        exposure_ev=exposure,
        iso=iso,
        shutter_speed_s=preset.shutter_speed_s,
        distortion=preset.distortion,
        chromatic_aberration_px=preset.chromatic_aberration_px,
        jpeg_quality=preset.jpeg_quality,
        motion_blur_enabled=motion_blur_enabled,
        motion_blur_shutter=motion_blur_shutter,
    )
