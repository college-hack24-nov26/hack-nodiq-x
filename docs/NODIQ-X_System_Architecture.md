# NODIQ-X System Architecture

**AI-Powered Microstructure Intelligence — Ductile/Nodular Cast Iron Microstructure and
Nodularity Analysis · Version 1.6.0**

Companion files: `NODIQ-X_System_Architecture.png` (3224×2502 px, print-ready),
`NODIQ-X_System_Architecture.svg` (vector, scales cleanly to A4/A3),
`NODIQ-X_System_Architecture.drawio` (editable). Factual source: `docs/NODIQ-X_PROJECT_INFO.md`.
SRS: `docs/NODIQ-X_SRS.md`.

## 1. Layered overview

```
┌────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 1 — PRESENTATION                                                        │
│  User / Operator → NODIQ-X Web Interface                                       │
│  (React 19.2.8 + Vite 8.2.0 SPA: Upload · Dataset · Microscope Panel ·         │
│   Live Preview · Capture · Analysis & Results · History · Reports · Copilot)   │
└────────────────────────────────────────────────────────────────────────────────┘
        ▲ image file/dataset (up)                    ▲ capture + preview (HTTP)
        │                                            │
┌───────┴────────────────────────────────────────────┴───────────────────────────┐
│  LAYER 2 — MICROSCOPE / IMAGE ACQUISITION   (additional input source)          │
│  Metallurgical Microscope → MATRIX VISION Camera (mvBlueFOX-ML/IGC205C)        │
│    → mvIMPACT Acquire SDK → Local Camera Agent 127.0.0.1:8765                  │
│    (/status · /preview · /capture · 15 s idle-close)                           │
└────────────────────────────────────────────────────────────────────────────────┘
                                    │  both inputs converge
                                    ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 3 — APPLICATION / API                                                   │
│  NODIQ-X Flask API — server.py :8001                                           │
│  (Auth · Upload · Analysis API · Reports · History · Calibration · SPC/Lots/   │
│   Batch · Anomalies · Review · Copilot API · Dataset serving)                  │
└────────────────────────────────────────────────────────────────────────────────┘
                                    │ engine run
                                    ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 4 — ANALYSIS ENGINE (SINGLE PIPELINE — BOTH INPUTS CONVERGE)            │
│  1 Image loading/normalization → 2 annotation blanking → 3 validation →        │
│  4 adaptive segmentation → 5 contour filtering & pair splitting →              │
│  6 particle morphology → 7 ISO 945-4 + JIS G 5502 (forms I–VI) →               │
│  8 Results (masks · overlay · histogram · self-check)                          │
│  (OpenCV 5.0.0.93 + NumPy 2.4.6 · crash-isolated child process)                │
└────────────────────────────────────────────────────────────────────────────────┘
                                    │ persist analysis + original image
                                    ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 5 — DATA / PERSISTENCE                                                  │
│  SQLite (WAL) server_data/nodiq.db  ─ or ─  Supabase PostgreSQL + Storage      │
│  users · sessions · analyses · reports · feedback · calibrations ·             │
│  revoked_tokens · uploads (hash-deduped) · dataset (1,000 images)              │
└────────────────────────────────────────────────────────────────────────────────┘
        ┌────────────────────  results & history (read)  ◄────────────────────┐
        │                                                                     │
┌───────┴─────────────────────────────────────────────────────────────────────┴──┐
│  LAYER 6 — EXTERNAL / SUPPORTING SERVICES (all optional)                       │
│  Firebase Authentication (Google sign-in) · AI Providers (Groq → Gemini →      │
│  OpenAI-compatible → Local → Fallback) · SMTP Mailer (OTP/reset/SPC alerts)    │
└────────────────────────────────────────────────────────────────────────────────┘
```

## 2. The single analysis funnel (most important property)

```
NORMAL IMAGE UPLOAD ──────────────┐
                                  │
                                  ▼
                     NODIQ-X Web Interface (browser)
                                  ▲
MICROSCOPE CAMERA CAPTURE         │
  Metallurgical Microscope        │
        ↓                         │
  MATRIX VISION Camera            │
        ↓                         │
  mvIMPACT Acquire                │
        ↓                         │
  Local Camera Agent :8765 ───────┘
                  │
                  ▼
        NODIQ-X Flask API :8001        POST /api/analyze (202 + poll)
                  │
                  ▼
        Image Validation
                  │
                  ▼
        Existing Nodularity Engine (nodularity_pipeline.py)
                  │
                  ▼
        Analysis / Morphology
                  │
                  ▼
        ISO 945-4 (area-weighted) · JIS G 5502 (count-weighted)
                  │
                  ▼
              Results
                  │
                  ▼
        Persistence / History
```

The microscope is an **additional image input source**. There is **no second analysis
pipeline**: captured microscope images enter the same endpoint and the same engine as uploaded
images (byte-identical parity verified — see SRS §11).

## 3. Layer reference

