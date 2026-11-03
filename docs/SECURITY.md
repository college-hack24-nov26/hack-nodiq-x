# Security Requirements — NODIQ-X

Security posture and rules for any change touching auth, data, or infrastructure.
The verified baseline is documented in `docs/FINAL_SECURITY_REPORT.md`; rotation
procedures in `docs/SECURITY_ROTATION.md`; hosting setup in `docs/HOSTING_CHECKLIST.md`.

---

## Authentication

- All analysis, report, batch, copilot, and admin routes require a valid session.
- Sessions are **HttpOnly cookie JWTs** — `HttpOnly`, `Secure` in production,
  `SameSite=Lax`, `Path=/`, `Max-Age=604800` (7-day policy).
- Tokens are **never** returned in API JSON, stored in JavaScript, or logged.
- Logout revokes the token server-side **and** clears the cookie.
- JWT secret rotation invalidates all sessions — intentional deployment action only.
- Password reset tokens are a separate family; they can never authenticate as sessions.
- Firebase (Google/email/phone) verifies client-side; the backend verifies the
  Firebase ID token before issuing any session.

## Authorization

- Every resource access checks ownership **server-side**, per user — never from
  client-supplied identity.
- **Role-Based Access Control (RBAC foundation, IMPLEMENTED):** every account has
  a server-stored role — `operator` (default; upload/analyze/history/reports),
  `reviewer` (adds electronic sign-off on analyses), `admin` (adds role
  administration via `GET /api/admin/users` and
  `POST /api/admin/users/<id>/role`). Authorization is derived server-side from
  the stored role plus the `NODIQ_ADMIN_EMAILS` / `NODIQ_REVIEWER_EMAILS`
  environment allow-lists (bootstrap/elevation path); clients can never send a
  role (rejected globally by the body validator). A last-admin lockout guard
  prevents removing the only admin.
- Reviewer identity for sign-offs is derived from the session, never the request body.
- Regression gates: `tests/test_ownership_isolation.py` and
  `tests/test_security_hardening.py` must stay green.

## Secrets

- Secrets live only in environment variables / hosting provider config.
- `.env` is never committed; `.env.example` contains placeholders only.
- Never print, log, or expose: API keys, SMTP credentials, JWT secrets, Firebase
  private keys, OTP codes, phone numbers, or session tokens.
- Never place provider keys in frontend code — Firebase web config is public by
  design; everything else is server-side.
- Rotation runbook: `docs/SECURITY_ROTATION.md` (Groq, Gmail app password, JWT,
  Firebase) — executed manually at deployment.

## Database

- SQLite with per-user scoping on every query; no raw string-built SQL
  (parameterized statements only — audited).
- Backups and the production DB never enter the repo or Docker image.
- **Backup / recovery (documented, manual):** see `docs/DEPLOY_SUPABASE.md`
  (Supabase PostgreSQL automatic daily backups + point-in-time recovery;
  Storage bucket contents via `migrate_to_supabase.py` re-sync; local SQLite:
  stop the server, copy `server_data/` — the DB, `secret.key` and uploads —
  then restart). Restore is a reverse of the same steps; schema changes are
  additive-only (no destructive migrations).

## Input

- All user input validated server-side (type, length, format, range).
- Malicious-payload rejection is regression-tested (`tests/test_input_security.py`).

## APIs

- Validate request bodies and parameters on every endpoint.
- **CSRF / Origin protection (IMPLEMENTED):** every state-changing `/api/*`
  request (POST/PUT/PATCH/DELETE) must name a trusted origin. An Origin or
  Referer is checked against the CORS allow-list + `CSRF_TRUSTED_ORIGINS` + the
  request's own host (scheme-insensitive, so TLS-terminating proxies work);
  `Origin: null` never matches; a browser `Sec-Fetch-Site: cross-site` request
  with no origin headers is rejected too. Rejections are **403** and
  audit-logged (`csrf_rejected`). Bearer-token API clients are exempt (a header
  credential is not ambient); non-browser clients without a session cookie are
  not CSRF-capable and keep working — login/logout, `/api/analyze` and normal
  browser usage are regression-tested. This sits on top of (not instead of)
  SameSite=Lax and the JSON-only body contract.
