# NODIQ-X — Security Hardening Phase Report

Phase: security hardening of the existing NODIQ-X application.
Hardware: MATRIX VISION camera + metallurgical microscope were **NOT available**
during this phase; nothing below claims hardware validation.

Baseline protection honored: `nodularity_pipeline.py`, all thresholds,
morphology, ISO/JIS calculations and calibration mathematics were **not
modified** by this phase. Pre-existing uncommitted work from earlier phases
was left untouched.

---

## 1. Security controls implemented

| # | Control | Status | Where |
|---|---------|--------|-------|
| 1 | CSRF / Origin protection (403 on reject; login/logout/analyze intact) | IMPLEMENTED | `server.py` `_csrf_protect` before_request + tests |
| 2 | Strict upload validation (magic bytes, decode, dimensions, size; MIME cross-checked) | IMPLEMENTED | `server.py` `_check_image`/`_image_dimensions`; 25 MB cap unchanged |
| 3 | Path traversal protection (safe server-side filenames + containment) | IMPLEMENTED (uploads were already hash-named; containment + dataset allow-list added) | `server.py` `_stored_upload_path`, `dataset_static` |
| 4 | RBAC foundation (operator / reviewer / admin, server-authoritative) | IMPLEMENTED (minimal foundation) | `services/auth.py`, `server.py` `require_role`, admin endpoints |
| 5 | Secret management audit | VERIFIED (no changes needed; `.env` gitignored, no secrets in source/bundle/logs — regression-tested) | `tests/test_secrets_hygiene.py` |
| 6 | Production HTTPS/TLS readiness | VERIFIED (Secure cookie auto over HTTPS, HSTS over HTTPS/trusted-proxy only; localhost unaffected) — browser deployment validation **Deferred — hardware unavailable during this phase** | `server.py` `_cookie_secure`, `_add_security_headers` |
| 7 | Security HTTP headers (nosniff, frame DENY, Referrer-Policy, Permissions-Policy, enforced CSP, HSTS) | ALREADY IMPLEMENTED + verified live; CSP preserved untouched | `server.py` `_SECURITY_HEADERS` |
| 8 | Camera agent review (bind/CORS/methods/errors/no secrets) | CODE/CONFIGURATION REVIEWED — NOT physically validated | see §8 |
| 9 | Security audit logging (login/authz/CSRF/upload/rate-limit/admin/review/token-revocation) | IMPLEMENTED — extended categories; never logs secrets | `services/seclog.py` consumers |
| 10 | Session security (expiry, rotation, logout invalidation, Secure cookie, deleted-session revocation) | IMPLEMENTED (deleted-session check added; rest verified) | `server.py` `_current_user` |
| 11 | Dependency audit (Python / npm / camera agent) | COMPLETE — findings documented, no blind upgrades | §7, §11 |
| 12 | Database / data protection (backup/recovery doc, additive-only migrations, credentials in env) | IMPLEMENTED (documentation + additive role migration) | `docs/DEPLOY_SUPABASE.md` §8 |

## 2. Files changed (this phase)

- [server.py](../server.py) — CSRF/Origin gate; upload dimension/decompression guards
  + MIME cross-check audit; `require_role`; admin role endpoints; review RBAC;
  audit-log events; deleted-session token check; stored-path containment;
  dataset route allow-list; logout token-revocation logging.
- [services/auth.py](../services/auth.py) — `role` column (additive migration,
  sqlite + Postgres via pgcompat); `ROLES`/`effective_role`/`set_role`/
  `list_users`; env allow-list bootstrap (`NODIQ_ADMIN_EMAILS`,
  `NODIQ_REVIEWER_EMAILS`); role in all user payloads.
