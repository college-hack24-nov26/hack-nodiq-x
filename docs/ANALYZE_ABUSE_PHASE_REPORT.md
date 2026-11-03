# Analysis API Abuse Protection / Rate Limiting — Phase Report

Scope: protect `POST /api/analyze` from abusive request volumes and unbounded
resource use, without changing any analysis behavior, the engine, or any other
route family. Baseline before this phase: **329 tests passing** (full suite),
`npx oxlint src` clean, `npm run build` clean, `pip-audit` clean.

---

## 1. Files changed

| File | Change |
|---|---|
| `server.py` | Added `/api/analyze` rate limiting (per-user primary key, IP fallback for unauthenticated), env-configurable limits, Retry-After on all 429s, env-driven per-account concurrency, optional per-job wall-clock timeout (thread watchdog + child kill), owner-aware job-registry prune fix, audit events |
| `tests/test_analyze_rate_limit.py` | NEW — 16 focused abuse-protection tests |
| `tests/test_input_security.py`, `tests/test_security_hardening.py` | Fixture contract extended: also raise `_MAX_CONCURRENT_CHILDREN` in tests (the prune fix made the global cap genuinely count) |
| `docs/SECURITY.md` | New "Analysis Abuse Protection" section (limits, variables, 429, concurrency, timeout, storage semantics) |
| `docs/ANALYZE_ABUSE_PHASE_REPORT.md` | This report |

The engine (`nodularity_pipeline.py`), `analysis_child.py` (its `run()`
protocol is unchanged), the camera agent, and every other route are untouched.

---

## 2. Exact rate-limit behavior

- Applies **only** to `POST /api/analyze`. Health, static assets, GETs, and
  camera-agent endpoints are not limited.
- **Bucket key**: authenticated callers → `/api/analyze|user:<uid>` (user id
  from the verified session/Bearer token — never from client-controlled
  data). Unauthenticated callers → `/api/analyze|ip:<client_ip>` where
  `_client_ip()` is the socket peer unless the operator set `TRUST_PROXY=true`
  (X-Forwarded-For first hop). Spoofed `X-Forwarded-For` cannot mint fresh
  budgets when TRUST_PROXY is off (regression-tested).
- **Ordering**: the anonymous IP check runs before the 401; the per-user
  check runs after authentication and before any file reading, magic-byte
  checks, decode, or record creation. Exceeding the budget costs the caller
  nothing except the limiter hit.
- **Shared counters**: the limiter is `services/rate_limit.py` (SQLite
  sliding window, `BEGIN IMMEDIATE` atomic admission, fail-closed). This is
  the multi-worker-safe store — NOT in-memory, no Redis introduced. See §8.
- **Response on exceed**: HTTP 429, body `{"error": "too many requests.
  please try again later."}`, header `Retry-After: <window seconds>`. No
  bucket composition, store layout, or quota internals are disclosed. The
  same response shape (with the existing per-route wording) now also applies
  to the auth routes, which previously had no Retry-After.
- **Audit**: exceeding emits `rate_limited` (route `/api/analyze`, status
  429, user_id when authenticated, ip) into the existing structured
  `security.log` — consistent with the established event model.
- **Disable**: `NODIQ_ANALYZE_RATE_LIMIT=0` disables the analyze limiter
  entirely (window `<=0` likewise). `RATE_LIMITS_ENABLED=False` (test hook)
  also disables it.

---

## 3. Exact environment variables

| Variable | Default | Meaning |
|---|---|---|
| `NODIQ_ANALYZE_RATE_LIMIT` | `30` | Max `/api/analyze` requests per user (or per IP for anonymous) per window; `0` disables |
| `NODIQ_ANALYZE_RATE_WINDOW` | `300` | Sliding window seconds |
| `NODIQ_ANALYZE_MAX_CONCURRENCY` | `2` | Per-account analyses allowed in flight (previously hardcoded 2) |
| `NODIQ_ANALYZE_TIMEOUT` | `0` (off) | Wall-clock cap per analysis job, seconds. `0` = unlimited, the historic behavior |
| `NODIQ_MAX_CHILDREN` | `1` | Pre-existing global cap on simultaneously running analysis children (now truly enforced after the prune fix — env var unchanged) |

