# Test Plan — NODIQ-X

What "working" means. The automated suite is the regression gate; the manual
checklists cover what automation can't see.

---

## Automated Suite (backend)

Run: `python -m pytest tests/ -q` — **275 tests, 0 failures, 0 skipped**.

| Area | File | Proves |
| --- | --- | --- |
| Cookie auth | `test_cookie_auth.py` | HttpOnly login/logout/rotation; no token in JSON/localStorage/logs; forged/expired/revoked → 401 |
| Auth security | `test_auth_security.py` | bcrypt, reset-token family separation |
| Ownership | `test_ownership_isolation.py` | Users can never read/write another user's resources |
| Input security | `test_input_security.py` | Malicious payloads rejected |
| Upload security | `test_invalid_microstructure.py`, `test_size_filter.py` | Magic-byte validation, oversized files |
| API contracts | `test_api_contracts.py` | Endpoint shapes stable |
| Rate limiting | `test_rate_limit_shared.py` | Shared-worker limits enforced |
| Secrets | `test_secrets_hygiene.py`, `test_key_rotation.py` | No real credentials; rotation works |
| Regression gate | `test_regression_gate.py` | Frozen engine outputs unchanged |
| Services/sessions | `test_services.py`, `test_sessions.py` | Service layer, session mgmt |
| Multifield | `test_multifield.py` | Aggregation correctness |
| Benchmarks | `tests/benchmarks/` | 39/39 ML benchmark tests |

Frontend: `npm run build` in `apps/web/` stays clean; no console errors.

## Manual: Authentication

- [ ] Signup → login → dashboard reachable
- [ ] Invalid credentials show a clear error, no state leak
- [ ] Logged-out user cannot open any protected page (redirects to login)
- [ ] Google login works; Firebase errors surface as friendly messages
- [ ] Phone login: reCAPTCHA renders, OTP sent (requires Firebase Console config)
- [ ] Refresh keeps you logged in; logout → refresh → still logged out

## Manual: Analysis Workflow

- [ ] New Analysis: upload real micrograph → quality gate → analyze → results
      (nodule count, ISO %, JIS %, self-check) render
- [ ] Non-micrograph/malicious upload rejected with a clear message
- [ ] Batch: multiple images process; results table shows REVIEW for ISO < 80%;
      review popover opens with "Review & create report" + decisions; decision
      persists and shows reviewer
- [ ] Copilot: question about an analysis returns a formatted answer (tables render)
- [ ] Report: generate → preview → export; analysis fields match results page
- [ ] My Analyses: cards show each analysis's own micrograph; View Report opens
      existing report or preselects generator

## Manual: UI/Responsive

- [ ] Test at **375px, 768px, 1440px**
- [ ] Light and dark mode both correct on every visited page
- [ ] Loading, empty, and error states appear on async pages
- [ ] Login video plays; animations intact
- [ ] No clipped popovers/menus; no horizontal page scroll at 375px

## Manual: Security Spot-Checks (per release)

- [ ] Anonymous request to a protected endpoint → 401
- [ ] Cross-user access attempt → denied
- [ ] Cookie flags visible in devtools: HttpOnly, Secure (prod), SameSite=Lax
- [ ] No token in any API JSON or localStorage
- [ ] CSP violations: zero in console across the full journey
