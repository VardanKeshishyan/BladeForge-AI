"""Environment and weather registry.

Every preset carries a stable id, a semantic version, a checksum, an authorship or
license record, allowed randomization ranges, and a renderer implementation key.
Presets are not labels: :func:`resolve_environment` turns one into a flat dictionary
of concrete physical numbers that drive the Blender world, sun, sky, volumetrics,
particles, blade material response, camera stability, and sensor model.

``tests/test_environment_differences.py`` proves that every pair of presets resolves
to a materially different configuration, and that the same preset with the same seed
resolves identically.

Customer-facing control surface
-------------------------------
A customer picks a preset and one ``intensity`` value in 0..1. Every technical
parameter stays inside the preset's validated bounds. Advanced API customers may
supply a structured ``WeatherOverride``, which is clamped to the same bounds.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .errors import ParameterValidationError, RegistryLookupError
from .severity import BandRange as Range
from .versioning import (
    INTERNAL_AUTHORSHIP,
    LicenseRecord,
    ReleaseStatus,
    SemanticVersion,
    checksum,
    validate_registry_id,
)

# Sky implementations available in the v2 renderer.
SKY_NISHITA = "nishita_physical_sky"
SKY_OVERCAST_DOME = "gradient_overcast_dome"
SKY_BROKEN_CLOUD = "broken_cloud_dome"
SKY_NIGHT = "procedural_night_sky"
SKY_HDRI = "hdri_environment"

VIEW_TRANSFORM_AGX = "AgX"
VIEW_TRANSFORM_FILMIC = "Filmic"
VIEW_TRANSFORM_STANDARD = "Standard"


@dataclass(frozen=True)
class WeatherRanges:
    """The randomization envelope for one environment's weather behaviour.

    Units: ``precipitation_rate_mm_h`` millimetres per hour, ``droplet_size_mm``
    millimetres, angles degrees, ``wind_speed_ms`` metres per second,
    ``visibility_m`` metres, everything else a 0..1 fraction.
    """

    cloud_cover: Range
    precipitation_rate_mm_h: Range
    droplet_size_mm: Range
    rain_direction_deg: Range
    rain_incline_deg: Range
    wetness: Range
    haze_density: Range
    wind_speed_ms: Range
    wind_direction_deg: Range
    camera_stability: Range
    lightning_flash_probability: Range
    flash_intensity: Range
    visibility_m: Range
    surface_roughness_delta: Range
    motion_blur_shutter: Range
    sensor_noise_iso_scale: Range
    # Fraction of the surface showing standing water, streaks, or clinging droplets.
    puddling: Range = field(default_factory=lambda: Range(0.0, 0.0))
    residual_droplet_density: Range = field(default_factory=lambda: Range(0.0, 0.0))

    def field_names(self) -> tuple[str, ...]:
        return (
            "cloud_cover",
            "precipitation_rate_mm_h",
            "droplet_size_mm",
            "rain_direction_deg",
            "rain_incline_deg",
            "wetness",
            "haze_density",
            "wind_speed_ms",
            "wind_direction_deg",
            "camera_stability",
            "lightning_flash_probability",
            "flash_intensity",
            "visibility_m",
            "surface_roughness_delta",
            "motion_blur_shutter",
            "sensor_noise_iso_scale",
            "puddling",
            "residual_droplet_density",
        )

    def as_dict(self) -> dict[str, dict[str, float]]:
        return {name: getattr(self, name).as_dict() for name in self.field_names()}

    def clamp(self, name: str, value: float) -> float:
        band: Range = getattr(self, name)
        if not band.minimum <= value <= band.maximum:
            raise ParameterValidationError(
                f"Weather parameter {name}={value} is outside the preset's validated range "
                f"{band.minimum}-{band.maximum}."
            )
        return value


def _range(minimum: float, maximum: float) -> Range:
    return Range(float(minimum), float(maximum))


DRY_STILL_WEATHER = WeatherRanges(
    cloud_cover=_range(0.0, 0.15),
    precipitation_rate_mm_h=_range(0.0, 0.0),
    droplet_size_mm=_range(0.0, 0.0),
    rain_direction_deg=_range(0.0, 360.0),
    rain_incline_deg=_range(0.0, 0.0),
    wetness=_range(0.0, 0.0),
    haze_density=_range(0.0, 0.02),
    wind_speed_ms=_range(0.5, 6.0),
    wind_direction_deg=_range(0.0, 360.0),
    camera_stability=_range(0.92, 1.0),
    lightning_flash_probability=_range(0.0, 0.0),
    flash_intensity=_range(0.0, 0.0),
    visibility_m=_range(25000.0, 60000.0),
    surface_roughness_delta=_range(0.0, 0.02),
    motion_blur_shutter=_range(0.0, 0.15),
    sensor_noise_iso_scale=_range(0.9, 1.2),
)


@dataclass(frozen=True)
class ArtificialLighting:
    """Navigation or drone-mounted lighting, used mainly by the night preset."""

    enabled: bool = False
    probability: float = 0.0
    strength_w: Range = field(default_factory=lambda: Range(0.0, 0.0))
    color_temperature_k: Range = field(default_factory=lambda: Range(5000.0, 5600.0))
    beam_angle_deg: Range = field(default_factory=lambda: Range(30.0, 60.0))
    mount: str = "none"

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "probability": self.probability,
            "strength_w": self.strength_w.as_dict(),
            "color_temperature_k": self.color_temperature_k.as_dict(),
            "beam_angle_deg": self.beam_angle_deg.as_dict(),
            "mount": self.mount,
        }


@dataclass(frozen=True)
class EnvironmentVersion:
    id: str
    version: str
    status: str
    title: str
    summary: str
    renderer_key: str
    sky_model: str
    sun_elevation_deg: Range
    sun_azimuth_deg: Range
    # Angular diameter of the light source. 0.526 is the real solar disc; larger
    # values are how an overcast sky produces genuinely soft shadows.
    sun_angular_diameter_deg: Range
    sun_strength_w: Range
    sun_color_temperature_k: Range
    sky_turbidity: Range
    world_strength: Range
    ambient_color_temperature_k: Range
    exposure_ev: Range
    view_transform: str
    weather: WeatherRanges
    feature_flag: str
    # Non-uniform sky brightness, which is what makes broken cloud read as broken.
    sky_nonuniformity: Range = field(default_factory=lambda: Range(0.0, 0.05))
    volumetric_enabled: bool = False
    volumetric_anisotropy: Range = field(default_factory=lambda: Range(0.0, 0.0))
    # Multiplier on chroma. Night vision and heavy haze both desaturate.
    color_response_scale: Range = field(default_factory=lambda: Range(1.0, 1.0))
    # Atmospheric perspective: how strongly distant geometry washes toward the sky.
    distance_fade_strength: Range = field(default_factory=lambda: Range(0.0, 0.02))
    artificial_lighting: ArtificialLighting = field(default_factory=ArtificialLighting)
    is_night: bool = False
    is_wet: bool = False
    has_active_precipitation: bool = False
    # Night renders must actually be dark. The validator checks mean luminance
    # against this ceiling so a night preset cannot be a dimmed daylight render.
    max_mean_luminance: float | None = None
    min_mean_luminance: float | None = None
    hdri_asset_id: str | None = None
    preview_path: str | None = None
    license: LicenseRecord = INTERNAL_AUTHORSHIP
    notes: str = ""

    def __post_init__(self) -> None:
        validate_registry_id(self.id)
        SemanticVersion.parse(self.version)
        if self.status not in ReleaseStatus.ALL:
            raise ValueError(f"Unknown release status {self.status!r}")
        if self.sky_model not in {
            SKY_NISHITA, SKY_OVERCAST_DOME, SKY_BROKEN_CLOUD, SKY_NIGHT, SKY_HDRI
        }:
            raise ValueError(f"{self.id}: unknown sky model {self.sky_model!r}")
        if self.view_transform not in {
            VIEW_TRANSFORM_AGX, VIEW_TRANSFORM_FILMIC, VIEW_TRANSFORM_STANDARD
        }:
            raise ValueError(f"{self.id}: unknown view transform {self.view_transform!r}")
        if self.sky_model == SKY_HDRI and not self.hdri_asset_id:
            raise ValueError(f"{self.id}: an HDRI sky needs hdri_asset_id.")
        if self.has_active_precipitation and self.weather.precipitation_rate_mm_h.maximum <= 0:
            raise ValueError(f"{self.id}: declares precipitation but its rate range is zero.")
        if self.is_wet and self.weather.wetness.maximum <= 0:
            raise ValueError(f"{self.id}: declares wetness but its wetness range is zero.")

    @property
    def is_selectable(self) -> bool:
        return self.status == ReleaseStatus.RELEASED

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "status": self.status,
            "title": self.title,
            "summary": self.summary,
            "renderer_key": self.renderer_key,
            "sky_model": self.sky_model,
            "sun_elevation_deg": self.sun_elevation_deg.as_dict(),
            "sun_azimuth_deg": self.sun_azimuth_deg.as_dict(),
            "sun_angular_diameter_deg": self.sun_angular_diameter_deg.as_dict(),
            "sun_strength_w": self.sun_strength_w.as_dict(),
            "sun_color_temperature_k": self.sun_color_temperature_k.as_dict(),
            "sky_turbidity": self.sky_turbidity.as_dict(),
            "world_strength": self.world_strength.as_dict(),
            "ambient_color_temperature_k": self.ambient_color_temperature_k.as_dict(),
            "exposure_ev": self.exposure_ev.as_dict(),
            "view_transform": self.view_transform,
            "sky_nonuniformity": self.sky_nonuniformity.as_dict(),
            "volumetric_enabled": self.volumetric_enabled,
            "volumetric_anisotropy": self.volumetric_anisotropy.as_dict(),
            "color_response_scale": self.color_response_scale.as_dict(),
            "distance_fade_strength": self.distance_fade_strength.as_dict(),
            "artificial_lighting": self.artificial_lighting.as_dict(),
            "is_night": self.is_night,
            "is_wet": self.is_wet,
            "has_active_precipitation": self.has_active_precipitation,
            "max_mean_luminance": self.max_mean_luminance,
            "min_mean_luminance": self.min_mean_luminance,
            "hdri_asset_id": self.hdri_asset_id,
            "preview_path": self.preview_path,
            "weather": self.weather.as_dict(),
            "feature_flag": self.feature_flag,
            "license": self.license.as_dict(),
            "notes": self.notes,
        }

    @property
    def checksum(self) -> str:
        return checksum(self.as_dict())

    def public_summary(self) -> dict[str, Any]:
        """What the customer sees: a name, a description, and an intensity slider."""
        return {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "summary": self.summary,
            "is_night": self.is_night,
            "is_wet": self.is_wet,
            "has_active_precipitation": self.has_active_precipitation,
            "supports_intensity": True,
            "preview_path": self.preview_path,
            "checksum": self.checksum,
        }


# ---------------------------------------------------------------------------
# The nine shipped presets
# ---------------------------------------------------------------------------

CLEAR_DAY_V1 = EnvironmentVersion(
    id="CLEAR_DAY_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Clear day",
    summary=(
        "High sun, clean sky, strong directional shadows, and crisp specular highlights "
        "on intact gelcoat."
    ),
    renderer_key="env_clear_day_v1",
    sky_model=SKY_NISHITA,
    sun_elevation_deg=_range(35.0, 70.0),
    sun_azimuth_deg=_range(0.0, 360.0),
    sun_angular_diameter_deg=_range(0.526, 0.60),
    sun_strength_w=_range(900.0, 1150.0),
    sun_color_temperature_k=_range(5400.0, 6100.0),
    sky_turbidity=_range(1.8, 3.0),
    world_strength=_range(0.90, 1.25),
    ambient_color_temperature_k=_range(9000.0, 12000.0),
    exposure_ev=_range(-0.30, 0.40),
    view_transform=VIEW_TRANSFORM_AGX,
    weather=DRY_STILL_WEATHER,
    feature_flag="environment_clear_day_v1",
    min_mean_luminance=0.16,
    preview_path="environment-assets/CLEAR_DAY_V1/1.0.0/preview.jpg",
    notes="Sharp shadow terminators make erosion depth and crack openings most readable.",
)

OVERCAST_DAY_V1 = EnvironmentVersion(
    id="OVERCAST_DAY_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Overcast day",
    summary=(
        "A bright, fully clouded sky acting as one large area light. Low contrast, very "
        "soft shadows, and almost no directional modelling."
    ),
    renderer_key="env_overcast_day_v1",
    sky_model=SKY_OVERCAST_DOME,
    sun_elevation_deg=_range(25.0, 60.0),
    sun_azimuth_deg=_range(0.0, 360.0),
    # A 25-60 degree source is what actually produces soft shadows, rather than
    # simply lowering the sun's intensity.
    sun_angular_diameter_deg=_range(25.0, 60.0),
    sun_strength_w=_range(90.0, 180.0),
    sun_color_temperature_k=_range(6200.0, 7000.0),
    sky_turbidity=_range(6.0, 9.0),
    world_strength=_range(2.20, 3.20),
    ambient_color_temperature_k=_range(6400.0, 7600.0),
    exposure_ev=_range(-0.20, 0.30),
    view_transform=VIEW_TRANSFORM_AGX,
    weather=WeatherRanges(
        cloud_cover=_range(0.88, 1.00),
        precipitation_rate_mm_h=_range(0.0, 0.0),
        droplet_size_mm=_range(0.0, 0.0),
        rain_direction_deg=_range(0.0, 360.0),
        rain_incline_deg=_range(0.0, 0.0),
        wetness=_range(0.0, 0.05),
        haze_density=_range(0.05, 0.12),
        wind_speed_ms=_range(2.0, 10.0),
        wind_direction_deg=_range(0.0, 360.0),
        camera_stability=_range(0.90, 1.0),
        lightning_flash_probability=_range(0.0, 0.0),
        flash_intensity=_range(0.0, 0.0),
        visibility_m=_range(8000.0, 20000.0),
        surface_roughness_delta=_range(-0.02, 0.02),
        motion_blur_shutter=_range(0.0, 0.20),
        sensor_noise_iso_scale=_range(1.0, 1.5),
    ),
    feature_flag="environment_overcast_day_v1",
    min_mean_luminance=0.18,
    preview_path="environment-assets/OVERCAST_DAY_V1/1.0.0/preview.jpg",
    notes="The most common real inspection condition. Hardest for depth cues.",
)

CLOUDY_DAY_V1 = EnvironmentVersion(
    id="CLOUDY_DAY_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Cloudy day (broken cloud)",
    summary=(
        "Partial directional sun through broken cloud. Sky brightness varies across the "
        "dome and shadow strength changes between samples."
    ),
    renderer_key="env_cloudy_day_v1",
    sky_model=SKY_BROKEN_CLOUD,
    sun_elevation_deg=_range(25.0, 65.0),
    sun_azimuth_deg=_range(0.0, 360.0),
    sun_angular_diameter_deg=_range(3.0, 12.0),
    sun_strength_w=_range(350.0, 700.0),
    sun_color_temperature_k=_range(5800.0, 6600.0),
    sky_turbidity=_range(3.5, 6.0),
    world_strength=_range(1.40, 2.20),
    ambient_color_temperature_k=_range(7000.0, 9500.0),
    exposure_ev=_range(-0.35, 0.35),
    view_transform=VIEW_TRANSFORM_AGX,
    sky_nonuniformity=_range(0.30, 0.70),
    weather=WeatherRanges(
        cloud_cover=_range(0.40, 0.80),
        precipitation_rate_mm_h=_range(0.0, 0.0),
        droplet_size_mm=_range(0.0, 0.0),
        rain_direction_deg=_range(0.0, 360.0),
        rain_incline_deg=_range(0.0, 0.0),
        wetness=_range(0.0, 0.10),
        haze_density=_range(0.03, 0.08),
        wind_speed_ms=_range(3.0, 12.0),
        wind_direction_deg=_range(0.0, 360.0),
        camera_stability=_range(0.86, 0.99),
        lightning_flash_probability=_range(0.0, 0.0),
        flash_intensity=_range(0.0, 0.0),
        visibility_m=_range(12000.0, 35000.0),
        surface_roughness_delta=_range(-0.03, 0.02),
        motion_blur_shutter=_range(0.0, 0.25),
        sensor_noise_iso_scale=_range(1.0, 1.6),
    ),
    feature_flag="environment_cloudy_day_v1",
    min_mean_luminance=0.14,
    preview_path="environment-assets/CLOUDY_DAY_V1/1.0.0/preview.jpg",
)

GOLDEN_HOUR_V1 = EnvironmentVersion(
    id="GOLDEN_HOUR_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Golden hour",
    summary=(
        "Low warm sun with long raking shadows against a cooler ambient sky. Grazing "
        "light exaggerates surface relief, which changes how erosion and delamination read."
    ),
    renderer_key="env_golden_hour_v1",
    sky_model=SKY_NISHITA,
    sun_elevation_deg=_range(2.0, 12.0),
    sun_azimuth_deg=_range(0.0, 360.0),
    sun_angular_diameter_deg=_range(0.60, 1.50),
    sun_strength_w=_range(420.0, 720.0),
    sun_color_temperature_k=_range(2400.0, 3200.0),
    sky_turbidity=_range(3.5, 7.0),
    world_strength=_range(0.50, 0.90),
    ambient_color_temperature_k=_range(7500.0, 11000.0),
    exposure_ev=_range(-0.60, 0.20),
    view_transform=VIEW_TRANSFORM_AGX,
    weather=WeatherRanges(
        cloud_cover=_range(0.10, 0.45),
        precipitation_rate_mm_h=_range(0.0, 0.0),
        droplet_size_mm=_range(0.0, 0.0),
        rain_direction_deg=_range(0.0, 360.0),
        rain_incline_deg=_range(0.0, 0.0),
        wetness=_range(0.0, 0.05),
        haze_density=_range(0.04, 0.12),
        wind_speed_ms=_range(1.0, 7.0),
        wind_direction_deg=_range(0.0, 360.0),
        camera_stability=_range(0.90, 1.0),
        lightning_flash_probability=_range(0.0, 0.0),
        flash_intensity=_range(0.0, 0.0),
        visibility_m=_range(15000.0, 40000.0),
        surface_roughness_delta=_range(0.0, 0.02),
        motion_blur_shutter=_range(0.0, 0.20),
        sensor_noise_iso_scale=_range(1.1, 1.8),
    ),
    feature_flag="environment_golden_hour_v1",
    min_mean_luminance=0.10,
    preview_path="environment-assets/GOLDEN_HOUR_V1/1.0.0/preview.jpg",
)

NIGHT_MOONLIT_V1 = EnvironmentVersion(
    id="NIGHT_MOONLIT_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Night, moonlit",
    summary=(
        "A genuinely dark scene: a physically low-intensity moon, a dark sky, long "
        "exposure with high-ISO grain, reduced colour response, and optional navigation "
        "or drone lighting."
    ),
    renderer_key="env_night_moonlit_v1",
    sky_model=SKY_NIGHT,
    sun_elevation_deg=_range(12.0, 58.0),
    sun_azimuth_deg=_range(0.0, 360.0),
    sun_angular_diameter_deg=_range(0.50, 0.58),
    # Moonlight is roughly six orders of magnitude below direct sun. Modelling that
    # honestly and then raising exposure is what distinguishes night from a dimmed day.
    sun_strength_w=_range(0.0015, 0.0120),
    sun_color_temperature_k=_range(4000.0, 4800.0),
    sky_turbidity=_range(1.5, 4.0),
    world_strength=_range(0.0040, 0.0200),
    ambient_color_temperature_k=_range(8000.0, 14000.0),
    exposure_ev=_range(3.00, 5.50),
    view_transform=VIEW_TRANSFORM_AGX,
    color_response_scale=_range(0.45, 0.70),
    weather=WeatherRanges(
        cloud_cover=_range(0.10, 0.60),
        precipitation_rate_mm_h=_range(0.0, 0.0),
        droplet_size_mm=_range(0.0, 0.0),
        rain_direction_deg=_range(0.0, 360.0),
        rain_incline_deg=_range(0.0, 0.0),
        wetness=_range(0.0, 0.15),
        haze_density=_range(0.02, 0.10),
        wind_speed_ms=_range(0.5, 9.0),
        wind_direction_deg=_range(0.0, 360.0),
        camera_stability=_range(0.70, 0.94),
        lightning_flash_probability=_range(0.0, 0.0),
        flash_intensity=_range(0.0, 0.0),
        visibility_m=_range(5000.0, 20000.0),
        surface_roughness_delta=_range(0.0, 0.03),
        motion_blur_shutter=_range(0.10, 0.60),
        sensor_noise_iso_scale=_range(8.0, 24.0),
    ),
    feature_flag="environment_night_moonlit_v1",
    artificial_lighting=ArtificialLighting(
        enabled=True,
        probability=0.55,
        strength_w=_range(8.0, 90.0),
        color_temperature_k=_range(4600.0, 6500.0),
        beam_angle_deg=_range(25.0, 70.0),
        mount="drone_forward",
    ),
    is_night=True,
    max_mean_luminance=0.30,
    preview_path="environment-assets/NIGHT_MOONLIT_V1/1.0.0/preview.jpg",
    notes=(
        "Validation rejects a night sample whose mean luminance exceeds the ceiling, which "
        "is what stops this preset degenerating into a darkened daylight render."
    ),
)

OFFSHORE_HAZE_V1 = EnvironmentVersion(
    id="OFFSHORE_HAZE_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Offshore haze",
    summary=(
        "Marine haze with real volumetric scattering: reduced contrast, atmospheric "
        "perspective, a cool colour shift, and visibility that falls off with distance."
    ),
    renderer_key="env_offshore_haze_v1",
    sky_model=SKY_NISHITA,
    sun_elevation_deg=_range(15.0, 55.0),
    sun_azimuth_deg=_range(0.0, 360.0),
    sun_angular_diameter_deg=_range(2.0, 9.0),
    sun_strength_w=_range(500.0, 820.0),
    sun_color_temperature_k=_range(6000.0, 7200.0),
    sky_turbidity=_range(5.0, 9.0),
    world_strength=_range(1.60, 2.60),
    ambient_color_temperature_k=_range(7200.0, 9800.0),
    exposure_ev=_range(-0.20, 0.45),
    view_transform=VIEW_TRANSFORM_AGX,
    volumetric_enabled=True,
    volumetric_anisotropy=_range(0.55, 0.80),
    color_response_scale=_range(0.70, 0.90),
    distance_fade_strength=_range(0.35, 0.75),
    weather=WeatherRanges(
        cloud_cover=_range(0.20, 0.75),
        precipitation_rate_mm_h=_range(0.0, 0.0),
        droplet_size_mm=_range(0.0, 0.0),
        rain_direction_deg=_range(0.0, 360.0),
        rain_incline_deg=_range(0.0, 0.0),
        wetness=_range(0.05, 0.30),
        haze_density=_range(0.020, 0.080),
        wind_speed_ms=_range(4.0, 16.0),
        wind_direction_deg=_range(0.0, 360.0),
        camera_stability=_range(0.80, 0.96),
        lightning_flash_probability=_range(0.0, 0.0),
        flash_intensity=_range(0.0, 0.0),
        visibility_m=_range(900.0, 4000.0),
        surface_roughness_delta=_range(-0.10, 0.0),
        motion_blur_shutter=_range(0.0, 0.30),
        sensor_noise_iso_scale=_range(1.0, 2.0),
    ),
    feature_flag="environment_offshore_haze_v1",
    is_wet=True,
    preview_path="environment-assets/OFFSHORE_HAZE_V1/1.0.0/preview.jpg",
)

LIGHT_RAIN_WET_V1 = EnvironmentVersion(
    id="LIGHT_RAIN_WET_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Light rain, wet surface",
    summary=(
        "Moderate falling rain with a wetted blade: lower coating roughness, stronger "
        "reflections, visible droplets and streaks, clouded illumination, and mild "
        "camera noise."
    ),
    renderer_key="env_light_rain_wet_v1",
    sky_model=SKY_OVERCAST_DOME,
    sun_elevation_deg=_range(20.0, 55.0),
    sun_azimuth_deg=_range(0.0, 360.0),
    sun_angular_diameter_deg=_range(20.0, 50.0),
    sun_strength_w=_range(120.0, 260.0),
    sun_color_temperature_k=_range(6300.0, 7200.0),
    sky_turbidity=_range(6.5, 9.5),
    world_strength=_range(1.80, 2.60),
    ambient_color_temperature_k=_range(6500.0, 7800.0),
    exposure_ev=_range(-0.10, 0.50),
    view_transform=VIEW_TRANSFORM_AGX,
    volumetric_enabled=True,
    volumetric_anisotropy=_range(0.30, 0.55),
    color_response_scale=_range(0.82, 0.96),
    distance_fade_strength=_range(0.20, 0.45),
    weather=WeatherRanges(
        cloud_cover=_range(0.75, 0.95),
        precipitation_rate_mm_h=_range(1.0, 4.0),
        droplet_size_mm=_range(0.8, 1.6),
        rain_direction_deg=_range(0.0, 360.0),
        rain_incline_deg=_range(5.0, 20.0),
        wetness=_range(0.55, 0.80),
        haze_density=_range(0.060, 0.140),
        wind_speed_ms=_range(3.0, 8.0),
        wind_direction_deg=_range(0.0, 360.0),
        camera_stability=_range(0.82, 0.94),
        lightning_flash_probability=_range(0.0, 0.0),
        flash_intensity=_range(0.0, 0.0),
        visibility_m=_range(4000.0, 12000.0),
        surface_roughness_delta=_range(-0.35, -0.15),
        motion_blur_shutter=_range(0.0, 0.30),
        sensor_noise_iso_scale=_range(1.6, 2.6),
        residual_droplet_density=_range(0.30, 0.70),
    ),
    feature_flag="environment_light_rain_wet_v1",
    is_wet=True,
    has_active_precipitation=True,
    preview_path="environment-assets/LIGHT_RAIN_WET_V1/1.0.0/preview.jpg",
)

HEAVY_RAIN_STORM_V1 = EnvironmentVersion(
    id="HEAVY_RAIN_STORM_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Heavy rain storm",
    summary=(
        "Dense cloud, heavy wind-driven rain, sharply reduced visibility, a saturated wet "
        "surface, an unstable camera, optional motion blur, and occasional lightning "
        "illumination."
    ),
    renderer_key="env_heavy_rain_storm_v1",
    sky_model=SKY_OVERCAST_DOME,
    sun_elevation_deg=_range(12.0, 45.0),
    sun_azimuth_deg=_range(0.0, 360.0),
    sun_angular_diameter_deg=_range(35.0, 75.0),
    sun_strength_w=_range(40.0, 140.0),
    sun_color_temperature_k=_range(6400.0, 7600.0),
    sky_turbidity=_range(8.0, 10.0),
    world_strength=_range(1.20, 2.00),
    ambient_color_temperature_k=_range(6200.0, 7400.0),
    exposure_ev=_range(0.30, 1.40),
    view_transform=VIEW_TRANSFORM_AGX,
    volumetric_enabled=True,
    volumetric_anisotropy=_range(0.25, 0.50),
    color_response_scale=_range(0.62, 0.85),
    distance_fade_strength=_range(0.55, 0.92),
    weather=WeatherRanges(
        cloud_cover=_range(0.96, 1.00),
        precipitation_rate_mm_h=_range(14.0, 60.0),
        droplet_size_mm=_range(1.4, 3.2),
        rain_direction_deg=_range(0.0, 360.0),
        rain_incline_deg=_range(25.0, 55.0),
        wetness=_range(0.85, 1.00),
        haze_density=_range(0.120, 0.300),
        wind_speed_ms=_range(14.0, 28.0),
        wind_direction_deg=_range(0.0, 360.0),
        camera_stability=_range(0.35, 0.60),
        lightning_flash_probability=_range(0.08, 0.30),
        flash_intensity=_range(3.0, 20.0),
        visibility_m=_range(300.0, 1800.0),
        surface_roughness_delta=_range(-0.55, -0.30),
        motion_blur_shutter=_range(0.60, 1.00),
        sensor_noise_iso_scale=_range(2.5, 6.0),
        residual_droplet_density=_range(0.60, 1.00),
        puddling=_range(0.30, 0.70),
    ),
    feature_flag="environment_heavy_rain_storm_v1",
    is_wet=True,
    has_active_precipitation=True,
    preview_path="environment-assets/HEAVY_RAIN_STORM_V1/1.0.0/preview.jpg",
    notes=(
        "Frequently occludes the defect. The annotation policy decides whether such a "
        "sample is rejected or kept as a deliberate occluded or hard-negative example."
    ),
)

POST_RAIN_WET_V1 = EnvironmentVersion(
    id="POST_RAIN_WET_V1",
    version="1.0.0",
    status=ReleaseStatus.RELEASED,
    title="Post-rain, wet and clearing",
    summary=(
        "Rainfall has stopped. The surface is still wet and reflective with clinging "
        "droplets, streaking, and local pooling, under clearing overcast light."
    ),
    renderer_key="env_post_rain_wet_v1",
    sky_model=SKY_BROKEN_CLOUD,
    sun_elevation_deg=_range(18.0, 58.0),
    sun_azimuth_deg=_range(0.0, 360.0),
    sun_angular_diameter_deg=_range(6.0, 28.0),
    sun_strength_w=_range(260.0, 560.0),
    sun_color_temperature_k=_range(5900.0, 6800.0),
    sky_turbidity=_range(4.5, 7.5),
    world_strength=_range(1.50, 2.40),
    ambient_color_temperature_k=_range(6800.0, 9000.0),
    exposure_ev=_range(-0.25, 0.35),
    view_transform=VIEW_TRANSFORM_AGX,
    sky_nonuniformity=_range(0.25, 0.60),
    color_response_scale=_range(0.88, 1.00),
    distance_fade_strength=_range(0.10, 0.30),
    weather=WeatherRanges(
        cloud_cover=_range(0.35, 0.80),
        # Residual dripping only. No active rainfall.
        precipitation_rate_mm_h=_range(0.0, 0.20),
        droplet_size_mm=_range(0.6, 1.2),
        rain_direction_deg=_range(0.0, 360.0),
        rain_incline_deg=_range(0.0, 8.0),
        wetness=_range(0.70, 0.95),
        haze_density=_range(0.030, 0.090),
        wind_speed_ms=_range(1.0, 8.0),
        wind_direction_deg=_range(0.0, 360.0),
        camera_stability=_range(0.90, 1.00),
        lightning_flash_probability=_range(0.0, 0.0),
        flash_intensity=_range(0.0, 0.0),
        visibility_m=_range(9000.0, 25000.0),
        surface_roughness_delta=_range(-0.45, -0.25),
        motion_blur_shutter=_range(0.0, 0.20),
        sensor_noise_iso_scale=_range(1.0, 1.7),
        residual_droplet_density=_range(0.45, 0.90),
        puddling=_range(0.20, 0.60),
    ),
    feature_flag="environment_post_rain_wet_v1",
    is_wet=True,
    has_active_precipitation=False,
    preview_path="environment-assets/POST_RAIN_WET_V1/1.0.0/preview.jpg",
)

ALL_ENVIRONMENTS: tuple[EnvironmentVersion, ...] = (
    CLEAR_DAY_V1,
    OVERCAST_DAY_V1,
    CLOUDY_DAY_V1,
    GOLDEN_HOUR_V1,
    NIGHT_MOONLIT_V1,
    OFFSHORE_HAZE_V1,
    LIGHT_RAIN_WET_V1,
    HEAVY_RAIN_STORM_V1,
    POST_RAIN_WET_V1,
)

DEFAULT_ENVIRONMENT_ID = OVERCAST_DAY_V1.id

# The legacy ``lighting_preset`` strings, mapped onto the closest v2 environment so
# pre-upgrade jobs resolve without changing their stored payload.
LEGACY_LIGHTING_PRESET_TO_ENVIRONMENT: dict[str, str] = {
    "overcast": OVERCAST_DAY_V1.id,
    "cloudy": CLOUDY_DAY_V1.id,
    "midday": CLEAR_DAY_V1.id,
    "golden_hour": GOLDEN_HOUR_V1.id,
}

_BY_ID = {environment.id: environment for environment in ALL_ENVIRONMENTS}
_BY_REFERENCE = {f"{e.id}@{e.version}": e for e in ALL_ENVIRONMENTS}


def get_environment(reference: str) -> EnvironmentVersion:
    key = reference.strip()
    if "@" in key:
        try:
            return _BY_REFERENCE[key]
        except KeyError as exc:
            raise RegistryLookupError(f"Unknown environment version {reference!r}") from exc
    try:
        return _BY_ID[key]
    except KeyError as exc:
        raise RegistryLookupError(f"Unknown environment {reference!r}") from exc


def environment_for_legacy_lighting_preset(preset: str) -> EnvironmentVersion:
    try:
        return get_environment(LEGACY_LIGHTING_PRESET_TO_ENVIRONMENT[preset])
    except KeyError as exc:
        raise RegistryLookupError(f"Unknown legacy lighting preset {preset!r}") from exc


def list_environments() -> tuple[EnvironmentVersion, ...]:
    return tuple(e for e in ALL_ENVIRONMENTS if e.is_selectable)


def registry_checksum() -> str:
    return checksum([environment.as_dict() for environment in ALL_ENVIRONMENTS])


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

WEATHER_FIELDS: tuple[str, ...] = WeatherRanges(
    *([_range(0.0, 1.0)] * 16)
).field_names()


@dataclass(frozen=True)
class ResolvedEnvironment:
    """A concrete scene configuration. Everything the renderer needs, nothing implicit."""

    environment_id: str
    environment_version: str
    renderer_key: str
    sky_model: str
    view_transform: str
    sun_elevation_deg: float
    sun_azimuth_deg: float
    sun_angular_diameter_deg: float
    sun_strength_w: float
    sun_color_temperature_k: float
    sky_turbidity: float
    sky_nonuniformity: float
    world_strength: float
    ambient_color_temperature_k: float
    exposure_ev: float
    color_response_scale: float
    distance_fade_strength: float
    volumetric_enabled: bool
    volumetric_anisotropy: float
    artificial_lighting_enabled: bool
    artificial_lighting_strength_w: float
    artificial_lighting_color_temperature_k: float
    artificial_lighting_beam_angle_deg: float
    lightning_flash_active: bool
    is_night: bool
    is_wet: bool
    has_active_precipitation: bool
    intensity: float
    weather: dict[str, float]
    max_mean_luminance: float | None
    min_mean_luminance: float | None
    hdri_asset_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "environment_id": self.environment_id,
            "environment_version": self.environment_version,
            "renderer_key": self.renderer_key,
            "sky_model": self.sky_model,
            "view_transform": self.view_transform,
            "sun_elevation_deg": round(self.sun_elevation_deg, 4),
            "sun_azimuth_deg": round(self.sun_azimuth_deg, 4),
            "sun_angular_diameter_deg": round(self.sun_angular_diameter_deg, 4),
            "sun_strength_w": round(self.sun_strength_w, 6),
            "sun_color_temperature_k": round(self.sun_color_temperature_k, 2),
            "sky_turbidity": round(self.sky_turbidity, 4),
            "sky_nonuniformity": round(self.sky_nonuniformity, 4),
            "world_strength": round(self.world_strength, 6),
            "ambient_color_temperature_k": round(self.ambient_color_temperature_k, 2),
            "exposure_ev": round(self.exposure_ev, 4),
            "color_response_scale": round(self.color_response_scale, 4),
            "distance_fade_strength": round(self.distance_fade_strength, 4),
            "volumetric_enabled": self.volumetric_enabled,
            "volumetric_anisotropy": round(self.volumetric_anisotropy, 4),
            "artificial_lighting_enabled": self.artificial_lighting_enabled,
            "artificial_lighting_strength_w": round(self.artificial_lighting_strength_w, 4),
            "artificial_lighting_color_temperature_k": round(
                self.artificial_lighting_color_temperature_k, 2
            ),
            "artificial_lighting_beam_angle_deg": round(
                self.artificial_lighting_beam_angle_deg, 3
            ),
            "lightning_flash_active": self.lightning_flash_active,
            "is_night": self.is_night,
            "is_wet": self.is_wet,
            "has_active_precipitation": self.has_active_precipitation,
            "intensity": round(self.intensity, 4),
            "weather": {k: round(v, 6) for k, v in sorted(self.weather.items())},
            "max_mean_luminance": self.max_mean_luminance,
            "min_mean_luminance": self.min_mean_luminance,
            "hdri_asset_id": self.hdri_asset_id,
        }

    def signature(self) -> tuple[float, ...]:
        """A numeric fingerprint used to prove two presets differ materially."""
        weather = self.weather
        return (
            self.sun_elevation_deg,
            self.sun_angular_diameter_deg,
            self.sun_strength_w,
            self.sun_color_temperature_k,
            self.sky_turbidity,
            self.world_strength,
            self.exposure_ev,
            self.color_response_scale,
            self.distance_fade_strength,
            self.volumetric_anisotropy,
            weather["cloud_cover"],
            weather["precipitation_rate_mm_h"],
            weather["wetness"],
            weather["haze_density"],
            weather["wind_speed_ms"],
            weather["camera_stability"],
            weather["visibility_m"],
            weather["surface_roughness_delta"],
            weather["sensor_noise_iso_scale"],
        )

    @property
    def wetness(self) -> float:
        return self.weather["wetness"]

    @property
    def visibility_m(self) -> float:
        return self.weather["visibility_m"]

    @property
    def motion_blur_enabled(self) -> bool:
        return self.weather["motion_blur_shutter"] > 0.25


def resolve_environment(
    environment: EnvironmentVersion,
    rng: random.Random,
    *,
    intensity: float = 0.5,
    overrides: dict[str, float] | None = None,
) -> ResolvedEnvironment:
    """Sample one concrete scene configuration from a preset.

    ``intensity`` in 0..1 biases every range towards its upper end, which is the only
    weather control a normal customer sees. ``overrides`` lets an advanced API
    customer pin individual weather values; each is validated against the preset's
    own bounds and rejected rather than clamped if it escapes them.
    """
    if not 0.0 <= intensity <= 1.0:
        raise ParameterValidationError(f"Weather intensity {intensity} must be within 0..1.")

    weather_values: dict[str, float] = {}
    for name in environment.weather.field_names():
        band: Range = getattr(environment.weather, name)
        if name in {"rain_direction_deg", "wind_direction_deg", "sun_azimuth_deg"}:
            weather_values[name] = band.sample(rng)
        elif name == "camera_stability":
            # Higher intensity means worse conditions, so stability moves the other way.
            weather_values[name] = band.sample(rng, 1.0 - intensity)
        elif name == "visibility_m":
            weather_values[name] = band.sample(rng, 1.0 - intensity)
        else:
            weather_values[name] = band.sample(rng, intensity)

    for name, value in (overrides or {}).items():
        if name not in environment.weather.field_names():
            raise ParameterValidationError(f"Unknown weather parameter {name!r}.")
        weather_values[name] = environment.weather.clamp(name, float(value))

    flash_active = (
        weather_values["lightning_flash_probability"] > 0.0
        and rng.random() < weather_values["lightning_flash_probability"]
    )
    lighting = environment.artificial_lighting
    lighting_active = lighting.enabled and rng.random() < lighting.probability

    return ResolvedEnvironment(
        environment_id=environment.id,
        environment_version=environment.version,
        renderer_key=environment.renderer_key,
        sky_model=environment.sky_model,
        view_transform=environment.view_transform,
        sun_elevation_deg=environment.sun_elevation_deg.sample(rng),
        sun_azimuth_deg=environment.sun_azimuth_deg.sample(rng),
        sun_angular_diameter_deg=environment.sun_angular_diameter_deg.sample(rng, intensity),
        sun_strength_w=environment.sun_strength_w.sample(rng, 1.0 - intensity),
        sun_color_temperature_k=environment.sun_color_temperature_k.sample(rng),
        sky_turbidity=environment.sky_turbidity.sample(rng, intensity),
        sky_nonuniformity=environment.sky_nonuniformity.sample(rng, intensity),
        world_strength=environment.world_strength.sample(rng),
        ambient_color_temperature_k=environment.ambient_color_temperature_k.sample(rng),
        exposure_ev=environment.exposure_ev.sample(rng),
        color_response_scale=environment.color_response_scale.sample(rng, 1.0 - intensity),
        distance_fade_strength=environment.distance_fade_strength.sample(rng, intensity),
        volumetric_enabled=environment.volumetric_enabled,
        volumetric_anisotropy=environment.volumetric_anisotropy.sample(rng),
        artificial_lighting_enabled=lighting_active,
        artificial_lighting_strength_w=(
            lighting.strength_w.sample(rng) if lighting_active else 0.0
        ),
        artificial_lighting_color_temperature_k=lighting.color_temperature_k.sample(rng),
        artificial_lighting_beam_angle_deg=lighting.beam_angle_deg.sample(rng),
        lightning_flash_active=flash_active,
        is_night=environment.is_night,
        is_wet=environment.is_wet,
        has_active_precipitation=environment.has_active_precipitation,
        intensity=intensity,
        weather=weather_values,
        max_mean_luminance=environment.max_mean_luminance,
        min_mean_luminance=environment.min_mean_luminance,
        hdri_asset_id=environment.hdri_asset_id,
    )


# ---------------------------------------------------------------------------
# Customer-supplied HDRI records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class HdriAssetLimits:
    """Validation limits for a customer HDRI or EXR upload."""

    max_bytes: int = 512 * 1024 * 1024
    min_width: int = 1024
    max_width: int = 16384
    min_height: int = 512
    max_height: int = 8192
    # A latitude-longitude environment map must be 2:1.
    required_aspect_ratio: float = 2.0
    aspect_ratio_tolerance: float = 0.02
    # An environment map with no values above 1.0 is not high dynamic range.
    min_peak_luminance: float = 1.5
    allowed_extensions: tuple[str, ...] = (".hdr", ".exr")
    allowed_magic: tuple[bytes, ...] = (b"#?RADIANCE", b"#?RGBE", b"\x76\x2f\x31\x01")

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_bytes": self.max_bytes,
            "min_width": self.min_width,
            "max_width": self.max_width,
            "min_height": self.min_height,
            "max_height": self.max_height,
            "required_aspect_ratio": self.required_aspect_ratio,
            "aspect_ratio_tolerance": self.aspect_ratio_tolerance,
            "min_peak_luminance": self.min_peak_luminance,
            "allowed_extensions": list(self.allowed_extensions),
        }


HDRI_LIMITS = HdriAssetLimits()
