# Development Rules — NODIQ-X

Rules for AI assistants and contributors working in this repository.
They exist to protect what already works: a verified analysis engine,
a hardened authentication/security layer, and a consistent design system.

---

## General

- **Never modify scientific logic.** ISO 945-4 / JIS G 5502 calculations, nodule
  detection, segmentation, image preprocessing, and `nodularity_pipeline.py` are
  validated and frozen. Presentation-only changes must not change engine output
  (nodule counts, ISO %, JIS %) by even one digit.
- Use **React 19 + Vite** for the frontend and **Flask** for the backend. Do not
  introduce new frameworks, state libraries, or UI kits.
- Reuse existing components, hooks, and CSS tokens. Do not duplicate logic that
  already exists in `apps/web/src/services/`, `apps/web/src/utils/`, or `src/nodiq/services/`.
- Keep functions small and single-purpose.
- **Do not modify unrelated files.** Every diff should be reviewable as one intent.
- Do not add dependencies without an existing, demonstrated need.
- Do not introduce Redis, new auth frameworks, or new databases.

## Before Coding

- Read the relevant documentation in `docs/` — especially `ARCHITECTURE.md`,
  `API.md`, and `ACCURACY.md` — plus `DESIGN.md` for UI work.
- Inspect the existing implementation first; extend it rather than replacing it.
- Follow `TASKS.md`: implement one task at a time, not "the whole app".
- For large changes, state a short plan before editing.
- Check `DECISIONS.md` — never reverse an architectural decision silently.

## UI

- Follow `DESIGN.md`. Use the canonical tokens in `apps/web/src/styles/variables.css`
  (colors, Inter/IBM Plex Mono tiers, radius 4/8/12). Never hardcode hex values.
- Maintain responsive behavior and both **light and dark mode** — theme via CSS
  variables only.
- Every async view needs **loading, empty, and error states**.
- Preserve the login video (`/videos/nodiq-login-loop.mp4`), existing animations,
  and page structure unless a task explicitly says otherwise.
- Content inside containers that scroll must not clip popovers/menus
  (see ADR-008 pattern: fixed-position layers anchored to triggers).

## Scientific Integrity

- Never fabricate metrics, accuracy claims, certifications, or benchmark results.
- Accuracy language follows `docs/ACCURACY.md`: "validated against
  available test data", "designed for", "decision-support" — never "certified"
  or "industrially proven" without evidence.
- When benchmark ground truth is unavailable, keep the `GROUND_TRUTH_UNAVAILABLE`
  posture. Do not invent numbers to fill tables.

## Security

- Never expose API keys or secrets client-side. `.env` is never committed;
  `.env.example` carries placeholders only.
- Validate **all** user input server-side (see `tests/test_input_security.py`).
- Verify authorization **server-side**, per-user, on every resource access
  (see `tests/test_ownership_isolation.py`). Never trust client-supplied identity.
- Authentication uses HttpOnly cookies — never return tokens in JSON, never store
  them in localStorage, never log them (see `tests/test_cookie_auth.py`).
- Do not weaken CSP, rate limits, security headers, or upload validation.
- New state-changing endpoints need a CSRF/review consideration before merge.

## Testing

- Run the backend suite after every change: `python -m pytest tests/ -q`.
- Fix failing tests before continuing. **Never delete, skip, or weaken a test**
  to make the suite green — fix the regression.
- Add a regression test for every bug fixed (see `tests/test_cookie_auth.py`
  for the session-rotation pattern).
- Frontend changes: `npm run build` in `apps/web/` must stay clean.

## Git

- Small, single-intent commits with descriptive imperative messages
  (e.g. `Batch review: report-first popover, fixed positioning`).
- Never rewrite history or force-push.
- Never commit `.env`, credentials, generated probe data, or debug artifacts.
- Do not commit unless the task explicitly asks for it.

## Cleanup Hygiene

- Probe/test accounts and analyses created during verification are removed from
  the database before finishing a task.
- Temporary scripts, logs, and preview launchers are never committed.
