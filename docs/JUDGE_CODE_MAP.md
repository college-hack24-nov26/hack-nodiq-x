# NODIQ-X — Judge Code Map

Answers: **"If I click this button, where does the request go?"**
All names are the actual functions in this repository (no invented names).

| # | Feature / Button | Frontend file → function | Service (JS) | HTTP | Endpoint | Backend function (server.py) | Processing module | Storage | Result to frontend |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Login | LoginPage.jsx → LoginForm.jsx `handleSubmit` | authService `loginWithEmail` | POST | `/api/auth/login` | `auth_login()` | services/auth.py `authenticate()` (bcrypt) | users table (SQLite) | user JSON + HttpOnly `nodiq_session` cookie |
| 2 | Signup | SignupPage.jsx → SignupForm.jsx `handleSubmit` | authService `registerUser` | POST | `/api/auth/signup` | `auth_signup()` | services/auth.py `create_user()` | users table | user + cookie |
| 3 | Google Login | LoginPage.jsx `handleGoogleLogin` | authService `signInWithGoogle` → `verifyFirebaseIdToken` | POST | `/api/auth/firebase` | `auth_firebase()` | Google identitytoolkit `accounts:lookup` → find/create user | users table | user + cookie |
| 4 | Phone OTP | LoginPage → PhoneLogin.jsx `signInWithPhoneNumber` → VerifyOtpPage.jsx `confirmationResult.confirm(otp)` | authService `verifyFirebaseIdToken` | POST | `/api/auth/firebase` | `auth_firebase()` | same Google verification path | users table | user + cookie |
| 5 | New Analysis page | Sidebar.jsx link → App.jsx route `/new-analysis` | — | — | — | — (RequireAuth guard) | — | — | Analysis.jsx renders |
| 6 | Upload Image | Analysis.jsx `openImagePicker` → `handleUpload` → `runOnFile` | (pending state) | — | — | — | — | — | preview + pending file |
| 7 | Drag & Drop | Analysis.jsx `handleDragOver` / `handleDrop` | (pending state) | — | — | — | — | — | same as #6 |
| 8 | Start Analysis | Analysis.jsx `startAnalysis` | api `analyzeUpload` / `analyzeDatasetImage` | POST | `/api/analyze` | `analyze_upload()` → `_run_analysis_job_guarded()` (thread) or `_spawn_analysis_child()` | analysis_child.py `run()` → nodularity_pipeline.py `analyze_image()` (+ `evaluate_microstructure_validity`, `analyze_for_frontend_json`) | db.insert_analysis + context.save_full_analysis + PNG artifacts | 202 `{status, analysis_id, poll_url}` → poll #11 |
| 9 | Microscope Capture | Analysis.jsx `captureFromMicroscope` | microscopeAgent.js `captureImage` | GET | agent `/capture` | nodiq-camera-agent/agent_server.py `AgentHandler.do_GET` | camera.py (mvIMPACT SDK) | JPEG file → becomes upload | file → same flow as #8 |
| 10 | Live Microscope Preview | Analysis.jsx `toggleCameraPanel` → `startPreviewLoop` | microscopeAgent.js `capturePreview` / `startLivePreview` | GET | agent `/preview` | `AgentHandler.do_GET` | camera.py | none (live frames) | `<img>` refresh loop |
| 11 | Analysis Result | Analysis.jsx poll loop → `applyResult` | api `analysisDetail` | GET | `/api/analyses/<id>` | `analysis_detail()` | services/context.py `load_full_analysis()` | SQLite row + JSON payload + `/artifact/<kind>` images | `{status, progress, record, payload}` |
| 12 | Analysis History | MyAnalyses.jsx | api `analyses` / `deleteAnalysis` | GET / DELETE | `/api/analyses`, `/api/analyses/<id>` | `analyses_list()` / `analyses_delete()` | services/db.py | SQLite | analysis list / deleted |
| 13 | Dashboard | Dashboard.jsx | api `analysisStats`, `analyses` | GET | `/api/analyses/stats` | `analyses_stats()` | services/db.py aggregates | SQLite | stats cards + recent list |
| 14 | Analytics | Analytics.jsx | api `batchStats`, `spc` | GET | `/api/batch/stats`, `/api/spc` | `batch_stats_endpoint()`, `spc_endpoint_metric()` | services/analytics.py `batch_statistics()` | SQLite over all analyses | distributions + SPC series |
| 15 | Compare | Compare.jsx | api `compare` | POST | `/api/compare` | `compare_endpoint()` | services/comparison.py | reads two payloads | side-by-side diff |
| 16 | Lots | Lots.jsx `lotsFetch` (raw cookie fetch) | (direct fetch) | GET | `/api/lots`, `/api/lots/<id>` | `lots_list()`, `lot_detail()` (tagging: `analysis_set_lot()` via `POST /api/analyses/<id>/lot`) | services/lots.py | SQLite lots tables | lot list + drill-down |
| 17 | Anomalies | Anomalies.jsx | api `anomalies`, `anomalyFor` | GET | `/api/anomalies`, `/api/anomalies/<id>` | `anomalies_endpoint()`, `anomaly_for()` | services/anomalies.py `assess_analysis()` | SQLite + payloads | anomaly list / detail |
| 18 | Review Center | ReviewCenter.jsx | api `setReview` | POST | `/api/analyses/<id>/review` | `analysis_review()` | services/review.py | review fields in SQLite | updated review state |
| 19 | Generate Report | ReportGenerator.jsx `handleGenerate` | api `generateReport` | POST | `/api/reports/generate` | `reports_generate_v2()` → `_generate_for()` | report_builder.py `build_report_data()` (+ optional AI interpretation via ai_chat) | db.insert_report (+ stored full report) | 201 report JSON |
| 20 | Download PDF | ReportPreview.jsx `handleDownloadPdf` | api `downloadReport(id,"pdf")` | GET | `/api/reports/<id>/download?format=pdf` | `reports_download()` | report_builder.py `to_pdf()` (fpdf2) | PDF bytes | PDF attachment |
| 21 | Download CSV | ReportPreview.jsx (same UI) | api `downloadReport(id,"csv")` | GET | `?format=csv` | `reports_download()` | report_builder.py `to_csv()` | CSV bytes | CSV attachment |
| 22 | Download JSON | ReportPreview.jsx (same UI) | api `downloadReport(id,"json")` | GET | `?format=json` | `reports_download()` | report_builder.py `to_json()` | JSON bytes | JSON attachment |
| 23 | AI Copilot | Copilot.jsx `sendMessage` | api `copilot` | POST | `/api/copilot` | `copilot()` → `_tool_context()` | ai/agent.py `handle_turn()` → ai/tools.py `execute_action()` → providers (groq/gemini/openai-compatible/local/fallback) | chat memory: server_data/copilot_sessions/ | reply + optional UI actions |
| 24 | Settings | Settings.jsx | api `health`, `aiStatus`, `validationSummary`, `runValidation` | GET / POST | `/api/health`, `/api/ai/status`, `/api/validation`, `/api/validation/run` | `health()`, `ai_status()`, `validation_endpoint()`, `validation_run()` | services/validation_lab.py, ai/config.py | system status | health/AI/validation panels (password change lives in Profile.jsx → `api.changePassword` → `POST /api/auth/change-password` → `auth_change_password()`) |
| 25 | Logout | Sidebar.jsx `logout` | AuthContext `logout()` → authService `logoutUser` | POST | `/api/auth/logout` | `auth_logout()` | services/auth.py `revoke_token()` | revoked tokens | cleared cookie + local state |

