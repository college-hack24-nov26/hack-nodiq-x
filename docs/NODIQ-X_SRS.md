# SOFTWARE REQUIREMENTS SPECIFICATION

# NODIQ-X

## AI-Powered Microstructure Intelligence for Ductile/Nodular Cast Iron Microstructure and Nodularity Analysis

**Version 1.6.0**

| | |
|---|---|  
| Prepared By | ____________________________ |
| Reviewed By | ____________________________ |
| Approved By | ____________________________ |
| Date | 01 / 10 / 2026 |

---

## 1. Introduction

### 1.1 Purpose

This Software Requirements Specification (SRS) defines the functional and non-functional
requirements of **NODIQ-X**, a web-based metallurgical analysis system that converts
metallographic (microstructure) images of ductile/nodular cast iron into measured, classified and
traceable nodularity results. The specification is the factual source for the design,
implementation, verification and acceptance of the system.

Every statement in this SRS is grounded in the implemented NODIQ-X repository and its verified
phase reports; facts are documented in `docs/NODIQ-X_PROJECT_INFO.md`. Requirements are labeled
with their implementation status:

- **[IMPLEMENTED]** — verified in the repository.
- **[PARTIALLY IMPLEMENTED]** — implemented with a documented, bounded gap.
- **[PLANNED]** — future work; not implemented.

### 1.2 Scope

NODIQ-X provides the following implemented capabilities (all verified; see §3 for requirement
IDs):

- Image input from **two sources**: (1) normal image upload (file picker, drag-and-drop) or
  selection from a bundled 1,000-image validated dataset, and (2) **microscope camera capture**
  through a MATRIX VISION mvBlueFOX-ML/IGC205C camera and a localhost camera agent.
- **A single analysis pipeline**: both input sources converge into the same
  `POST /api/analyze → existing nodularity engine` flow. No second engine exists.
- Image validation, preprocessing, annotation blanking, graphite particle detection, per-particle
  morphology, ISO 945-4-oriented (area-weighted) and JIS G 5502-oriented (count-weighted)
  nodularity, graphite form classification (I–VI), an engine self-check, and optional µm/pixel
  calibration.
- Result visualization (count, ISO/JIS views, masks, overlay, histogram, form shares, property
  estimates labeled as estimates), analysis history/persistence, PDF report generation.
- SPC analytics, anomaly screening, batch analysis, comparison, lot traceability, multi-field
  ISO sampling sessions, and an expert Review Center.
- A grounded AI Copilot (Groq → Gemini → OpenAI-compatible → local → fallback provider chain)
  that explains stored measurements and degrades fully offline.
- Authentication (bcrypt + HMAC-signed HTTP-only cookies, revocation, reset tokens, OTP via
  SMTP, optional Firebase Google sign-in), typed camera error states, and comprehensive error
  handling.

Out of scope: laboratory certification, automated stage/objective control, camera
exposure/gain/focus remote controls, WebSocket/MJPEG streaming, and any second analysis
pipeline (none exists by design).

### 1.3 Product Overview

NODIQ-X is a single-origin web application (Flask API serving a React 19 + Vite SPA on port
8001) with an optional laboratory camera attachment (a local Python camera agent on
127.0.0.1:8765 wrapping the mvIMPACT Acquire SDK). A user supplies a micrograph from either
input source; the system validates it, runs the existing OpenCV/NumPy nodularity engine,
renders the results (nodule count, ISO/JIS nodularity, graphite forms, masks, histogram,
self-check, property estimates), and persists the analysis with full traceability. Analysis
records support review sign-off, SPC analytics, lot acceptance decisions, comparison, and PDF
reporting.

