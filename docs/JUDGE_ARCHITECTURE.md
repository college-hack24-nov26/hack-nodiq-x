# NODIQ-X — Simple Architecture (Judge Version)

Everything below reflects the **actual running code** (verified against the repository).

## Main analysis flow

```
USER
 ↓
REACT FRONTEND            apps/web/src/pages/Analysis.jsx  (route /new-analysis, App.jsx)
 ↓
API SERVICE               apps/web/src/services/api.js  → analyzeUpload(file)
 ↓                        (cookie-authenticated fetch; vite proxies /api → 127.0.0.1:8001)
FLASK BACKEND             src/nodiq/api/server.py  → analyze_upload()   [POST /api/analyze, returns 202]
 ↓                        rate limit → magic-byte + dimension checks → store file →
                          insert "processing" row → spawn worker
ANALYSIS WORKER           NODIQ_EXEC_MODE=thread → _run_analysis_job_guarded() (watchdog)
 ↓                        or =child → _spawn_analysis_child() → analysis_child.py run()
OPENCV NODULARITY ENGINE  src/nodiq/pipelines/nodularity_pipeline.py → analyze_image()
 ↓                        grayscale → blank scale bars → median+Otsu segmentation →
                          frozen detector + recovery/merge/consolidation → consistency gate →
                          per-particle area + convex-hull Feret measurement
RESULT PROCESSING         roundness = area/(π·r²) → ISO nodularity (Σround area/Σarea×100, ≥0.6)
 ↓                        JIS nodularity = (0.3N₂+0.7N₃+0.9N₄+N₅)/N×100
                          validity gate → quality score → calibration → size filter →
                          graphite forms → property estimates (analysis_child.py run())
DATABASE / JSON / ARTIFACTS
 ↓                        services/db.py insert_analysis() → server_data/nodiq.db (SQLite)
                          services/context.py save_full_analysis() → analyses_full/<id>.json
                          <id>_annotated.png / <id>_mask.png (+ optional Supabase Storage)
FRONTEND RESULT           Analysis.jsx polls GET /api/analyses/<id> → applyResult()
 ↓                        shows %, nodule table, annotated overlay, chart
REPORT GENERATION         ReportGenerator.jsx → POST /api/reports/generate
                          → reports_generate_v2() → report_builder.build_report_data()
                          → GET /api/reports/<id>/download → report_builder.to_pdf() (fpdf2)
```

## Microscope flow

```
MICROSCOPE
 ↓
MATRIX VISION CAMERA
 ↓
mvIMPACT (apps/camera-agent/camera.py)
 ↓
LOCAL CAMERA AGENT        apps/camera-agent/agent_server.py (separate localhost process;
 ↓                        AgentHandler.do_GET → /status, /preview, /capture)
microscopeAgent.js        apps/web/src/services/microscopeAgent.js
 ↓
Analysis.jsx              captureFromMicroscope() / startPreviewLoop() → runOnFile()
 ↓
same existing /api/analyze
 ↓
same nodularity pipeline  (src/nodiq/api/server.py analyze_upload() → analysis_child.py →
                           src/nodiq/pipelines/nodularity_pipeline.py analyze_image())
```

**Important:** microscope capture is only an **additional image input source**.
The captured frame becomes the same uploaded file and goes through the **same
`/api/analyze` endpoint and the same nodularity pipeline** — there is **NO second
analysis algorithm** for the microscope.

## Storage facts

- SQLite `server_data/nodiq.db` (default; Postgres/Supabase optional via env).
- Full payloads: `server_data/analyses_full/<id>.json` + PNG artifacts.
- Firebase is used **only for authentication** (Google / phone OTP), never for data.
- `localStorage` holds only UI cache (current user, last result) — not the record system.

## Honesty note

The engine is **classical OpenCV computer vision** (no CNN/YOLO/regression).
The AI component is the **text Copilot** (LLM, `ai/`), separate from image analysis.
