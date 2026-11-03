# NODIQ-X — Viva / Judge Cheat Sheet

Beginner-friendly. Every technical answer uses the pattern **file → function → what it does**.

## 1. 30-second project explanation

"NODIQ-X analyzes ductile-iron micrographs and measures graphite **nodularity** using the
ISO 945-4 and JIS G5502 formulas, with classical OpenCV computer vision — no black box.
You upload an image (or capture from the microscope camera), a Flask worker runs
`nodularity_pipeline.analyze_image()`, and you get nodularity %, per-particle data, an
annotated overlay, and a downloadable PDF report. An LLM Copilot answers questions about
your results."

## 2. 1-minute technical explanation

"Frontend is React 19 + Vite; it calls `api.js analyzeUpload()` which POSTs to
`/api/analyze`. `server.py analyze_upload()` validates the image (magic bytes, size,
dimensions), stores it, inserts a *processing* row in SQLite, and returns 202 while a
watchdog-guarded worker runs `analysis_child.run()`. That calls
`nodularity_pipeline.analyze_image()`: grayscale → blank scale bars → median + Otsu
segmentation → frozen detector + recovery/merge/consolidation → consistency gate →
per-particle area and convex-hull Feret measurement. Roundness = area/(π·r²); ISO
nodularity = area of particles with roundness ≥ 0.6 / total graphite area × 100; JIS is
the count-weighted version. A validity gate rejects non-micrographs. Results persist to
SQLite + JSON payloads + PNG artifacts, the frontend polls `GET /api/analyses/<id>`, and
reports are built from the same measured data via `report_builder.build_report_data()`."

## 3. Complete image-analysis flow

```
Upload button → Analysis.jsx handleUpload() → runOnFile() → startAnalysis()
→ api.js analyzeUpload() → POST /api/analyze
→ server.py analyze_upload() [validate, store, insert "processing", spawn worker, 202]
→ analysis_child.py run() [downscale ≤2000px]
→ nodularity_pipeline.py analyze_image() [segment → detect → measure → ISO/JIS]
→ evaluate_microstructure_validity() [reject non-micrographs]
→ analyze_for_frontend_json() [JSON payload + annotated/mask images]
→ services/context.py save_full_analysis() + services/db.py insert_analysis("completed")
→ GET /api/analyses/<id> → Analysis.jsx applyResult()
```

## 4. Frontend → backend → engine flow

React (Analysis.jsx) → api.js (cookie fetch) → server.py (Flask :8001) →
worker thread/child → nodularity_pipeline.py (OpenCV) → SQLite + JSON + PNG →
poll → React result view.

## 5. Microscope → camera agent → browser → same pipeline

Camera (mvIMPACT, camera.py) → local agent_server.py (/capture) → microscopeAgent.js
captureImage() → Analysis.jsx runOnFile() → **same /api/analyze → same pipeline**.
The microscope is only another input source; there is no separate algorithm for it.

## 6. Database / storage flow

Summary rows → SQLite `server_data/nodiq.db` (services/db.py insert_analysis()).
Full payloads → `server_data/analyses_full/<id>.json` (services/context.py
save_full_analysis()). Images → `<id>_annotated.png` / `<id>_mask.png`.
Optional Supabase Storage for artifacts (services/storage.py). Firebase = **auth only**.
localStorage = UI cache only.

## 7. Authentication flow

Email: LoginForm → authService.loginWithEmail() → POST /api/auth/login →
services/auth.py authenticate() (bcrypt) → HMAC token in HttpOnly cookie.
Google: signInWithGoogle() (Firebase) → POST /api/auth/firebase → auth_firebase()
verifies the ID token with Google → provisions/loads user. Phone: signInWithPhoneNumber()
→ VerifyOtpPage confirm() → same /api/auth/firebase path. Guards: RequireAuth.jsx +
AuthContext (GET /api/auth/me). Logout: Sidebar → POST /api/auth/logout → revoke_token().

## 8. Report generation flow

ReportGenerator.jsx handleGenerate() → api.generateReport() → POST /api/reports/generate
→ reports_generate_v2() → _generate_for() → report_builder.build_report_data()
(**real measured values** from the stored record + payload) → insert_report.
Download: GET /api/reports/<id>/download?format=pdf|csv|json →
report_builder.to_pdf() (fpdf2) / to_csv() / to_json().

## 9. AI Copilot flow

