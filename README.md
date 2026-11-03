# NODIQ-X — AI-Powered Microstructure Intelligence

Web platform that analyzes ductile-iron micrographs and measures graphite **nodularity**
using the ISO 945-4 and JIS G5502 formulas, with annotated overlays, an analysis
dashboard, lot traceability, and downloadable PDF/CSV/JSON reports.

> **Honesty first:** the image-analysis engine is **classical OpenCV computer vision**
> (deterministic, rule-based). There is **no ML image inference** — no CNN/YOLO, no
> trained regression. The AI component is the **text Copilot** (an LLM that explains your
> results). See "Important limitations" below.

## Hackathon Provenance & Attribution Notice

> [!IMPORTANT]
> **Pre-Hackathon Permitted Baseline:** This repository contains the permitted pre-hackathon baseline of the **NODIQ-X** platform (classical metallurgical inspection, graphite nodularity, and quality analysis), transferred with explicit organizer permission into the official hackathon repository.
>
> All genuine new hackathon contributions are developed during the 24-hour event (November 3–4, 2026) across four distinct, dedicated member workstreams:
> - **Member 1 (PixelCrafter-ath):** Dashboard & Comparison, Material Metrics, Batch Analysis, Final Integration.
> - **Member 2 (Aditya1823):** Certified PDF Export, CSV/ZIP Data Export, Bulk Review, Anomaly Detail Modals.
> - **Member 3 (Sharvil):** Profile Persistence, Role-Based Access Control (RBAC), Lot Management, Authorization Testing.
> - **Member 4 (Hameed):** Calibration Ruler Tools, Spatial Calibration Integration, Copilot Metallurgical Tools, Voice & Audio Settings.

## 1. What the project does

- Upload a micrograph (or capture one from the microscope camera) → get ISO/JIS
  nodularity %, per-particle measurements, graphite forms, image-quality score, and an
  annotated overlay.
- Invalid inputs (photos that are not micrographs) are rejected by a validity gate.
- Every result is stored, traceable, reviewable, comparable, and exportable to a real PDF.

## 2. Technology stack  

- **Frontend:** React 19 + Vite 8 + react-router 7 (`apps/web/`), Firebase (auth only), oxlint.
- **Backend:** Python 3.11, Flask 3.1 (`src/nodiq/api/server.py`), SQLite (default) / Postgres-Supabase (optional).
- **Image engine:** OpenCV 5 (`opencv-python`), NumPy 2 — classical CV & deep learning models.
- **Reports:** fpdf2 (PDF), CSV/JSON builders (`src/nodiq/reports/`).
- **AI Copilot:** `src/nodiq/ai/` provider chain (Groq default, Gemini/OpenAI-compatible/local/offline-fallback).

## 3. Quick start

```bash
# Setup environment
pip install -r requirements.txt
pip install -e .

# Development & Testing
make dev               # starts Vite (:5173) + Flask API (:8001) + camera agent (:8765)
make run               # backend alone: python -m nodiq.api.server
make test              # run full pytest test suite
make lint              # run ruff linter check

# Containerized Deployment
make docker-build      # build production Docker container image
make docker-up         # launch container stack with persistent volume
```

## 4. Project structure

```
src/nodiq/             ← package root (api, pipelines, reports, adapters, ai, services, core)
apps/
  web/                 ← React 19 + Vite SPA
  camera-agent/        ← standalone microscope hardware capture daemon
deploy/                ← Dockerfile, docker-compose.yml, render.yaml
third_party/           ← cloned upstream repos with clean names (Nodularity, carde, GSAT, etc.)
config/                ← model capabilities and static configs
data/                  ← raw/ (gitignored), samples/ (tracked), processed/
models/                ← ML model weights & Cellpose checkpoints (gitignored)
outputs/               ← test outputs & artifacts (gitignored)
tests/                 ← unit, integration, and security test suites
scripts/               ← utility, benchmark, and migration scripts (tools/ under scripts/tools/)
docs/                  ← documentation, architecture guide, and reports
```

## 5. Main analysis flow

`Analysis.jsx startAnalysis()` → `api.js analyzeUpload()` → `POST /api/analyze` →
`nodiq.api.server analyze_upload()` (validate, store, 202) → worker (`_run_analysis_job_guarded`
thread or `_spawn_analysis_child` process) → `nodiq.pipelines.analysis_child.run()` →
`nodiq.pipelines.nodularity_pipeline.analyze_image()` → validity gate → quality/calibration/size filter →
results saved to SQLite + JSON + PNG → frontend polls `GET /api/analyses/<id>` →
`applyResult()` renders the result.

## 6. Microscope flow

Camera (mvIMPACT, `camera.py`) → local agent (`apps/camera-agent/agent_server.py`, /status /preview /capture)
→ `microscopeAgent.js` → `Analysis.jsx` → **the same `/api/analyze` and the same
nodularity pipeline**. The microscope is only an additional input source — no second
analysis algorithm exists.

## 7. Report flow

`ReportGenerator.jsx handleGenerate()` → `POST /api/reports/generate` →
`reports_generate_v2()` → `report_builder.build_report_data()` (**real measured values**)
→ download via `GET /api/reports/<id>/download?format=pdf|csv|json` (`to_pdf`/`to_csv`/`to_json`).

## 8. AI Copilot

`Copilot.jsx` → `POST /api/copilot` → `ai/agent.handle_turn()` with ~18 tools that read
your real analyses; LLM providers (Groq by default) with an offline rule-based fallback.
**Text only** — it never processes pixels and never detects graphite.

## 9. Database / storage

SQLite `server_data/nodiq.db` (rows) + `server_data/analyses_full/<id>.json` (payloads)
+ PNG artifacts; optional Supabase Storage. Firebase is used **only for authentication**.
Browser localStorage holds only UI cache (current user / last result).

## 10. Testing

37 pytest files under `tests/` (verified full run: **462 passed, 18 skipped, 0 failed**), covering the
engine, gray/white cast iron pipelines, ASTM grain size evaluation, API contracts, auth/security,
ownership isolation, rate limits, storage backends, and the validity gate. CI: `.github/workflows/ci.yml`.

## 11. Important limitations

- No deep-learning or regression model — nodularity is **measured** geometrically
  (ISO 945-4 / JIS G5502 methodology; not a certification).
- The in-app self-check is agreement with an independent OpenCV reference segmentation,
  **not** ground-truth accuracy; no expert-labeled benchmark has been run yet.
- Touching-particle splitting is implemented but gated off (validated-count path).
- Microscope capture is code-complete but not validated on physical hardware.
- `npm audit`: 4 pre-existing high advisories in the Firebase JS SDK (documented).

## Judge documents

- [docs/JUDGE_CODE_MAP.md](docs/JUDGE_CODE_MAP.md) — every button → endpoint → function
- [docs/JUDGE_FILE_GUIDE.md](docs/JUDGE_FILE_GUIDE.md) — file-by-file guide
- [docs/JUDGE_ARCHITECTURE.md](docs/JUDGE_ARCHITECTURE.md) — simple architecture flows
- [docs/JUDGE_VIVA_CHEAT_SHEET.md](docs/JUDGE_VIVA_CHEAT_SHEET.md) — Q&A + honesty rules
