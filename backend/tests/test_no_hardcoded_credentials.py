"""Guard against credentials or disabled TLS verification returning to source.

An earlier revision embedded a live Supabase PostgreSQL password in the
repository's diagnostic scripts. These tests fail the build if that class of
mistake reappears.
"""

from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

SCANNED_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".sql", ".yaml", ".yml", ".json"}

SKIPPED_DIRECTORY_NAMES = {
    ".git",
    ".next",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
    "var",
}

# This test file necessarily contains the patterns it searches for.
SELF = Path(__file__).resolve()

# The only reviewed location allowed to construct a permissive TLS context, and only
# behind an explicit BLADEFORGE_DIAGNOSTIC_SSL_MODE=insecure opt-in that prints a warning.
TLS_OPT_IN_ALLOWLIST = {REPOSITORY_ROOT / "tools" / "db_diagnostics.py"}

# postgres://user:password@host — an inline password in a connection string.
INLINE_PASSWORD_URL = re.compile(
    r"postgres(?:ql)?(?:\+[a-z0-9]+)?://[^\s:/@\"']+:[^\s:/@\"']+@",
    re.IGNORECASE,
)

DISABLED_TLS_VERIFICATION = re.compile(r"CERT_NONE|check_hostname\s*=\s*False")


def scanned_files() -> list[Path]:
    found: list[Path] = []
    stack = [REPOSITORY_ROOT]
    while stack:
        directory = stack.pop()
        try:
            entries = list(directory.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in SKIPPED_DIRECTORY_NAMES:
                    stack.append(entry)
                continue
            if entry.name.startswith(".env"):
                # Git-ignored local secret files are expected to hold real values.
                continue
            if entry.suffix.lower() in SCANNED_SUFFIXES and entry.resolve() != SELF:
                found.append(entry)
    return found


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def test_repository_contains_no_inline_database_password() -> None:
    offenders: list[str] = []
    for path in scanned_files():
        for match in INLINE_PASSWORD_URL.finditer(read(path)):
            # Placeholder documentation such as postgresql://postgres:YOUR_PASSWORD@host
            # and postgres:postgres@127.0.0.1 test defaults are not real credentials.
            fragment = match.group(0)
            if re.search(r":(YOUR_PASSWORD|password|postgres|CHANGEME|<[^>]+>)@", fragment):
                continue
            offenders.append(f"{path.relative_to(REPOSITORY_ROOT).as_posix()}: {fragment}")
    assert not offenders, (
        "A database URL with an inline password is present in tracked source. "
        "Read credentials from the environment instead. See SECURITY.md.\n"
        + "\n".join(offenders)
    )


def test_tls_verification_is_not_disabled_outside_the_reviewed_opt_in() -> None:
    offenders: list[str] = []
    for path in scanned_files():
        if path.resolve() in TLS_OPT_IN_ALLOWLIST:
            continue
        if DISABLED_TLS_VERIFICATION.search(read(path)):
            offenders.append(path.relative_to(REPOSITORY_ROOT).as_posix())
    assert not offenders, (
        "TLS certificate verification is disabled outside tools/db_diagnostics.py. "
        "Certificate verification must stay on. See SECURITY.md.\n" + "\n".join(offenders)
    )


def test_diagnostic_scripts_use_the_shared_helper() -> None:
    for name in ("check_schema.py", "check_schema2.py", "fix_schema.py"):
        source = read(REPOSITORY_ROOT / name)
        assert source, f"{name} is missing."
        assert "tools.db_diagnostics" in source, (
            f"{name} must obtain its connection from tools.db_diagnostics so that "
            "credentials stay in the environment and access stays read-only."
        )
        assert not INLINE_PASSWORD_URL.search(source), f"{name} contains an inline credential."


def test_security_notice_documents_rotation() -> None:
    notice = read(REPOSITORY_ROOT / "SECURITY.md").lower()
    assert notice, "SECURITY.md is missing."
    for expectation in ("rotate", "password", "history", "filter-repo"):
        assert expectation in notice, f"SECURITY.md must explain {expectation}."