All are plain `int(os.environ.get(...))`; invalid values crash at startup
loudly rather than silently weakening protection. Development defaults are
safe: the limiter is generous for real users and the timeout defaults off,
preserving today's behavior exactly.

---

## 4. Concurrency / timeout behavior

**Concurrency (pre-existing, now completed):**
- The per-account cap `_MAX_CONCURRENT_ANALYSES` is now env-driven
  (`NODIQ_ANALYZE_MAX_CONCURRENCY`, default 2 — identical default behavior).
- **Bug found & fixed**: the job-registry prune called
  `store.get_analysis_record(aid, None)`, but under strict per-account
  isolation `user_id=None` matches NOTHING (`1=0`), so every request wiped
  the registry and the concurrency cap never engaged (verified by a test
  that enqueues 2 stub jobs and gets a 202 for the 3rd on the old code —
  now 429). The prune is owner-aware: each job's record is looked up with
  its owning user id. This makes the caps real in production.
- When saturated (per-account cap or the global `NODIQ_MAX_CHILDREN` cap):
  HTTP 429, user-facing JSON ("too many analyses running — wait for one to
  finish before starting another"), `Retry-After` header (window length), and
  an `analysis_concurrency_limited` audit event. Accounts are isolated: user
  B can still analyze when user A is saturated.
- The async/poll workflow is untouched: 202 + `poll_url` →
  `GET /api/analyses/<id>` until completed/failed.

**Timeout (previously missing entirely — both modes could hang forever):**
- `NODIQ_ANALYZE_TIMEOUT=0` (default): no change at all to runtime behavior.
- `>0`: thread mode arms a watchdog timer per job; at the deadline the record
  flips to an honest failed record ("Analysis timed out on the server…"),
  the engine thread is abandoned (daemon thread; Python threads cannot be
  killed), the slot is freed, and the result of a later engine finish is
  ignored (record already terminal). Child mode wraps `proc.wait()` in a
  deadline: on expiry SIGTERM, then SIGKILL after a 60-second grace;
  timeout kills skip the existing one-crash-retry so a wedged job is not
  retried into another full budget. Exit rc 143/137 map to the standard
  failure path.
- The engine itself, its thresholds, and result semantics are untouched.

---

## 5. Tests added (`tests/test_analyze_rate_limit.py` — 16 tests)

1. `test_below_limit_succeeds_and_hits_429_after` — budget accepted, (limit+1)-th 429
2. `test_429_carries_retry_after_and_no_internals` — Retry-After present; body leaks no bucket/store internals
3. `test_rate_limited_event_audit_logged` — `rate_limited` event for /api/analyze
4. `test_users_are_isolated` — user A exhausted → user B unaffected
5. `test_anonymous_ip_fallback_and_401` — anonymous calls stay 401 but still consume the IP bucket; 429 with Retry-After; health unaffected
6. `test_spoofed_forwarded_for_cannot_bypass_anonymous_bucket` — XFF rotation cannot bypass (TRUST_PROXY off)
7. `test_analyze_limit_0_disables` — limit 0 disables
8. `test_auth_route_429_also_carries_retry_after` — auth routes gain Retry-After (compat: same 429 body)
9. `test_concurrency_saturation_429_retry_after_and_isolation` — 3rd concurrent job 429s with Retry-After + audit event; user B unaffected
10. `test_concurrency_slot_freed_after_terminal_state` — slot reusable after failure
11. `test_timeout_watchdog_fails_wedged_job_and_frees_slot` — wedged job → honest failure, slot freed, reusable
12. `test_timeout_disabled_by_default` — timeout 0 = unlimited (historic)
13. `test_normal_analysis_workflow_intact` — dataset analysis 202 → poll → completed
14. `test_upload_validation_and_auth_still_enforced` — magic-byte rejection + dataset flow
15. `test_bearer_and_cookie_equivalent` — Bearer and cookie flows both 202
16. `test_limiter_failure_fails_closed_for_analyze` — broken store ⇒ limited, never open

Plus fixture updates in two existing modules (global children cap) so the
fixed prune keeps their rapid-fire enqueues passing.

---

## 6. Complete validation results

Validation actually executed (not claimed) — all commands run on the final
tree, 2026-10-03:

- Full suite: `python -m pytest tests/ -q` — **345 passed, 0 failed**
  (35 warnings, pre-existing) in 625.79s (10:25). 329 baseline + 16 new
  abuse-protection tests. Log: `.freebuff/abuse_phase_pytest.log`.
- `npx oxlint src` (in `nodiq-x/`) — **0 errors** (26 pre-existing
  warnings). The task's "`npm run lint`" does NOT
  exist as a script in this repo (`nodiq-x/package.json` has no `lint`
  script; root has only `dev`). `npx oxlint src` is the project's actual
  lint check and was used instead.
- `npm run build` (in `nodiq-x/`) — **succeeded** ("✓ built", ~1.6s).
- `pip-audit -r requirements.txt --no-deps` — **no known vulnerabilities
  found** (run from repo root; running it from `nodiq-x/` mis-parses the
  input).
- `npm audit` (in `nodiq-x/`) — **4 high advisories, all pre-existing
  dormant firebase transitive advisories** documented in the previous
  phase's report; not auto-upgraded, consistent with that baseline
  decision.

---

## 7. Security implications

- **Positive**: abusive analysis volumes are now capped per account (and per
  IP for anonymous noise) with multi-worker-safe shared counters; a saturated
  or wedged engine can no longer pin a concurrency slot forever; saturation
  and limit events are auditable; all 429s carry Retry-After.
- **Fail-closed preserved**: a broken limiter store keeps limiting (tested).
- **No new identity surface**: keys derive from the verified session/Bearer
  identity or the socket peer; untrusted headers never decide identity.
- **No regression**: CSRF, RBAC, upload magic/size/dimension gates,
  decompression-bomb guard, session/token revocation, path-traversal
  protections, security headers/CSP are untouched and their regression
  suites still pass (run in this phase: input-security, security-hardening,
  crash-isolation, rate-limit-shared, ownership-isolation, api-contracts).
- **Consideration**: the anonymous IP bucket consumes on 401'd attempts —
  intentional (cheap mop against scripted hammering before auth work), and
  authenticated traffic is unaffected.

---

## 8. Known limitations

- **The limiter is SQLite-backed, not in-memory — and explicitly NOT
  Redis.** Counters are shared across all Gunicorn workers via the shared
  database and survive restarts, but correctness depends on the DB being
  shared. A multi-node deployment (several DB-less app servers) would need a
  shared store; NODIQ-X runs single-DB, so this is not a current exposure.
  We did not introduce Redis (no compelling reason; ops cost outweighs
  benefit at this scale).
- **Thread-mode timeout abandons, does not kill**: the wedged engine thread
  keeps consuming CPU until it dies naturally; the record and slot are
  released immediately. True hard-kill is only possible in child mode.
  This is the smallest compatible protection (Python has no thread kill).
- **Timeout default is off** (`NODIQ_ANALYZE_TIMEOUT=0`) to preserve historic
  behavior on long free-tier analyses; operators should set it in
  production (e.g. 600) once comfortable with their worst-case image sizes.
- `Retry-After` carries the configured window length, not a computed
  per-caller reset time (the shared sliding-window schema does not track
  per-bucket reset; exposing an approximation was judged worse than a stable
  honest value).
- The audit `rate_limited` event carries user id + ip only (established
  model — no request material, no bucket keys).
- Pre-existing, out of scope: the limiter counts every limiter-passing
  request, including ones later rejected by upload validation (by design —
  validation itself is the cheaper layer; the request budget protects the
  engine stage).

---

## 9. Hardware-blocked items

- **Camera / microscope physical validation remains deferred** — the MATRIX
  VISION mvBlueFOX-ML/IGC205C (S/N 29605128) is unavailable in this
  environment. Nothing in this phase touches acquisition behavior; the
  camera-agent endpoints were verified NOT to be rate limited (config-level,
  hardware-free checks only).
- Nothing else in this phase is hardware-blocked.

**STOP — phase complete. No further phases started.**
