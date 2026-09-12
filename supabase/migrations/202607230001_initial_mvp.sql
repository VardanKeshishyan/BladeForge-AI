begin;

create extension if not exists pgcrypto;

create type public.organization_role as enum ('owner', 'administrator', 'engineer', 'viewer');
create type public.member_status as enum ('active', 'invited', 'suspended');
create type public.invitation_status as enum ('pending', 'accepted', 'expired', 'revoked');
create type public.job_status as enum (
  'draft',
  'awaiting_worker',
  'queued',
  'rendering',
  'processing_annotations',
  'complete',
  'failed',
  'cancelled'
);
create type public.dataset_status as enum ('pending', 'available', 'archived');
create type public.api_key_status as enum ('active', 'revoked');
create type public.worker_status as enum ('offline', 'healthy', 'busy', 'error');
create type public.webhook_delivery_status as enum ('pending', 'delivered', 'failed');

create table public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(trim(name)) between 2 and 100),
  slug text not null unique check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$' and char_length(slug) between 2 and 63),
  owner_id uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  full_name text check (full_name is null or char_length(full_name) <= 120),
  job_title text check (job_title is null or char_length(job_title) <= 120),
  onboarding_role text check (onboarding_role is null or char_length(onboarding_role) <= 80),
  selected_use_cases text[] not null default '{}',
  organization_id uuid references public.organizations(id) on delete set null,
  onboarding_complete boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.organization_members (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role public.organization_role not null,
  status public.member_status not null default 'active',
  invited_by uuid references auth.users(id) on delete set null,
  joined_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, user_id)
);

create table public.organization_invitations (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  email text not null check (email = lower(email)),
  role public.organization_role not null check (role <> 'owner'),
  token_hash text not null unique,
  status public.invitation_status not null default 'pending',
  invited_by uuid not null references auth.users(id) on delete restrict,
  expires_at timestamptz not null,
  accepted_by uuid references auth.users(id) on delete set null,
  accepted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index organization_invitations_pending_email_idx
  on public.organization_invitations (organization_id, email)
  where status = 'pending';

create table public.render_workers (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references public.organizations(id) on delete cascade,
  name text not null check (char_length(trim(name)) between 2 and 100),
  adapter_type text not null default 'local' check (adapter_type in ('local', 'runpod')),
  status public.worker_status not null default 'offline',
  capabilities jsonb not null default '{}'::jsonb,
  current_job_id uuid,
  last_seen_at timestamptz,
  registered_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.generation_jobs (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  created_by uuid not null references auth.users(id) on delete restrict,
  name text not null check (name ~ '^[[:alnum:]][[:alnum:] _.-]{1,99}$'),
  description text check (description is null or char_length(description) <= 1000),
  status public.job_status not null default 'awaiting_worker',
  config jsonb not null,
  defect_type text not null check (defect_type = 'leading_edge_erosion'),
  severity_min smallint not null check (severity_min between 0 and 99),
  severity_max smallint not null check (severity_max between 1 and 100 and severity_max > severity_min),
  image_count integer not null check (image_count between 1 and 10000),
  image_width integer not null default 1024 check (image_width between 256 and 4096),
  image_height integer not null default 1024 check (image_height between 256 and 4096),
  annotation_format text not null check (annotation_format in ('coco_json', 'yolo_v8')),
  dataset_name text not null check (dataset_name ~ '^[[:alnum:]][[:alnum:] _.-]{1,99}$'),
  estimated_size_bytes bigint not null check (estimated_size_bytes > 0),
  progress smallint not null default 0 check (progress between 0 and 100),
  current_stage text not null default 'awaiting_worker',
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 10),
  worker_id uuid references public.render_workers(id) on delete set null,
  idempotency_key text not null check (char_length(idempotency_key) between 8 and 200),
  locked_at timestamptz,
  heartbeat_at timestamptz,
  cancellation_requested_at timestamptz,
  failure_code text,
  failure_message text,
  started_at timestamptz,
  submitted_at timestamptz not null default now(),
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, idempotency_key)
);

alter table public.render_workers
  add constraint render_workers_current_job_fk
  foreign key (current_job_id) references public.generation_jobs(id) on delete set null;

create index generation_jobs_org_created_idx on public.generation_jobs (organization_id, created_at desc);
create index generation_jobs_claim_idx on public.generation_jobs (status, submitted_at)
  where status in ('awaiting_worker', 'queued');
