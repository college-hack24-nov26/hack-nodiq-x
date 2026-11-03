# NODIQ-X — Architecture Decisions

![status](https://img.shields.io/badge/status-locked-b5495b?style=flat-square&labelColor=263449)
![revision](https://img.shields.io/badge/rev-09-6c63a6?style=flat-square&labelColor=263449)
![decisions](https://img.shields.io/badge/decisions-9-3e8e82?style=flat-square&labelColor=263449)

Permanent technical decisions for NODIQ-X. Once recorded, later work must not silently reverse them — a reversal requires a new ADR that supersedes the old one.

**Categories** ![Detection engine](https://img.shields.io/badge/-Detection%20engine-c08a2e?style=flat-square&labelColor=263449) ![Data & infra](https://img.shields.io/badge/-Data%20%26%20infra-3e8e82?style=flat-square&labelColor=263449) ![Auth & security](https://img.shields.io/badge/-Auth%20%26%20security-b5495b?style=flat-square&labelColor=263449) ![Frontend & quality](https://img.shields.io/badge/-Frontend%20%26%20quality-6c63a6?style=flat-square&labelColor=263449)

---

## Contents

| ADR | Decision | Category |
|:---:|---|---|
| 001 | [Classical CV pipeline as the production detector](#adr-001--classical-cv-pipeline-as-the-production-detector) | ![](https://img.shields.io/badge/-c08a2e?style=flat-square) Detection engine |
| 002 | [ISO 945 / JIS G 5502-oriented wording, never "certified"](#adr-002--iso-945--jis-g-5502-oriented-wording-never-certified) | ![](https://img.shields.io/badge/-c08a2e?style=flat-square) Detection engine |
| 003 | [SQLite, no external database or Redis](#adr-003--sqlite-no-external-database-or-redis) | ![](https://img.shields.io/badge/-3e8e82?style=flat-square) Data & infra |
| 004 | [HttpOnly cookie sessions, not bearer tokens](#adr-004--httponly-cookie-sessions-not-bearer-tokens) | ![](https://img.shields.io/badge/-b5495b?style=flat-square) Auth & security |
| 005 | [Firebase as the identity provider](#adr-005--firebase-as-the-identity-provider) | ![](https://img.shields.io/badge/-b5495b?style=flat-square) Auth & security |
| 006 | [Enforced CSP with hash-pinned Firebase bootstrap](#adr-006--enforced-csp-with-hash-pinned-firebase-bootstrap) | ![](https://img.shields.io/badge/-b5495b?style=flat-square) Auth & security |
| 007 | [Security regression tests are immutable](#adr-007--security-regression-tests-are-immutable) | ![](https://img.shields.io/badge/-b5495b?style=flat-square) Auth & security |
| 008 | [Floating UI escapes overflow containers via fixed layers](#adr-008--floating-ui-escapes-overflow-containers-via-fixed-layers) | ![](https://img.shields.io/badge/-6c63a6?style=flat-square) Frontend & quality |
| 009 | [Design tokens are canonical in variables.css](#adr-009--design-tokens-are-canonical-in-variablescss) | ![](https://img.shields.io/badge/-6c63a6?style=flat-square) Frontend & quality |

---

## 1 · Detection & compliance

### ADR-001 — Classical CV pipeline as the production detector
![Detection engine](https://img.shields.io/badge/-Detection%20engine-c08a2e?style=flat-square&labelColor=263449)

**Decision**
The shipped analysis engine is the deterministic OpenCV pipeline in `nodularity_pipeline.py`. The Detectron2 / ML path stays research-only, not production.

**Reason**
Deterministic, auditable, and dependency-light — validated against the available test data. Model inference would add GPU weight and non-reproducibility that the current evidence base can't justify.

### ADR-002 — ISO 945 / JIS G 5502-oriented wording, never "certified"
![Detection engine](https://img.shields.io/badge/-Detection%20engine-c08a2e?style=flat-square&labelColor=263449)

**Decision**
Documentation and UI describe metrics as ISO/JIS-*oriented*. Compliance claims are forbidden without external certification evidence.

**Reason**
Scientific honesty is a product requirement (see `docs/NODIQ-X_ACCURACY.md`). NODIQ-X is decision support — expert judgment stays central.

---

## 2 · Data & infrastructure

### ADR-003 — SQLite, no external database or Redis
![Data & infra](https://img.shields.io/badge/-Data%20%26%20infra-3e8e82?style=flat-square&labelColor=263449)

**Decision**
SQLite is the production datastore; rate limiting runs in-process across 2 Gunicorn workers.

**Reason**
Matches single-node deployment scale with zero-ops reliability. Accepted risk: a scaling ceiling — revisit only when measured load demands it.

---

## 3 · Auth & security

### ADR-004 — HttpOnly cookie sessions, not bearer tokens
![Auth & security](https://img.shields.io/badge/-Auth%20%26%20security-b5495b?style=flat-square&labelColor=263449)

**Decision**
Authentication moved from localStorage bearer tokens to HttpOnly + Secure (prod) + `SameSite=Lax` cookies with server-side token revocation. Tokens are never returned in JSON, stored in JS, or logged. CSRF is addressed via SameSite=Lax plus regression tests, given the same-origin deployment.

**Reason**
Removes token theft via XSS while keeping the existing JWT claims, reset-token family separation, and revocation model. Documented in `docs/FINAL_SECURITY_REPORT.md`.

### ADR-005 — Firebase as the identity provider
![Auth & security](https://img.shields.io/badge/-Auth%20%26%20security-b5495b?style=flat-square&labelColor=263449)

**Decision**
Firebase handles Google / email / phone authentication; the Flask backend verifies Firebase ID tokens and issues its own session.

**Reason**
Standards-based provider auth without building a phone/SMS stack. Constraint: Firebase Console (authorized domains, phone provider, billing) is operator-managed — the codebase cannot verify it.

### ADR-006 — Enforced CSP with hash-pinned Firebase bootstrap
![Auth & security](https://img.shields.io/badge/-Auth%20%26%20security-b5495b?style=flat-square&labelColor=263449)

**Decision**
CSP is enforced: `default-src 'self'`, no `unsafe-inline` / `unsafe-eval` in `script-src`. The Firebase SDK's inline bootstrap is allowed only by its verified exact hash. `style-src 'unsafe-inline'` stays as an accepted risk for the React implementation.

**Reason**
Browser-verified zero violations across the full app flow. The hash is maintainable on SDK upgrades — recompute, don't loosen.

### ADR-007 — Security regression tests are immutable
![Auth & security](https://img.shields.io/badge/-Auth%20%26%20security-b5495b?style=flat-square&labelColor=263449)

**Decision**
The 275-test suite — cookie auth, CSRF, ownership isolation, input security, rate limits — is a regression gate. Tests are never deleted, skipped, or weakened to go green.

**Reason**
The suite is the freeze guarantee. A failing test means the change is wrong, not the test.

---

## 4 · Frontend & quality

### ADR-008 — Floating UI escapes overflow containers via fixed layers
![Frontend & quality](https://img.shields.io/badge/-Frontend%20%26%20quality-6c63a6?style=flat-square&labelColor=263449)

**Decision**
Menus and popovers anchored to elements inside scrollable containers (e.g. the batch results table) render in `position: fixed` layers, positioned from the trigger's viewport rect, with viewport-edge clamping.

**Reason**
`overflow: auto` wrappers clip absolute-positioned popovers, and portals add dependency weight. Proven in the batch review popover (commit `08cbc41`).

### ADR-009 — Design tokens are canonical in variables.css
![Frontend & quality](https://img.shields.io/badge/-Frontend%20%26%20quality-6c63a6?style=flat-square&labelColor=263449)

**Decision**
`styles/variables.css` is the single token source — colors, Inter / IBM Plex Mono tiers, radius 4/8/12. `tokens.css` is retired aliases kept for ~130 legacy rules; new code uses canonical variables and never hardcodes hex.

**Reason**
One token architecture ends the copper/cyan and 6/10/14 drift; light/dark theming flows from the same variables.

---

*NODIQ-X — Architecture Decision Records. 9 decisions, all locked.*