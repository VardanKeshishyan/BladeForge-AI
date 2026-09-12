"""List the columns of the core application tables in the configured database.

Read-only. Credentials come from the environment, never from this file. See
SECURITY.md and tools/db_diagnostics.py for configuration.

    py -3.11 check_schema.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.db_diagnostics import (  # noqa: E402
    DiagnosticConfigurationError,
    connect,
    read_only_transaction,
)

TABLES = (
    "organization_members",
    "organizations",
    "generation_jobs",
    "render_workers",
    "profiles",
    "datasets",
    "api_keys",
    "usage_events",
    "job_events",
)

QUERY = """
    select table_name, column_name, data_type, is_nullable
    from information_schema.columns
    where table_schema = 'public'
      and table_name = any($1::text[])
    order by table_name, ordinal_position
"""


async def main() -> int:
    async with connect() as connection:
        async with read_only_transaction(connection) as read_only:
            rows = await read_only.fetch(QUERY, list(TABLES))
    if not rows:
        print("No matching tables were found in the public schema.")
        return 1
    current: str | None = None
    for row in rows:
        if row["table_name"] != current:
            current = row["table_name"]
            print(f"\n-- {current}")
        nullable = "null" if row["is_nullable"] == "YES" else "not null"
        print(f"  {row['column_name']} :: {row['data_type']} {nullable}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except DiagnosticConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
