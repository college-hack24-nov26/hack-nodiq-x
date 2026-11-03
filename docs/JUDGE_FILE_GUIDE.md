# NODIQ-X — Judge File Guide

Where everything lives, organized by question. Every name is actual code.

## 1. Project entry points

- **src/nodiq/api/server.py** — Flask app + all routes. `analyze_upload()` (`POST /api/analyze`),
  `analysis_detail()`, `reports_generate_v2()`, `auth_login()`, `copilot()`.
  Runs on `127.0.0.1:8001`. *Judge question: "Where is the API?"* → src/nodiq/api/server.py.
- **src/nodiq/pipelines/analysis_child.py** — worker lifecycle `run()`: downscale → engine → validity gate →
  enrichment → persistence. *Judge question: "How does an analysis actually execute?"* → here.
- **src/nodiq/pipelines/nodularity_pipeline.py** — the engine itself (below).
- **apps/web/src/main.jsx + App.jsx** — frontend entry + route table.
- **scripts/run_1000_fixed.py** — batch runner over the 1000-image dataset (offline validation).
- **deploy/Dockerfile / deploy/render.yaml / deploy/docker-compose.yml** — deployment (gunicorn nodiq.api.server:app).

## 2. Frontend (apps/web/src)

- **pages/Analysis.jsx** — upload/drag-drop/dataset/camera UI, `startAnalysis()` poll loop,
  `applyResult()`. *Judge question: "Where does the user interact?"*
- **pages/MyAnalyses.jsx** (history), **Dashboard.jsx** (stats), **Analytics.jsx**
  (batch/SPC), **Compare.jsx**, **Lots.jsx**, **Anomalies.jsx**, **ReviewCenter.jsx**,
  **Settings.jsx**, **Profile.jsx** (password change), **Copilot.jsx**, **Reports.jsx**,
  **ReportGenerator.jsx**, **ReportPreview.jsx** (download/share), auth pages
  (Login/Signup/VerifyOtp/ResetPassword/AuthCallback), **LandingPage.jsx**.
