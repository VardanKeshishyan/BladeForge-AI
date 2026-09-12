"""Environment and weather tests.

The requirement these enforce is that a preset changes the scene, not just a label. Each
test below inspects resolved numeric configuration, so renaming a preset or adding it to
a dropdown cannot make any of them pass.
"""

from __future__ import annotations

import itertools
import random

import pytest

from bladeforge_core import environments, materials

REQUIRED_PRESETS = (
    "CLEAR_DAY_V1",
    "OVERCAST_DAY_V1",
    "CLOUDY_DAY_V1",
    "GOLDEN_HOUR_V1",
    "NIGHT_MOONLIT_V1",
    "OFFSHORE_HAZE_V1",
    "LIGHT_RAIN_WET_V1",
    "HEAVY_RAIN_STORM_V1",
    "POST_RAIN_WET_V1",
)


def resolve(preset_id: str, *, intensity: float = 0.5, seed: int = 4242):
    return environments.resolve_environment(
        environments.get_environment(preset_id), random.Random(seed), intensity=intensity
    )


def test_all_nine_requested_presets_exist_and_are_selectable() -> None:
    available = {environment.id for environment in environments.list_environments()}
    missing = sorted(set(REQUIRED_PRESETS) - available)
    assert not missing, missing


@pytest.mark.parametrize("preset_id", REQUIRED_PRESETS)
def test_resolution_is_deterministic_for_a_fixed_seed(preset_id: str) -> None:
    first = resolve(preset_id, seed=99)
    second = resolve(preset_id, seed=99)
    assert first.as_dict() == second.as_dict()


@pytest.mark.parametrize("preset_id", REQUIRED_PRESETS)
def test_resolution_varies_with_the_seed(preset_id: str) -> None:
    """Two images from one preset must not be identical, or randomization is a no-op."""
    assert resolve(preset_id, seed=1).as_dict() != resolve(preset_id, seed=2).as_dict()


@pytest.mark.parametrize(
    ("left", "right"), list(itertools.combinations(REQUIRED_PRESETS, 2))
)
def test_every_pair_of_presets_differs_materially(left: str, right: str) -> None:
    """Not "the names differ": at least half of the scene scalars must differ."""
    a = resolve(left).signature()
    b = resolve(right).signature()
    differing = sum(1 for x, y in zip(a, b, strict=True) if abs(x - y) > 1e-6)
    assert differing >= len(a) // 2, (
        f"{left} and {right} only differ in {differing} of {len(a)} scene scalars, "
        "which is not a materially different scene."
    )


def test_clear_day_has_a_high_hard_sun_and_a_clean_sky() -> None:
    resolved = resolve("CLEAR_DAY_V1")
    assert resolved.sun_elevation_deg >= 30.0
    # A small solar disc is what produces sharp, strongly directional shadows.
    assert resolved.sun_angular_diameter_deg <= 1.5
    assert resolved.sun_strength_w >= 500.0
    assert resolved.weather["cloud_cover"] <= 0.25
    assert resolved.weather["precipitation_rate_mm_h"] == 0.0
    assert not resolved.is_wet


def test_overcast_is_soft_and_low_contrast_not_just_dim() -> None:
    overcast = resolve("OVERCAST_DAY_V1")
    clear = resolve("CLEAR_DAY_V1")
    # A large apparent source is the physical cause of soft shadows.
    assert overcast.sun_angular_diameter_deg > clear.sun_angular_diameter_deg * 5
    # Sky dome dominates rather than the sun.
    assert overcast.world_strength > clear.world_strength
    assert overcast.sun_strength_w < clear.sun_strength_w
    assert overcast.weather["cloud_cover"] >= 0.8


def test_cloudy_sits_between_clear_and_overcast_with_a_nonuniform_sky() -> None:
    cloudy = resolve("CLOUDY_DAY_V1")
    clear = resolve("CLEAR_DAY_V1")
    overcast = resolve("OVERCAST_DAY_V1")
    assert overcast.sun_strength_w < cloudy.sun_strength_w < clear.sun_strength_w
    assert cloudy.sky_nonuniformity > clear.sky_nonuniformity
    assert 0.25 < cloudy.weather["cloud_cover"] < 0.95


def test_golden_hour_is_low_warm_and_cool_in_shadow() -> None:
    golden = resolve("GOLDEN_HOUR_V1")
    clear = resolve("CLEAR_DAY_V1")
    assert golden.sun_elevation_deg < 15.0
    assert golden.sun_elevation_deg < clear.sun_elevation_deg
    # Warm direct light against cooler ambient is what makes the look.
    assert golden.sun_color_temperature_k < 4200.0
    assert golden.ambient_color_temperature_k > golden.sun_color_temperature_k


