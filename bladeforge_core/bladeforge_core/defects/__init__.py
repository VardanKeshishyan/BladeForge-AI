"""Defect profile registry.

Lookup is by immutable id, optionally pinned to a version. Archived versions stay
resolvable so historical datasets remain reproducible, but only ``released``
profiles whose feature flag is on are offered for new jobs.
"""

from __future__ import annotations

from ..errors import ParameterValidationError, RegistryLookupError
from ..versioning import ReleaseStatus
from .base import (
    RENDERER_SCHEMA_VERSION,
    CoverageLimits,
    DefectProfileVersion,
    ResolvedDefect,
    bands,
    spec,
)
from .library import (
    ALL_PROFILES,
    COATING_FAILURE_STANDARD_V1,
    CORROSION_RUNOFF_STAINING_V1,
    CORROSION_RUST_STANDARD_V1,
    DELAMINATION_STANDARD_V1,
    DELAMINATION_SUBSURFACE_V1,
    LEE_STANDARD_V1,
    LIGHTNING_STRIKE_STANDARD_V1,
    SURFACE_CRACK_STANDARD_V1,
)

_BY_ID: dict[str, DefectProfileVersion] = {profile.id: profile for profile in ALL_PROFILES}
_BY_REFERENCE: dict[str, DefectProfileVersion] = {
    f"{profile.id}@{profile.version}": profile for profile in ALL_PROFILES
}

# The legacy ``defect_type`` string every existing job row carries, mapped onto the
# profile that reproduces it. This is what keeps pre-upgrade jobs renderable.
LEGACY_DEFECT_TYPE_TO_PROFILE: dict[str, str] = {
    "leading_edge_erosion": "LEE_STANDARD_V1",
    "lightning_strike_damage": "LIGHTNING_STRIKE_STANDARD_V1",
    "surface_crack": "SURFACE_CRACK_STANDARD_V1",
    "delamination": "DELAMINATION_STANDARD_V1",
    "coating_failure": "COATING_FAILURE_STANDARD_V1",
    "corrosion_rust": "CORROSION_RUST_STANDARD_V1",
}

# The reverse direction: the ``defect_type`` column value written for a v2 job so the
# existing dashboard, dataset list, and external API keep showing a sensible string.
PROFILE_TO_LEGACY_DEFECT_TYPE: dict[str, str] = {
    "LEE_STANDARD_V1": "leading_edge_erosion",
    "LIGHTNING_STRIKE_STANDARD_V1": "lightning_strike_damage",
    "SURFACE_CRACK_STANDARD_V1": "surface_crack",
    "DELAMINATION_STANDARD_V1": "delamination",
    "DELAMINATION_SUBSURFACE_V1": "delamination",
    "COATING_FAILURE_STANDARD_V1": "coating_failure",
    "CORROSION_RUST_STANDARD_V1": "corrosion_rust",
    "CORROSION_RUNOFF_STAINING_V1": "corrosion_rust",
}


def get_profile(reference: str) -> DefectProfileVersion:
    """Resolve ``ID`` or ``ID@version`` to a profile version."""
    key = reference.strip()
    if "@" in key:
        try:
            return _BY_REFERENCE[key]
        except KeyError as exc:
            raise RegistryLookupError(f"Unknown defect profile version {reference!r}") from exc
    try:
        return _BY_ID[key]
    except KeyError as exc:
        raise RegistryLookupError(f"Unknown defect profile {reference!r}") from exc


def profile_for_legacy_defect_type(defect_type: str) -> DefectProfileVersion:
    try:
        return get_profile(LEGACY_DEFECT_TYPE_TO_PROFILE[defect_type])
    except KeyError as exc:
        raise RegistryLookupError(
            f"No defect profile is registered for the legacy defect type {defect_type!r}"
        ) from exc


def legacy_defect_type_for_profile(profile_id: str) -> str:
    return PROFILE_TO_LEGACY_DEFECT_TYPE.get(profile_id, "leading_edge_erosion")


def list_profiles(
    *, include_experimental: bool = False, include_archived: bool = False
) -> tuple[DefectProfileVersion, ...]:
    selected = []
    for profile in ALL_PROFILES:
        if profile.status == ReleaseStatus.RELEASED:
            selected.append(profile)
        elif profile.status == ReleaseStatus.EXPERIMENTAL and include_experimental:
            selected.append(profile)
        elif profile.status == ReleaseStatus.ARCHIVED and include_archived:
            selected.append(profile)
    return tuple(selected)


def primary_selectable_profiles() -> tuple[DefectProfileVersion, ...]:
    return tuple(p for p in list_profiles() if p.supports_as_primary)


def secondary_selectable_profiles(primary_id: str) -> tuple[DefectProfileVersion, ...]:
    """Secondary profiles whose interaction with ``primary_id`` is implemented and tested.

    Combinations are allowed only when both sides declare each other, which keeps
    unvalidated interactions out of production datasets.
    """
    primary = get_profile(primary_id)
    allowed = []
    for candidate in list_profiles():
        if candidate.id == primary.id or not candidate.supports_as_secondary:
            continue
        if candidate.id in primary.validated_secondary_profiles:
            allowed.append(candidate)
    return tuple(allowed)


def assert_combination_supported(primary_id: str, secondary_ids: tuple[str, ...]) -> None:
    if not secondary_ids:
        return
    supported = {profile.id for profile in secondary_selectable_profiles(primary_id)}
    unsupported = [item for item in secondary_ids if item not in supported]
    if unsupported:
        raise ParameterValidationError(
            f"Secondary defect profiles {unsupported} are not a validated combination with "
            f"{primary_id}. Supported: {sorted(supported) or 'none yet'}."
        )
    if len(set(secondary_ids)) != len(secondary_ids):
        raise ParameterValidationError("A secondary defect profile was listed twice.")


def registry_checksum() -> str:
    from ..versioning import checksum

    return checksum([profile.as_dict() for profile in ALL_PROFILES])


__all__ = [
    "ALL_PROFILES",
    "COATING_FAILURE_STANDARD_V1",
    "CORROSION_RUNOFF_STAINING_V1",
    "CORROSION_RUST_STANDARD_V1",
    "DELAMINATION_STANDARD_V1",
    "DELAMINATION_SUBSURFACE_V1",
    "LEE_STANDARD_V1",
    "LEGACY_DEFECT_TYPE_TO_PROFILE",
    "LIGHTNING_STRIKE_STANDARD_V1",
    "PROFILE_TO_LEGACY_DEFECT_TYPE",
    "RENDERER_SCHEMA_VERSION",
    "SURFACE_CRACK_STANDARD_V1",
    "CoverageLimits",
    "DefectProfileVersion",
    "ResolvedDefect",
    "assert_combination_supported",
    "bands",
    "get_profile",
    "legacy_defect_type_for_profile",
    "list_profiles",
    "primary_selectable_profiles",
    "profile_for_legacy_defect_type",
    "registry_checksum",
    "secondary_selectable_profiles",
    "spec",
]
