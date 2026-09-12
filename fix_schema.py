"""Report (and, only with an explicit opt-in, apply) additive column reconciliation.

The supported way to change the schema is a forward migration in
supabase/migrations. This script exists for operators who need to inspect a
drifted deployment. It is read-only by default: it reports which additive
statements would be required and changes nothing.

Credentials come from the environment, never from this file. See SECURITY.md and
tools/db_diagnostics.py for configuration.

    py -3.11 fix_schema.py                 # report only, read-only transaction
    BLADEFORGE_DIAGNOSTIC_ALLOW_WRITES=1 py -3.11 fix_schema.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools.db_diagnostics import (  # noqa: E402
    DiagnosticConfigurationError,
    connect,
    read_only_transaction,
    require_write_permission,
)

# Every statement is additive and idempotent: it never drops or rewrites data.
ADDITIVE_STATEMENTS: tuple[tuple[str, str, str], ...] = (
    (
        "organization_members",
        "created_at",
        "alter table public.organization_members "
        "add column if not exists created_at timestamptz not null default now()",
    ),
    (
        "organization_members",
        "updated_at",
        "alter table public.organization_members "
        "add column if not exists updated_at timestamptz not null default now()",
    ),
    (
        "render_workers",
        "registered_at",
        "alter table public.render_workers "
        "add column if not exists registered_at timestamptz not null default now()",
    ),
    (
        "api_keys",
        "expires_at",
        "alter table public.api_keys add column if not exists expires_at timestamptz",
    ),
)

PRESENCE_QUERY = """
    select table_name, column_name
    from information_schema.columns
    where table_schema = 'public'
      and (table_name, column_name) in (
        select * from unnest($1::text[], $2::text[])
      )
"""


async def missing_columns(connection: object) -> list[tuple[str, str, str]]:
    tables = [table for table, _, _ in ADDITIVE_STATEMENTS]
    columns = [column for _, column, _ in ADDITIVE_STATEMENTS]
    rows = await connection.fetch(PRESENCE_QUERY, tables, columns)  # type: ignore[attr-defined]
    present = {(row["table_name"], row["column_name"]) for row in rows}
    return [item for item in ADDITIVE_STATEMENTS if (item[0], item[1]) not in present]


async def main(apply_changes: bool) -> int:
    async with connect() as connection:
        async with read_only_transaction(connection) as read_only:
            outstanding = await missing_columns(read_only)

        if not outstanding:
            print("Schema already contains every expected additive column. Nothing to do.")
            return 0

        print(f"{len(outstanding)} additive change(s) are outstanding:")
        for table, column, statement in outstanding:
            print(f"  {table}.{column}")
            print(f"    {statement};")

        if not apply_changes:
            print(
                "\nReport only. Apply these through supabase/migrations "
                "(`npx supabase db push`) so the repository stays the source of truth. "
                "To apply directly anyway, re-run with --apply and "
                "BLADEFORGE_DIAGNOSTIC_ALLOW_WRITES=1."
            )
            return 1

        require_write_permission("Applying additive schema statements")
        async with connection.transaction():
            for _, _, statement in outstanding:
                await connection.execute(statement)
        remaining = await missing_columns(connection)
        if remaining:
            print(f"\n{len(remaining)} change(s) still missing after apply.")
            return 1
        print(f"\nApplied {len(outstanding)} additive change(s). Verified present.")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the additive statements. Also requires BLADEFORGE_DIAGNOSTIC_ALLOW_WRITES=1.",
    )
    arguments = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(main(arguments.apply)))
    except DiagnosticConfigurationError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
