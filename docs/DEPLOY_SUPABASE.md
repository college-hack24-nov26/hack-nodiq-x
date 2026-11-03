# NODIQ-X — Supabase Persistence Deployment Guide

This migration moves all persistent state off Render's ephemeral disk:

| Before (ephemeral)                       | After (persistent)                |
|------------------------------------------|-----------------------------------|
| `server_data/nodiq.db` (SQLite)          | Supabase PostgreSQL               |
| `server_data/analyses_full/*.json`       | `full_payloads` table             |
| `server_data/uploads/`, `*_annotated.png`, `*_mask.png` | Supabase Storage (private bucket) |

Nothing else changes: same API routes, same frontend, same Firebase auth,
same nodularity engine.

## 1. Create the Supabase project

1. Create a project at <https://supabase.com> (free tier is sufficient to start).
2. **Database connection string** — Project Settings → Database → Connection
   string → choose the **Transaction pooler (port 6543)** URI. Its shape is:
   ```
   postgresql://<user>:<password>@<pooler-host>:6543/postgres
   ```
   e.g. user `postgres.<ref>`, host `aws-0-<region>.pooler.supabase.com`.
   Use this as `DATABASE_URL`. (The direct port-5432 URI also works but the
   pooler handles Render's worker model more gracefully.)
3. **API keys** — Project Settings → API:
   - `Project URL` → `SUPABASE_URL`
   - `service_role` key → `SUPABASE_SERVICE_ROLE_KEY`
     ⚠️ The service-role key bypasses row-level security. It is used
     SERVER-SIDE ONLY (Flask + analysis child). Never add it to the React
     build, never prefix it with `VITE_`, never commit it.

## 2. Create the private storage bucket

In the Supabase dashboard → Storage → New bucket:

- Name: `nodiq-artifacts` (or set `SUPABASE_BUCKET` to your own name)
- **Public bucket: OFF** — artifacts are served exclusively through
  ownership-checked Flask routes (`/api/analyses/<id>/artifact/<kind>`).
  Do NOT create public policies for this bucket.

Alternatively create it from the machine running the migration:

```bash
curl -X POST "$SUPABASE_URL/storage/v1/bucket" \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"nodiq-artifacts","public":false}'
```

## 3. One-time data migration (existing Render data)

Run from any machine that has the current `server_data/` directory
(download it from the Render service shell first if needed):

```bash
export NODIQ_BACKEND=supabase
export DATABASE_URL="postgresql://...pooler...:6543/postgres"
export SUPABASE_URL="https://<ref>.supabase.co"
export SUPABASE_SERVICE_ROLE_KEY="<service-role key>"
# point at the legacy data (defaults to ./server_data)
export NODIQ_DATA_DIR=/path/to/server_data

python migrate_to_supabase.py            # migrate
python migrate_to_supabase.py --verify   # row-count verification
```

The tool is idempotent — rerun freely; it upserts by primary key, preserves
analysis IDs and ownership, uploads artifacts that are missing from the
bucket, and never deletes the SQLite source.

## 4. Render environment variables

Add to the existing Render service (Settings → Environment) — do NOT create
a second service. (The `render.yaml` Blueprint already declares all of these;
Blueprint users only fill in the two `sync: false` secrets.)

```
NODIQ_BACKEND=supabase
DATABASE_URL=postgresql://<user>:<password>@<pooler-host>:6543/postgres
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role key>
SUPABASE_BUCKET=nodiq-artifacts
```

Render redeploys automatically on the next `main` push. Verify after boot:

```bash
curl -s https://nodiq.onrender.com/api/health
# expect: "persistence":"supabase", "artifact_storage":{"backend":"supabase",...}
```

If `persistence` shows `sqlite`, the env vars did not reach the service —
fix that before trusting any data on the site.

## 5. Restart-persistence check (the point of the whole migration)

1. Create a test account and run one analysis on the live site.
2. In the Render dashboard press **Manual Deploy → Deploy latest commit**
   (or wait for the next automatic one).
3. After redeploy: log in with the SAME account — history, analysis result,
   annotated image, mask and report must all still be there.

Before this migration everything lived on Render's ephemeral disk and was
wiped by every deploy/restart; after it, only transient caches (rate-limit
counters, warm payload cache) are local by design.

## 6. What stays local (by design)

- **Rate-limit counters** — brute-force protection budgets are transient by
  nature; they persist in the DB on the supabase backend and reset on
  redeploy otherwise. Not user data.
- **Temporary processing files** during an analysis run (cleaned up by the
  child process lifecycle).
- **Warm payload cache** — a mirror of what Postgres already stores.

## 7. Rollback

Set `NODIQ_BACKEND=sqlite` (or remove the var) and redeploy: the app
returns to the pre-migration behavior. SQLite files were never deleted by
the migration tool, and Supabase data is untouched by rolling back.

## 8. Backup & recovery

**Supabase PostgreSQL (production):** backups are handled by the Supabase
Dashboard (Database → Backups): daily automatic backups plus point-in-time
recovery on paid plans. Restore = restore the snapshot / pick the PITR moment
in the dashboard — no app changes needed (schema is created idempotently at
boot). The service-role key and DATABASE_URL are credentials: they live only
in Render's environment, never in the repo, and are rotated manually per
`docs/SECURITY_ROTATION.md`.

**Supabase Storage (analysis artifacts):** objects live in the private
`nodiq-artifacts` bucket under `users/<user_id>/analyses/<analysis_id>/...`.
For a bucket-level recovery, re-upload from any surviving source with
`python migrate_to_supabase.py` (it re-reads local `server_data/uploads` and
the DB records). The bucket is never public: every read goes through an
ownership-gated Flask route.

**Local SQLite (development):** stop the server, copy the whole
`server_data/` directory (contains `nodiq.db` + WAL files, `secret.key`,
uploads and the security log), restart. Restoring is copying it back. The
`secret.key` MUST be included — without it every existing session token fails
signature verification and all users are logged out.

**Rules:** schema changes are additive-only (`CREATE TABLE IF NOT EXISTS` /
`ADD COLUMN`); never run destructive SQL against production; test restores
against a scratch project, not the live one.
