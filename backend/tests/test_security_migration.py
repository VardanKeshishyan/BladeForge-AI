from pathlib import Path


def migration() -> str:
    return (
        Path(__file__).parents[2]
        / "supabase"
        / "migrations"
        / "202607230001_initial_mvp.sql"
    ).read_text(encoding="utf-8")


def test_every_organization_resource_has_rls_enabled() -> None:
    sql = migration()
    tables = [
        "organizations",
        "profiles",
        "organization_members",
        "organization_invitations",
        "generation_jobs",
        "job_events",
        "datasets",
        "dataset_files",
        "defect_profiles",
        "api_keys",
        "usage_events",
        "render_workers",
        "webhook_endpoints",
        "webhook_deliveries",
    ]
    for table in tables:
        assert f"alter table public.{table} enable row level security;" in sql


def test_claiming_uses_row_locking_and_onboarding_is_transactional() -> None:
    sql = migration().lower()
    assert "for update skip locked" in sql
    assert "create or replace function public.complete_onboarding" in sql
    assert "on conflict (organization_id, user_id)" in sql
    assert "bladeforge_admin" not in sql


def test_api_key_hash_is_not_granted_to_authenticated_clients() -> None:
    sql = migration().lower()
    assert "grant select on all tables" not in sql
    safe_grant = sql.split("grant select (", 1)[1].split(") on public.api_keys", 1)[0]
    assert "key_hash" not in safe_grant


def test_role_policies_and_cross_organization_guards_exist() -> None:
    sql = migration().lower()
    assert "create policy jobs_select" in sql
    assert "public.is_org_member(organization_id)" in sql
    assert "array['owner', 'administrator', 'engineer']" in sql
    assert "create policy api_keys_manage" in sql
    assert "array['owner', 'administrator']" in sql