- **components/auth/** — LoginForm, SignupForm, GoogleLogin, PhoneLogin, OTPVerification,
  **RequireAuth** (route guard).
- **components/layout/** — DashboardLayout, Sidebar (logout), TopBar.
- **components/charts/NodularityChart.jsx** — hand-rolled SVG chart (no chart lib).
- **context/AuthContext.jsx** — session state, validates via `GET /api/auth/me`.
- **services/api.js** — every HTTP call, cookie-based. *Judge question: "How does the
  frontend talk to the backend?"* → same-origin fetch + HttpOnly cookie; vite proxy in dev.
- **services/authService.js** — auth helpers + `signInWithGoogle`/`verifyFirebaseIdToken`.
- **services/microscopeAgent.js** — camera-agent client.
- **utils/, styles/** — shareReport, formatRichText, design tokens.

## 3. Backend

- **server.py** — routing, auth decorators (`require_auth`, `require_role`), CSRF origin
  check, security headers, rate limiting, upload validation (`_check_image`,
  `_image_dimensions`), worker orchestration (`_run_analysis_job_guarded` thread w/ watchdog,
  `_spawn_analysis_child` subprocess w/ timeout+retry).
- **analysis_child.py** — `run()`: `store.init_db()` → read bytes → downscale ≤2000 px →
  `analyze_image()` → progress 45 → `evaluate_microstructure_validity()` →
  `analyze_for_frontend_json()` → progress 70 → `assess_quality()` + `auto_calibrate()` +
  `apply_size_filter_and_iso()` + `enrich_rows()` + `classify_graphite_forms()` +
  `estimate_properties()` → progress 90 → write PNGs → optional Supabase upload →
  `save_full_analysis()` THEN `insert_analysis("completed")`.
- **services/** — one module per domain (see sections below).

## 4. Image processing

- **nodularity_pipeline.py** — `load_with_source()`, `blank_figure_annotations()`
  (scale bars/labels/panels removed), `physical_blob_map()` (median + Otsu),
  `blob_label_map()`, `reference_particles()`, `accuracy_vs_reference()`,
  `analyze_file()`, `analyze_for_frontend_json()`.
  *Judge question: "What image processing is used?"* → OpenCV: median blur, Otsu
  threshold, morphological opening, connected components, contours, convex hulls.
- **analyze_with_recovery.py** — `detect_frozen()` (legacy detector), `recover_and_merge()`,
  `consolidate_joined()`, `fill_owned_blobs()`, `jis_bucket()`, `draw_banner()`.
- **third_party/Nodularity/nodularity.py + nodularity_adaptive.py** — frozen reference detector
  (imported, never modified).

## 5. Nodularity calculation

- **nodularity_pipeline.py → analyze_image() (per-particle loop, ~L962–1001)**
  - `marumi = area / (π · r²)`, `r` = half the convex-hull max point-pair distance
    (= max Feret / 2), from `max_half_length()`.
  - `iso_pct = Σ area[marumi ≥ 0.6] / Σ area × 100` (MARUMI_ISO = 0.6, ISO 945-4).
  - `iso_inframe_pct` — strict variant excluding border particles.
  - `jis_pct = (0.3·N₂ + 0.7·N₃ + 0.9·N₄ + 1.0·N₅) / N × 100` via `jis_bucket()`.
  - `apply_size_filter_and_iso()` — ISO 945-4 clause 6.3 "≥10 µm only" figure.
  *Judge question: "Where is the actual nodularity math?"* → this exact block.

## 6. Database / storage

- **services/db.py** — SQLite (default) / Postgres: `init_db()`, `insert_analysis()`,
  `list_analyses()`, `get_analysis_record()`, `insert_report()`, sessions/calibration.
- **services/context.py** — `save_full_analysis()` / `load_full_analysis()`
  (`server_data/analyses_full/<id>.json`), `build_contract()`.
- **services/storage.py** — local vs Supabase Storage for original/annotated/mask.
- *Judge question: "Where do results live?"* → SQLite row + JSON payload + PNG artifacts.
  Firebase is NOT the database.

## 7. Authentication

- **services/auth.py** — bcrypt `hash_password`/`verify_password`, HMAC
  `issue_token`/`verify_token`/`revoke_token`, `create_user`/`authenticate`,
  `effective_role`, reset tokens.
- **server.py auth routes** — signup/login/firebase/me/change-password/logout/forgot/reset.
- **apps/web/src/firebase.js + authService.js** — Google + phone sign-in; the ID token is
  verified server-side in `auth_firebase()` via Google identitytoolkit.
- *Judge question: "How is a session kept?"* → HttpOnly `nodiq_session` cookie + server
  revocation list + `/api/auth/me`.

## 8. AI Copilot

- **ai/agent.py** `handle_turn()` — orchestration, context summaries, deterministic
  intent answers, UI actions.
- **ai/tools.py** — tool registry (`register_tool`, `execute_action`, ~18 tools).
- **Providers:** `groq_provider.py` (default), `gemini_provider.py`,
  `openai_compatible_provider.py`, `local_provider.py`, **`fallback_provider.py`**
  (offline rule-based, clearly labeled).
- **ai/memory.py** — chat sessions under `server_data/copilot_sessions/`.
- *Judge question: "Is the AI analyzing images?"* → No. Text only.

## 9. Microscope

- **apps/camera-agent/agent_server.py** — stdlib ThreadingHTTPServer; `AgentHandler`
  serves `/status`, `/preview`, `/capture`.
- **camera.py** — mvIMPACT (Matrix Vision) acquisition.
- **camera_agent.py / config.py** — CLI + config.
- **apps/web/src/services/microscopeAgent.js** — browser client.
- *Judge question: "Does the microscope use a different algorithm?"* → No — capture only;
  the image goes through the same `/api/analyze` pipeline.

## 10. Reports

- **report_builder.py** — `build_report_data()` (real measured values + comparison/
  anomaly/SPC sections), `set_ai_interpretation()`, `to_pdf()` (fpdf2), `to_csv()`,
  `to_json()`.
- **server.py** — `reports_generate_v2()`, `_generate_for()`, `_store_full_report()`,
  `reports_download()`.
- **ReportGenerator.jsx / ReportPreview.jsx** — config UI + preview/share/download.
- *Judge question: "Are report numbers real?"* → yes, built from the stored analysis.

## 11. Security

- **server.py** — `_csrf_protect`, `_add_security_headers`, `_check_image` (magic bytes),
  `_image_dimensions` (decompression-bomb guard), `_analyze_limited` (per-user analysis
  budget), `_current_user`.
- **services/rate_limit.py, seclog.py, validate.py** — buckets, security event log,
  request validation.
- **services/auth.py** — bcrypt, HMAC tokens, revocation, roles.
- *Judge question: "How do you prevent abuse?"* → rate limits (429 + Retry-After),
  size/dimension caps, cookie + CSRF hardening, security log (tests cover all).

## 12. Tests

- **tests/** — 31 pytest files + `conftest.py` + `rc_gate.py`. Highlights:
  `test_nodularity_audit.py`, `test_invalid_microstructure.py` (validity gate incl.
  colored-photo rejection), `test_api_contracts.py`, `test_auth_security.py`,
  `test_ownership_isolation.py`, `test_analyze_rate_limit.py`, `test_crash_isolation.py`,
  `test_size_filter.py`, `test_storage_backends.py`, `test_supabase_persistence.py`.
- Last full run: **347 passed, 0 failed**. CI runs pytest + frontend build.
- **scripts/tools/** — `e2e_check.py`, `hardening_smoke.py`, benchmark/merge-experiment tools.

## 13. Documentation

- **docs/** — this guide plus: `JUDGE_CODE_MAP.md` (button → endpoint map),
  `JUDGE_ARCHITECTURE.md` (flows), `JUDGE_VIVA_CHEAT_SHEET.md` (Q&A + honesty rules),
  `NODIQ-X_PROJECT_INFO.md`, `NODIQ-X_SRS.md`, `ARCHITECTURE.md`, `API.md`,
  `SECURITY.md`, `ACCURACY.md` (states `GROUND_TRUTH_UNAVAILABLE`),
  `ANALYZE_ABUSE_PHASE_REPORT.md`, and more (28 files).
- Root **README.md** — quick overview + run commands.
