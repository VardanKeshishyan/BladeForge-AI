"""Verify that specific expected columns exist in the configured database.

Read-only. Credentials come from the environment, never from this file. See
SECURITY.md and tools/db_diagnostics.py for configuration.

    py -3.11 check_schema2.py
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

EXPECTED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("organization_members", "created_at"),
    ("organization_members", "updated_at"),
    ("render_workers", "registered_at"),
    ("api_keys", "expires_at"),
)

QUERY = """
    select table_name, column_name
    from information_schema.columns
    where table_schema = 'public'
      and (table_name, column_name) in (
        select * from unnest($1::text[], $2::text[])
      )
    order by table_name, column_name
"""


async def main() -> int:
    table_names = [table for table, _ in EXPECTED_COLUMNS]
    column_names = [column for _, column in EXPECTED_COLUMNS]
    async with connect() as connection:
        async with read_only_transaction(connection) as read_only:
            rows = await read_only.fetch(QUERY, table_names, column_names)

    present = {(row["table_name"], row["column_name"]) for row in rows}
    print("Expected columns:")
    for table, column in EXPECTED_COLUMNS:
        state = "present" if (table, column) in present else "MISSING"
        print(f"  {table}.{column} :: {state}")

    missing = [pair for pair in EXPECTED_COLUMNS if pair not in present]
    if missing:
        print(
            f"\n{len(missing)} of {len(EXPECTED_COLUMNS)} columns are missing. "
            "Apply the forward migrations in supabase/migrations instead of patching "
            "the database by hand."
        )
        return 1
    print(f"\nAll {len(EXPECTED_COLUMNS)} expected columns are present.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except DiagnosticConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
