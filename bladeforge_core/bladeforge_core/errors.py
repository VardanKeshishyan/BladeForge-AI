"""Error types shared by the registries, resolver, renderer, and validators."""

from __future__ import annotations


class BladeForgeCoreError(Exception):
    """Base class for every error raised by bladeforge_core."""

    code = "core_error"


class RegistryLookupError(BladeForgeCoreError):
    """A requested registry entry does not exist or is not released."""

    code = "registry_entry_not_found"


class ParameterValidationError(BladeForgeCoreError):
    """A supplied parameter is outside the bounds the registry allows."""

    code = "parameter_out_of_bounds"


class RecipeResolutionError(BladeForgeCoreError):
    """A generation recipe cannot be resolved into a renderable configuration."""

    code = "recipe_resolution_failed"


class RegionMaskError(BladeForgeCoreError):
    """A painted region cannot be used with the requested model version."""

    code = "region_mask_invalid"


class MaskValidationError(BladeForgeCoreError):
    """A rendered mask violates the invariants a training label must satisfy."""

    code = "mask_invalid"


class PackageValidationError(BladeForgeCoreError):
    """A rendered dataset package failed structural or content validation."""

    code = "dataset_package_invalid"


class FeatureDisabledError(BladeForgeCoreError):
    """A capability exists in code but its feature flag is off."""

    code = "feature_disabled"
