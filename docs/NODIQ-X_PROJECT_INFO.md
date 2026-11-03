# NODIQ-X — PROJECT INFORMATION (FACT SHEET FOR SRS WRITING)

Document type: source-of-truth project information. Every statement below was verified against the
repository (code, schema, configs) and the existing phase reports at documentation time
(2026-10-01). Nothing is inferred or projected. Where documentation inside the repository is
stale relative to the code, the discrepancy is stated explicitly.

---

## 1. PRODUCT IDENTITY

| Item | Verified value |
|---|---|
| Product name | NODIQ-X |
| Tagline (repository) | "AI-Powered Microstructure Intelligence" (`PRD.md`) |
| Version | 1.6.0 (`VERSION` file) |
| Domain | Ductile (spheroidal-graphite) cast iron quality analysis |
| Purpose | Web-based metallurgical analysis platform that converts metallographic (microstructure) images of ductile/nodular cast iron into measured, classified and traceable nodularity-related results |
| Engine version label | v4.2.1 (`docs/ARCHITECTURE.md` badge, referring to `nodularity_pipeline.py`) |
| Product status (repository's own words) | "Functional prototype / decision-support platform (production-hardened codebase; scientific validation in progress)" (`PRD.md`) |
| Document type of this file | Fact sheet for authoring the SRS (this file is NOT the SRS) |

---

## 2. TECHNOLOGY STACK (EXACT VERSIONS)

Frontend (`nodiq-x/package.json`):

| Component | Version |
|---|---|
| React | 19.2.8 (`^19.2.8`) |
| React DOM | 19.2.8 (`^19.2.8`) |
| Vite | 8.2.0 (`^8.2.0`) |
| React Router | client-side routing (`App.jsx`, 27 route entries) |
| Firebase JS SDK | `firebase` `^12.19.0` (root `package.json`) — used for the optional Google sign-in popup |

Backend (Python, `requirements.txt` and verified runtime):

| Component | Version |
|---|---|
| Python | 3.11.8 |
| Flask | 3.1.3 |
| flask-cors | >= 6.0.0 |
| opencv-python | 5.0.0.93 |
| NumPy | 2.4.6 |
| fpdf2 | >= 2.8 (PDF report generation) |
| reportlab | >= 4.0 |
| bcrypt | >= 4.0 |
| psycopg2-binary | >= 2.9 (PostgreSQL/Supabase) |
| requests | 2.34.2 |

Other runtime/tooling:

| Component | Verified value |
|---|---|
| Node.js | v22.23.2 |
| Root `package.json` scripts | `dev` = `concurrently -n vite,server,camera "npm run dev --prefix nodiq-x" "python server.py" "python nodiq-camera-agent/agent_server.py"` · `camera` = `python nodiq-camera-agent/agent_server.py` |
| Database | SQLite (WAL) by default; PostgreSQL via Supabase in production (`services/db.py`, `NODIQ_BACKEND`) |
| Camera SDK | mvIMPACT Acquire (MATRIX VISION/Balluff Python binding `ImpactAcquire`, built from `D:\LanguageBindings\Python`) |
| Camera agent HTTP server | Python stdlib `http.server.ThreadingHTTPServer` (no web framework) |
| AI providers (optional) | Groq (default), Google Gemini, OpenAI-compatible, local, static fallback (`ai/`) |
| Mailer (optional) | SMTP (`services/mailer.py`; degrades to logging without credentials) |
| Deployment artifacts | `Dockerfile`, `docker-compose.yml`, `render.yaml`, `DEPLOY_SUPABASE.md` |

---

## 3. ROUTE / API TERMINOLOGY (RESOLVED)

The repository contains two numbers that can be confused; their exact meaning, verified by
static analysis of `server.py`:

| Term | Exact value | Meaning |
|---|---|---|
| `@app.*` decorator lines | **71** | All Flask decorators in `server.py`: 68 route decorators + 2 `@app.errorhandler` + 1 `@app.after_request` |
| Flask route decorators | **68** | `@app.get` = 41, `@app.post` = 23, `@app.delete` = 4 (method-level registrations; `server.py` uses the shortcut decorators, not `@app.route`) |
| Unique URL paths | **61** | Distinct path strings across those 68 registrations |
| REST API endpoint paths | **58** | The `/api/*` subset of the 61 unique paths |
| Non-API paths | **3** | `/` (SPA root), `/<path:path>` (SPA fallback), `/dataset/<path:filename>` (dataset files) |
| React Router routes (frontend) | **27** | `<Route path=...>` entries in `nodiq-x/src/App.jsx` (26 named paths + `*` catch-all/404) |
| Camera-agent endpoints | **3** | `/status`, `/preview`, `/capture` (plus a JSON 404 listing them) in `nodiq-camera-agent/agent_server.py` |

Note on the "49 endpoints" figure: `docs/ARCHITECTURE.md` states "49 REST endpoints". That number
reflects the endpoint-group count at the time that document was written; the API has grown since
(Firebase auth, artifact/review/context routes, copilot chat/health, sessions, multifield, etc.).
The current, code-verified count is **58 REST API endpoint paths (68 method-level route
registrations)**. For the SRS, the accurate phrasing is "58 REST API endpoint paths across
68 Flask route registrations (41 GET / 23 POST / 4 DELETE)".

Frontend routes (27, `nodiq-x/src/App.jsx`):
`/`, `/login`, `/signup`, `/verify-otp`, `/auth/callback`, `/forgot-password`, `/reset-password`,
`/privacy`, `/terms`, `/home`, `/dashboard`, `/new-analysis`, `/analyses`, `/copilot`, `/reports`,
`/batch-analysis`, `/analytics`, `/compare`, `/lots`, `/sessions`, `/anomalies`,
`/review-center`, `/settings`, `/reports/generate`, `/reports/:reportId`, `/profile`, `*`.

---

## 4. SYSTEM ARCHITECTURE (LAYERS AND VERIFIED FLOW)

Layered architecture (as implemented):

1. **Presentation layer** — React 19 + Vite SPA in the browser (`nodiq-x/src`), dark-theme UI,
   scoped per-page CSS, `RequireAuth` route guard, `AuthContext` session state.
2. **Microscope / image acquisition layer** — the MATRIX VISION camera on the metallurgical
   microscope, the mvIMPACT Acquire SDK, and the local camera agent HTTP service on
   `127.0.0.1:8765`. This layer is an **additional image input source**; the other input source is
   a normal image file (upload or dataset).
3. **Application / API layer** — Flask 3.1.3 (`server.py`) on port 8001; serves the REST API, the
   built SPA, dataset files and evidence images on one origin; cookie-session auth; per-user
   scoping; async analysis (202 + polling).
4. **Analysis engine layer** — the single `nodularity_pipeline.py` OpenCV + NumPy pipeline
   (crash-isolated via `analysis_child.py` / `analyze_with_recovery.py`), plus the domain services
   in `services/` (morphology, properties, quality, calibration, comparison, anomalies,
   analytics/SPC, lots, multifield, review, validation).
5. **Data / persistence layer** — SQLite (WAL) file `server_data/nodiq.db` in development, or
   PostgreSQL via Supabase plus Supabase Storage in production; local hash-deduplicated uploads;
   the bundled 1,000-image dataset.
6. **External / supporting services (optional)** — Firebase Authentication (Google sign-in),
   AI provider chain for the Copilot, SMTP mailer. The system degrades gracefully to offline
   operation without them.

**Verified end-to-end flow (the only analysis pipeline that exists):**

```
Metallurgical Microscope
        ↓
MATRIX VISION Camera (mvBlueFOX-ML/IGC205C)
        ↓
mvIMPACT Acquire (SDK)
        ↓
Camera Agent :8765  (/status · /preview · /capture)
        ↓
Browser (NODIQ-X Web Interface)
        ↓  Blob → File
POST /api/analyze   (same funnel as uploads)
        ↓
Existing NODIQ-X Analysis Engine (nodularity_pipeline.py)
        ↓
Results → Persistence / History
```

Normal upload path (also verified):

```
Image File (upload or dataset selection)
        ↓
Browser (NODIQ-X Web Interface)
        ↓  File / dataset reference
POST /api/analyze   (identical endpoint)
        ↓
Existing NODIQ-X Analysis Engine
        ↓
Results → Persistence / History
```

**Explicit statement for the SRS:** the microscope is an additional image input source. There is
**no second analysis pipeline**; captured microscope images enter the same `POST /api/analyze`
funnel and the same engine as uploaded images. (Byte-identical parity is proven; see §12.)

Ports: Flask API `8001`, Vite dev server `5173` (proxies `/api` to 8001), camera agent `8765`
(overridable via `NODIQ_CAMERA_PORT`).

---

## 5. FRONTEND INVENTORY

Pages/modules in `nodiq-x/src/pages/` (verified files):

- Public: `LandingPage`, `LoginPage`, `SignupPage`, `VerifyOtpPage`, `ResetPasswordPage`,
  `AuthCallbackPage`, `LegalPages` (privacy/terms), `NotFoundPage`.
- Authenticated (behind `RequireAuth`): `Home`, `Dashboard`, `Analysis` (New Analysis — includes
  the microscope panel), `BatchAnalysis`, `MyAnalyses`, `Sessions`, `Analytics`, `Compare`,
  `Anomalies`, `Lots`, `ReviewCenter`, `Copilot`, `Reports`, `ReportGenerator`, `ReportPreview`,
  `Settings`, `Profile`.

Services: `services/api.js` (typed REST helpers; all requests same-origin), `services/authService.js`
(backend auth; explicitly documented: "auth token NEVER reaches JavaScript, is never stored in
localStorage"), `services/microscopeAgent.js` (camera-agent client with typed error codes).

Analysis page (New Analysis) verified behavior:

- Input workspace with three input sources: image upload (file picker + drag-and-drop), dataset
  browser (1,000 images, searchable grid), and the microscope camera panel.
- Microscope panel: status dot (`● Connected` / `○ Camera disconnected` / `○ Camera agent
  offline`), camera model / serial / resolution line, live preview (~1 Hz), `PREVIEW: LIVE (1 s
  refresh)` state line, `CAPTURE IMAGE` button directly below the preview, capture-ready wording
  "✓ Capture ready — click START ANALYSIS to analyze." (only after capture; analysis wording
  "Analysis started…" only while a run is in progress), RETRY buttons for recoverable states.
- Results area: nodule count, ISO/JIS nodularity views, engine self-check accuracy, graphite forms
  (ISO 945 I–VI), estimated properties (labeled estimates), segmentation/annotation overlays,
  roundness histogram.

---

## 6. BACKEND ENDPOINT GROUPS (58 API PATHS)

Grouped listing of the 58 verified `/api/*` paths in `server.py`:

| Group | Paths |
|---|---|
| Authentication (8) | `/api/auth/signup`, `/login`, `/logout`, `/me`, `/firebase`, `/forgot-password`, `/reset-password`, `/change-password` |
| Analysis (12) | `/api/analyze`; `/api/analyses`; `/api/analyses/stats`; `/api/analyses/<id>`; `…/image`, `…/overlay`, `…/artifact/<kind>`, `…/context`, `…/lot`, `…/review`, `…/nodules`, `…/nodules/<n>` |
| Reports (6) | `/api/reports`, `/api/reports/<id>`, `/api/reports/<id>/download`, `/api/reports/<id>/evidence/<kind>`, `/api/reports/generate`, `/api/reports/ai-summary` |
| Copilot / AI (5) | `/api/copilot`, `/api/copilot/chat`, `/api/copilot/health`, `/api/copilot/capabilities`, `/api/ai/status` |
| Dataset (4) | `/api/dataset`, `/api/dataset/sample`, `/api/dataset/file/<name>`, `/api/dataset/analysis/<name>` |
| Multi-field sessions (4) | `/api/multifield`, `/api/multifield/<sid>`, `/api/multifield/<sid>/fields`, `/api/multifield/<sid>/statistics` |
| Login sessions (3) | `/api/sessions`, `/api/sessions/<sid>`, `/api/sessions/current` |
| Batch / SPC (4) | `/api/batch/stats`, `/api/batch/distributions`, `/api/batch/<id>/spc`, `/api/spc` |
| Anomalies (2) | `/api/anomalies`, `/api/anomalies/<id>` |
| Lots (2) | `/api/lots`, `/api/lots/<lot_id>` |
| Validation lab (2) | `/api/validation`, `/api/validation/run` |
| Other single routes (6) | `/api/compare`, `/api/decision-support`, `/api/calibration`, `/api/quality/<id>`, `/api/feedback`, `/api/health` |

Non-API paths (3): `/` (SPA root), `/<path:path>` (SPA fallback for client-side routes),
`/dataset/<path:filename>` (dataset image files).

---

## 7. ANALYSIS ENGINE FACTS

File: `nodularity_pipeline.py` (1,225 lines; OpenCV + NumPy). Verified pipeline stages and
functions:

| Stage | Verified implementation |
|---|---|
| Image load | `load_grayscale` / `load_with_source` — grayscale load, scale normalization, EXR-safe read path |
| Annotation handling | `find_annotation_overlays` + `blank_figure_annotations` — detects and blanks figure furniture (scale bars, labels, panels) using `ANNOT_*` thresholds (e.g. `ANNOT_MAX_BOXES = 8`, `ANNOT_BAR_MIN_MAX_DIM = 200`) |
| Validity gate | `evaluate_microstructure_validity` — rejects blank/black/saturated/non-microstructure inputs and strongly colored photographs (colorfulness > 45; all 1,000 dataset micrographs measure ≤ 20.6) |
| Segmentation | Adaptive segmentation of graphite particles; `blob_label_map` matrix reference |
| Contour filtering | Area filtering + `contour_dark_fraction` against the blob label map |
| Touching particles | `_split_touching_pair` — splits touching particle pairs |
| Per-particle metrics | circularity, aspect ratio, solidity, roundness |
| Reference/self-check | `reference_particles` + `accuracy_vs_reference` — the engine's own self-check metric |
| Nodularity | `apply_size_filter_and_iso` — ISO 945-4-oriented **area-weighted** nodularity and JIS G 5502-oriented **count-weighted** nodularity; optional ISO 10 µm size rule when calibrated |
| Calibration | `microns = pixels × microns_per_pixel`; calibration accepted only when finite and > 0 (invalid values mean "no calibration"); sources: direct value, manual scale bar, or scale-bar auto-detect |
| Frontend output | `analyze_for_frontend` / `analyze_for_frontend_json` — nodule table, ISO/JIS %, form shares, base64 masks, overlay |
| Downscaling | Large images are downscaled to a 2000 px long side for analysis (e.g. 2592×1944 → 2000×1500) with an explicit user-facing warning ("nodularity percentages are unaffected"); original bytes preserved |
| Crash isolation | `analysis_child.py` + `analyze_with_recovery.py` run the engine out-of-process; `NODIQ_EXEC_MODE` defaults to `thread` in development (engine loads in the Flask process at boot) |

Downstream domain services (`services/`): `morphology.py` (graphite form classification I–VI),
`properties.py` (tensile/yield estimates + nearest EN-GJS grade, explicitly labeled estimates),
`quality.py` (quality verdict), `calibration.py`, `comparison.py`, `anomalies.py`,
`analytics.py` (SPC), `lots.py`, `multifield.py` (ISO 945-4 multi-field sampling sessions),
`review.py`, `validation_lab.py`, `accuracy_bench.py`, `ground_truth.py`, `nodule_data.py`,
`storage.py`, `mailer.py`, `rate_limit.py`, `seclog.py`.

PDF reports: `report_builder.py` assembles traceability, metrics, ISO/JIS classification,
morphology, property estimates (labeled ESTIMATE), self-check, batch/SPC context, observations,
AI interpretation and a review block.

---

## 8. MICROSCOPE / CAMERA INTEGRATION (PHASES 1–6A, ALL VERIFIED)

Hardware (reference lab setup):

| Item | Verified value |
|---|---|
| Camera | MATRIX VISION mvBlueFOX-ML/IGC205C |
| Serial number | 29605128 |
| Connection | USB (USB 3.0) |
| Mount | Physical metallurgical microscope (optics/stage/illumination are physical, user-operated) |
| SDK | mvIMPACT Acquire Python binding (`ImpactAcquire`) |
| Agent service | `nodiq-camera-agent/agent_server.py` — Python `ThreadingHTTPServer` on `127.0.0.1:8765` |

Agent configuration (verified in `nodiq-camera-agent/config.py`):

| Setting | Value |
|---|---|
| Expected device matching | manufacturer "MATRIX VISION"; model substrings ("mvBlueFOX", "IGC205C"); preferred substrings ("mvBlueFOX", "MATRIX", "Balluff") |
| Acquisition timeout | `ACQUISITION_TIMEOUT_MS = 10_000` (10 s bounded single-frame wait) |
| Idle close | `DEVICE_IDLE_CLOSE_S = 15` (device stays open between requests, closes after 15 s idle so other applications can claim it; env `NODIQ_CAMERA_IDLE_CLOSE_S`) |
| Preview downscale | `PREVIEW_MAX_SIDE = 1024` (env `NODIQ_CAMERA_PREVIEW_MAX`) → live preview JPEG ≈ **1024×768** |
| Capture resolution | Full sensor capture → **2592×1944 PNG** (unchanged by the preview size) |
| CORS | Strict allow-list, never a wildcard host: exact loopback origins only — `localhost` / `127.0.0.1` on ports 5173-5184 (Vite dev, which auto-increments when 5173 is taken) and 4173-4184 (preview); extensible via `NODIQ_CAMERA_ALLOWED_ORIGINS` |
| Frame validation thresholds | `BLACK_MEAN_MAX = 1.0`, `DARK_MEAN_MAX = 20.0`, `WHITE_MEAN_MIN = 254.0` (8-bit-equivalent scale) |
| Pixel handling | 4-byte RGBx stride handling in `camera.py`; no pixel modification of captures |

Agent HTTP API (3 endpoints):

| Endpoint | Behavior |
|---|---|
| `GET /status` | `{connected, device_id, model, manufacturer, serial, resolution}` when connected; `{connected:false}` when no device (including the Phase 5 honest-disconnected case) |
| `GET /preview` | ≈1024×768 JPEG frame (polled ≈1 Hz by the browser) |
| `GET /capture` | Full-resolution 2592×1944 PNG |

Typed error mapping (HTTP status → error code): `NoDeviceFound` → **503** `camera_not_found`;
`DeviceOpenFailed` → **409** `camera_busy`; `CaptureFailed` → **504** `capture_failed`;
`SdkUnavailable` → **503** `sdk_unavailable`; unexpected → **500** `internal_error`.

Phase history (as reported by the phase reports; no engine or funnel changes in any phase):

- **Phase 1** — SDK/device integration: device detection, open/close, capture through the SDK.
- **Phase 2** — capture integration into the app + CSP: `connect-src` extended in `server.py`
  for the agent origin (`http://127.0.0.1:8765` / `localhost:8765`) only; PNA handling.
- **Phase 3** — live preview (~1 Hz sequential polls, stop-before-start, unmount cleanup; no
  duplicate loops) + recovery behavior; device idle-close so other camera applications can
  acquire the device.
- **Phase 4** — real microscope + real specimen validation: live preview of the real field,
  three real captures analyzed through the existing pipeline; exact capture bytes re-uploaded
  produced identical metrics (ANL-71BA41 microscope vs ANL-AB7402 upload; count 10, ISO 14.91 %,
  JIS 53.0 %, accuracy 100, confidence 100 — identical; capture md5
  `0139cfe6430c38e75a9be9b523a1c3ec`).
- **Phase 5** — production hardening: unplug-vs-busy distinction (fresh `DeviceManager`
  enumeration check `_device_gone`; open failure on a vanished device → 503 "Camera
  disconnected" instead of 409; conservative fallback preserves the busy path), honest
  `/status` (`connected:false` when the device is gone), truthful UI wording
  ("Capture ready — click START ANALYSIS to analyze." / "Analysis started…"), typed
  disconnected/offline/busy states with RETRY; 5 new camera-state tests. Parity re-proven on a
  second real capture: ANL-8D4FE7 vs ANL-48B528 (count 19, ISO 28.2 %, JIS 50.0 %, identical
  source 2592×1944 → 2000×1500 downscale warning; capture md5
  `affaf1862ca4ddc44c8cc40492264e64`).
- **Phase 6A** — large live preview (UI only): microscope panel made a full-width sibling of the
  upload zone with an 860 px cap; measured live preview area grew from ≈445×333 px to
  **825×618 px** at a 1600 px viewport (790×592 at 1024 px), aspect ratio 4:3 preserved
  (measured 1.334), no stretching, no page-level horizontal scroll. `/preview` remained
  1024×768 JPEG and capture remained 2592×1944 PNG. A larger on-screen preview does NOT change
  the physical microscope field of view or the number of nodules in a capture.

Camera behaviors verified in real sessions: camera disconnect (USB unplug → typed
disconnected/busy states; replug recovers without agent restart), camera busy (409 + friendly
"being used by another application" message + RETRY + self-recovery), agent offline (clear
message + startup hint + RETRY + recovery after agent restart without page reload), no page
crashes in any state.

---

## 9. DATABASE / PERSISTENCE

Backend selection (`services/db.py`), explicit, never silent:

| Mode | Trigger | Storage |
|---|---|---|
| SQLite (development) | `NODIQ_BACKEND=sqlite`, or unset without `DATABASE_URL` | Single WAL-mode file `server_data/nodiq.db`; stdlib `sqlite3`; module connection guarded by an RLock; one-time import of legacy JSON "databases" (files renamed `*.imported`) |
| Supabase PostgreSQL (production) | `NODIQ_BACKEND=supabase` + `DATABASE_URL` (or unset with `DATABASE_URL` present) | PostgreSQL via `psycopg2` + compatibility layer `services/pgcompat.py`; image artifacts in Supabase Storage at `users/{user_id}/analyses/{analysis_id}/{kind}.{ext}` |

Safety rule (verified): on a Render deployment with unset persistence variables, the app refuses
to boot on the ephemeral SQLite fallback rather than silently losing data; a deliberate rollback
requires explicit `NODIQ_BACKEND=sqlite`.

Design: rows carry a JSON `data` column (payloads evolve without migrations); typed columns exist
only for filter/sort keys (`id`, `user_id`, `created_at`). `user_id = NULL` means shared/legacy
data (kept visible to everyone for back-compat).

Verified tables and fields:

**users** (`services/auth.py`)

| Field | Type | Constraint | Description |
|---|---|---|---|
| id | TEXT | PRIMARY KEY | User ID (e.g. `USR-…`) |
| email | TEXT | UNIQUE NOT NULL | Login email |
| name | TEXT | — | Display name |
| phone | TEXT | — | Phone (optional) |
| password_hash | TEXT | NOT NULL | bcrypt hash ($2b$, cost 12) |
| created_at | TEXT | NOT NULL | ISO timestamp |

**revoked_tokens** (`services/auth.py`)

| Field | Type | Constraint | Description |
|---|---|---|---|
| token_hash | TEXT | PRIMARY KEY | Hash of a revoked token |
| expires_at | REAL | NOT NULL | Natural expiry (revocation rows are rejected until then) |

**sessions** (`services/db.py`) — login-scoped work sessions; analyses are tagged with their session

| Field | Type | Constraint | Description |
|---|---|---|---|
| id | TEXT | PRIMARY KEY | Session ID (e.g. `SES-…`) |
| user_id | TEXT | NOT NULL (indexed with started_at) | Owning user |
| label | TEXT | — | Optional label |
| started_at | TEXT | NOT NULL | Login time |
| ended_at | TEXT | — | Logout time (NULL = active) |

**analyses**

| Field | Type | Constraint | Description |
|---|---|---|---|
| id | TEXT | PRIMARY KEY | Analysis ID (e.g. `ANL-…`) |
| user_id | TEXT | indexed with created_at | Owning user; NULL = shared/legacy |
| created_at | TEXT | — | ISO timestamp |
| data | TEXT | NOT NULL | Full analysis payload JSON (metrics, nodules, masks, quality, calibration, session_id, warnings, …) |

**reports**

| Field | Type | Constraint | Description |
|---|---|---|---|
| id | TEXT | PRIMARY KEY | Report ID |
| user_id | TEXT | indexed with created_at | Owning user |
| created_at | TEXT | — | ISO timestamp |
| data | TEXT | NOT NULL | Full report JSON (embedded document + downloads) |

**feedback**

| Field | Type | Constraint | Description |
|---|---|---|---|
| id | TEXT | PRIMARY KEY | Feedback ID |
| created_at | TEXT | — | ISO timestamp |
| data | TEXT | NOT NULL | Feedback payload JSON |

**calibrations**

| Field | Type | Constraint | Description |
|---|---|---|---|
| key | TEXT | PRIMARY KEY | Calibration key |
| data | TEXT | NOT NULL | Calibration JSON (µm/px, method, provenance) |

Complementary storage (filesystem/objects): `server_data/uploads/` — content-hash-deduplicated
original images (development); Supabase Storage objects (production); `dataset/` — the bundled
1,000 validated micrographs (read-only, served at `/dataset/<file>`).

---

## 10. AUTHENTICATION AND SECURITY

| Aspect | Verified implementation |
|---|---|
| Password hashing | bcrypt, cost 12; legacy PBKDF2-HMAC-SHA256 hashes transparently upgraded to bcrypt on next successful login; a precomputed dummy hash burns the same bcrypt cost for unknown-email logins (timing equalization) |
| Session tokens | HMAC-signed stateless strings `payload.signature`, payload `{uid, exp, sid?}`; 7-day expiry; server-side revocation table (`revoked_tokens`); revoked tokens rejected until natural expiry |
| Transport | HttpOnly + SameSite=Lax + Path=/ cookie with Max-Age matching the 7-day token; the token is never returned in JSON bodies and never exposed to JavaScript (frontend `api.js`: "No Authorization header: browsers attach the HttpOnly session cookie themselves"); the server also accepts an explicit `Authorization: Bearer` header for API clients/tests |
| Reset tokens | Single-use, 30-minute expiry; carry `"k":"reset"`; never accepted as login bearer tokens and vice versa |
| OTP / email | Signup verification (Verify OTP page) and password reset flows via SMTP (`services/mailer.py`; degrades to logging without credentials) |
| Google sign-in | Optional Firebase popup (`signInWithPopup`), exchanged with the backend at `/api/auth/firebase` |
| Authorization | Every protected query scoped by `user_id`; ownership checked on records/evidence; NULL-user legacy rows intentionally shared |
| Rate limiting | `services/rate_limit.py` |
| Security logging | `services/seclog.py` |
| Camera-agent security | Loopback-only (`127.0.0.1:8765`); strict CORS allow-list (never wildcard); Flask CSP `connect-src` extended only for the agent origin and Firebase endpoints; no camera credentials in the browser; no NODIQ credentials sent to the camera agent |
| Secrets | Environment/`.env` only; install secret for token signing in `server_data/secret.key` (auto-generated, chmod 0600 where supported) |

---

## 11. AI COPILOT

| Aspect | Verified implementation |
|---|---|
| Package | `ai/` (`agent.py`, `config.py`, `provider.py`, `groq_provider.py`, `gemini_provider.py`, `openai_compatible_provider.py`, `local_provider.py`, `fallback_provider.py`, `key_rotation.py`, `memory.py`, `prompts.py`, `reference.py`, `tools.py`) |
| Provider chain | Groq (default) → Gemini → OpenAI-compatible → local model → static fallback; provider selection via `AI_PROVIDER`; Groq key rotation (`GROQ_API_KEY`, `GROQ_API_KEY_2…_6`, or comma-separated `GROQ_API_KEYS`) |
| Grounding | Answers are grounded in the actual stored analysis payload (tools + reference context); the copilot explains measured numbers, never invents them |
| Capabilities | Multi-turn with session history (`memory.py`), capability registry, tool calls with tool trace, UI actions |
| Endpoints | `POST /api/copilot`, `POST /api/copilot/chat`, `GET /api/copilot/health`, `GET /api/copilot/capabilities`, `GET /api/ai/status` |
| Offline | Fully functional without provider keys (fallback answers); reports can embed an optional AI interpretation section |

---

## 12. VALIDATION BASELINE (VERIFIED TEST/LINT/BUILD RESULTS)

| Gate | Result (verified this project) |
|---|---|
| Full test suite | **298/298 pytest PASS** (includes 56 engine-pinning tests and 5 camera-state tests); measured run 644 s on the reference machine |
| Pinning tests | **56/56 PASS** (engine regression pinning) |
| Camera-state tests | **5/5 PASS** (`tests/test_camera_agent_states.py` — busy→409, gone→503, honest `/status`, busy status shape, happy path skips the check; stubbed SDK, no hardware needed) |
| Lint | `npx oxlint src` → **0 errors** (26 pre-existing warnings, unchanged) |
| Build | `npm run build` → **PASS** (Vite, 567 modules) |
| Real microscope end-to-end | PASS — real MATRIX VISION camera + real metallurgical microscope: live preview, real specimen capture, capture analyzed by the existing pipeline |
| Capture ↔ upload parity | PASS — exact captured PNG bytes re-uploaded through the normal funnel produced identical metrics, same server boot (Phase 4: count 10 / ISO 14.91 / JIS 53.0 / accuracy 100 / confidence 100 identical; Phase 5: count 19 / ISO 28.2 / JIS 50.0 identical) |
| Camera error handling | PASS — disconnect/reconnect, busy-camera recovery, agent-offline recovery each verified in real sessions |

**Accuracy honesty (required distinction):**

- **Engine self-check / consistency**: the accuracy/confidence values shown in the UI are the
  engine's own comparison against its reference segmentation (e.g. "100 %" = internal
  consistency on that image).
- **Independent metallurgical ground truth**: **none established.** The repository contains no
  certified ground-truth specimen/dataset evidence that would support a metallurgical accuracy
  claim. NODIQ-X results are decision support, not certification, and the SRS must not claim
  certified or independently validated metallurgical accuracy.

---

## 13. LIMITATIONS AND HONESTY NOTES (DOCUMENTED, NOT DEFECTS)

1. **Clean-unplug enumeration staleness**: the camera SDK's in-process device enumeration can keep
   a stale entry after a physical USB unplug; in some live-drop sequences the agent therefore
   surfaces the typed busy path (409) rather than the disconnected path (503). The Phase 5
   `_device_gone` fresh-enumeration check fixes the case where the fresh enumeration is
   authoritative (verified by hardware probe: count 0 unplugged / 1 replugged) and preserves the
   busy behavior conservatively otherwise. Every path is typed, recoverable (RETRY), and
   crash-free.
2. **No camera exposure/gain/focus controls** — illumination and focus are physical operations
   (explicit scope decision; not implemented).
3. **Single-client camera** — while another application (e.g. ImpactControlCenter / wxPropView)
   holds the camera, the agent reports busy; the agent releases the device after 15 s idle.
4. **Live preview ≠ capture** — preview is a ≈1024×768 JPEG positioning aid at ≈1 Hz; capture is
   the full 2592×1944 PNG. The on-screen preview size (enlarged in Phase 6A) does not change the
   physical field of view or the captured content.
5. **Hardware flakiness observed** — the reference camera dropped off the USB bus three times on
   one test day (fresh SDK count 0; recovery by physical replug); this is a physical/driver-level
   issue, outside software scope.
6. **Too-bright condition** — not physically reachable with the reference lamp; engine saturation
   handling is covered by the test suite instead.
7. **"Analysis started…" is transient** on fast runs (the result can render between UI polls).
8. **Docs drift** — some repository documents are older than the code (e.g. `docs/ARCHITECTURE.md`
   "49 endpoints" and its Bearer/localStorage auth description; `docs/ARCHITECTURE.md` CI note
   mentions 41 tests). The code-verified values in this document take precedence.
9. **Metallurgical ground truth** — not established (see §12).

---

## 14. KNOWN CONSTRAINTS (FOR SRS §CONSTRAINTS)

| Constraint | Verified value |
|---|---|
| Supported upload formats | PNG / JPEG (UI text: "SUPPORTED: JPG / PNG") |
| Maximum upload size | 25 MB (UI text: "MAX 25 MB") |
| Analysis downscaling | Images downscaled to 2000 px long side for analysis (2592×1944 → 2000×1500) with a visible warning; original bytes preserved |
| Quality validation thresholds | Reject black (<1 mean), effectively dark (<20), saturated (>254); non-microstructure images and strongly colored photographs (Hasler–Süsstrunk colorfulness > 45) rejected by the engine validity gate |
| Camera dependency | MATRIX VISION camera connected, not held by another application; mvIMPACT Acquire runtime + Python binding installed |
| Agent dependency | Local camera agent process on 127.0.0.1:8765; browser origin must be in the agent allow-list; CSP `connect-src` must include the agent origin |
| Network exposure | Camera agent is loopback-only; no public exposure; no wildcard CORS |
| Browser requirements | Chromium-class desktop browser with `fetch`/Blob/File APIs; Private Network Access handled for loopback calls |
| Platform scope | Camera integration validated on Windows (SDK binding); the web application itself is cross-platform |
| Ports | 8001 (Flask), 5173 (Vite dev), 8765 (camera agent, `NODIQ_CAMERA_PORT` overridable) |
| Engine authority | Exactly one analysis pipeline (`nodularity_pipeline.py`); microscope capture reuses the upload funnel verbatim; the engine must not be duplicated or bypassed |
| Persistence | `NODIQ_BACKEND=sqlite` (dev) or `supabase` + `DATABASE_URL` (prod); Render refuses silent ephemeral-SQLite fallback |
| Optional services | AI provider keys, SMTP credentials, Firebase config — all optional; full offline degradation |
| Deployment | Dev: `python server.py` (serves API + built SPA on 8001); prod: Docker/Gunicorn + Render config (`render.yaml`, `DEPLOY_SUPABASE.md`) |

---

*End of fact sheet. Compiled 2026-10-01 from the NODIQ-X repository, its schema/configs, and the
Phase 1–6A reports. No application code, tests, configuration, or existing reports were modified
in producing this document.*