def test_night_uses_a_distinct_lighting_model_not_a_darkened_day() -> None:
    night = resolve("NIGHT_MOONLIT_V1")
    clear = resolve("CLEAR_DAY_V1")
    assert night.is_night
    assert night.sky_model != clear.sky_model
    # Moonlight is around four millionths of sunlight, not a brightness slider.
    assert night.sun_strength_w < clear.sun_strength_w / 1000.0
    # Exposure has to be lifted for the scene to be visible at all.
    assert night.exposure_ev > clear.exposure_ev + 2.0
    # Reduced colour response and higher sensor noise are the real night signatures.
    assert night.color_response_scale < 0.8
    assert night.weather["sensor_noise_iso_scale"] > clear.weather["sensor_noise_iso_scale"]
    assert night.max_mean_luminance is not None, "night needs dark-background validation"


def test_offshore_haze_reduces_distance_contrast() -> None:
    haze = resolve("OFFSHORE_HAZE_V1")
    clear = resolve("CLEAR_DAY_V1")
    assert haze.volumetric_enabled
    assert haze.weather["haze_density"] > clear.weather["haze_density"] * 5
    assert haze.distance_fade_strength > clear.distance_fade_strength
    assert haze.visibility_m < clear.visibility_m


def test_light_rain_is_wet_with_moderate_precipitation() -> None:
    rain = resolve("LIGHT_RAIN_WET_V1")
    clear = resolve("CLEAR_DAY_V1")
    assert rain.is_wet
    assert rain.has_active_precipitation
    assert 0.0 < rain.weather["precipitation_rate_mm_h"] <= 8.0
    assert rain.weather["droplet_size_mm"] > 0.0
    assert rain.wetness > 0.3
    # Wet surfaces are smoother and therefore more reflective.
    assert rain.weather["surface_roughness_delta"] < 0.0
    assert rain.weather["camera_stability"] < clear.weather["camera_stability"]


def test_heavy_storm_changes_light_rain_visibility_wetness_and_camera() -> None:
    storm = resolve("HEAVY_RAIN_STORM_V1", intensity=0.9)
    light = resolve("LIGHT_RAIN_WET_V1", intensity=0.5)
    assert storm.weather["cloud_cover"] >= 0.9
    assert storm.weather["precipitation_rate_mm_h"] > light.weather["precipitation_rate_mm_h"]
    assert storm.visibility_m < light.visibility_m
    assert storm.wetness > light.wetness
    assert storm.weather["wind_speed_ms"] > light.weather["wind_speed_ms"]
    assert storm.weather["camera_stability"] < light.weather["camera_stability"]
    assert storm.motion_blur_enabled
    assert storm.weather["lightning_flash_probability"] > 0.0


def test_post_rain_is_wet_without_active_rainfall() -> None:
    post = resolve("POST_RAIN_WET_V1")
    assert post.is_wet
    assert post.wetness > 0.3
    assert not post.has_active_precipitation
    # Residual dripping is allowed; active rainfall is not. 0.5 mm/h is the boundary
    # between "surfaces are still shedding water" and "it is raining".
    assert post.weather["precipitation_rate_mm_h"] < 0.5
    assert post.weather["residual_droplet_density"] > 0.2
    assert post.weather["puddling"] > 0.0
    assert post.visibility_m > resolve("HEAVY_RAIN_STORM_V1").visibility_m


def test_intensity_moves_weather_towards_its_upper_bound() -> None:
    mild = resolve("HEAVY_RAIN_STORM_V1", intensity=0.0)
    harsh = resolve("HEAVY_RAIN_STORM_V1", intensity=1.0)
    assert harsh.weather["precipitation_rate_mm_h"] > mild.weather["precipitation_rate_mm_h"]
    assert harsh.wetness >= mild.wetness
    # Visibility and stability move the other way as conditions worsen.
    assert harsh.visibility_m < mild.visibility_m
    assert harsh.weather["camera_stability"] <= mild.weather["camera_stability"]


def test_intensity_outside_zero_to_one_is_rejected() -> None:
    from bladeforge_core.errors import ParameterValidationError

    with pytest.raises(ParameterValidationError):
        resolve("CLEAR_DAY_V1", intensity=1.4)


