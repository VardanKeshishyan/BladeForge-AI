"""BladeForge versioned generation registries.

This package is the single source of truth for what BladeForge can generate. It is
imported by three different runtimes, so it stays dependency-light and free of any
framework code:

* the FastAPI backend, which validates job requests and reports capabilities;
* the render worker, which forwards a resolved recipe;
* the headless Blender renderer, which executes it.

Nothing here touches a database, a network, or ``bpy``.

Start at :func:`bladeforge_core.recipes.resolve_recipe`. It takes a request expressed in
registry references and returns an immutable, checksummed configuration that is
reproducible on any machine. :meth:`bladeforge_core.recipes.RecipeRequest.for_legacy_job`
builds that request from the pre-upgrade job payload, which is how jobs submitted before
this upgrade keep working.
"""

from __future__ import annotations

from . import (
    blades,
    cameras,
    defects,
    environments,
    errors,
    flags,
    licenses,
    materials,
    outputs,
    recipes,
    regions,
    severity,
    taxonomy,
    versioning,
)
from .flags import RENDER_ENGINE_LEGACY, RENDER_ENGINE_V2, is_enabled, render_engine_version
from .recipes import (
    DefectSelection,
    QualitySpec,
    RandomizationSpec,
    RecipeRequest,
    ResolvedRecipe,
    resolve_legacy_job,
    resolve_recipe,
)
from .taxonomy import ACTIVE_TAXONOMY

__version__ = "2.0.0"

# Kept as module-level names because the worker and the legacy renderer import them.
RENDER_ENGINE_VERSION_LEGACY = RENDER_ENGINE_LEGACY
RENDER_ENGINE_VERSION_V2 = RENDER_ENGINE_V2

__all__ = [
    "ACTIVE_TAXONOMY",
    "RENDER_ENGINE_LEGACY",
    "RENDER_ENGINE_V2",
    "RENDER_ENGINE_VERSION_LEGACY",
    "RENDER_ENGINE_VERSION_V2",
    "DefectSelection",
    "QualitySpec",
    "RandomizationSpec",
    "RecipeRequest",
    "ResolvedRecipe",
    "__version__",
    "blades",
    "cameras",
    "defects",
    "environments",
    "errors",
    "flags",
    "is_enabled",
    "licenses",
    "materials",
    "outputs",
    "recipes",
    "regions",
    "render_engine_version",
    "resolve_legacy_job",
    "resolve_recipe",
    "severity",
    "taxonomy",
    "versioning",
]