---

## ML / Regression / AI

**There is NO trained ML/regression model in this repository.** Image analysis is
classical OpenCV; the only AI is the text Copilot (LLM). Proof points are listed per row.

| Judge question | Actual technology | File | Function | Input | Output | Is it trained ML? | Explanation for judge |
|---|---|---|---|---|---|---|---|
| Where is image analysis done? | Classical CV | nodularity_pipeline.py | `analyze_image()` | decoded micrograph | contours + metrics + nodularity | **No** | Hand-designed OpenCV pipeline (median+Otsu, contour geometry). |
| Segmentation? | Median blur + Otsu threshold + morphology | nodularity_pipeline.py | `physical_blob_map()`, consistency gate in `analyze_image()` | grayscale image | dark-particle blob map | **No** | Rule-based, deterministic thresholding. |
| Morphology / graphite forms? | Geometric rules on measured features | services/morphology.py | `classify_graphite_forms()` | per-particle roundness/shape rows | form classes (e.g. spheroidal vs irregular) | **No** | Threshold/classification rules, not a trained classifier. |
| ISO calculation? | ISO 945-4 area-ratio formula | nodularity_pipeline.py | `analyze_image()` (L962–1001); `apply_size_filter_and_iso()` | particle areas + roundness | `iso_pct`, `iso_inframe_pct` | **No** | `Σ area[roundness ≥ 0.6] / Σ area × 100` — explicit standard formula. |
| JIS calculation? | JIS G5502 count-weighted formula | nodularity_pipeline.py + analyze_with_recovery.py `jis_bucket()` | same block | per-particle roundness buckets | `jis_pct` | **No** | `(0.3N₂+0.7N₃+0.9N₄+N₅)/N×100`. |
| Self-check (P/R/F1, count %) | Agreement vs an independent Otsu reference segmentation | nodularity_pipeline.py | `accuracy_vs_reference()`, `reference_particles()` | contours vs opened reference map | precision/recall/F1 | **No** | Deterministic cross-check; NOT human ground truth, NOT model accuracy. |
| Benchmark / ground truth? | Offline evaluation tooling vs hand-labeled panels | services/gt_benchmark.py, services/accuracy_bench.py, tools/build_benchmark_v1.py | benchmark runners | labeled panels (Nodularity-main/evaluation/ground_truth) | reports/ground_truth, reports/accuracy summaries | **No** | Evaluation of the CV pipeline; no training happens anywhere. |
| AI Copilot | LLM (text only), provider chain + offline rule-based fallback | ai/agent.py, ai/tools.py, ai/groq_provider.py, ai/fallback_provider.py | `handle_turn()` | user message + analysis context | text reply + UI actions | **No (not trained by us; it is a hosted LLM API)** | Text explanation/report assistant; it does NOT detect graphite. |
| Regression model | **DOES NOT EXIST** | — | — | — | — | **No** | No sklearn/TensorFlow/PyTorch in requirements.txt; no training code; no model files (the deleted `.pkl` files under reports/merge_experiment were cached OpenCV results, not models). |
