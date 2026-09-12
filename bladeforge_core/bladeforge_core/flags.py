"""Feature flags that gate capabilities until their acceptance tests pass.

A capability is advertised to the frontend only when its flag is enabled. This is the
mechanism that keeps a half-finished renderer path from ever appearing as a working
button, and it lets one failing module be disabled without touching the rest.

Defaults live here so that the backend, the worker, and Blender all agree. An operator
can override any flag through the environment:

    BLADEFORGE_FLAG_DEFECT_CORROSION_RUST_V1=0     disables one capability
    BLADEFORGE_FLAGS=defect_lee_v1,env_clear_day_v1  enables only this allowlist
"""

from __future__ import annotations

import os
from dataclasses import dataclass

ENV_PREFIX = "BLADEFORGE_FLAG_"
ENV_ALLOWLIST = "BLADEFORGE_FLAGS"

RENDER_ENGINE_LEGACY = "legacy"
RENDER_ENGINE_V2 = "v2"
ENV_RENDER_ENGINE = "RENDER_ENGINE_VERSION"


@dataclass(frozen=True)
class FeatureFlag:
    key: str
    default: bool
    summary: str
    # Flags that must also be on for this one to mean anything.
    requires: tuple[str, ...] = ()


_FLAGS: tuple[FeatureFlag, ...] = (
    # --- renderer -----------------------------------------------------------
    FeatureFlag("renderer_v2", True, "Versioned v2 render pipeline."),
    FeatureFlag("renderer_cycles_final", True, "Cycles for final dataset renders.", ("renderer_v2",)),
    FeatureFlag("renderer_eevee_preview", True, "Eevee for fast previews.", ("renderer_v2",)),
    FeatureFlag("renderer_gpu", True, "Use GPU compute when the worker reports one."),
    FeatureFlag("renderer_denoise", True, "Denoise Cycles output."),
    # --- blade models -------------------------------------------------------
    FeatureFlag("blade_bf_generic_blade_v1", True, "BF_GENERIC_BLADE_V1 built-in blade."),
    FeatureFlag(
        "blade_bf_legacy_dev_blade_v1", True, "The original procedural development blade."
    ),
    FeatureFlag("model_import", True, "Customer 3D model import and conversion."),
    FeatureFlag("model_import_usd", True, "USD, USDA, USDC, and USDZ import.", ("model_import",)),
    FeatureFlag("model_import_fbx", True, "FBX import.", ("model_import",)),
    FeatureFlag("model_import_obj", True, "OBJ import.", ("model_import",)),
    FeatureFlag("model_import_gltf", True, "GLB and glTF import.", ("model_import",)),
    # --- defects ------------------------------------------------------------
    FeatureFlag("defect_lee_standard_v1", True, "Leading-edge erosion."),
    FeatureFlag("defect_lightning_strike_standard_v1", True, "Lightning strike damage."),
    FeatureFlag("defect_surface_crack_standard_v1", True, "Surface cracks."),
    FeatureFlag("defect_delamination_standard_v1", True, "Surface-visible delamination."),
    FeatureFlag("defect_delamination_subsurface_v1", True, "Subsurface delamination."),
    FeatureFlag("defect_coating_failure_standard_v1", True, "Coating failure."),
    FeatureFlag(
        "defect_corrosion_rust_standard_v1", True, "Corrosion on metallic hardware."
    ),
    FeatureFlag(
        "defect_corrosion_runoff_staining_v1", True, "Rust runoff staining on composite."
    ),
    FeatureFlag("defect_multi", True, "One primary defect plus validated secondaries."),
    # --- environments -------------------------------------------------------
    FeatureFlag("environment_clear_day_v1", True, "Clear daylight."),
    FeatureFlag("environment_overcast_day_v1", True, "Overcast daylight."),
    FeatureFlag("environment_cloudy_day_v1", True, "Broken cloud daylight."),
    FeatureFlag("environment_golden_hour_v1", True, "Golden hour."),
    FeatureFlag("environment_night_moonlit_v1", True, "Moonlit night."),
    FeatureFlag("environment_offshore_haze_v1", True, "Offshore haze."),
    FeatureFlag("environment_light_rain_wet_v1", True, "Light rain, wet surface."),
    FeatureFlag("environment_heavy_rain_storm_v1", True, "Heavy rain storm."),
    FeatureFlag("environment_post_rain_wet_v1", True, "Post-rain wet."),
    FeatureFlag("hdri_upload", True, "Customer HDRI upload."),
    # --- cameras ------------------------------------------------------------
    FeatureFlag("camera_generic_square_1024_v1", True, "Legacy square 1024 camera."),
    FeatureFlag("camera_drone_wide_20mp_v1", True, "Wide-angle inspection drone."),
    FeatureFlag("camera_drone_tele_12mp_v1", True, "Telephoto inspection drone."),
    FeatureFlag("camera_drone_zoom_inspection_v1", True, "Long-standoff zoom drone."),
    FeatureFlag("camera_handheld_fullframe_v1", True, "Handheld full-frame camera."),
    FeatureFlag("camera_saved_views", True, "Save a viewport camera as a job camera."),
    # --- regions ------------------------------------------------------------
    FeatureFlag("region_painting", True, "Paint allowed damage regions in the viewport."),
    FeatureFlag(
        "region_multi_layer",
        True,
        "Multiple coloured region layers, each bound to a defect profile.",
        ("region_painting",),
    ),
    # --- outputs ------------------------------------------------------------
    FeatureFlag("output_legacy_coco_v1", True, "Legacy COCO package."),
    FeatureFlag("output_legacy_yolo_v1", True, "Legacy YOLO package."),
    FeatureFlag("output_standard_detection_v1", True, "Standard detection package."),
    FeatureFlag("output_full_analysis_v1", True, "Full analysis package."),
    FeatureFlag("output_defect_crop_v1", True, "Damaged-area crops."),
    FeatureFlag("output_hard_negative_v1", True, "Hard-negative and occluded samples."),
    FeatureFlag("annotation_yolo_segmentation", True, "YOLO segmentation labels."),
    # --- product surfaces ---------------------------------------------------
    FeatureFlag("preview_render", True, "Single low-cost preview before submitting."),
    FeatureFlag("org_defect_profiles", True, "Organisation-owned defect profile versions."),
    FeatureFlag("validation_projects", True, "Pilot validation projects and reports."),
    FeatureFlag("quotas", True, "Per-organisation quota enforcement."),
    FeatureFlag("billing", False, "Charging. Deliberately off until validation proves value."),
    FeatureFlag("lifecycle_deletion", True, "Customer-initiated deletion and retention."),
    FeatureFlag("data_export", True, "Customer data export."),
)