Accuracy framing: accuracy/confidence values shown by the system are the **engine self-check**
(consistency against the engine's own reference segmentation). **No independent metallurgical
ground truth has been established**; NODIQ-X is decision support, not certification.

### 1.4 Intended Users

| User class | Description | Capabilities |
|---|---|---|
| Visitor | Unauthenticated browser user | Landing page, login, signup, OTP verification, password reset, legal pages |
| User / Operator (Analyst) | Authenticated account (primary user) | Upload/capture/dataset analysis, results, history, sessions, reports, Copilot, batch, SPC views |
| Reviewer / Quality Engineer | Authenticated account using quality features | Review Center sign-off, lot acceptance, decision support |
| Deployment operator | Person hosting/operating the server | Process and environment management, persistence-backend configuration, secret management (outside the application UI) |

### 1.5 Definitions and Acronyms

| Term | Definition |
|---|---|
| SRS | Software Requirements Specification (this document) |
| NODIQ-X | The system specified here |
| Nodule | Spheroidal (globular) graphite particle in ductile cast iron |
| Nodularity | Proportion of spheroidal graphite; computed as ISO 945-4-oriented area-weighted % and JIS G 5502-oriented count-weighted % |
| Micrograph | Photograph of a microstructure (primary input image) |
| Microstructure | Microscopic appearance of graphite particles in the metal matrix |
| Microscope | Physical metallurgical microscope used with the mounted camera for live capture |
| ROI | Region of interest (analysed image area) |
| CV | Computer vision |
| API | Application Programming Interface (HTTP/JSON) |
| UI | User interface (React SPA) |
| OpenCV / NumPy | Image-processing and numeric libraries used by the engine |
| ISO / JIS | ISO 945-4 and JIS G 5502 — oriented graphite classification frameworks |
| PNG / JPEG | Supported image formats |
| SDK | Software development kit (here: camera vendor SDK) |
| MATRIX VISION | Camera manufacturer (mvBlueFOX-ML/IGC205C, S/N 29605128) |
| mvIMPACT Acquire | MATRIX VISION/Balluff SDK used by the camera agent |
| Camera Agent | Local Python HTTP service (port 8765) wrapping the SDK: `/status`, `/preview`, `/capture` |
| SPA | Single-page application |
| SPC | Statistical process control |
| Copilot | NODIQ-X's AI assistant feature (grounded in stored measurements) |
| Engine self-check | The engine's consistency metric against its own reference segmentation — not a metallurgical verdict |

### 1.6 References

1. `docs/NODIQ-X_PROJECT_INFO.md` — verified fact sheet (primary source of truth for this SRS).
2. `PRD.md` — NODIQ-X Product Requirements Document v1.0 (2026-09-21).
3. `docs/ARCHITECTURE.md`, `docs/API.md` — system architecture and API reference (note: "49
   endpoints" predates the current 58-path API; §3.0 of this SRS states the verified counts).
4. `docs/ACCURACY.md`, `docs/GROUND_TRUTH.md`, `docs/BASELINE.md`, `docs/TEST_PLAN.md` —
   accuracy/validation documentation.
5. `docs/SECURITY.md`, `docs/FINAL_SECURITY_REPORT.md` — security documentation.
6. Phase reports: `nodiq-camera-agent/phase23_report.md`, `phase4_report.md`,
   `phase5_report.md`, `phase6a_large_preview_report.md`.
7. `.freebuff/run.md` — developer run instructions (three-process startup).
8. mvIMPACT Acquire SDK (MATRIX VISION/Balluff Python binding `ImpactAcquire`).
9. OpenCV documentation — https://docs.opencv.org
10. ISO 945-4 and JIS G 5502 — oriented classification frameworks implemented in
    `services/morphology.py` and `nodularity_pipeline.py`.

---

## 2. Overall Description

### 2.1 Product Perspective

NODIQ-X is implemented as six layers (see also the System Architecture deliverable):

1. **Presentation layer** — React 19.2.8 SPA (Vite 8.2.0, React Router, 27 route entries) in the
   browser; dark-theme UI; `RequireAuth` guard; `AuthContext` session state.
2. **Microscope / image acquisition layer** — MATRIX VISION mvBlueFOX-ML/IGC205C camera
   (S/N 29605128) on a physical metallurgical microscope; mvIMPACT Acquire SDK; local Python
   camera agent on 127.0.0.1:8765 (`/status`, `/preview`, `/capture`).
3. **Application / API layer** — Flask 3.1.3 (`server.py`) on port 8001; 58 REST API endpoint
   paths across 68 route registrations (41 GET / 23 POST / 4 DELETE) plus 3 non-API paths (SPA
   root, SPA fallback, dataset files); serves the built SPA, dataset and evidence on one origin.
4. **Analysis engine layer** — the single `nodularity_pipeline.py` pipeline (OpenCV 5.0.0.93 +
   NumPy 2.4.6) with crash isolation (`analysis_child.py`, `analyze_with_recovery.py`), plus
   domain services in `services/`.
5. **Data / persistence layer** — SQLite (WAL) `server_data/nodiq.db` (development) or
   PostgreSQL via Supabase + Supabase Storage (production), selected by `NODIQ_BACKEND`; local
   hash-deduplicated uploads; bundled dataset.
6. **External / supporting services (optional)** — Firebase Authentication (Google sign-in), AI
   provider chain (Groq → Gemini → OpenAI-compatible → local → fallback), SMTP mailer.

**Convergence rule (critical architecture concept):** both image input sources — normal upload
and microscope capture — enter the **same** analysis pipeline (`POST /api/analyze → existing
nodularity engine`). The microscope is an additional input source; there is no second analysis
pipeline.

### 2.2 Product Functions

Verified implemented functions (requirement IDs in §3): user authentication; image upload with
validation and content-hash dedupe; dataset browsing (1,000 micrographs with reference metrics);
camera detection/status display with three typed states; live preview (~1 Hz, large responsive
4:3 view); full-resolution capture (2592×1944 PNG); image validation and annotation blanking;
adaptive segmentation and nodule detection; per-particle morphology; ISO 945-4 and JIS G 5502
nodularity with graphite forms I–VI; optional µm calibration with ISO 10 µm size rule; result
visualization with masks/overlay/histogram; per-user analysis history and sessions; PDF report
generation; SPC/analytics/anomalies/batch/compare/lots/multi-field sessions; Review Center;
grounded AI Copilot; typed camera error handling; engine crash isolation.

Planned (not implemented): camera exposure/gain/focus controls, automatic µm calibration from
objective metadata, WebSocket/MJPEG streaming, stage automation.

### 2.3 User Classes

See §1.4. NODIQ-X has no server-side role objects; authorization is account-scoped (per-user
record scoping; legacy NULL-user rows remain shared by design).

### 2.4 Operating Environment

| Component | Verified value |
|---|---|
| OS | Windows 10/11 (development/lab); Docker (Dockerfile, docker-compose.yml) / Render (render.yaml) for deployment |
| Python | 3.11.8 (Flask 3.1.3, flask-cors ≥ 6.0.0, opencv-python 5.0.0.93, NumPy 2.4.6, fpdf2 ≥ 2.8, reportlab ≥ 4.0, bcrypt ≥ 4.0, psycopg2-binary ≥ 2.9, requests 2.34.2) |
| Node.js | v22.23.2 (frontend tooling) |
| Frontend | React 19.2.8, React Router, Vite 8.2.0, Firebase JS SDK ^12.19.0 |
| Browser | Chromium-class desktop browser (fetch/Blob/File APIs; loopback Private Network Access) |
| Database | SQLite WAL (dev) / Supabase PostgreSQL (prod) |
| Storage | `server_data/uploads/` hash-deduped (dev) / Supabase Storage (prod); `dataset/` 1,000 images |
| Camera | MATRIX VISION mvBlueFOX-ML/IGC205C (USB, S/N 29605128); mvIMPACT Acquire SDK + Python binding |
| Camera agent | Python stdlib `ThreadingHTTPServer`, 127.0.0.1:8765 |
| Ports | 8001 (Flask), 5173 (Vite dev, proxies /api), 8765 (agent; `NODIQ_CAMERA_PORT` overridable) |
| Optional services | Groq/Gemini/OpenAI-compatible/local AI providers; SMTP |

### 2.5 Design Constraints

- Supported upload formats: PNG/JPEG; maximum upload size 25 MB (frontend guard).
- Engine analyzes at ≤ 2000 px long side (2592×1944 → 2000×1500) with an explicit user-facing
  warning ("nodularity percentages are unaffected"); original bytes preserved.
- Microscope capture requires: camera connected, camera agent running, camera not held by
  another application (single-client; ImpactControlCenter/wxPropView must be closed).
- Camera agent is loopback-only with a strict CORS allow-list (never a wildcard); Flask CSP
  extends `connect-src` only for the agent origin and Firebase endpoints; PNA handled.
- The camera is slow at full resolution: agent caches the open device for 15 s idle
  (`NODIQ_CAMERA_IDLE_CLOSE_S`), preview downscales to a 1024 px long side (≈1024×768 JPEG),
  capture waits up to 10 s (`ACQUISITION_TIMEOUT_MS`).
- Preview is a positioning aid only; it never substitutes for full-resolution capture; on-screen
  preview size does not change the physical field of view.
- The existing engine is authoritative: exactly one pipeline; camera capture reuses the upload
  funnel verbatim; no pixel modification of captures (4-byte RGBx stride handling preserved).
- Engine self-check accuracy is a consistency metric, not metallurgical ground truth.
- Camera integration validated on Windows (SDK binding); the web app itself is cross-platform.

### 2.6 Assumptions and Dependencies

- A compatible MATRIX VISION camera is connected for microscope features; upload/dataset flows
  work without it.
- The camera agent process is running for microscope features; the UI detects its absence and
  shows recovery instructions.
- A supported desktop browser with loopback access is used.
- The Flask backend is reachable and the configured persistence backend is available
  (`DATABASE_URL` for Supabase; writable `server_data/` for SQLite).
- Dependencies are installed (`pip install -r requirements.txt`; `npm ci` in `nodiq-x/`; the
  ImpactAcquire wheel for camera features).
- Inputs are usable micrographs; invalid images are rejected gracefully.
- AI provider keys and SMTP credentials are optional; without them the Copilot uses its fallback
  and email features degrade to server logs.

## 3. Functional Requirements

Status labels: [IMPLEMENTED] verified in the repository; [PARTIALLY IMPLEMENTED] with a
documented gap; [PLANNED] future work. All requirements use "The system shall…".

### 3.1 Authentication and Accounts

| ID | Requirement | Status |
|---|---|---|
| FR-001 | The system shall register users with name, phone, email and password, store passwords only as bcrypt hashes (cost 12), and upgrade legacy PBKDF2 hashes to bcrypt on next successful login. | [IMPLEMENTED] |
| FR-002 | The system shall authenticate users by email and password and issue a session as an HMAC-signed token in an HttpOnly, SameSite=Lax cookie with 7-day expiry; the token shall never be exposed to JavaScript or returned in JSON bodies. | [IMPLEMENTED] |
| FR-003 | The system shall support server-side token revocation (revoked tokens rejected until natural expiry) and logout that clears the session and closes the login-scoped session record. | [IMPLEMENTED] |
| FR-004 | The system shall provide single-use password-reset tokens (30-minute expiry) that are never accepted as login tokens, and email OTP verification for account creation. | [IMPLEMENTED] |
| FR-005 | The system shall optionally support Google sign-in via a Firebase popup, exchanging the Firebase credential with the backend at `/api/auth/firebase`. | [IMPLEMENTED] |
| FR-006 | The system shall scope every protected record and evidence request to the authenticated user; legacy rows with no owner remain shared. | [IMPLEMENTED] |
| FR-007 | The system shall equalize login timing for unknown emails by performing a dummy bcrypt verification. | [IMPLEMENTED] |
| FR-008 | The system shall rate-limit abusive request patterns and record security-relevant events to a security log. | [IMPLEMENTED] |

### 3.2 Image Input (Source 1 — Upload and Dataset)

| ID | Requirement | Status |
|---|---|---|
| FR-009 | The system shall accept PNG/JPEG images up to 25 MB via file picker and drag-and-drop, and shall reject unsupported or oversized inputs with a clear message. | [IMPLEMENTED] |
| FR-010 | The system shall store uploaded images content-hash-deduplicated and preserve the original bytes unmodified. | [IMPLEMENTED] |
| FR-011 | The system shall serve a bundled dataset of 1,000 validated micrographs with per-image reference metrics and allow one-click analysis of any dataset image. | [IMPLEMENTED] |
| FR-012 | The system shall stage any selected input (upload or dataset) as the current analysis input and display its filename and preview before analysis. | [IMPLEMENTED] |

### 3.3 Image Input (Source 2 — Microscope Camera)

| ID | Requirement | Status |
|---|---|---|
| FR-013 | The system shall detect the locally available camera through the camera agent (`GET /status`) and display connection status with camera model, serial number and resolution. | [IMPLEMENTED] |
| FR-014 | The system shall distinguish three recoverable states in the microscope panel: connected (`● Connected`), camera disconnected (`○ Camera disconnected` + RETRY) and agent offline (`○ Camera agent offline` + startup hint + RETRY). | [IMPLEMENTED] |
| FR-015 | The system shall display a live preview by polling the agent (`GET /preview`) approximately once per second, sequentially (never concurrent duplicate loops), started when the microscope panel opens and stopped when it closes or the page unmounts. | [IMPLEMENTED] |
| FR-016 | The system shall render the live preview in a large responsive container that uses the available panel width (up to an 860 px cap), preserves the 4:3 camera aspect ratio without stretching, and introduces no page-level horizontal scrolling. | [IMPLEMENTED] |
| FR-017 | The system shall capture a full-resolution image (`GET /capture`, 2592×1944 PNG on the reference camera) when the user presses CAPTURE IMAGE, and shall disable the capture control while a capture is running (no duplicate captures). | [IMPLEMENTED] |
| FR-018 | The system shall state capture readiness truthfully: after a capture the panel/message shall read "Capture ready — click START ANALYSIS to analyze."; the wording "Analysis started…" shall appear only while an analysis run is in progress. | [IMPLEMENTED] |
| FR-019 | The system shall route captured images into the same analysis funnel as uploads (`captureImage() → Blob → File → runOnFile() → startAnalysis() → POST /api/analyze`); no separate microscope endpoint or engine shall exist. | [IMPLEMENTED] |
| FR-020 | The system shall handle a busy camera (`409 camera_busy`) with a friendly "being used by another application" message and RETRY, and shall self-recover when the holder releases the camera. | [IMPLEMENTED] |
| FR-021 | The system shall, on open failure with the device no longer enumerating in a fresh device scan, report a typed `503 camera_not_found` "Camera disconnected" state with RETRY; where SDK enumeration staleness prevents a reliable distinction, it shall conservatively fall back to the busy state rather than risk a false disconnected state. | [PARTIALLY IMPLEMENTED] |
| FR-022 | The system shall recover from camera-agent restarts and camera replugs without a page reload (RETRY restores the connected state and live preview). | [IMPLEMENTED] |
| FR-023 | The system shall keep the camera agent loopback-only and gate browser access with a strict origin allow-list. | [IMPLEMENTED] |

### 3.4 Analysis

| ID | Requirement | Status |
|---|---|---|
| FR-024 | The system shall validate input images before analysis and reject blank/black (lens-cap), effectively dark, saturated or non-microstructure images gracefully with an explanatory message. | [IMPLEMENTED] |
| FR-025 | The system shall preprocess accepted images: grayscale loading with scale normalization, annotation/figure-furniture detection and blanking (scale bars, labels, panels). | [IMPLEMENTED] |
| FR-026 | The system shall detect graphite particles by adaptive segmentation with contour filtering (area and dark-fraction against a matrix blob label map) and shall split touching particle pairs. | [IMPLEMENTED] |
| FR-027 | The system shall compute per-particle morphology (circularity, aspect ratio, solidity, roundness) and export a particle table with per-particle measurements. | [IMPLEMENTED] |
| FR-028 | The system shall compute ISO 945-4-oriented area-weighted nodularity and JIS G 5502-oriented count-weighted nodularity, and classify graphite forms (I–VI) with dominant-form reporting. | [IMPLEMENTED] |
| FR-029 | The system shall compute an engine self-check accuracy/confidence (consistency against the engine's own reference segmentation) and shall present it as a self-check, not as independent metallurgical accuracy. | [IMPLEMENTED] |
| FR-030 | The system shall support optional µm/pixel calibration (direct value, manual scale bar, or scale-bar auto-detect), converting particle sizes to physical units and applying the ISO 10 µm size rule when calibrated. | [IMPLEMENTED] |
| FR-031 | The system shall run analyses asynchronously (`POST /api/analyze` returns 202 with an analysis id; the client polls progress) and shall run the engine in a crash-isolated child process with automatic recovery so an engine fault cannot take down the API. | [IMPLEMENTED] |
| FR-032 | The system shall downscale large images to a 2000 px long side for analysis and inform the user (warning) that nodularity percentages are unaffected. | [IMPLEMENTED] |

### 3.5 Results, Persistence and Reporting

| ID | Requirement | Status |
|---|---|---|
| FR-033 | The system shall display results: nodule count, ISO/JIS nodularity views, self-check accuracy, graphite-form shares, estimated properties explicitly labeled as estimates, segmentation/annotation overlays and a roundness histogram. | [IMPLEMENTED] |
| FR-034 | The system shall persist each analysis record (full payload) scoped to its user, list records newest-first, and support detail view, nodule drill-down, deletion and login-session grouping. | [IMPLEMENTED] |
| FR-035 | The system shall generate downloadable PDF reports containing traceability, metrics, morphology, property estimates, self-check, review block and an optional AI interpretation. | [IMPLEMENTED] |
| FR-036 | The system shall support SPC analytics, anomaly screening, batch analysis, comparison, lot traceability with acceptance decisions, multi-field ISO sampling sessions and a review sign-off workflow. | [IMPLEMENTED] |

### 3.6 AI Copilot

| ID | Requirement | Status |
|---|---|---|
| FR-037 | The system shall provide a conversational Copilot grounded in stored analysis measurements (multi-turn with session history, capability registry and tool calls) using the provider chain Groq → Gemini → OpenAI-compatible → local → static fallback. | [IMPLEMENTED] |
| FR-038 | The system shall operate the Copilot fully offline when no provider keys are configured (fallback answers), and shall never fabricate measurement values. | [IMPLEMENTED] |
| FR-039 | The system shall expose camera exposure/gain/focus controls in the UI. | [PLANNED] |
| FR-040 | The system shall derive µm-per-pixel calibration automatically from microscope objective/magnification metadata. | [PLANNED] |
| FR-041 | The system shall provide WebSocket/MJPEG/WebRTC streaming beyond the 1 Hz polling preview. | [PLANNED] |

## 4. Non-Functional Requirements

### 4.1 Performance

| ID | Requirement | Status |
|---|---|---|
| NFR-001 | The system shall refresh the live preview approximately once per second (≈1 Hz sequential polls; the agent caches the open device for 15 s idle to avoid multi-second re-opens). | [IMPLEMENTED] |
| NFR-002 | The system shall complete a single-image analysis in seconds on the reference hardware (observed ≈2–4 s for 2592×1944 microscope captures after engine downscaling) and shall keep the UI responsive by running analyses asynchronously with progress polling. | [IMPLEMENTED] |
| NFR-003 | The system shall serve dataset and history listings from persisted records (precomputed dataset metrics) without recomputation. | [IMPLEMENTED] |

### 4.2 Security

| ID | Requirement | Status |
|---|---|---|
| SEC-001 | The system shall store passwords only as bcrypt hashes (cost 12) and shall never store or log plaintext passwords. | [IMPLEMENTED] |
| SEC-002 | The system shall transmit the session token only as an HttpOnly, SameSite=Lax cookie (never in JSON bodies or JavaScript-accessible storage), accepting an explicit Bearer header only for non-browser API clients/tests. | [IMPLEMENTED] |
| SEC-003 | The system shall reject revoked tokens (server-side revocation table) and single-use reset tokens shall never authenticate as login tokens. | [IMPLEMENTED] |
| SEC-004 | The system shall restrict the camera agent to loopback with a strict CORS allow-list (never a wildcard) and shall gate browser calls to it through the Flask CSP `connect-src` extension; no camera credentials shall exist in the browser and no NODIQ credentials shall be sent to the camera agent. | [IMPLEMENTED] |
| SEC-005 | The system shall validate uploads and API inputs, deduplicate uploads by content hash, and serve evidence images only to their owning user. | [IMPLEMENTED] |
| SEC-006 | The system shall rate-limit abusive patterns and log security-relevant events. | [IMPLEMENTED] |
| SEC-007 | The system shall keep secrets exclusively in the environment/`.env` (token-signing secret in `server_data/secret.key`), never in code. | [IMPLEMENTED] |

### 4.3 Reliability

| ID | Requirement | Status |
|---|---|---|
| NFR-004 | The system shall survive engine faults on pathological images by running the engine in a crash-isolated child process with automatic recovery (the API stays alive). | [IMPLEMENTED] |
| NFR-005 | The system shall recover from camera USB replugs and camera-agent restarts without agent or page restarts (self-recovery on the next request / via RETRY). | [IMPLEMENTED] |
| NFR-006 | The system shall preserve the pre-existing busy-camera behavior conservatively when the SDK cannot reliably confirm a device's disappearance (no false "disconnected" states). | [IMPLEMENTED] |

### 4.4 Availability

| ID | Requirement | Status |
|---|---|---|
| NFR-007 | The system shall remain fully usable for upload/dataset analysis when the camera, AI providers or SMTP are unavailable (graceful degradation, offline modes). | [IMPLEMENTED] |
| NFR-008 | The system shall refuse unsafe silent persistence fallbacks in production (a Render deployment with unset persistence variables must fail visibly rather than boot on ephemeral storage). | [IMPLEMENTED] |

### 4.5 Usability

| ID | Requirement | Status |
|---|---|---|
| NFR-009 | The system shall present every recoverable error with an understandable message and a RETRY action, and shall never expose stack traces in the user interface (developer detail stays in logs/console). | [IMPLEMENTED] |
| NFR-010 | The system shall display truthful state wording (capture-ready ≠ analysis-started; status chips WAITING → READY TO ANALYZE → ANALYZING → ANALYSIS COMPLETE). | [IMPLEMENTED] |
| NFR-011 | The system shall provide a large, responsive, unstretched live preview (4:3) suitable for focusing, field positioning and illumination checks. | [IMPLEMENTED] |

### 4.6 Maintainability

| ID | Requirement | Status |
|---|---|---|
| NFR-012 | The system shall keep a layered code organization (SPA / API gateway / domain services / engine / camera agent), typed camera error codes, per-page CSS modules, repository documentation and a regression test suite (298 tests) as the maintenance gate. | [IMPLEMENTED] |

### 4.7 Scalability

| ID | Requirement | Status |
|---|---|---|
| NFR-013 | The system shall support multi-worker deployment with stateless token authentication and a selectable PostgreSQL backend (Supabase) with object storage, so heavy data can grow independently of app processes. | [IMPLEMENTED] |

### 4.8 Compatibility

| ID | Requirement | Status |
|---|---|---|
| NFR-014 | The system shall run on Chromium-class desktop browsers and shall keep SQLite (development) and PostgreSQL/Supabase (production) behavior consistent through the compatibility layer. | [IMPLEMENTED] |

---

## 5. External Interface Requirements

### 5.1 User Interface

Verified screens (React SPA, 27 route entries): public — Landing, Login, Signup, Verify OTP,
Forgot/Reset Password, Auth Callback, Privacy, Terms, 404; authenticated — Home, Dashboard,
New Analysis (upload / dataset / microscope panel; viewer with masks, zoom; results cards;
START ANALYSIS), Batch Analysis, My Analyses, Sessions, Analytics (SPC), Compare, Anomalies,
Lots, Review Center, Copilot, Reports → Report Generator → Report Preview, Settings, Profile.

Interface conventions: dark theme with scoped per-page CSS; drag-and-drop and file-picker
upload; searchable dataset grid; status chips; truthful capture/analysis wording; RETRY on
recoverable errors; large responsive microscope preview.

### 5.2 Software Interfaces

| Software | Interface role |
|---|---|
| React 19.2.8 + React Router | SPA framework and client-side routing (27 routes) |
| Vite 8.2.0 | Dev server (:5173, proxies `/api` → 8001) and production build |
| Flask 3.1.3 + flask-cors | REST API gateway, SPA/dataset/evidence serving, CORS, CSP |
| OpenCV 5.0.0.93 + NumPy 2.4.6 | Engine image processing and numerics |
| fpdf2 / reportlab | PDF report generation |
| SQLite (stdlib sqlite3) / psycopg2-binary | Local / production persistence |
| Firebase JS SDK ^12.19.0 | Optional Google sign-in popup |
| mvIMPACT Acquire (`ImpactAcquire` Python binding) | Camera SDK used by the agent |
| Groq / Gemini / OpenAI-compatible / local | Optional Copilot providers |
| smtplib (SMTP) | OTP, password reset, SPC alert email |

### 5.3 Hardware Interfaces

| Hardware | Interface |
|---|---|
| Computer (reference) | Windows PC with USB 3.0; mvIMPACT Acquire runtime + Python binding installed |
| MATRIX VISION mvBlueFOX-ML/IGC205C (S/N 29605128) | USB camera; accessed exclusively through the camera agent (single-client ownership) |
| Metallurgical microscope | Physical optics/stage/illumination operated by the user; no software control (planned, see FR-039) |
| Specimen + lamp | Physical sample preparation and illumination; engine quality gates judge the resulting frame |

### 5.4 Camera/Microscope Interface

| ID | Requirement | Status |
|---|---|---|
| CAM-001 | The camera agent shall expose exactly three endpoints on 127.0.0.1:8765: `GET /status` (connected state, model, serial, resolution), `GET /preview` (≈1024×768 JPEG for ≈1 Hz polling) and `GET /capture` (full-resolution 2592×1944 PNG). | [IMPLEMENTED] |
| CAM-002 | The camera agent shall match the expected device by manufacturer "MATRIX VISION" and model substrings ("mvBlueFOX", "IGC205C") and shall fail cleanly when no camera is present. | [IMPLEMENTED] |
| CAM-003 | The camera agent shall keep the device open between requests and close it after 15 seconds idle (`NODIQ_CAMERA_IDLE_CLOSE_S`) so other applications can claim the camera. | [IMPLEMENTED] |
| CAM-004 | The camera agent shall bound single-frame acquisition at 10 s (`ACQUISITION_TIMEOUT_MS`). | [IMPLEMENTED] |
| CAM-005 | The camera agent shall map SDK failures to typed HTTP errors: 503 `camera_not_found`, 409 `camera_busy`, 504 `capture_failed`, 503 `sdk_unavailable`, 500 `internal_error` (message + machine-readable code). | [IMPLEMENTED] |
| CAM-006 | The camera agent shall refresh device enumeration only on failure paths (fresh `DeviceManager` scan) to distinguish a physically absent camera from a busy camera, falling back conservatively to the busy path when the scan cannot confirm absence. | [IMPLEMENTED] |
| CAM-007 | The camera agent shall validate frames (black <1 mean, dark <20, saturated >254 on the 8-bit-equivalent scale) before serving captures/preview data. | [IMPLEMENTED] |
| CAM-008 | The camera agent shall preserve capture pixel integrity (original 2592×1944 PNG, 4-byte RGBx stride handling; preview JPEG downscale to a 1024 px long side is for display only). | [IMPLEMENTED] |

### 5.5 API Interfaces

Transport: same-origin HTTP/JSON, port 8001 (dev via the Vite proxy). Session via HttpOnly
cookie; Bearer accepted for API clients/tests. Verified endpoint groups (58 REST API endpoint
paths; 3 non-API paths serve the SPA and dataset):

| Group | Representative paths |
|---|---|
| Auth (8) | `/api/auth/signup` · `/login` · `/logout` · `/me` · `/firebase` · `/forgot-password` · `/reset-password` · `/change-password` |
| Analysis (12) | `/api/analyze` · `/api/analyses` · `/api/analyses/stats` · `/api/analyses/<id>` (image, overlay, artifact/<kind>, context, lot, review, nodules, nodules/<n>) |
| Reports (6) | `/api/reports` · `/api/reports/<id>` · `…/download` · `…/evidence/<kind>` · `/api/reports/generate` · `/api/reports/ai-summary` |
| Copilot / AI (5) | `/api/copilot` · `/api/copilot/chat` · `/api/copilot/health` · `/api/copilot/capabilities` · `/api/ai/status` |
| Dataset (4) | `/api/dataset` · `/sample` · `/file/<name>` · `/analysis/<name>` |
| Multi-field sessions (4) | `/api/multifield` · `/<sid>` · `/<sid>/fields` · `/<sid>/statistics` |
| Login sessions (3) | `/api/sessions` · `/<sid>` · `/current` |
| Batch / SPC (4) | `/api/batch/stats` · `/api/batch/distributions` · `/api/batch/<id>/spc` · `/api/spc` |
| Anomalies (2) · Lots (2) | `/api/anomalies`(+`/<id>`) · `/api/lots`(+`/<lot_id>`) |
| Single routes (6) | `/api/compare` · `/api/decision-support` · `/api/calibration` · `/api/quality/<id>` · `/api/feedback` · `/api/health` |
| Validation lab (2) | `/api/validation` · `/api/validation/run` |

Camera-agent interface: `GET /status`, `GET /preview`, `GET /capture` on 127.0.0.1:8765 (§5.4).

## 6. System Features / Modules

### 6.1 Authentication Module — [IMPLEMENTED]

- **Purpose:** account lifecycle and session security.
- **Inputs:** signup/login/reset/OTP form data; Firebase Google credential (optional).
- **Processing:** bcrypt verification (cost 12; legacy PBKDF2 upgrade; dummy-hash timing
  equalization); HMAC token issue/verify/revocation; single-use reset tokens; OTP via SMTP.
- **Outputs:** HttpOnly session cookie; `users`/`revoked_tokens` rows; login-scoped session row.
- **Major functions:** `services/auth.py` (`create_user`, `authenticate`, `issue_token`,
  `verify_token`, `revoke_token`, `generate_reset_token`, `consume_reset_token`, `set_password`).

### 6.2 Image Input Module — [IMPLEMENTED]

- **Purpose:** acquire a micrograph from either source into the browser.
- **Inputs:** file picker/drag-drop (≤ 25 MB PNG/JPEG); dataset selection; microscope capture.
- **Processing:** type/size checks; dataset fetch; capture bytes → `File` with truthful
  capture-ready state; advisory quality hint (never a hard block).
- **Outputs:** staged input for the analysis funnel (`runOnFile` / `runOnDatasetImage`).
- **Major functions:** `Analysis.jsx` handlers; `services/api.js`.

### 6.3 Microscope Camera Module — [IMPLEMENTED]

- **Purpose:** operate the MATRIX VISION camera for status/preview/capture.
- **Inputs:** agent HTTP responses; user actions (open panel, RETRY, CAPTURE).
- **Processing:** status refresh; sequential ≈1 Hz preview polls (stop-before-start; unmount
  stop); duplicate-suppressed capture; typed error mapping (`unavailable`, `camera_busy`,
  `camera_not_found`, `capture_failed`, `sdk_unavailable`, `timeout`); large responsive 4:3
  preview rendering (CSS scaling only — pixels unchanged).
- **Outputs:** live preview frames; captured 2592×1944 PNG `File`; typed status/error states.
- **Major functions:** `nodiq-camera-agent/agent_server.py` (`_pick`, `_fresh_frame`,
  `_device_gone`, `_route_status`, `_route_capture`, idle close), `camera.py` (SDK layer);
  `nodiq-x/src/services/microscopeAgent.js`.

### 6.4 Image Validation Module — [IMPLEMENTED]

- **Purpose:** admit only usable micrographs.
- **Inputs:** decoded image.
- **Processing:** blank/black/dark/saturation checks; microstructure-validity heuristics;
  annotation/figure-furniture detection (scale bars, labels, panels) with blanking; quality
  score/verdict.
- **Outputs:** pass/fail verdict with a clear message; blanked image for the engine.
- **Major functions:** `nodularity_pipeline.evaluate_microstructure_validity`,
  `find_annotation_overlays`, `blank_figure_annotations`; `services/quality.py`.

### 6.5 Microstructure Analysis Engine — [IMPLEMENTED]

- **Purpose:** the single authoritative CV pipeline for both input sources.
- **Inputs:** validated image (upload, dataset, or microscope capture — identical path).
- **Processing:** grayscale load + normalization → adaptive segmentation → contour filtering →
  touching-pair splitting → per-particle morphology → ISO/JIS aggregation → self-check →
  masks/overlay rendering; executed in a crash-isolated child.
- **Outputs:** nodule count, ISO 945-4-oriented %, JIS G 5502-oriented %, form shares, particle
  table, base64 masks, overlay, quality verdict, warnings (e.g., downscale note).
- **Major functions:** `nodularity_pipeline.analyze_image`, `analyze_for_frontend`,
  `apply_size_filter_and_iso`, `accuracy_vs_reference`, `reference_particles`;
  `analysis_child.py`, `analyze_with_recovery.py`.

### 6.6 Nodularity & Morphology Module — [IMPLEMENTED]

- **Purpose:** standards-oriented metric computation.
- **Processing:** ISO 945-4-oriented area-weighted share; JIS G 5502-oriented count-weighted
  share; graphite-form classification (I–VI); optional ISO 10 µm size rule (calibrated).
- **Outputs:** ISO %, JIS %, form shares, per-particle classes, estimated properties (labeled).
- **Major functions:** `apply_size_filter_and_iso`; `services/morphology.py`;
  `services/properties.py`.

### 6.7 Result Visualization Module — [IMPLEMENTED]

- **Purpose:** present results understandably.
- **Processing:** zoomable viewer with mask toggles; result cards; histogram; form bars; status
  chips; Copilot context binding.
- **Major functions:** `Analysis.jsx` (`applyResult`), viewer components, `ReportPreview.jsx`.

### 6.8 History / Persistence Module — [IMPLEMENTED]

- **Purpose:** durable per-user records.
- **Processing:** SQLite/PostgreSQL writes with user scoping; hash-deduplicated uploads;
  session tagging; delete operations.
- **Major functions:** `services/db.py`, `services/storage.py`.

### 6.9 Reporting Module — [IMPLEMENTED]

- **Purpose:** customer-ready traceable PDF documents.
- **Processing:** report assembly (traceability, metrics, ISO/JIS, morphology, property
  estimates labeled ESTIMATE, self-check, batch/SPC context, observations, AI interpretation,
  review block); preview and download.
- **Major functions:** `report_builder.py`; `/api/reports/*` endpoints.

### 6.10 AI Copilot Module — [IMPLEMENTED]

- **Purpose:** explain stored measurements in plain language; never fabricate numbers.
- **Processing:** provider chain (Groq → Gemini → OpenAI-compatible → local → static fallback)
  with key rotation; multi-turn session memory; tool calls over stored analyses; capability
  registry; full offline fallback.
- **Outputs:** reply, provider label, tool trace, UI actions.
- **Major functions:** `ai/agent.py`, `ai/tools.py`, `ai/memory.py`, `ai/reference.py`;
  `POST /api/copilot`, `/api/copilot/chat`.

---

## 7. Database Requirements

Two explicit backends behind one persistence API (`services/db.py`), selected by
`NODIQ_BACKEND=sqlite | supabase` (auto: Supabase when `DATABASE_URL` is present, otherwise
SQLite; unsafe silent fallbacks refused on Render):

- **SQLite (development):** single WAL-mode file `server_data/nodiq.db`; JSON `data` column per
  row (payloads evolve without migrations); typed columns only for filter/sort keys; one-time
  import of legacy JSON files (renamed `*.imported`).
- **PostgreSQL via Supabase (production):** same logical schema via the `services/pgcompat.py`
  compatibility layer; image artifacts in Supabase Storage at
  `users/{user_id}/analyses/{analysis_id}/{kind}.{ext}` (original / annotated / masks).

The seven verified tables:

### 7.1 users

| Field | Type | Constraint | Description |
|---|---|---|---|
| id | TEXT | PRIMARY KEY | User ID (`USR-…`) |
| email | TEXT | UNIQUE NOT NULL | Login email |
| name | TEXT | — | Display name |
| phone | TEXT | — | Phone (optional) |
| password_hash | TEXT | NOT NULL | bcrypt hash ($2b$, cost 12) |
| created_at | TEXT | NOT NULL | ISO timestamp |

### 7.2 revoked_tokens

| Field | Type | Constraint | Description |
|---|---|---|---|
| token_hash | TEXT | PRIMARY KEY | Hash of a revoked token |
| expires_at | REAL | NOT NULL | Natural expiry (rows rejected until then) |

### 7.3 sessions

| Field | Type | Constraint | Description |
|---|---|---|---|
| id | TEXT | PRIMARY KEY | Session ID (`SES-…`); one per login |
| user_id | TEXT | NOT NULL (indexed with started_at) | Owning user |
| label | TEXT | — | Optional label |
| started_at | TEXT | NOT NULL | Login time |
| ended_at | TEXT | — | Logout time (NULL = active) |

### 7.4 analyses

| Field | Type | Constraint | Description |
|---|---|---|---|
| id | TEXT | PRIMARY KEY | Analysis ID (`ANL-…`) |
| user_id | TEXT | indexed with created_at | Owning user; NULL = shared/legacy |
| created_at | TEXT | — | ISO timestamp |
| data | TEXT | NOT NULL | Full analysis payload JSON (metrics, nodules, masks, quality, calibration, session_id, warnings, …) |

### 7.5 reports

| Field | Type | Constraint | Description |
|---|---|---|---|
| id | TEXT | PRIMARY KEY | Report ID |
| user_id | TEXT | indexed with created_at | Owning user |
| created_at | TEXT | — | ISO timestamp |
| data | TEXT | NOT NULL | Full report JSON (document + downloads) |

### 7.6 feedback

| Field | Type | Constraint | Description |
|---|---|---|---|
| id | TEXT | PRIMARY KEY | Feedback ID |
| created_at | TEXT | — | ISO timestamp |
| data | TEXT | NOT NULL | Feedback payload JSON |

### 7.7 calibrations

| Field | Type | Constraint | Description |
|---|---|---|---|
| key | TEXT | PRIMARY KEY | Calibration key |
| data | TEXT | NOT NULL | Calibration JSON (µm/px, method, provenance) |

Complementary storage: `server_data/uploads/` (content-hash-deduplicated originals;
development), Supabase Storage objects (production), `dataset/` (1,000 bundled micrographs,
read-only).

## 8. Use Case Requirements

### 8.1 Actors

- **Visitor** — unauthenticated browser user.
- **User / Operator (Analyst)** — authenticated account (primary actor).
- **Reviewer / Quality Engineer** — authenticated account using review/lot features.
- **Camera Agent** — system actor representing the local camera service.
- **AI Provider** — optional external LLM used by the Copilot.

### 8.2 Use Cases

| ID | Use case | Actor(s) | Preconditions | Main flow | Alternative flow | Postconditions |
|---|---|---|---|---|---|---|
| UC-01 | Login | User | Account exists | Enter credentials → `POST /api/auth/login` → bcrypt verify → HttpOnly cookie → redirect to intended page | Google popup (Firebase) → `/auth/callback` exchange | Session active; login-scoped session row created |
| UC-02 | Upload image | User | Signed in | SELECT IMAGE / drag-drop → type/size checks → image staged | Invalid file → clear message, no crash | Input staged in the workspace |
| UC-03 | Browse dataset | User | Signed in | BROWSE DATASET → searchable grid (reference metrics in tooltips) → pick image | — | Dataset image staged |
| UC-04 | Open microscope panel | User | Agent running (else offline state) | Click MICROSCOPE → `GET /status` → panel shows `● Connected` + model/serial/resolution; preview starts | Agent offline → hint + RETRY; camera absent → disconnected + RETRY | Panel active; preview polling |
| UC-05 | View live preview | User | UC-04 connected | ≈1 Hz sequential `/preview` polls render in the large 4:3 view; user focuses/positions/checks illumination; changes appear within ≈1 s | Preview error → "UNAVAILABLE — will retry"; panel close stops polling | Operator confident in field setup |
| UC-06 | Capture microscope image | User | UC-05; camera free | CAPTURE IMAGE → control disables ("CAPTURING…") → 2592×1944 PNG staged → panel closes → "Capture ready — click START ANALYSIS to analyze." | 409 busy → friendly message + RETRY; disconnect → RETRY | Capture `File` staged |
| UC-07 | Analyze image | User | An input is staged | START ANALYSIS → `POST /api/analyze` → 202 + polling → progress → results | Invalid/dark image → graceful rejection; backend/engine failure → clean error (child-process recovery) | Analysis record persisted; results shown |
| UC-08 | View results | User | UC-07 completed | Result cards (count, ISO/JIS, self-check, forms, estimates), mask overlays with zoom, histogram | — | User can report or ask Copilot |
| UC-09 | View history | User | Past analyses exist | My Analyses list (newest first) → detail / nodules / delete / session grouping | — | History reflects persisted records |
| UC-10 | Use Copilot | User | Optional analysis context | Ask question → grounded reply with provider label + tool trace | No provider keys → offline fallback | Conversation retained in session memory |
| UC-11 | Generate report | User | Completed analysis | Reports → generate → preview → download PDF | — | Report row persisted |
| UC-12 | Review analysis | Reviewer | Analysis exists | Review Center → approve/reject/annotate with audit trail | — | Review status reflected in reports |
| UC-13 | Batch / SPC / Lots | User, Reviewer | Analyses exist | Batch runs; SPC charts + out-of-control alerts; lot acceptance decisions | — | Traceability records updated |

---

## 9. System Constraints

| # | Constraint |
|---|---|
| SC-01 | Supported inputs: PNG/JPEG uploads ≤ 25 MB; bundled dataset (1,000 images); microscope captures. |
| SC-02 | Engine analyzes at ≤ 2000 px long side (2592×1944 → 2000×1500, visible warning; percentages unaffected); original bytes preserved. |
| SC-03 | Microscope capture requires the camera connected, the agent running, and the camera free (single-client; ImpactControlCenter/wxPropView must be closed). |
| SC-04 | Camera agent is loopback-only (127.0.0.1:8765), origin allow-listed, CSP-gated; not reachable from other networks. |
| SC-05 | Agent holds the device between requests and releases it after 15 s idle; capture bounded by a 10 s SDK timeout. |
| SC-06 | Quality gates reject black (<1 mean), dark (<20), saturated (>254), non-microstructure and strongly-colored-photograph frames (colorfulness > 45 vs ≤ 20.6 on all 1,000 dataset micrographs); annotation furniture is blanked automatically. |
| SC-07 | Sessions are HttpOnly-cookie based; protected routes redirect to login; the browser never stores the token. |
| SC-08 | Exactly one analysis pipeline: microscope capture reuses the upload funnel verbatim; the engine is never duplicated or bypassed. |
| SC-09 | Preview is a positioning aid (≈1024×768 JPEG, ≈1 Hz); it never substitutes for full-resolution capture; preview display size does not change the physical field of view. |
| SC-10 | Camera integration validated on Windows (SDK binding); analysis and UI are cross-platform. |

---

## 10. Error Handling Requirements

| Error condition | System response |
|---|---|
| Invalid/unsupported image | Clear message; no crash; no fake result; user can retry |
| Dark / lens-cap / blank frame | Advisory hint ("Image appears too dark. Check microscope illumination."); backend gate rejects gracefully with an explanatory message |
| Saturated / non-microstructure image | Engine validity gate rejects with a clear reason |
| Oversized upload (> 25 MB) | Frontend guard message before upload |
| Upload/network failure | Error banner; retry the upload action |
| Backend analysis failure / poll timeout | "Analysis failed — <server reason>" or timeout guidance pointing to history; progress resets |
| Engine crash on a pathological image | Child-process recovery; clean API error; page alive |
| Camera agent offline | `○ Camera agent offline` + "Cannot reach the camera agent at http://127.0.0.1:8765. Start it with: python agent_server.py" + RETRY; CAPTURE disabled; no preview loop |
| Camera disconnected | Typed `503 camera_not_found` → `○ Camera disconnected` + RETRY; `/status` reports `connected:false` when fresh enumeration agrees |
| Camera busy | Typed `409 camera_busy` → "being used by another application" + RETRY; self-recovery on release |
| Capture failure / SDK timeout | Typed `504 capture_failed` → recoverable panel state |
| Live preview failure | `PREVIEW: UNAVAILABLE — will retry` in-panel; loop retries; page stable |
| Authentication failure | Login error message; unknown emails burn dummy-hash time; protected routes redirect to login |
| Revoked/expired session | Cookie invalidated; re-authentication requested |
| AI provider unavailable | Provider chain falls back (next → local → static); Copilot remains usable |
| SMTP not configured | Email features degrade to server-log delivery |

---

## 11. Acceptance Criteria

| # | Criterion | Status at documentation time |
|---|---|---|
| AC-01 | Image upload works and stages the file | PASS (verified E2E) |
| AC-02 | A valid image reaches the engine and returns results | PASS |
| AC-03 | Invalid/dark images are rejected gracefully (no crash, clear message) | PASS |
| AC-04 | Microscope connects and shows model/serial/resolution | PASS |
| AC-05 | Live preview works at ≈1 Hz in a large responsive 4:3 view without stretching or page scroll | PASS (measured 825×618 @1600 px; ratio 1.334) |
| AC-06 | Microscope capture delivers a full-resolution PNG (2592×1944) | PASS |
| AC-07 | Captured images enter the existing pipeline (`POST /api/analyze`) — no second endpoint/engine | PASS |
| AC-08 | Real microscope specimen analyzed end-to-end | PASS (Phase 4/5 sessions) |
| AC-09 | Exact capture bytes re-uploaded produce identical metrics (byte-identical parity) | PASS (Phase 4: count 10 / ISO 14.91 / JIS 53.0; Phase 5: count 19 / ISO 28.2 / JIS 50.0 — identical both times) |
| AC-10 | Camera disconnect/reconnect works (typed states; replug recovers without agent restart) | PASS (residual: some live-drop sequences surface the busy state — documented) |
| AC-11 | Busy-camera recovery works (409 + friendly message + RETRY + self-recovery) | PASS |
| AC-12 | Agent-offline recovery works (hint + RETRY after restart, no page reload) | PASS |
| AC-13 | Full test suite passes | PASS — 298/298 pytest (includes 56 pinning + 5 camera-state tests) |
| AC-14 | Lint passes | PASS — `npx oxlint src` 0 errors |
| AC-15 | Build passes | PASS — `npm run build` |

**Accuracy disclaimer.** Self-check accuracy/confidence values measure the engine's consistency
against its own reference segmentation. **Independent metallurgical ground truth has not been
established**; no certified metallurgical accuracy is claimed anywhere in the system or its
reports.

---

## 12. Future Enhancements

| ID | Enhancement | Status |
|---|---|---|
| FE-01 | Camera exposure/gain/focus controls (FR-039) | PLANNED |
| FE-02 | Automatic µm calibration from objective/magnification metadata (FR-040) | PLANNED |
| FE-03 | Advanced camera streaming (WebSocket/MJPEG/WebRTC) (FR-041) | PLANNED |
| FE-04 | Microscope stage automation / automated objective selection | PLANNED (hardware not present) |
| FE-05 | Expanded metallurgical validation against certified ground-truth specimens and inter-laboratory comparison | PLANNED |
| FE-06 | Additional report templates / batch report bundles | PLANNED |
| FE-07 | Advanced image-quality controls (illumination guidance, focus scoring) | PLANNED |
| FE-08 | Process provenance capture (objective, illuminance) attached automatically to analyses | PLANNED |

---

## 13. Approval

| Role | Name | Signature | Date |
|---|---|---|---|
| Prepared By | ____________________________ | ____________________________ | ____ / ____ / ______ |
| Reviewed By | ____________________________ | ____________________________ | ____ / ____ / ______ |
| Approved By | ____________________________ | ____________________________ | ____ / ____ / ______ |

---

*End of Document — NODIQ-X SRS, Version 1.6.0 (01/10/2026). All implemented claims verified
against the repository; the analysis engine and the camera funnel are unmodified as described.*