- CORS: explicit allowed origins only — never wildcard with credentials.
- Rate limiting on auth and sensitive routes (shared-worker tested); never weakened.

## File Uploads

Validate before acceptance (order matters — cheap checks first):

- **Size** — 25 MB request cap at the WSGI layer (413) + per-file cap (413)
- **Type** — magic-byte allow-list: PNG / JPEG / TIFF / BMP only (415)
- **Declared MIME** — client-controlled, cross-checked for the audit trail only
  (`upload_mime_mismatch`); never used to accept or reject
- **Dimensions** — parsed from the container header WITHOUT decoding, before any
  allocation: per-side ≤ 20,000 px, pixel area ≤ 50 MP (decompression-bomb
  guard; 400). Backed by `OPENCV_IO_MAX_IMAGE_PIXELS` on every decode path.
- **Decode** — real decode in the request (400 on failure); the microstructure
  validity gate stays the scientific engine's job
- **Filename** — never trusted: uploads are stored under a server-generated
  content hash with a content-derived extension; the client name is sanitized
  for display only
- **Path safety** — persisted-upload paths resolve inside `server_data/uploads/`
  or the file is not served (`suspicious_path` audit event); dataset files are
  exactly `micrograph_NNNN.png` on every serving route

Regression gates: `tests/test_input_security.py`, `tests/test_security_hardening.py`.

## Analysis Abuse Protection

`POST /api/analyze` — the most expensive endpoint (a full engine pass per
accepted request) — carries its own budget on top of the per-account
concurrency cap:

- **What is limited** — `POST /api/analyze` only. Health/status, static
  assets, normal GETs, and the camera-agent endpoints are never rate limited.
- **Limiter key** — the authenticated user id (bucket `/api/analyze|user:<id>`);
  unauthenticated callers (rejected 401 before any work) are IP-bucketed
  (`/api/analyze|ip:<ip>`) as a mop. Client-supplied headers are never the
  sole identity — the socket peer is used unless `TRUST_PROXY=true`.
- **Storage** — the same shared SQLite sliding-window limiter as the auth
  routes (`services/rate_limit.py`): counters are shared across ALL Gunicorn
  workers, survive a worker restart, and fail CLOSED if the store is
  unavailable. This is NOT an in-memory limiter; there is no Redis.
- **Configuration** —
  - `NODIQ_ANALYZE_RATE_LIMIT` — requests per window (default `30`;
    `0` disables)
  - `NODIQ_ANALYZE_RATE_WINDOW` — window seconds (default `300`)
  - `NODIQ_ANALYZE_MAX_CONCURRENCY` — per-account analyses in flight
    (default `2`)
  - `NODIQ_ANALYZE_TIMEOUT` — wall-clock cap per analysis job in seconds
    (default `0` = unlimited, the historic behavior). `>0` arms a watchdog:
    thread mode flips the job to an honest failed record at the deadline;
    child mode SIGTERMs the child (SIGKILL after a 60 s grace) — freeing the
    concurrency slot the job would otherwise hold forever.
- **429 behavior** — `Retry-After` (seconds) + a generic JSON error. No
  internals leak (no bucket keys, store layout, or remaining quota).
  Saturation of the per-account concurrency cap returns 429 with the same
  header and is audit-logged (`analysis_concurrency_limited`); limit
  exceeded events are audit-logged (`rate_limited`).

Regression gates: `tests/test_analyze_rate_limit.py`,
`tests/test_rate_limit_shared.py`.

## Frontend

- CSP **enforced**: `default-src 'self'`; no `unsafe-inline`/`unsafe-eval` scripts;
  Firebase bootstrap via exact hash. Policy changes need re-verification across
  the full journey.
- No `dangerouslySetInnerHTML` for user/AI content (rich text renders as React nodes).
- Security headers, HSTS (behind trusted proxy), and TRUST_PROXY settings follow
  `docs/HOSTING_CHECKLIST.md` — never enabled blindly.

## Incidents & Change Control

- Any suspected secret exposure → rotate per runbook immediately.
- Security-relevant changes require the full suite + live smoke (23/23) before merge.
- New endpoints handling auth/uploads need threat consideration in the PR description.
