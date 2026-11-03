# TASKS.md — NODIQ-X

One task at a time. For each: **implement → test → review → mark complete**.
Never ask an AI to build "the whole app" in one prompt; hand it a single TASK-ID.

---

## Phase 1 — Foundation ✅

- [x] TASK-001 — Flask backend + Vite React frontend scaffold
- [x] TASK-002 — SQLite datastore, schema, migrations
- [x] TASK-003 — Design token system (`styles/variables.css`), light/dark theming
- [x] TASK-004 — Docker packaging, Gunicorn 2-worker runtime

## Phase 2 — Authentication ✅

- [x] TASK-010 — Email/password signup + login (bcrypt)
- [x] TASK-011 — Firebase Google authentication
- [x] TASK-012 — Phone authentication UI + OTP flow
- [x] TASK-013 — Password reset (email, token family separated from auth)
- [x] TASK-014 — HttpOnly cookie sessions, server-side revocation, CSRF regression tests
- [ ] TASK-015 — **MANUAL:** Firebase Console — phone provider on billing-enabled
      project, authorized domains, verify real +91 SMS end-to-end

## Phase 3 — Analysis Engine ✅

- [x] TASK-020 — Nodule detection + segmentation pipeline (classical CV)
- [x] TASK-021 — ISO 945-4 roundness + nodularity, area/count-weighted variants
- [x] TASK-022 — JIS G 5502 form classification (count-weighted)
- [x] TASK-023 — Multi-field analysis + aggregation
- [x] TASK-024 — Image quality gate + scale calibration
- [x] TASK-025 — Regression gate: frozen outputs, benchmark suites
- [ ] TASK-026 — Expert ground-truth validation program (external)

## Phase 4 — Product Surfaces ✅

- [x] TASK-030 — Landing + login (video, animations preserved)
- [x] TASK-031 — Dashboard, New Analysis, My Analyses (real thumbnails, View Report)
- [x] TASK-032 — Batch Analysis + working review sign-off popover
- [x] TASK-033 — Compare, Lots, Sessions, Anomalies, Analytics
- [x] TASK-034 — Review Center, Reference Library, Microstructure
- [x] TASK-035 — AI Copilot (Groq + Gemini + offline fallback, Markdown tables)

## Phase 5 — Reports ✅

- [x] TASK-040 — Report generation (fpdf2), preview, traceability fields
- [x] TASK-041 — Report sign-off integration with review workflow

## Phase 6 — Security Freeze ✅

- [x] TASK-050 — Full hardening pass (CSP enforced, cookie auth, rotation runbook)
- [x] TASK-051 — 275-test regression suite green, 23/23 live smoke
- [ ] TASK-052 — **MANUAL:** Execute `docs/SECURITY_ROTATION.md` (Groq, Gmail app
      password, JWT secret) at deployment time

## Phase 7 — Deployment

- [ ] TASK-060 — **MANUAL:** Hosting config per `docs/HOSTING_CHECKLIST.md`
      (HTTPS/TLS, TRUST_PROXY decision, COOKIE_SECURE, secrets storage)
- [ ] TASK-061 — Rebuild Docker image with current frontend bundle
- [ ] TASK-062 — Final production smoke (full user journey on deployed URL)
- [ ] TASK-063 — Project freeze

## Phase 8 — Future (not started)

- [ ] TASK-070 — Expert-validated benchmark dataset expansion
- [ ] TASK-071 — Redis-backed rate limiting if scale demands (needs ADR revision)
- [ ] TASK-072 — CSP tightening: remove `style-src 'unsafe-inline'`
- [ ] TASK-073 — Extend real-micrograph treatment to Compare/Lots