Copilot.jsx sendMessage() → api.copilot() → POST /api/copilot → server.py copilot() →
ai/agent.py handle_turn() → tool calls (ai/tools.py ~18 tools reading real analyses)
→ LLM provider (Groq; offline rule-based fallback) → text reply + UI actions.
The Copilot is **text AI only** — it never processes pixels.

## 10. ML / regression explanation (READ THIS TWICE)

**There is NO regression model and NO trained ML in this repo.**
- Nodularity is **measured geometrically** (ISO 945-4 / JIS G5502 formulas) in
  nodularity_pipeline.py analyze_image() — it is not predicted.
- requirements.txt has **no sklearn / TensorFlow / PyTorch / scipy**.
- No training code, no train/test split, no model files exist.
- The self-check % is agreement with an independent OpenCV reference segmentation —
  not model accuracy.
- The AI component is the **text Copilot** (LLM API + offline fallback), separate from
  image analysis.

## 11. What IS implemented

Upload + validation (magic bytes/size/dimensions) · classical CV segmentation/detection ·
ISO 945-4 + JIS G5502 nodularity math · non-micrograph rejection gate · quality score ·
calibration + ISO 10 µm size filter · graphite forms + property estimates · SQLite/JSON
persistence · history/dashboard/analytics/compare/lots/anomalies/review · real PDF/CSV/JSON
reports · email + Google + phone auth with cookies, rate limits, security log ·
text AI Copilot with tools · microscope capture/preview agent · 347 passing pytest tests.

## 12. What is NOT implemented

- No CNN/YOLO/deep-learning image model.
- No trained regression model.
- No ground-truth-trained nodularity prediction.
- No certified metallurgical accuracy claim (methodology is "ISO 945-based", not certified).
- Self-check ≠ ML accuracy (it is a deterministic reference cross-check).
- Camera hardware validated only in code, not on physical hardware.

## 13. Future scope (safe to say)

- Add a validated regression model mapping microstructure features → mechanical
  properties (we already expose the feature side: services/properties.py
  estimate_properties()).
- Train a validity/segmentation model once expert-labeled ground truth is collected.
- Physically validate the microscope agent on hardware.

## 14. 25 likely judge questions + short answers

1. **What does it do?** Measures graphite nodularity in ductile-iron micrographs with ISO 945-4/JIS formulas, classical OpenCV, and generates reports.
2. **Is the AI doing the analysis?** No — analysis is rule-based OpenCV; the AI Copilot is text-only, in ai/agent.py handle_turn().
3. **Which ML model did you use?** None for images — deterministic CV pipeline (nodularity_pipeline.py analyze_image()).
4. **How is nodularity computed?** roundness = area/(π·r²); ISO = Σround-area/Σarea×100 (≥0.6); JIS = (0.3N₂+0.7N₃+0.9N₄+N₅)/N×100 (nodularity_pipeline.py L962–1001).
5. **How do you segment graphite?** Median blur + Otsu (physical_blob_map()) + frozen detector with recovery stages (analyze_with_recovery.py).
6. **How do you avoid wrong uploads?** evaluate_microstructure_validity() rejects uniform/colorful/no-signal images before results are trusted.
7. **Is 0.6 meaningful?** Yes — ISO 945-4 defines spheroidal graphite as roundness ≥ 0.6.
8. **What about particles touching the border?** Headline ISO keeps them for robustness; iso_inframe_pct excludes them per the standard's strict formula.
9. **Where are results stored?** SQLite server_data/nodiq.db + JSON payloads + PNG artifacts (services/db.py, services/context.py).
10. **Is Firebase your database?** No — Firebase is only for Google/phone sign-in; data lives in SQLite (optional Supabase).
11. **How does the report avoid fake numbers?** build_report_data() reads the stored measured record/payload only; ReportPreview says "no mock fallbacks".
12. **What if the backend dies mid-analysis?** Worker is watchdog-guarded; failures write an honest "failed" record (analysis_child.py, _run_analysis_job_guarded()).
13. **Security?** bcrypt, HttpOnly cookies, CSRF origin checks, rate limits, magic-byte validation, security event log (services/auth.py, seclog.py, rate_limit.py).
14. **How big is the dataset?** 1,000 reference micrographs (nodiq-x/public/dataset) used for demos/validation — **not for training**.
15. **What tests exist?** 31 pytest files; last full run 347 passed, 0 failed.
16. **Can it run on weak hardware?** Yes — 2000px downscale (scale-invariant metrics), thread/child execution modes, size caps.
17. **What's the Copilot's accuracy?** Not applicable — it's an LLM text assistant with tool access to real data, plus an offline rule-based fallback.
18. **Why OpenCV and not deep learning?** Deterministic, auditable, no training data required; geometry directly implements the ISO/JIS definitions.
19. **What is the self-check percentage?** Agreement (P/R/F1) with an independent Otsu reference segmentation inside analyze_image() — a consistency check, not lab accuracy.
20. **Is it certified to ISO?** No — it implements the ISO 945-4 / JIS G5502 **methodology**; no certification claim.
21. **How would you scale it?** child mode isolates heavy jobs; Supabase/Postgres backend exists; Dockerfile/render.yaml ready.
22. **Where does the annotated image come from?** drawContours + draw_banner in nodularity_pipeline.py analyze_image(); saved as <id>_annotated.png.
23. **Can two users see each other's analyses?** No — owner-scoped queries (db.py _visible/user_id) + ownership isolation tests.
24. **What happens with a photo of a landscape?** It is rejected: colorfulness > 45 or missing graphite signal (evaluate_microstructure_validity()).
25. **Biggest limitation?** No expert-labeled accuracy benchmark yet — values are geometrically correct but not certified against human metallurgist labels.

