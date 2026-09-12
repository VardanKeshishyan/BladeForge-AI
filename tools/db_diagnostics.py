"""Shared connection helpers for the repository's database diagnostic scripts.

Design rules enforced here:

* Credentials are never stored in the repository. They are read from the process
  environment, optionally seeded from ``backend/.env.local`` or ``backend/.env``,
  which are git-ignored.
* TLS certificate verification is enabled. Disabling it requires an explicit
  ``BLADEFORGE_DIAGNOSTIC_SSL_MODE=insecure`` opt-in and prints a warning.
* Every connection runs inside a read-only transaction unless the caller asks for
  write access *and* the operator sets ``BLADEFORGE_DIAGNOSTIC_ALLOW_WRITES=1``.

Recognised environment variables:

``BLADEFORGE_DIAGNOSTIC_DATABASE_URL``
    Preferred. A PostgreSQL URL used only by these diagnostics.
``DATABASE_URL``
    Fallback. The same value the FastAPI backend uses. The
    ``postgresql+asyncpg://`` SQLAlchemy scheme is accepted and normalised.
``BLADEFORGE_DIAGNOSTIC_SSL_MODE``
    ``verify-full`` (default), ``verify-ca``, or ``insecure``.
``BLADEFORGE_DIAGNOSTIC_ALLOW_WRITES``
    ``1`` to permit a script that explicitly requests write access.
``BLADEFORGE_DIAGNOSTIC_CA_FILE``
    Optional path to an additional CA bundle.
"""

from __future__ import annotations

import os
import ssl
import sys
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

ENV_FILE_CANDIDATES: tuple[Path, ...] = (
    REPOSITORY_ROOT / "backend" / ".env.local",
    REPOSITORY_ROOT / "backend" / ".env",
    REPOSITORY_ROOT / ".env.local",
    REPOSITORY_ROOT / ".env",
)

DATABASE_URL_VARIABLES: tuple[str, ...] = (
    "BLADEFORGE_DIAGNOSTIC_DATABASE_URL",
    "DATABASE_URL",
)

SQLALCHEMY_SCHEME_PREFIXES: tuple[str, ...] = (
    "postgresql+asyncpg://",
    "postgresql+psycopg://",
    "postgresql+psycopg2://",
)


class DiagnosticConfigurationError(RuntimeError):
    """Raised when the diagnostic environment is not configured safely."""


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_environment_files(candidates: Iterable[Path] = ENV_FILE_CANDIDATES) -> None:
    """Seed missing variables from git-ignored env files without overriding real ones."""
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for key, value in _parse_env_file(candidate).items():
            os.environ.setdefault(key, value)


def normalise_database_url(url: str) -> str:
    """Convert a SQLAlchemy async URL into the plain URL asyncpg accepts."""
    for prefix in SQLALCHEMY_SCHEME_PREFIXES:
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def load_database_url() -> str:
    load_environment_files()
    for variable in DATABASE_URL_VARIABLES:
        value = os.environ.get(variable, "").strip()
        if value:
            return normalise_database_url(value)
    raise DiagnosticConfigurationError(
        "No database URL found. Set BLADEFORGE_DIAGNOSTIC_DATABASE_URL (preferred) or "
        "DATABASE_URL in the environment, or place it in backend/.env.local. "
        "Never commit a credential into this repository."
    )


def build_ssl_context() -> ssl.SSLContext | bool:
    mode = os.environ.get("BLADEFORGE_DIAGNOSTIC_SSL_MODE", "verify-full").strip().lower()
    if mode == "insecure":
        print(
            "WARNING: BLADEFORGE_DIAGNOSTIC_SSL_MODE=insecure disables certificate "
            "verification. Use this only against a local database you control.",
            file=sys.stderr,
        )
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    if mode not in {"verify-full", "verify-ca"}:
        raise DiagnosticConfigurationError(
            "BLADEFORGE_DIAGNOSTIC_SSL_MODE must be verify-full, verify-ca, or insecure."
        )
    ca_file = os.environ.get("BLADEFORGE_DIAGNOSTIC_CA_FILE", "").strip() or None
    context = ssl.create_default_context(cafile=ca_file)
    context.check_hostname = mode == "verify-full"
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def writes_allowed() -> bool:
    return os.environ.get("BLADEFORGE_DIAGNOSTIC_ALLOW_WRITES", "").strip() == "1"


def require_write_permission(operation: str) -> None:
    if not writes_allowed():
        raise DiagnosticConfigurationError(
            f"{operation} would modify the database. Diagnostics are read-only by default. "
            "Prefer applying a forward migration through supabase/migrations. If you really "
            "need this script, set BLADEFORGE_DIAGNOSTIC_ALLOW_WRITES=1 deliberately."
        )


@asynccontextmanager
async def connect() -> AsyncIterator[Any]:
    """Open a verified asyncpg connection using environment configuration."""
    try:
        import asyncpg
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on local install
        raise DiagnosticConfigurationError(
            "asyncpg is required for database diagnostics. Install the backend package first."
        ) from exc

    url = load_database_url()
    connection = await asyncpg.connect(
        url,
        ssl=build_ssl_context(),
        # Supabase's transaction pooler does not support prepared-statement caching.
        statement_cache_size=0,
    )
    try:
        yield connection
    finally:
        await connection.close()


@asynccontextmanager
async def read_only_transaction(connection: Any) -> AsyncIterator[Any]:
    """Run statements inside an explicit read-only transaction."""
    transaction = connection.transaction(readonly=True)
    await transaction.start()
    try:
        yield connection
    finally:
        await transaction.rollback()