def test_structured_weather_override_inside_the_preset_bounds_is_honoured() -> None:
    """An advanced API customer may pin a value, but only inside the validated range."""
    from bladeforge_core.errors import ParameterValidationError

    environment = environments.get_environment("LIGHT_RAIN_WET_V1")
    ceiling = environment.weather.precipitation_rate_mm_h.maximum
    resolved = environments.resolve_environment(
        environment, random.Random(1), intensity=0.5,
        overrides={"precipitation_rate_mm_h": ceiling},
    )
    assert resolved.weather["precipitation_rate_mm_h"] == ceiling

    # Out of bounds is rejected outright rather than clamped, so a customer never
    # silently receives a different scene from the one they asked for.
    with pytest.raises(ParameterValidationError, match="outside the preset"):
        environments.resolve_environment(
            environment, random.Random(1),
            overrides={"precipitation_rate_mm_h": 10_000.0},
        )


def test_unknown_weather_override_is_rejected() -> None:
    from bladeforge_core.errors import ParameterValidationError

    with pytest.raises(ParameterValidationError):
        environments.resolve_environment(
            environments.get_environment("CLEAR_DAY_V1"),
            random.Random(1),
            overrides={"not_a_weather_parameter": 1.0},
        )


def test_material_wetness_response_is_monotonic_and_physical() -> None:
    """Wetter means smoother and more reflective, with no discontinuity."""
    gelcoat = materials.GELCOAT_WHITE_V1
    samples = [gelcoat.wet(w / 10.0) for w in range(11)]
    roughness = [s["roughness"] for s in samples]
    specular = [s["specular_ior_level"] for s in samples]
    assert roughness == sorted(roughness, reverse=True)
    assert specular == sorted(specular)
    assert roughness[-1] < roughness[0]
    assert specular[-1] > specular[0]
    # A water film cannot make a surface perfectly smooth or a perfect mirror.
    assert roughness[-1] > 0.0
    assert specular[-1] <= 1.0


@pytest.mark.parametrize("preset_id", REQUIRED_PRESETS)
def test_wetness_actually_changes_the_blade_material_response(preset_id: str) -> None:
    """A wet preset must change the coating's physical response, not only the sky."""
    resolved = resolve(preset_id)
    gelcoat = materials.GELCOAT_WHITE_V1
    dry = gelcoat.wet(0.0)
    wet = gelcoat.wet(resolved.wetness)
    if resolved.wetness <= 0.0:
        assert wet == dry, preset_id
        return
    assert wet["roughness"] < dry["roughness"], preset_id
    assert wet["specular_ior_level"] > dry["specular_ior_level"], preset_id
    assert wet["coat_weight"] > dry["coat_weight"], preset_id
    if resolved.is_wet:
        # A declared-wet preset must move roughness by a visible margin, not a trace.
        assert wet["roughness"] < dry["roughness"] * 0.97, preset_id


# The three rain presets are unambiguously wet. Offshore is wet too, from marine
# aerosol and salt film rather than rainfall, which is why it is graded separately.
SOAKED_PRESETS = {"LIGHT_RAIN_WET_V1", "HEAVY_RAIN_STORM_V1", "POST_RAIN_WET_V1"}
DAMP_PRESETS = {"OFFSHORE_HAZE_V1"}


def test_declared_wetness_matches_the_sampled_wetness() -> None:
    """is_wet is a declaration, so it has to agree with the numbers behind it."""
    for preset_id in REQUIRED_PRESETS:
        resolved = resolve(preset_id)
        if preset_id in SOAKED_PRESETS:
            assert resolved.is_wet, preset_id
            assert resolved.wetness > 0.5, (preset_id, resolved.wetness)
        elif preset_id in DAMP_PRESETS:
            assert resolved.is_wet, preset_id
            assert 0.03 < resolved.wetness < 0.5, (preset_id, resolved.wetness)
        else:
            # Dry presets may still carry trace dew or humidity, but not a water film.
            assert not resolved.is_wet, preset_id
            assert resolved.wetness <= 0.2, (preset_id, resolved.wetness)


def test_only_rain_presets_have_active_precipitation() -> None:
    raining = {"LIGHT_RAIN_WET_V1", "HEAVY_RAIN_STORM_V1"}
    for preset_id in REQUIRED_PRESETS:
        resolved = resolve(preset_id)
        assert resolved.has_active_precipitation == (preset_id in raining), preset_id


def test_legacy_lighting_presets_all_map_to_an_environment() -> None:
    for preset, expected in (
        ("overcast", "OVERCAST_DAY_V1"),
        ("golden_hour", "GOLDEN_HOUR_V1"),
        ("midday", "CLEAR_DAY_V1"),
        ("cloudy", "CLOUDY_DAY_V1"),
    ):
        assert environments.environment_for_legacy_lighting_preset(preset).id == expected
