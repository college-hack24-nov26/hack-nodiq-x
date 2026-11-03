# Steel Grain-Size Analysis — Setup & Operations

NODIQ-X ships **Steel Grain-Size Analysis** as an independent feature next to
the protected Cast Iron Graphite Nodularity product. It runs two real,
bundled third-party pipelines and never substitutes one for the other:

| Pipeline | Repository | Method | License |
|---|---|---|---|
| **GSAT Classical** | `third_party/grain-size-analysis-tools/` (NIST) | Classical boundary segmentation + ASTM E112 circle-and-line **intercept** measurement | NIST software licensing statement (`LICENSE.md` in the repo) — NIST is acknowledged as the source (see `src/nodiq/services/grain_size/gsat_adapter.py`) |
| **ASTM Grain-Size Estimator** | `third_party/ASTM-Grain-Size-Estimator/` | Cellpose-SAM instance segmentation + ASTM E112-25 **Jeffries planimetric** grain-size number | MIT (per the repository README) |

Both repositories are invoked **unmodified** through adapters:

* `src/nodiq/services/grain_size/gsat_adapter.py` — imports GSAT's `imppy3d_functions`
  package and calls its own driver/measurement functions.
* `src/nodiq/services/grain_size/astm_estimator_adapter.py` — runs the repository's
  exact Cellpose-SAM inference call (`CellposeModel.eval(img, diameter=0,
  channels=[0, 0])`) and imports `4_evaluate_jeffries.py`'s
  `calculate_jeffries()` as-is.
* `src/nodiq/pipelines/steel_grain_size_pipeline.py` — orchestration (method selection,
  calibration normalization, comparison, artifact map). It contains no
  segmentation algorithm of its own.

---

## 1. Environment setup

Base (already required by NODIQ-X):

* Python 3.11+, `opencv-python`, `numpy`, `scipy`, `scikit-image`, `matplotlib`
  (all present in the existing nodularity environment).