create index generation_jobs_worker_idx on public.generation_jobs (worker_id, status);

create table public.job_events (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references public.generation_jobs(id) on delete cascade,
  organization_id uuid not null references public.organizations(id) on delete cascade,
  event_type text not null check (char_length(event_type) between 2 and 80),
  message text not null check (char_length(message) between 1 and 1000),
  metadata jsonb not null default '{}'::jsonb,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create index job_events_job_created_idx on public.job_events (job_id, created_at);
create index job_events_org_created_idx on public.job_events (organization_id, created_at desc);

create table public.datasets (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  job_id uuid unique references public.generation_jobs(id) on delete set null,
  created_by uuid not null references auth.users(id) on delete restrict,
  name text not null check (char_length(trim(name)) between 2 and 100),
  defect_type text not null check (defect_type = 'leading_edge_erosion'),
  image_count integer not null check (image_count > 0),
  annotation_formats text[] not null check (cardinality(annotation_formats) > 0),
  file_size_bytes bigint not null default 0 check (file_size_bytes >= 0),
  archive_storage_path text,
  manifest_storage_path text,
  preview_storage_path text,
  status public.dataset_status not null default 'pending',
  validated_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (
    status <> 'available'
    or (archive_storage_path is not null and manifest_storage_path is not null and validated_at is not null)
  )
);

create index datasets_org_created_idx on public.datasets (organization_id, created_at desc);

create table public.dataset_files (
  id uuid primary key default gen_random_uuid(),
  dataset_id uuid not null references public.datasets(id) on delete cascade,
  organization_id uuid not null references public.organizations(id) on delete cascade,
  file_name text not null check (file_name !~ '(^|/)\.\.(/|$)'),
  file_type text not null check (file_type in ('archive', 'image', 'mask', 'annotation', 'manifest', 'metadata', 'readme', 'thumbnail')),
  storage_path text not null unique,
  content_type text not null,
  file_size_bytes bigint not null check (file_size_bytes >= 0),
  checksum_sha256 text not null check (checksum_sha256 ~ '^[a-f0-9]{64}$'),
  created_at timestamptz not null default now()
);

create index dataset_files_dataset_idx on public.dataset_files (dataset_id, created_at);

create table public.defect_profiles (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid references public.organizations(id) on delete cascade,
  created_by uuid references auth.users(id) on delete set null,
  name text not null check (char_length(trim(name)) between 2 and 100),
  defect_type text not null check (defect_type = 'leading_edge_erosion'),
  description text,
  severity_levels text[] not null default array['early', 'moderate', 'severe'],
  surface_parameters jsonb not null,
  reference_image_paths text[] not null default '{}',
  is_system boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((is_system and organization_id is null) or (not is_system and organization_id is not null))
);

create unique index one_system_lee_profile_idx
  on public.defect_profiles (defect_type)
  where is_system;

create table public.api_keys (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  created_by uuid not null references auth.users(id) on delete restrict,
  name text not null check (char_length(trim(name)) between 2 and 100),
  key_prefix text not null unique,
  key_hash text not null unique,
  status public.api_key_status not null default 'active',
  expires_at timestamptz,
  last_used_at timestamptz,
  revoked_at timestamptz,
  revoked_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create index api_keys_org_idx on public.api_keys (organization_id, status);

create table public.usage_events (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  job_id uuid references public.generation_jobs(id) on delete set null,
  event_type text not null check (event_type in (
    'images_generated',
    'render_attempt',
    'gpu_success',
    'gpu_failure',
    'storage_written',
    'dataset_download',
    'api_request'
  )),
  image_count integer not null default 0 check (image_count >= 0),
  gpu_seconds numeric(14,3) not null default 0 check (gpu_seconds >= 0),
  storage_bytes bigint not null default 0,
  metadata jsonb not null default '{}'::jsonb,
  recorded_at timestamptz not null default now()
);

create index usage_events_org_recorded_idx on public.usage_events (organization_id, recorded_at desc);
create index usage_events_job_idx on public.usage_events (job_id);

create table public.webhook_endpoints (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references public.organizations(id) on delete cascade,
  created_by uuid not null references auth.users(id) on delete restrict,
  url text not null check (url ~ '^https://'),
  secret_hash text not null,
  encrypted_secret text not null,
  enabled boolean not null default true,
  failure_count integer not null default 0,
  last_verified_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.webhook_deliveries (
  id uuid primary key default gen_random_uuid(),
  webhook_endpoint_id uuid not null references public.webhook_endpoints(id) on delete cascade,
  organization_id uuid not null references public.organizations(id) on delete cascade,
  job_id uuid references public.generation_jobs(id) on delete set null,
  event_type text not null,
  payload jsonb not null,
  status public.webhook_delivery_status not null default 'pending',
  attempt_count integer not null default 0,
  next_attempt_at timestamptz,
  response_status integer,
  last_error text,
  delivered_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index webhook_deliveries_retry_idx on public.webhook_deliveries (status, next_attempt_at);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

do $$
declare
  table_name text;
begin
  foreach table_name in array array[
    'organizations', 'profiles', 'organization_members', 'organization_invitations',
    'generation_jobs', 'datasets', 'defect_profiles', 'render_workers',
    'webhook_endpoints', 'webhook_deliveries'
  ]
  loop
    execute format(
      'create trigger %I_set_updated_at before update on public.%I for each row execute function public.set_updated_at()',
      table_name,
      table_name
    );
  end loop;
end;
$$;

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.profiles (id, email, full_name)
  values (
    new.id,
    lower(new.email),
    nullif(trim(coalesce(new.raw_user_meta_data ->> 'full_name', '')), '')
  )
  on conflict (id) do update
  set email = excluded.email,
      full_name = coalesce(public.profiles.full_name, excluded.full_name);
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert or update of email, raw_user_meta_data on auth.users
  for each row execute function public.handle_new_user();

create or replace function public.is_org_member(target_org uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.organization_members m
    where m.organization_id = target_org
      and m.user_id = auth.uid()
      and m.status = 'active'
  );
$$;

create or replace function public.has_org_role(target_org uuid, allowed_roles public.organization_role[])
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.organization_members m
    where m.organization_id = target_org
      and m.user_id = auth.uid()
      and m.status = 'active'
      and m.role = any(allowed_roles)
  );
$$;

grant execute on function public.is_org_member(uuid) to authenticated;
grant execute on function public.has_org_role(uuid, public.organization_role[]) to authenticated;

create or replace function public.storage_object_organization(object_name text)
returns uuid
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  segment text;
begin
  segment := (storage.foldername(object_name))[1];
  if segment is null or segment !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$' then
    return null;
  end if;
  return segment::uuid;
end;
$$;

grant execute on function public.storage_object_organization(text) to authenticated;

create or replace function public.complete_onboarding(
  requested_name text,
  requested_slug text,
  requested_role text,
  requested_job_title text,
  requested_use_cases text[]
)
returns public.organizations
language plpgsql
security definer
set search_path = ''
as $$
declare
  current_profile public.profiles;
  created_org public.organizations;
  normalized_name text := trim(requested_name);
  normalized_slug text := lower(trim(requested_slug));
begin
  if auth.uid() is null then
    raise exception using errcode = '42501', message = 'Authentication required';
  end if;

  select * into current_profile
  from public.profiles
  where id = auth.uid()
  for update;

  if current_profile.onboarding_complete and current_profile.organization_id is not null then
    select * into created_org
    from public.organizations
    where id = current_profile.organization_id;
    return created_org;
  end if;

  if char_length(normalized_name) not between 2 and 100 then
    raise exception using errcode = '22023', message = 'Organization name must be 2 to 100 characters';
  end if;
  if normalized_slug !~ '^[a-z0-9]+(?:-[a-z0-9]+)*$' or char_length(normalized_slug) not between 2 and 63 then
    raise exception using errcode = '22023', message = 'Invalid organization slug';
  end if;

  insert into public.organizations (name, slug, owner_id)
  values (normalized_name, normalized_slug, auth.uid())
  returning * into created_org;

  insert into public.organization_members (organization_id, user_id, role, status)
  values (created_org.id, auth.uid(), 'owner', 'active')
  on conflict (organization_id, user_id) do nothing;

  update public.profiles
  set organization_id = created_org.id,
      onboarding_role = nullif(trim(requested_role), ''),
      job_title = nullif(trim(requested_job_title), ''),
      selected_use_cases = coalesce(requested_use_cases, '{}'),
      onboarding_complete = true
  where id = auth.uid();

  return created_org;
exception
  when unique_violation then
    raise exception using errcode = '23505', message = 'Organization slug is already in use';
end;
$$;

grant execute on function public.complete_onboarding(text, text, text, text, text[]) to authenticated;

create or replace function public.claim_generation_job(worker_uuid uuid)
returns public.generation_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
  worker_record public.render_workers;
  claimed public.generation_jobs;
begin
  select * into worker_record
  from public.render_workers
  where id = worker_uuid
  for update;

  if worker_record.id is null or worker_record.status not in ('healthy', 'busy') then
    return null;
  end if;

  select * into claimed
  from public.generation_jobs
  where status in ('awaiting_worker', 'queued')
    and cancellation_requested_at is null
    and attempt_count < max_attempts
    and (organization_id = worker_record.organization_id or worker_record.organization_id is null)
  order by submitted_at
  for update skip locked
  limit 1;

  if claimed.id is null then
    return null;
  end if;

  update public.generation_jobs
  set status = 'queued',
      current_stage = 'accepted_by_worker',
      worker_id = worker_uuid,
      locked_at = now(),
      heartbeat_at = now(),
      attempt_count = attempt_count + 1
  where id = claimed.id
  returning * into claimed;

  update public.render_workers
  set status = 'busy', current_job_id = claimed.id, last_seen_at = now()
  where id = worker_uuid;

  insert into public.job_events (job_id, organization_id, event_type, message, metadata)
  values (
    claimed.id,
    claimed.organization_id,
    'worker_accepted',
    'Render worker accepted the job.',
    jsonb_build_object('worker_id', worker_uuid)
  );

  insert into public.usage_events (organization_id, job_id, event_type, metadata)
  values (
    claimed.organization_id,
    claimed.id,
    'render_attempt',
    jsonb_build_object('attempt', claimed.attempt_count, 'worker_id', worker_uuid)
  );

  return claimed;
end;
$$;

revoke all on function public.claim_generation_job(uuid) from public, anon, authenticated;
grant execute on function public.claim_generation_job(uuid) to service_role;

create or replace function public.recover_stale_jobs(stale_before timestamptz)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  recovered integer;
begin
  with stale as (
    update public.generation_jobs
    set status = case when attempt_count < max_attempts then 'awaiting_worker'::public.job_status else 'failed'::public.job_status end,
        current_stage = case when attempt_count < max_attempts then 'awaiting_worker' else 'failed' end,
        failure_code = case when attempt_count < max_attempts then null else 'worker_stale' end,
        failure_message = case when attempt_count < max_attempts then null else 'Render worker heartbeat expired.' end,
        worker_id = null,
        locked_at = null,
        heartbeat_at = null,
        completed_at = case when attempt_count < max_attempts then null else now() end
    where status in ('queued', 'rendering', 'processing_annotations')
      and heartbeat_at < stale_before
    returning id
  )
  select count(*) into recovered from stale;

  update public.render_workers
  set status = 'offline', current_job_id = null
  where last_seen_at < stale_before;

  return recovered;
end;
$$;

revoke all on function public.recover_stale_jobs(timestamptz) from public, anon, authenticated;
grant execute on function public.recover_stale_jobs(timestamptz) to service_role;

insert into public.defect_profiles (
  name,
  defect_type,
  description,
  severity_levels,
  surface_parameters,
  is_system
) values (
  'Leading Edge Erosion Standard',
  'leading_edge_erosion',
  'Procedural leading-edge erosion for a single composite blade material profile. Severity controls pitting density, erosion depth, roughness, and affected span.',
  array['early', 'moderate', 'severe'],
  '{
    "severity_min": 0,
    "severity_max": 100,
    "pit_density": {"min": 0.08, "max": 0.85},
    "erosion_depth_mm": {"min": 0.1, "max": 3.0},
    "roughness": {"min": 0.35, "max": 0.95},
    "affected_span_fraction": {"min": 0.08, "max": 0.65},
    "blade_material": "gelcoat_composite_v1"
  }'::jsonb,
  true
);

alter table public.organizations enable row level security;
alter table public.profiles enable row level security;
alter table public.organization_members enable row level security;
alter table public.organization_invitations enable row level security;
alter table public.generation_jobs enable row level security;
alter table public.job_events enable row level security;
alter table public.datasets enable row level security;
alter table public.dataset_files enable row level security;
alter table public.defect_profiles enable row level security;
alter table public.api_keys enable row level security;
alter table public.usage_events enable row level security;
alter table public.render_workers enable row level security;
alter table public.webhook_endpoints enable row level security;
alter table public.webhook_deliveries enable row level security;

create policy organizations_select on public.organizations for select
  using (public.is_org_member(id));
create policy organizations_update on public.organizations for update
  using (public.has_org_role(id, array['owner', 'administrator']::public.organization_role[]))
  with check (public.has_org_role(id, array['owner', 'administrator']::public.organization_role[]));

create policy profiles_select on public.profiles for select
  using (id = auth.uid() or (organization_id is not null and public.is_org_member(organization_id)));
create policy profiles_update_self on public.profiles for update
  using (id = auth.uid())
  with check (id = auth.uid());

create policy members_select on public.organization_members for select
  using (public.is_org_member(organization_id));
create policy members_manage on public.organization_members for all
  using (public.has_org_role(organization_id, array['owner', 'administrator']::public.organization_role[]))
  with check (public.has_org_role(organization_id, array['owner', 'administrator']::public.organization_role[]));

create policy invitations_manage on public.organization_invitations for all
  using (public.has_org_role(organization_id, array['owner', 'administrator']::public.organization_role[]))
  with check (public.has_org_role(organization_id, array['owner', 'administrator']::public.organization_role[]));

create policy jobs_select on public.generation_jobs for select
  using (public.is_org_member(organization_id));
create policy jobs_mutate on public.generation_jobs for all
  using (public.has_org_role(organization_id, array['owner', 'administrator', 'engineer']::public.organization_role[]))
  with check (public.has_org_role(organization_id, array['owner', 'administrator', 'engineer']::public.organization_role[]));

create policy events_select on public.job_events for select
  using (public.is_org_member(organization_id));

create policy datasets_select on public.datasets for select
  using (public.is_org_member(organization_id));
create policy files_select on public.dataset_files for select
  using (public.is_org_member(organization_id));

create policy defects_select on public.defect_profiles for select
  using (is_system or public.is_org_member(organization_id));
create policy defects_manage on public.defect_profiles for all
  using (
    not is_system
    and public.has_org_role(organization_id, array['owner', 'administrator']::public.organization_role[])
  )
  with check (
    not is_system
    and public.has_org_role(organization_id, array['owner', 'administrator']::public.organization_role[])
  );

create policy api_keys_manage on public.api_keys for all
  using (public.has_org_role(organization_id, array['owner', 'administrator']::public.organization_role[]))
  with check (public.has_org_role(organization_id, array['owner', 'administrator']::public.organization_role[]));

create policy usage_select on public.usage_events for select
  using (public.is_org_member(organization_id));

create policy workers_select on public.render_workers for select
  using (organization_id is null or public.is_org_member(organization_id));
create policy workers_manage on public.render_workers for all
  using (
    organization_id is not null
    and public.has_org_role(organization_id, array['owner', 'administrator']::public.organization_role[])
  )
  with check (
    organization_id is not null
    and public.has_org_role(organization_id, array['owner', 'administrator']::public.organization_role[])
  );

create policy webhooks_manage on public.webhook_endpoints for all
  using (public.has_org_role(organization_id, array['owner', 'administrator']::public.organization_role[]))
  with check (public.has_org_role(organization_id, array['owner', 'administrator']::public.organization_role[]));
create policy webhook_deliveries_select on public.webhook_deliveries for select
  using (public.is_org_member(organization_id));

insert into storage.buckets (id, name, public, file_size_limit)
values
  ('dataset-files', 'dataset-files', false, 5368709120),
  ('defect-references', 'defect-references', false, 52428800)
on conflict (id) do update set public = false;

create policy dataset_storage_select on storage.objects for select to authenticated
  using (
    bucket_id = 'dataset-files'
    and public.is_org_member(public.storage_object_organization(name))
  );

create policy defect_storage_select on storage.objects for select to authenticated
  using (
    bucket_id = 'defect-references'
    and public.is_org_member(public.storage_object_organization(name))
  );

grant select on public.organizations to authenticated;
grant select on public.profiles to authenticated;
grant select on public.organization_members to authenticated;
grant select on public.generation_jobs to authenticated;
grant select on public.job_events to authenticated;
grant select on public.datasets to authenticated;
grant select on public.dataset_files to authenticated;
grant select on public.defect_profiles to authenticated;
grant select on public.usage_events to authenticated;
grant select on public.render_workers to authenticated;
grant select (
  id, organization_id, created_by, name, key_prefix, status, expires_at,
  last_used_at, revoked_at, revoked_by, created_at
) on public.api_keys to authenticated;

commit;
