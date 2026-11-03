# Project Memory — NODIQ-X

Current state of the project. Update after every completed task.
(Permanent technical decisions live in `DECISIONS.md`; this file is the living status.)

---

## Current Status

**Production-ready pending deployment.** Security hardening complete
(272→275 tests, enforced CSP, HttpOnly cookie sessions). UI polish pass in
progress. Firebase phone auth needs operator-side console configuration.

## Completed

- Analysis engine: nodule detection, ISO 945-4 / JIS G 5502 metrics, multi-field,
  batch, compare — output frozen and regression-gated
- Security freeze: HttpOnly cookie auth with server-side revocation, enforced CSP
  (Firebase hash-pinned), CSRF regression tests, rate limiting, upload magic-byte
  validation, ownership isolation tests
- Credential rotation runbook (`docs/SECURITY_ROTATION.md`) — execution is a
  **manual deployment action**
- Docker: 2-worker Gunicorn, healthy, no `.env`/`server_data` in image
- Frontend polish: professional roundness-distribution chart, Copilot Markdown
  tables, My Analyses real micrograph thumbnails + View Report action, batch
  review popover (report-first, no clipping)
- Governance docs: PRD, RULES, DESIGN, TASKS, DECISIONS, TEST_PLAN, SECURITY

## Current Task

None — all committed through `e677e68` plus the governance docs.

## Known Issues

- **Firebase phone auth**: real +91 SMS requires Firebase Console configuration
  (phone provider on a billing-enabled project + authorized domain). `auth/internal-error`
  seen in plain-browser testing needs verification against the authorized-domains list.
- Docker container (8001) serves an older frontend bundle until rebuilt
  (`docker compose up -d --build`).
- `.anomaly-label` global styles in `Home.css` historically leak into other pages —
  scoped overrides exist in ReportGenerator.css; watch for new occurrences.
- `Nodularity-main/archive/` (~4 GB) and `reports/merge_experiment/summary.json`
  are deferred REVIEW items from the cleanup pass — do not delete without review.

## Next Step

1. Execute credential rotation runbook (manual, hosting-side)
2. Finalize hosting configuration per `docs/HOSTING_CHECKLIST.md`
3. Rebuild Docker image with current bundle; final production smoke
4. Verify Firebase authorized domains for phone/Google auth