- [tests/test_ownership_isolation.py](../tests/test_ownership_isolation.py) —
  adapted to RBAC (foreign review: operator → 403; reviewer still 404 on
  another user's analysis; fixture now captures uid/email/role).
- [docs/SECURITY.md](../docs/SECURITY.md) — RBAC, CSRF, upload, DB sections updated.
- [docs/NODIQ-X_System_Architecture.md](../docs/NODIQ-X_System_Architecture.md) —
  "SECURITY — CROSS-CUTTING" section (IMPLEMENTED markers + hardware deferrals).
- [docs/DEPLOY_SUPABASE.md](../docs/DEPLOY_SUPABASE.md) — §8 Backup & recovery.

## 3. Files added (this phase)

- [tests/test_security_hardening.py](../tests/test_security_hardening.py) — 31 regression tests.
- [docs/SECURITY_HARDENING_PHASE_REPORT.md](../docs/SECURITY_HARDENING_PHASE_REPORT.md) — this report.

## 4. Tests executed

- Full pytest suite: **329 passed, 0 failed** (783 s) — baseline 298 (incl. 56
  analysis-pinning tests) + 31 new hardening tests.
- `npx oxlint src`: **0 errors** (26 pre-existing warnings, unchanged).
- `npm run build`: **success**.
- Live server smoke (Flask :8001, real DB): 20+ curl checks (§6).
- `pip-audit -r requirements.txt --no-deps`: **no known vulnerabilities**.
- `npm audit` (nodiq-x): **4 high** — one transitive advisory (§7).
- Camera agent: bind/method/CORS probe on the static `/` endpoint only.

## 5. Test results (key hardening cases proven)

- Untrusted `Origin`/`Referer`/`Origin: null`/`Sec-Fetch-Site: cross-site` on
  state-changing API → **403 + `csrf_rejected` audit event**.
- Trusted origins (CORS allow-list, own host) and Bearer API clients pass;
  login, logout, `/api/analyze`, `/api/feedback` unaffected.
- 100 000×100 000 PNG header in a 90-byte file → **400 before any decode**
  (decompression bomb); 64 MP declaration → 400; 5 MP micrographs unaffected.
- Garbage bytes as `.png` → 415; 26 MB upload → 413; valid PNG → 202.
- `/dataset/../server.py`, encoded dot-dot, backslash, absolute paths, subdirs,
  wrong extensions → never dataset bytes (404 / SPA fallback); legitimate
  `micrograph_NNNN.png` → 200.
- Tampered `stored_path` outside `server_data/uploads` → never served.
- Operator review → 403 (+`authz_failed`); reviewer/admin review → 200;
  non-admin role management → 403; invalid role → 400; last-admin demotion
  blocked; `NODIQ_ADMIN_EMAILS` elevation works and disappears with the env var.
- Tokens bound to a deleted work session → 401.
- Logout revokes server-side (stolen token re-presentation → 401).
- Upload path vs direct engine path on the live server: **identical results**
  (micrograph_0001: count 34, ISO 19.09 %, JIS 59.41 %, self-check 100 %).
- Audit log contains all new categories and **no passwords/tokens/keys**.

## 6. Existing functionality verified (no behavior change)

- Auth (login/logout/me, HttpOnly SameSite=Lax Max-Age=604800 cookie, Secure
  auto over HTTPS), history (`/api/analyses`), reports, dataset endpoints,
  feedback, uploads, `/api/analyze` (202 + poll → completed) — live-verified.
- Analysis results unchanged: 56 pinning tests green + live parity check
  (upload == direct engine run).
- Frontend untouched this phase: oxlint 0 errors, build success.
- Cross-site browser usage: same-origin POSTs always carry a trusted Origin.

## 7. Security vulnerabilities discovered & remediation

1. **Decompression-bomb exposure** (high, fixed): any authenticated user could
   upload a tiny file declaring a gigantic canvas; decode happened before any
   size sanity → worker OOM / DoS. Fixed: header-level caps before decode +
   `OPENCV_IO_MAX_IMAGE_PIXELS=50 MP` backstop.
2. **No CSRF/Origin enforcement** (high, fixed): cookie-authenticated
   state-changing endpoints relied on SameSite=Lax only. Fixed: origin gate,
   403 + audit.
3. **Deleted-session tokens kept authenticating** (medium, fixed): deleting a
   work session did not invalidate the login bound to it. Fixed: sid
   existence check in `_current_user`.
4. **Missing RBAC** (medium, fixed): any account could perform electronic
   sign-off. Fixed: reviewer/admin-only review; role administration admin-only.
5. **Dataset static route over-broad** (low, fixed): `/dataset/<path>` served
   any file in the dataset directory. Now allow-listed to `micrograph_NNNN.png`
   with `suspicious_path` auditing.
6. **stored_path trusted from DB records** (low, fixed): file-serving routes
   trusted `record.stored_path`; now contained to the uploads directory.
7. **Transitive npm advisory** (high severity, LOW practical impact, open):
   `@grpc/grpc-js <1.13.6` (GHSA-m9gg-hp2v-232j, CWE-295) enters via
   `@firebase/firestore@4.17.2` ← `firebase@12.19.0`. NODIQ-X imports **only**
   `firebase/app` + `firebase/auth`; Firestore is never imported, so the
   vulnerable code is not exercised at runtime. NOT auto-upgraded (per phase
   rules); remediation in §11.

## 8. Camera-agent code review findings

Scope: `nodiq-camera-agent/agent_server.py`, `camera.py`, `config.py` + a
hardware-free configuration probe (static `/` endpoint only — no capture,
no preview, no device open).

- **Binding:** `ThreadingHTTPServer(("127.0.0.1", port))` — loopback only;
  live `netstat` shows `127.0.0.1:8765 LISTENING`, never `0.0.0.0`. ✔
- **CORS:** strict allow-list membership check (`CAMERA_AGENT_ALLOWED_ORIGINS`,
  default `localhost/127.0.0.1:5173`, extendable via
  `NODIQ_CAMERA_ALLOWED_ORIGINS`, never a wildcard). Verified: untrusted
  Origin → no `Access-Control-Allow-*` headers emitted; trusted Origin →
  echoed + `Access-Control-Allow-Methods: GET, OPTIONS`. ✔
- **Methods:** only `GET` and `OPTIONS` implemented; POST/PUT/DELETE return
  `501` from the HTTP layer with no side effects. ✔ (Live-verified on `/`.)
- **Typed errors:** `NoDeviceFound→503 camera_not_found`,
  `DeviceOpenFailed→409 camera_busy`, `CaptureFailed→504 capture_failed`,
  `SdkUnavailable→503 sdk_unavailable`, else `500 internal_error`. Preserved. ✔
- **No secrets:** no credentials in the agent; config via env vars only;
  `Cache-Control: no-store` on camera responses. ✔
- No changes were made to the camera agent (per phase rules).

**Camera security was code/configuration reviewed but NOT physically
validated because the MATRIX VISION camera and microscope were unavailable.**

## 9. Hardware tests deferred

All of the following are **"DEFERRED — hardware unavailable during this
phase."** (matrix camera S/N 29605128, mvBlueFOX-ML/IGC205C):

live microscope capture · live camera connection · physical disconnect /
reconnect · microscope optical security · physical acquisition security ·
hardware-level camera validation · production HTTPS browser validation with
the microscope UI.

## 10. Remaining security risks

- `@grpc/grpc-js` advisory in the unused Firestore dependency tree (§7.7).
- CSRF: requests with **no** Origin/Referer **and** no session cookie pass
  (non-browser clients by design — not CSRF-capable); requests with a session
  cookie but no origin headers are allowed and logged (`csrf_no_origin`).
  Browsers always send Origin on state-changing requests, so the browser
  threat model is covered; a future strict mode could 403 that last case.
- Rate limiting covers auth routes (fail-closed) but not `/api/analyze`;
  upload caps + per-account concurrency (2) + global child cap bound the
  exposure. Consider a broader limiter if abuse appears.
- HSTS uses `max-age=31536000` without `includeSubDomains` (deliberate; the
  app may share a subdomain with non-TLS services).
- Session tokens are 7 days, stateless HMAC; revocation exists but there is no
  server-side "log out everywhere" button yet (secret rotation invalidates all
  sessions — deployment action).
- Physical camera/microscope security validation outstanding (§9).

## 11. Manual deployment / security steps required

1. **Bootstrap the first admin** — set `NODIQ_ADMIN_EMAILS=you@example.com`
   (comma-separated) in the environment; that account becomes admin at
   request time. Optional: `NODIQ_REVIEWER_EMAILS` for reviewer accounts.
   Promote further users via `POST /api/admin/users/<id>/role` with
   `{"new_role": "reviewer" | "admin"}` (admin-only, audit-logged). Note: all
   existing accounts keep working as `operator` — normal analysis is
   unaffected; only review sign-off now needs reviewer/admin.
2. **Extra hostnames** behind a different frontend host: add them to
   `CORS_ORIGINS` (or `CSRF_TRUSTED_ORIGINS`) so browser POSTs pass the
   CSRF/Origin gate.
3. **HTTPS production** — keep `TRUST_PROXY=true` behind the TLS-terminating
   proxy (Secure cookies + HSTS then activate automatically); never set it
   where X-Forwarded-* headers are attacker-controllable.
4. **Backups** — enable Supabase daily backups / PITR for production
   (`docs/DEPLOY_SUPABASE.md` §8); for local dev back up the whole
   `server_data/` directory (including `secret.key`).
5. **Dependencies** — in a controlled change (not this phase), upgrade
   `firebase` (a major-version bump) or add an npm `overrides` entry to lift
   `@grpc/grpc-js` ≥ 1.13.6, then re-verify Google/phone login end-to-end and
   rebuild. Until then the advisory is dormant (Firestore is never imported).
6. **Camera hardware validation** (when available): repeat the physical
   unplug/reconnect, preview and capture security checks against the running
   agent, and record them in a follow-up report.

---

*Generated during the NODIQ-X security hardening phase. No camera, microscope
or hardware claim above is hardware-verified; those items are deferred.*