---

## Rapid-fire ML/regression questions (Q1–Q20)

- **Q1 Which ML model?** None — deterministic OpenCV pipeline.
- **Q2 Did you use regression?** No.
- **Q3 Which regression algorithm?** None exists in the repo.
- **Q4 Dependent variable?** N/A — nodularity is *measured*, not predicted.
- **Q5 Independent variables/features?** N/A for a model; the engine measures area, Feret diameter, roundness per particle.
- **Q6 What did you train on?** Nothing — there is no training.
- **Q7 Train/test split?** Not applicable.
- **Q8 R²?** Not applicable.
- **Q9 MAE?** Not applicable.
- **Q10 RMSE?** Not applicable.
- **Q11 Why no CNN?** No labeled training set; ISO/JIS are explicit geometric formulas, so a deterministic pipeline is auditable and reproducible.
- **Q12 Why OpenCV?** Standard, fast, explainable image analysis; directly implements the standards' geometry.
- **Q13 AI or rule-based?** Image analysis: rule-based CV. Copilot: LLM API (text only) with offline rule-based fallback.
- **Q14 Where is the image-analysis logic?** nodularity_pipeline.py analyze_image() (+ analyze_with_recovery.py).
- **Q15 Where is the Copilot AI?** ai/agent.py handle_turn(), ai/tools.py, ai/groq_provider.py; fallback_provider.py offline.
- **Q16 Is reported accuracy from regression?** No — the self-check is agreement with an independent OpenCV reference, not model accuracy.
- **Q17 How would you add regression later?** Extract per-field features (nodularity %, form shares, particle counts), pair with measured mechanical properties, fit/validate a model with sklearn in a separate training script.
- **Q18 Target variable for future regression?** e.g. tensile strength / elongation as a function of nodularity and graphite form distribution.
- **Q19 Training data required?** Specimens with both micrographs and measured mechanical properties (metallography + tensile tests).
- **Q20 What would validation need?** Held-out specimens, expert-labeled nodularity, and standard error metrics (R²/MAE/RMSE) reported honestly.

## "Never say these things" (unless evidence changes)

- ❌ "We trained a Linear Regression model." — no regression exists.
- ❌ "We used Random Forest regression." — no sklearn anywhere.
- ❌ "Our CNN predicts nodularity." — no CNN; nodularity is computed from contour geometry.
- ❌ "95% accuracy is our regression-model accuracy." — no model; don't quote model accuracy.
- ❌ "The model was trained on 1000 images." — the 1000 images are demo/validation inputs, not training data.
- ❌ "Our ISO/JIS calculation is a regression model." — it is an explicit area/count formula.
- ❌ "The Copilot detects graphite nodules." — image analysis is the CV pipeline; the Copilot is text-only.
- ❌ "We are ISO 945 certified." — methodology follows the standard; no certification exists.
- ❌ "The self-check proves lab accuracy." — it is an internal reference cross-check, not ground truth.

## If the judge asks "Which regression model did you use?" — say:

"None. Nodularity isn't predicted by a model — it's measured geometrically with the
ISO 945-4 area ratio and the JIS G5502 count formula in nodularity_pipeline.py.
There is no sklearn or training code in the repository. A regression model mapping
microstructure features to mechanical properties is a natural future step; we already
compute the feature side (services/properties.py estimate_properties())."