| Layer | Components (verified) | Key facts |
|---|---|---|
| 1 Presentation | React 19.2.8, Vite 8.2.0, React Router (27 routes), Analysis UI, Microscope UI | Same-origin API calls; HttpOnly cookie session |
| 2 Acquisition | Metallurgical microscope; MATRIX VISION mvBlueFOX-ML/IGC205C (S/N 29605128); mvIMPACT Acquire; Local Camera Agent | Agent :8765 — `GET /status`, `GET /preview` (≈1024×768 JPEG, ≈1 Hz), `GET /capture` (2592×1944 PNG); 15 s idle-close; typed errors 409/503/504 |
| 3 Application/API | Flask 3.1.3 (`server.py`, :8001) | 58 REST API endpoint paths / 68 route registrations (41 GET, 23 POST, 4 DELETE) + 3 non-API paths; auth, upload, analysis (202+poll), reports, history, calibration, quality, SPC/batch/compare/lots, anomalies, review, Copilot, dataset |
| 4 Analysis engine | `nodularity_pipeline.py` (OpenCV + NumPy), crash-isolated child | Loading → blanking → validation → segmentation → filtering/splitting → morphology → ISO 945-4/JIS G 5502 (forms I–VI) → results; engine self-check |
| 5 Data | SQLite WAL / Supabase PostgreSQL + Storage | Tables: users, sessions, analyses, reports, feedback, calibrations, revoked_tokens; uploads hash-deduped; dataset/ 1,000 images |
| 6 External (optional) | Firebase Auth; AI providers; SMTP | All optional; full offline degradation |

## 4. Cross-cutting notes

### SECURITY — CROSS-CUTTING

**Authentication & Session** — bcrypt (cost 12) password hashing; HMAC-signed tokens in
HttpOnly SameSite=Lax cookies (Secure auto-enabled over HTTPS); 7-day expiry; server-side
token revocation on logout; single-use 30-min reset tokens (separate token family);
per-login work sessions — tokens bound to a deleted session stop authenticating.
IMPLEMENTED.

**Authorization** — per-user data scoping on every record route (404 for strangers);
RBAC foundation: operator (default) / reviewer (electronic sign-off) / admin (role
administration), stored server-side, environment allow-list bootstrap, clients can never
send a role. IMPLEMENTED.

**API & Web Security** — CSRF/Origin protection on all state-changing API routes (403 +
audit log on untrusted origin; Bearer API clients and non-browser clients unaffected);
CORS allow-list (never wildcard); sliding-window rate limiting shared across workers
(fail-closed); structured security audit log (login failures, authz failures, CSRF
rejects, upload rejects, rate-limit events, admin actions, review actions, token
revocation — never any credential material); enforced CSP with Firebase reCAPTCHA hosts
and camera-agent `connect-src`; security headers (nosniff, frame DENY, Referrer-Policy,
Permissions-Policy) + HSTS over HTTPS only. IMPLEMENTED.

**File Security** — PNG/JPEG/TIFF/BMP magic-byte allow-list; real decode gate;
declared MIME cross-checked for audit only; 25 MB size cap; header-level dimension caps
(≤20,000 px/side, ≤50 MP) before decode (decompression-bomb guard) +
`OPENCV_IO_MAX_IMAGE_PIXELS` backstop; client filenames never trusted (server-generated
hash names; sanitized display name); persisted-upload paths contained inside
`server_data/uploads/`; dataset serving restricted to `micrograph_NNNN.png`.
IMPLEMENTED.

**Infrastructure** — HTTPS/TLS readiness: Secure cookies auto over HTTPS, HSTS over
HTTPS/trusted-proxy only, plain-HTTP localhost unaffected (hardware/browser deployment
validation deferred — hardware unavailable during this phase); secret management: env
vars + gitignored `.env` (placeholders-only `.env.example`), no secrets in React bundle,
logs or source (regression-tested); dependency audit: Python direct deps clean,
npm tree clean except `@grpc/grpc-js` (see phase report) — documented, no blind major
upgrades; database backup/recovery documented in `docs/DEPLOY_SUPABASE.md` +
`docs/SECURITY.md`; additive-only schema changes (no destructive migrations).
IMPLEMENTED (documentation-level).

**Camera Agent** — binds 127.0.0.1:8765 (never 0.0.0.0); GET/OPTIONS only; CORS
allow-list (localhost dev origins + `NODIQ_CAMERA_ALLOWED_ORIGINS`, never wildcard);
typed errors (409/503/504); no credentials handled. Code/configuration reviewed.
IMPLEMENTED. Physical camera security validation: **Deferred — hardware unavailable
during this phase.**

### Other cross-cutting notes

- Error states (camera): offline (`agent not reachable` + hint + RETRY), disconnected
  (`503 camera_not_found` + RETRY), busy (`409 camera_busy` + RETRY + self-recovery) — typed
  and user-readable; preview failures degrade to "UNAVAILABLE — will retry".
- Honesty: accuracy/confidence values are the engine self-check (internal consistency); no
  independent metallurgical ground truth has been established.

*Regenerate the diagram with `python .freebuff/srs_build/gen_diagram.py` (layout defined once;
emits SVG, PNG and drawio together).*