* **GSAT extra dependency:** `PyWavelets` (scikit-image's `estimate_sigma`,
  used by GSAT's non-local-means denoise, requires it):

```bash
pip install PyWavelets
```

* **ASTM estimator dependencies (isolated on purpose):** `cellpose` (>= 4.x,
  `cpsam`-capable) plus `torch`. They are installed into a dedicated
  virtual environment so the nodularity environment is never touched.
  The isolated venv MUST also contain `pandas` (a module-level dependency
  of the estimator's `4_evaluate_jeffries.py` — the Jeffries planimetric
  function cannot be imported without it) and `opencv-python` (writes
  the binary mask that feeds the Jeffries calculation):

```bash
python -m venv --system-site-packages .venv-astm
.venv-astm/Scripts/python -m pip install cellpose torch pandas opencv-python     # Windows
.venv-astm/bin/pip install cellpose torch pandas opencv-python                   # macOS/Linux
```

`--system-site-packages` lets the venv reuse the existing numpy/scipy/torch
installs. The adapter discovers `.venv-astm` (or `/opt/venv-astm` in Docker) automatically; override with:

```
NODIQ_ASTM_PYTHON=/path/to/python
```

## 2. Docker Deployment Configurations

NODIQ-X provides two reproducible Docker deployment targets via multi-stage builds in `deploy/Dockerfile`:

### Target A: Standard Production (Default / Lightweight)
Fits free-tier (512MB RAM) and cloud hostings like Render. GSAT classical analysis and nodularity pipelines are fully operational. The ASTM estimator reports `status: "unavailable"` honestly with actionable instructions, preventing container OOM kills.

```bash
# Build (default target is 'standard')
docker build -f deploy/Dockerfile -t nodiq .

# Run
docker run -p 8001:8001 nodiq
```

* **RAM Requirement:** 512MB RAM minimum.
* **Disk Requirement:** ~1.2 GB image.

### Target B: Full Production with ASTM Estimator (`with-astm`)
Includes the dedicated, isolated `/opt/venv-astm` virtual environment containing PyTorch (CPU-only) and Cellpose. The main application Python environment remains clean and lightweight.

```bash
# Build the extended target
docker build -f deploy/Dockerfile --target with-astm -t nodiq:astm .

# Run with pre-cached model weights mounted into /app/models
docker run -p 8001:8001 -v /path/to/host/models:/app/models nodiq:astm
```

* **RAM Requirement:** 2 GB RAM minimum (Cellpose-SAM inference operates in memory).
* **Disk Requirement:** ~3.0 GB image.

---

## 3. Model / Checkpoint Prerequisites

The repository's documented zero-shot model is Cellpose's **`cpsam`**
foundation weights (~1.2 GB).

### Option 1: Pre-Cached Weights (Recommended for Production & Air-Gapped Environments)
Place the `cpsam` model file into one of the recognized discovery locations:
* Docker container volume: `/app/models/cpsam` (mount with `-v /host/dir:/app/models`)
* User cache directory: `~/.cellpose/models/cpsam`
* Custom path via environment variable: `CELLPOSE_LOCAL_MODELS_PATH=/path/to/models/dir`

### Option 2: Fine-Tuned Local Checkpoint
To use a fine-tuned checkpoint (e.g. trained with the repo's `1_prepare_dataset.py` / `2_train.py`):

```bash
# Host environment
export NODIQ_ASTM_CHECKPOINT="/path/to/grain_sam_finetuned.pt"

# Docker container
docker run -p 8001:8001 \
  -v /host/models:/app/models \
  -e NODIQ_ASTM_CHECKPOINT="/app/models/grain_sam_finetuned.pt" \
  nodiq:astm
```

### Option 3: Explicit Automatic Download
If weights are not pre-cached on disk, you can explicitly permit automatic downloading by setting:

```bash
export NODIQ_ASTM_ALLOW_DOWNLOAD=1
```

When this flag is not set and weights are missing, the engine honestly reports `unavailable` with missing `weights` status rather than failing unpredictably during analysis.

### Environment Variables Summary

| Env var | Meaning | Default |
|---|---|---|
| `NODIQ_ASTM_PYTHON` | Interpreter hosting cellpose | `.venv-astm` or `/opt/venv-astm/bin/python` |
| `CELLPOSE_LOCAL_MODELS_PATH` | Directory containing Cellpose model files | `/app/models` or `~/.cellpose/models` |
| `NODIQ_ASTM_CHECKPOINT` | Checkpoint file path or `cpsam` | `cpsam` |
| `NODIQ_ASTM_ALLOW_DOWNLOAD` | Allow downloading `cpsam` if not cached (`0` or `1`) | `0` (require pre-cached weights) |
| `NODIQ_ASTM_TIMEOUT` | Inference runner subprocess timeout (seconds) | `900` |

---

## 4. Startup & Verification

Backend (unchanged from the rest of NODIQ-X):

```bash
python -m nodiq.api.server  # dev; NODIQ_EXEC_MODE=thread by default
gunicorn nodiq.api.server:app # production (see deploy/Dockerfile / deploy/render.yaml)
```

Verify engine availability via API:

```bash
curl -s http://localhost:8001/api/steel/engines | jq .
```

Steel requests ride the same async job system: `POST /api/analyze` →
`analysis_child.run(...)` (thread or isolated child process, per
`NODIQ_EXEC_MODE`) → `steel_grain_size_pipeline.analyze_image()`.

Frontend:

```bash
npm run dev --prefix apps/web    # dev
npm run build --prefix apps/web  # production bundle
```

The feature lives at **`/steel-analysis`** ("Steel Grain Size" in the
sidebar's Analysis group).

---

## 5. Troubleshootin g

1. **"ASTM estimator prerequisites are missing: cellpose"**:
   The container was built with the standard target or the isolated virtual environment is missing. Build with `docker build -f deploy/Dockerfile --target with-astm -t nodiq:astm .` or configure `NODIQ_ASTM_PYTHON`.
2. **"Model weights for 'cpsam' are not pre-cached on disk"**:
   Mount your host directory containing the `cpsam` model file to `/app/models` (`-v /path/to/models:/app/models`), or set `NODIQ_ASTM_ALLOW_DOWNLOAD=1` if the container has internet access.
3. **Out of Memory during inference (OOM Killed)**:
   PyTorch / Cellpose-SAM requires at least 1.5–2GB RAM for CPU inference on high-resolution micrographs. On memory-constrained hosts (e.g. 512MB free tier), use the GSAT Classical pipeline instead or scale up host memory.
4. **Compare Both Mode with ASTM Unavailable**:
   Compare Both preserves full GSAT analysis results, records `status: "partial"`, and marks `comparison.complete = False` with the exact reason why ASTM was omitted.


### Upload Image
`Steel Grain Size` → select pipeline → drop/select a micrograph (or drag &
drop) → optionally enter µm/px → **RUN ANALYSIS**.

### Scan with Microscope
The same page's **🔬 SCAN WITH MICROSCOPE** panel uses the existing camera
agent (`/status`, `/preview`, `/capture` via `nodiq-camera-agent`). A capture
is handed to the **same** steel service as an upload — only tagged
`input_source: microscope` for traceability. The nodularity microscope flow
is untouched.

### Pipeline selection
* **GSAT Classical** — segmentation + intercept measurement only.
* **ASTM Grain-Size Estimator** — Cellpose-SAM + Jeffries only.
* **Compare Both Pipelines** — both run independently on the same image;
  outputs, masks and measurements are preserved separately. Comparison
  reports differences only where definitions/units are compatible (both
  calibrated G values, from different E112 methods). Nothing is averaged;
  agreement is explicitly not proof of accuracy. If one engine fails, the
  other's results survive and the comparison is marked `INCOMPLETE`.

## 5. Calibration

* Supply **µm/px** from a stage-micrometer calibration at the same
  magnification (form field `microns_per_pixel`, API field
  `microns_per_pixel`).
* Physical scale is **never** inferred from magnification alone.
* Without calibration: measurements are pixel-only, physical sizes and
  ASTM grain-size numbers are **not** computed (explicit warnings instead).
* GSAT G (intercept method): `G = -6.643856·log10(mean intercept in mm) − 3.288`.
* Estimator G (Jeffries): `G = 3.321928·log10(N_A) − 2.954` with the dynamic
  multiplier `f = 1/A_circle` exactly as in `4_evaluate_jeffries.py`.
* Both G values are labeled **automated estimates, not certified ASTM
  compliance determinations**.

## 6. Results, masks and artifacts

Artifacts are written by the analysis worker as PNGs
(`server_data/analyses_full/<id>_<kind>.png`, mirrored to Supabase Storage
when configured) and served through the ownership-checked route
`GET /api/analyses/<id>/artifact/<kind>`:

| Kind | Content |
|---|---|
| `gsat_mask` | GSAT grain-boundary mask (white boundaries) |
| `gsat_overlay` | Boundaries + E112 intercept pattern mapped onto the original |
| `gsat_intercept` | GSAT's native marked image (measured chords, gray 150) |
| `gsat_preprocessed` | Denoise+sharpen diagnostic image |
| `astm_mask` | Estimator binary boundary mask (repo's `binary_masks/` format) |
| `astm_overlay` | Colour-coded grain instances over the micrograph |
| `astm_labels` | 16-bit instance-label mask (archival/quantitative reuse) |

`GET /api/analyses/<id>` attaches `<kind>_url` entries for every artifact that
can resolve. The UI shows an explicit "not available" state for missing
artifacts — it never draws a fake mask.

Engine prerequisite status (what can run right now): `GET /api/steel/engines`.

## 7. Report generation

`POST /api/reports/generate` with a steel analysis id produces a dedicated
steel report (`report_kind: steel_grain_size`) covering: sample + input
method, pipeline execution info (engine, checkpoint, GSAT implementation
fingerprint, parameters), calibration, GSAT measurements, estimator +
Jeffries measurements, comparison, artifacts, warnings, observations,
validation status and limitations. PDF/CSV/JSON downloads work through the
existing endpoints; the nodularity report layout is unchanged and used only
for nodularity analyses.

## 8. Testing

```bash
pytest tests/test_steel_grain_size.py -q       # new feature tests
pytest tests -q                                # full regression suite
```

`tests/test_steel_grain_size.py` runs the **real** GSAT engine (including a
cross-check against the reference CSV shipped inside the GSAT repo) and
asserts the estimator's honesty contract (no fabricated measurements when
prerequisites are missing; real instance masks when they are present).

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `astm_estimator: unavailable — cellpose missing` | Create `.venv-astm` and `pip install cellpose` there (see §1). Check `GET /api/steel/engines`. |
| `runner exited <code>` with download errors | First run needs network for `cpsam` weights; or set `NODIQ_ASTM_CHECKPOINT` to a local `.pt`. |
| GSAT mask nearly empty (boundary density < 0.2%) | Etch too weak / wrong polarity — the auto-polarity heuristic records its decision in `parameters.polarity_decision`; retry with a better-etched micrograph. |
| `PyWavelets is not installed` | `pip install PyWavelets` in the app environment. |
| Estimator returns 0 instances | Image outside the model's domain (trained on porous AM stainless steel) — use GSAT or Compare mode; the error says so explicitly. |
| `pandas` warnings | pandas was not importable in the app interpreter; the Jeffries planimetric function now runs in the isolated ASTM runtime (no fake stub is injected — the repository module requires a real pandas). |
| GPU not used | Cellpose auto-detects CUDA; `model.gpu` in the payload states what was used. |

## 10. Known limitations

* GSAT parameters default to the values documented in GSAT's own optical
  example; very different microstructures may need different thresholds
  (exposed as `parameters` in the payload; per-request tuning is not yet in
  the UI).
* The E112 intercept pattern measures the center square of the image.
* The estimator's model was trained on a specific AM stainless dataset — its
  accuracy on other alloys/etches is not guaranteed and is not claimed.
* Neither pipeline's output is a certified standards determination; both are
  decision-support estimates (labels and report text say so).
* Compare mode's "comparable" set is deliberately narrow (calibrated G from
  two different E112 methods); chord length vs equivalent diameter is shown
  only as a "different definitions" row.
