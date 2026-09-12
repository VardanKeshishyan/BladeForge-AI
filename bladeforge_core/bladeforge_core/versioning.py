"""Deterministic versioning, canonical serialisation, and checksum helpers.

Every registry entry is immutable and carries a semantic version plus a SHA-256
checksum derived from its canonical JSON form. The checksum is what lets a
manifest prove which exact configuration produced a dataset, and what lets the
platform refuse to reuse a painted region after its model's UV layout changed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SEMANTIC_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
REGISTRY_ID = re.compile(r"^[A-Z][A-Z0-9_]{2,79}$")


class ReleaseStatus:
    """Lifecycle of a registry entry.

    ``released`` entries may be selected by customers. ``experimental`` entries
    exist in code and are exercised by tests but stay hidden behind a feature
    flag until their acceptance suite passes. ``archived`` entries remain
    resolvable so historical datasets stay reproducible, but cannot be selected
    for new jobs.
    """

    EXPERIMENTAL = "experimental"
    RELEASED = "released"
    ARCHIVED = "archived"

    ALL = (EXPERIMENTAL, RELEASED, ARCHIVED)


@dataclass(frozen=True, order=True)
class SemanticVersion:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: str) -> SemanticVersion:
        match = SEMANTIC_VERSION.match(value.strip())
        if match is None:
            raise ValueError(f"Not a semantic version: {value!r}")
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def validate_registry_id(value: str) -> str:
    """Registry identifiers are stable, uppercase, and never reused."""
    if not REGISTRY_ID.match(value):
        raise ValueError(
            f"Registry id {value!r} must be uppercase letters, digits, and underscores, "
            "3 to 80 characters, starting with a letter."
        )
    return value


def canonical_json(payload: Any) -> str:
    """Stable JSON: sorted keys, no insignificant whitespace, ASCII-safe."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_encode_unknown,
    )


def _encode_unknown(value: Any) -> Any:
    if isinstance(value, SemanticVersion):
        return str(value)
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, set | frozenset):
        return sorted(value)
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "as_dict"):
        return value.as_dict()
    raise TypeError(f"Cannot canonically serialise {type(value).__name__}")


def checksum(payload: Any) -> str:
    """SHA-256 of the canonical JSON form of ``payload``."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def checksum_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checksum_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class LicenseRecord:
    """Provenance for any asset that ends up in a customer deliverable.

    BladeForge never claims ownership of customer uploads. ``owner`` records who
    actually owns the asset; for customer imports it is the customer.
    """

    source: str
    owner: str
    license_name: str
    license_url: str | None = None
    allows_commercial_use: bool = False
    allows_redistribution: bool = False
    review_status: str = "pending"
    notes: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "owner": self.owner,
            "license_name": self.license_name,
            "license_url": self.license_url,
            "allows_commercial_use": self.allows_commercial_use,
            "allows_redistribution": self.allows_redistribution,
            "review_status": self.review_status,
            "notes": self.notes,
        }


INTERNAL_AUTHORSHIP = LicenseRecord(
    source="internal:bladeforge_core",
    owner="BladeForge AI",
    license_name="Proprietary, internally authored",
    allows_commercial_use=True,
    allows_redistribution=False,
    review_status="approved",
    notes="Generated procedurally by BladeForge code. No third-party asset is embedded.",
)


@dataclass(frozen=True)
class VersionedEntry:
    """Shared identity fields for every immutable registry record."""

    id: str
    version: str
    status: str
    title: str
    summary: str

    def __post_init__(self) -> None:
        validate_registry_id(self.id)
        SemanticVersion.parse(self.version)
        if self.status not in ReleaseStatus.ALL:
            raise ValueError(f"Unknown release status {self.status!r}")

    @property
    def semantic_version(self) -> SemanticVersion:
        return SemanticVersion.parse(self.version)

    @property
    def is_selectable(self) -> bool:
        return self.status == ReleaseStatus.RELEASED

    def identity(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "status": self.status,
            "title": self.title,
            "summary": self.summary,
        }