FLAGS: dict[str, FeatureFlag] = {flag.key: flag for flag in _FLAGS}


def _env_override(key: str) -> bool | None:
    raw = os.environ.get(f"{ENV_PREFIX}{key.upper()}")
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _allowlist() -> set[str] | None:
    raw = os.environ.get(ENV_ALLOWLIST)
    if raw is None or not raw.strip():
        return None
    return {part.strip() for part in raw.split(",") if part.strip()}


def is_enabled(key: str) -> bool:
    """Resolve a flag, honouring dependencies, per-flag overrides, and the allowlist."""
    flag = FLAGS.get(key)
    if flag is None:
        # An unknown flag is treated as off. A typo must not silently open a capability.
        return False
    allowlist = _allowlist()
    if allowlist is not None and key not in allowlist:
        return False
    override = _env_override(key)
    enabled = flag.default if override is None else override
    if not enabled:
        return False
    return all(is_enabled(dependency) for dependency in flag.requires)


def enabled_flags() -> dict[str, bool]:
    return {key: is_enabled(key) for key in sorted(FLAGS)}


def render_engine_version() -> str:
    """Which renderer the worker should invoke."""
    raw = os.environ.get(ENV_RENDER_ENGINE, RENDER_ENGINE_V2).strip().lower()
    if raw not in {RENDER_ENGINE_LEGACY, RENDER_ENGINE_V2}:
        return RENDER_ENGINE_V2
    if raw == RENDER_ENGINE_V2 and not is_enabled("renderer_v2"):
        return RENDER_ENGINE_LEGACY
    return raw


def require(key: str, what: str) -> None:
    from .errors import FeatureDisabledError

    if not is_enabled(key):
        raise FeatureDisabledError(
            f"{what} is not currently available on this deployment "
            f"(feature flag {key!r} is off)."
        )
