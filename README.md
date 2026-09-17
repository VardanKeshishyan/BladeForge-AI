# BladeForge AI

Link: https://bladeforge.vardan.app/

BladeForge AI is an open-source synthetic data generation platform for creating customizable 3D environments and datasets to train AI and robotic systems. It gives users control over models, defects, weather, lighting, camera positions, and environmental conditions to generate data tailored to their specific projects:

- Leading-edge erosion on `gelcoat_composite_v1`
- COCO JSON and YOLO v8 exports
- RGB images, pixel-aligned binary masks, mask-derived boxes, and per-image metadata
- A PostgreSQL-backed worker queue with real Blender progress
- Private Supabase Storage objects and short-lived signed downloads

Additional defect types, billing, webhooks, hosted GPU capacity, SDK packages, and
RunPod dispatch are intentionally not represented as available.

## Architecture

The existing Next.js 16 app remains the customer interface. Supabase Auth owns user
sessions; the browser sends only the user's access token to FastAPI. FastAPI verifies
the JWT signature through the project's JWKS endpoint, loads organization membership,
enforces roles, validates mutations, and talks to PostgreSQL and private Storage with
server-only credentials.

FastAPI writes generation jobs as `awaiting_worker`. A worker secured by
`X-Worker-Secret` registers and claims one job through a PostgreSQL
`FOR UPDATE SKIP LOCKED` function. A local adapter starts Blender only for the claimed
job. Blender writes a validated package to a shared worker volume. FastAPI uploads the
validated archive, manifest, and preview, creates dataset records in a transaction,
and removes uploaded objects if database finalization fails.

Important directories:

```text
app/                 Existing Next.js interface
lib/api/             Authenticated browser and server API clients
backend/app/         FastAPI configuration, auth, routes, repositories, and services
backend/tests/       Unit/security tests and opt-in Blender E2E
render_worker/       Polling worker and local/RunPod adapter boundary
render_engine/       Headless Blender procedural renderer
supabase/migrations/ PostgreSQL schema, functions, RLS, buckets, and seed profile
```

## 1. Create Supabase

1. Create a Supabase project.
2. In Authentication settings, add these redirect URLs:

   ```text
   http://localhost:3000/auth/callback
   http://localhost:3000/auth/reset-password
   ```

3. For production, add the equivalent HTTPS URLs for the deployed frontend.
4. Keep email confirmation enabled unless the project deliberately uses another
   verified signup policy.

The migration creates the two private buckets, `dataset-files` and
`defect-references`. Do not make either bucket public.

## 2. Apply the database migration

Install or invoke the Supabase CLI, link the repository, then push:

```bash
npx supabase login
npx supabase link --project-ref YOUR_PROJECT_REF
npx supabase db push
```

For a local Supabase stack:

```bash
npx supabase start
npx supabase db reset
```

The migration creates every application table, the Auth profile trigger,
transactional/idempotent onboarding, organization role helpers, complete RLS,
private Storage policies, stale-job recovery, and the atomic job claim function.

## 3. Configure the frontend

Create `.env.local` from [.env.example](.env.example):

```dotenv
NEXT_PUBLIC_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=YOUR_ANON_KEY
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_DEV_SUPABASE_REDIRECT_URL=http://localhost:3000/auth/callback
```

Only the Supabase URL, anon key, and public API URL belong in the frontend
environment. Never add the service-role key, database password, worker secret,
API-key pepper, or RunPod key to a `NEXT_PUBLIC_*` variable.

Run the UI:

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

## 4. Configure FastAPI

Create `backend/.env.local` from
[backend/.env.example](backend/.env.example). Generate independent strong values:

```powershell
py -3.11 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Use one value for `WORKER_SECRET` and a different value for `API_KEY_PEPPER`.
The PostgreSQL URL must use the `postgresql+asyncpg://` scheme.

Python 3.11 is the deployment target:

```bash
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[dev]"
cd backend
..\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

On macOS/Linux, replace the executable paths with `.venv/bin/...`.

Health and documentation:

```text
GET http://localhost:8000/health
GET http://localhost:8000/ready
http://localhost:8000/docs
http://localhost:8000/openapi.json
```

## 5. Run the local Blender worker

Install Blender 4.x and make `blender` available on `PATH`. Create
`render_worker/.env.local` from
[render_worker/.env.example](render_worker/.env.example). Its `WORKER_SECRET` must
match the backend.

Install the worker package and start polling:

```bash
.\.venv\Scripts\python.exe -m pip install -e .\render_worker
cd render_worker
..\.venv\Scripts\python.exe -m bladeforge_worker.main
```

The equivalent direct Blender command is:

```bash
blender --background --python render_engine/main.py -- --job-file PATH_TO_JOB_JSON
```

The worker starts Blender only after claiming a real job and returns to polling after
completion. It does not use a timer to simulate progress.

## 6. Docker development

Create the backend and worker `.env.local` files, then run:

```bash
docker compose up --build
```

The API and worker share only the `/work` output volume. PostgreSQL and Storage remain
in the configured Supabase project.

## 7. Submit and download a small test job

1. Sign up and confirm the email.
2. Complete onboarding once.
3. Start the API and worker.
4. Open **New Generation**.
5. Submit 2-10 images, `Leading Edge Erosion`, and `COCO JSON`.
6. Follow real progress and events on Job Detail.
7. When validation finishes, open Datasets and use Download.

The browser requests a short-lived URL only after FastAPI verifies membership in the
dataset's organization.

External API example:

```bash
curl "$BLADEFORGE_API_URL/v1/external/jobs" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Idempotency-Key: YOUR_UNIQUE_REQUEST_ID" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Small erosion batch",
    "defect_type": "leading_edge_erosion",
    "severity_min": 20,
    "severity_max": 60,
    "image_count": 2,
    "annotation_format": "coco_json",
    "dataset_name": "small-erosion-batch",
    "config": {
      "lighting_preset": "overcast",
      "camera_fov": 45,
      "image_width": 512,
      "image_height": 512
    }
  }'
```

## Roles and account deletion

- `owner` and `administrator`: organization, members, invitations, API keys, workers,
  and defect profiles
- `engineer`: create, cancel, retry, duplicate, and read jobs and datasets
- `viewer`: read jobs and datasets only

An owner cannot delete their account while other active organization members exist.
Ownership must be transferred first. A sole-member owner's organization is removed
before the Auth account; a non-owner leaves the organization. Deletion requires a
Supabase token issued within the last ten minutes.

## Verification

```bash
npx tsc --noEmit
npm run lint
npm run build
cd backend
..\.venv\Scripts\ruff.exe check app tests
..\.venv\Scripts\mypy.exe app
..\.venv\Scripts\python.exe -m pytest -q
```

The Blender E2E is deliberately opt-in because it launches the real renderer:

```powershell
$env:BLADEFORGE_E2E = "1"
..\.venv\Scripts\python.exe -m pytest -q tests/test_blender_e2e.py
```

## Optional integrations

Email invitations activate only when `RESEND_API_KEY` and
`INVITATION_FROM_EMAIL` are configured. Otherwise the Team interface explains why
the action is disabled.

The RunPod adapter boundary is present, but dispatch is disabled until endpoint and
callback verification are implemented and configured. Webhooks and billing are also
reported as unavailable by `/v1/capabilities`.
