"""Apply one repository migration to the configured BladeForge PostgreSQL database.

This is intentionally opt-in and reuses the TLS-verified diagnostic connection. Set
``BLADEFORGE_DIAGNOSTIC_ALLOW_WRITES=1`` and pass only a file inside
``supabase/migrations``. Credentials remain in the ignored backend environment file.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from db_diagnostics import REPOSITORY_ROOT, connect, require_write_permission


async def apply(path: Path) -> None:
    require_write_permission(f"Applying {path.name}")
    migration_root = (REPOSITORY_ROOT / "supabase" / "migrations").resolve()
    resolved = path.resolve()
    if migration_root not in resolved.parents or resolved.suffix.lower() != ".sql":
        raise RuntimeError("Only SQL files inside supabase/migrations may be applied.")
    sql = resolved.read_text(encoding="utf-8")
    async with connect() as connection:
        async with connection.transaction():
            await connection.execute(sql)
    print(f"Applied {resolved.name} successfully.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("migration", type=Path)
    args = parser.parse_args()
    asyncio.run(apply(args.migration))


if __name__ == "__main__":
    main()
