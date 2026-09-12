# Security notice

## Action required: rotate the exposed PostgreSQL password

Earlier revisions of `check_schema.py`, `check_schema2.py`, and `fix_schema.py`
contained a hardcoded Supabase PostgreSQL connection string, including the
database password, and disabled TLS certificate verification.

Those literals have been removed from the working tree. **Removing them from the
files is not sufficient.** Anyone who obtained a copy of the repository, a
clone, a fork, an archive, a build log, or a CI cache still holds a valid
credential until it is rotated.

Complete these steps outside this repository, in this order:

1. **Rotate the database password.** In the Supabase dashboard open
   *Project Settings → Database → Reset database password*. Generate a new
   strong password and record it in your secret manager.
2. **Update every consumer.** Set the new value in `backend/.env.local`
   (`DATABASE_URL`), in your deployment platform's secret store, and in any CI
   secret. Restart the API and workers.
3. **Rotate anything that shared the blast radius.** Reissue the Supabase
   service-role key, `WORKER_SECRET`, and `API_KEY_PEPPER` if there is any chance
   they were committed or logged. Rotating `API_KEY_PEPPER` invalidates existing
   BladeForge API keys, so schedule it and notify affected organizations.
4. **Purge the credential from version-control history.** Rewriting history is a
   destructive operation and is intentionally not automated here. Coordinate with
   everyone who has a clone, then use `git filter-repo`:

   ```bash
   git filter-repo --path check_schema.py --path check_schema2.py --path fix_schema.py --invert-paths
   # or, to keep the files but scrub the string:
   git filter-repo --replace-text secrets-to-redact.txt
   ```

   Force-push the rewritten history, then have every collaborator re-clone.
   GitHub also caches unreachable objects: open a support request to have the
   old blobs purged, or treat the credential as permanently public and rely on
   step 1.
5. **Review access logs.** Check Supabase logs for connections from unexpected
   addresses during the exposure window.

Until step 1 is done, assume the old password is public.

## How diagnostics read credentials now

`tools/db_diagnostics.py` is the only place that opens a diagnostic database
connection. It:

* reads the URL from `BLADEFORGE_DIAGNOSTIC_DATABASE_URL`, falling back to
  `DATABASE_URL`, seeded from the git-ignored `backend/.env.local` if present;
* accepts the SQLAlchemy `postgresql+asyncpg://` scheme and normalises it;
* enables TLS certificate verification (`verify-full`) by default, and requires
  an explicit `BLADEFORGE_DIAGNOSTIC_SSL_MODE=insecure` opt-in plus a printed
  warning to weaken it;
* wraps every diagnostic query in an explicit `read only` transaction;
* refuses write statements unless the operator sets
  `BLADEFORGE_DIAGNOSTIC_ALLOW_WRITES=1` *and* passes `--apply`.

Supabase browser and backend environment-variable names are unchanged.
`NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`,
`SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`, `WORKER_SECRET`, and
`API_KEY_PEPPER` keep their existing meanings.

## Secret handling rules

* Never place a service-role key, database password, worker secret, or API-key
  pepper in a `NEXT_PUBLIC_*` variable. Those are compiled into browser bundles.
* Storage buckets `dataset-files`, `defect-references`, `blade-models`,
  `region-masks`, and `environment-assets` are private. Access is granted only
  through short-lived signed URLs issued after the backend verifies organization
  membership.
* `backend/.env.local`, `render_worker/.env.local`, and `.env*.local` are
  git-ignored. Keep it that way.
* `backend/tests/test_no_hardcoded_credentials.py` fails the build if a
  PostgreSQL URL with an inline password, or a disabled-verification TLS
  pattern, reappears in tracked source.
