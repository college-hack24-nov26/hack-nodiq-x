# Repository Restructure Migration Plan

**Document Version:** 1.0.0  
**Date:** October 30, 2026  
**Scope:** Safe, behavior-preserving repository restructure into target layout.

---

## 1. Executive Summary & Strategy

The repository is currently organized as a flat root containing Python analysis pipelines, services, AI modules, test suites, third-party cloned repositories (`*-main`), runtime data (`server_data`), experimental artifacts, and a Vite React frontend (`nodiq-x`).

The target layout separates code into `src/nodiq/` (standard `src` package layout), frontends/agents into `apps/`, configuration into `config/`, data into `data/`, models into `models/`, outputs into `outputs/`, third-party code into `third_party/`, and deployment manifests into `deploy/`.

### Guiding Principles
1. **Behavior-preserving:** Zero logic changes, zero feature additions, zero function renames.
2. **Git History Preservation:** Every file move is executed strictly via `git mv`. No file deletions.
3. **Configuration & Path Centralization:** All hardcoded paths (including absolute `D:\...` paths and relative `PROJECT_ROOT / ...` lookups) are replaced with a single canonical helper in `src/nodiq/core/config.py` using `pathlib.Path` and environment variables.
4. **Clean Root:** Root retains strictly `pyproject.toml`, `Makefile`, `requirements.txt`, `README.md`, `VERSION`, `.env.example`, `.gitignore`, `.dockerignore`.
5. **Phase-by-Phase Verification:** Each phase must pass smoke imports (`python -c "import nodiq"`) and test suites, committed with atomic semantic messages (`restructure: phase N - ...`).

---

## 2. Target Directory Structure

```text
hi/
├── .dockerignore
├── .env.example
├── .gitignore
├── Makefile
├── pyproject.toml
├── README.md
├── requirements.txt
├── VERSION
│
├── apps/
│   ├── camera-agent/                     # Standalone microscope capture agent
│   │   ├── agent_server.py
│   │   ├── camera.py
│   │   ├── camera_agent.py
│   │   ├── config.py
│   │   ├── requirements.txt
│   │   └── README.md
│   └── web/                              # React 19 + Vite 8 frontend (formerly nodiq-x)
│       ├── package.json
│       ├── package-lock.json
│       ├── vite.config.js
│       ├── index.html
│       ├── src/
│       └── public/
│
├── config/
│   └── model_capabilities.yaml           # Moved from root
│
├── data/
│   ├── raw/                              # Source datasets and persistent store
│   │   ├── gray_cast_iron_raw/
│   │   ├── img_gray_iron/
│   │   ├── nodularity_1000_fixed/
│   │   └── server_data/
│   ├── processed/                        # .gitkeep
│   └── samples/                          # .gitkeep
│
├── deploy/
│   ├── Dockerfile                        # Multi-stage production Dockerfile
│   ├── docker-compose.yml                # Docker Compose orchestration
│   └── render.yaml                       # Render cloud deployment blueprint
│
├── docs/
│   ├── architecture.md                   # New repository architecture guide
│   ├── reports/                          # Audit & penetration reports
│   │   ├── security-report.md
│   │   └── Scanned_20261018-2035.pdf
│   └── ...                               # Existing design specs and docs
│
├── logs/                                 # *.log files (gitignored)
├── backups/                              # Database backups (gitignored)
├── models/                               # Pre-trained ML weights (e.g. cpsam)
├── outputs/                              # Benchmark & experiment outputs (formerly reports/)
│   ├── accuracy/
│   ├── ground_truth/
│   └── merge_experiment/
│
├── scripts/                              # Operational & benchmark runners
│   ├── migrate_to_supabase.py
│   ├── run_1000_fixed.py
│   ├── generate_all_drafts_v2.py
│   ├── generate_sample_*.py
│   ├── tools/                            # Diagnostic and ground-truth scripts (formerly tools/)
│   │   ├── annotate_ground_truth.py
│   │   ├── build_benchmark_v1.py
│   │   ├── diag_*.py
│   │   ├── e2e_check.py
│   │   ├── hardening_smoke.py
│   │   ├── mask_reviewer.py
│   │   └── run_merge_experiment.py
│   └── validate-*.sh / *.ps1
│
├── src/
│   └── nodiq/
│       ├── __init__.py
│       ├── api/                          # HTTP & WebSocket API
│       │   ├── __init__.py
│       │   └── server.py                 # Exports app
│       ├── core/                         # Central path, logging, and settings resolution
│       │   ├── __init__.py
│       │   └── config.py
│       ├── pipelines/                    # Computer vision & metallurgical pipelines
│       │   ├── __init__.py
│       │   ├── nodularity_pipeline.py
│       │   ├── steel_grain_size_pipeline.py
│       │   ├── analysis_child.py
│       │   └── analyze_with_recovery.py
│       ├── reports/                      # Report data builders & exporters
│       │   ├── __init__.py
│       │   └── report_builder.py
│       ├── adapters/                     # Third-party model & hardware adapters
│       │   ├── __init__.py
│       │   ├── CLAUDE.md
│       │   ├── GEMINI.md
│       │   └── GPT_OSS.md
│       ├── ai/                           # AI Copilot engine & tool calling
│       │   ├── __init__.py
│       │   ├── agent.py
│       │   ├── config.py
│       │   ├── provider.py
│       │   ├── key_rotation.py
│       │   ├── memory.py
│       │   ├── tools.py
│       │   └── ...
│       └── services/                     # Domain & infrastructure services
│           ├── __init__.py
│           ├── auth.py
│           ├── db.py
│           ├── storage.py
│           ├── context.py
│           ├── quality.py
│           ├── calibration.py
│           ├── grain_size/
│           ├── gray_cast_iron/
│           ├── white_cast_iron/
│           ├── security/
│           └── experimental/
│
├── tests/
│   ├── conftest.py
│   ├── rc_gate.py
│   ├── fixtures/
│   ├── unit/                             # Isolated formula, config, and utility tests
│   └── integration/                      # End-to-end API, pipeline, and database tests
│
├── third_party/                          # Unmodified external research repositories
│   ├── ASTM-Grain-Size-Estimator/        # (renamed from ASTM-Grain-Size-Estimator-main)
│   ├── carde/                           # (renamed from carde-main)
│   ├── EG_Pore_Segmentation/             # (renamed from EG_Pore_Segmentation-main)
│   ├── grain-size-analysis-tools/        # (renamed from grain-size-analysis-tools-main)
│   ├── Nodularity/                       # (renamed from Nodularity-main)
│   └── S-metallograph-segmentation/      # (renamed from S-metallograph-segmentation-main)
│
└── archive/                              # Gitignored local working scratch & copies
    ├── img_gray_iron - Copy/
    ├── scratch/
    └── root-npm/                         # Former root package.json and package-lock.json
```

---

## 3. Comprehensive File Movement Inventory

All moves below will be executed using `git mv` (or filesystem copy + git add for non-git tracked files):

### 3.1. Code & Backend (`src/nodiq/`)
| Source Path | Target Path | Notes |
|:---|:---|:---|
| `nodularity_pipeline.py` | `src/nodiq/pipelines/nodularity_pipeline.py` | Pipeline module |
| `steel_grain_size_pipeline.py` | `src/nodiq/pipelines/steel_grain_size_pipeline.py` | Pipeline module |
| `analysis_child.py` | `src/nodiq/pipelines/analysis_child.py` | Pipeline worker |
| `analyze_with_recovery.py` | `src/nodiq/pipelines/analyze_with_recovery.py` | Pipeline detector wrapper |
| `report_builder.py` | `src/nodiq/reports/report_builder.py` | Report generator |
| `server.py` | `src/nodiq/api/server.py` | API entrypoint (`app` preserved) |
| `adapters/` | `src/nodiq/adapters/` | Added `__init__.py` |
| `ai/` | `src/nodiq/ai/` | Full package move |
| `services/` | `src/nodiq/services/` | Full package move |
| *(new)* | `src/nodiq/__init__.py` | Package root |
| *(new)* | `src/nodiq/api/__init__.py` | API package root |
| *(new)* | `src/nodiq/pipelines/__init__.py` | Pipelines package root |
| *(new)* | `src/nodiq/reports/__init__.py` | Reports package root |
| *(new)* | `src/nodiq/core/__init__.py` | Core package root |
| *(new)* | `src/nodiq/core/config.py` | Centralized paths & runtime configuration |

### 3.2. Applications (`apps/`)
| Source Path | Target Path | Notes |
|:---|:---|:---|
| `nodiq-x/` | `apps/web/` | Full Vite React SPA |
| `nodiq-camera-agent/` | `apps/camera-agent/` | Standalone microscope agent |

### 3.3. Third-Party Repositories (`third_party/`)
| Source Path | Target Path | Notes |
|:---|:---|:---|
| `ASTM-Grain-Size-Estimator-main/` | `third_party/ASTM-Grain-Size-Estimator/` | Suffix `-main` stripped |
| `carde-main/` | `third_party/carde/` | Suffix `-main` stripped |
| `EG_Pore_Segmentation-main/` | `third_party/EG_Pore_Segmentation/` | Suffix `-main` stripped |
| `grain-size-analysis-tools-main/` | `third_party/grain-size-analysis-tools/` | Suffix `-main` stripped |
| `Nodularity-main/` | `third_party/Nodularity/` | Suffix `-main` stripped |
| `S-metallograph-segmentation-main/` | `third_party/S-metallograph-segmentation/` | Suffix `-main` stripped |

### 3.4. Deployment & Infrastructure (`deploy/`)
| Source Path | Target Path | Notes |
|:---|:---|:---|
| `Dockerfile` | `deploy/Dockerfile` | Updated paths and COPY rules |
| `docker-compose.yml` | `deploy/docker-compose.yml` | Updated build context and paths |
| `render.yaml` | `deploy/render.yaml` | Updated dockerfilePath to `deploy/Dockerfile` |

### 3.5. Scripts & Tools (`scripts/`)
| Source Path | Target Path | Notes |
|:---|:---|:---|
| `run_1000_fixed.py` | `scripts/run_1000_fixed.py` | Batch run script |
| `migrate_to_supabase.py` | `scripts/migrate_to_supabase.py` | Data migration script |
| `tools/` | `scripts/tools/` | Diagnostics and ground-truth helpers |

### 3.6. Configuration & Documentation
| Source Path | Target Path | Notes |
|:---|:---|:---|
| `model_capabilities.yaml` | `config/model_capabilities.yaml` | Capabilities manifest |
| `security-report.md` | `docs/reports/security-report.md` | Penetration test report |
| `Scanned_20261018-2035.pdf` | `docs/reports/Scanned_20261018-2035.pdf` | Scanned cert/report |
| *(new)* | `docs/architecture.md` | Comprehensive codebase map |

### 3.7. Data, Models, Outputs & Logs
| Source Path | Target Path | Notes |
|:---|:---|:---|
| `img_gray_iron/` | `data/raw/img_gray_iron/` | Raw BMP micrographs |
| `server_data/` | `data/raw/server_data/` | SQLite DB, uploads, JSON payloads |
| `nodularity_1000_fixed/` | `data/raw/nodularity_1000_fixed/` | 1000-image summary & logs |
| `data/gray_cast_iron_raw/` | `data/raw/gray_cast_iron_raw/` | Move into raw/ |
| *(new)* | `data/processed/.gitkeep` | Empty folder anchor |
| *(new)* | `data/samples/.gitkeep` | Empty folder anchor |
| `docker-models/` | `models/` | Model weights (`cpsam`, etc.) |
| `reports/` (existing) | `outputs/` | Accuracy benchmarks & overlays |
| `camera_agent.log`, `server.log`, `vite.log` | `logs/` | Runtime logs |

### 3.8. Archive (Preserved, Never Deleted)
| Source Path | Target Path | Notes |
|:---|:---|:---|
| `scratch/` | `archive/scratch/` | Local debug scratch |
| `img_gray_iron - Copy/` | `archive/img_gray_iron - Copy/` | Duplicate micrograph backup |
| `package.json` (root), `package-lock.json` (root) | `archive/root-npm/` | Former concurrently helper |

### 3.9. Test Categorization (`tests/{unit,integration}`)
- **`tests/conftest.py`**, **`tests/rc_gate.py`**, **`tests/fixtures/`** stay directly under `tests/`.
- **`tests/unit/`**:
  `test_advancements.py`, `test_ai.py`, `test_annotation_overlays.py`, `test_annotation_regressions.py`, `test_astm_init_timeout.py`, `test_astm_jeffries_reporting.py`, `test_auth_security.py`, `test_camera_agent_cors.py`, `test_camera_agent_states.py`, `test_change_password.py`, `test_dataset_validator.py`, `test_forgot_password.py`, `test_invalid_microstructure.py`, `test_key_rotation.py`, `test_mask_reviewer.py`, `test_multifield.py`, `test_nodularity_audit.py`, `test_pillar2_pillar5.py`, `test_secrets_hygiene.py`, `test_services.py`, `test_size_filter.py`, `test_steel_advancements.py`, `test_storage_backends.py`.
- **`tests/integration/`**:
  `test_accuracy_bench.py`, `test_analyze_rate_limit.py`, `test_api_contracts.py`, `test_audit_gray_cast_iron.py`, `test_cast_iron_new_modes.py`, `test_cookie_auth.py`, `test_crash_isolation.py`, `test_gray_cast_iron_lifecycle.py`, `test_ground_truth_bench.py`, `test_input_security.py`, `test_ownership_isolation.py`, `test_rate_limit_shared.py`, `test_regression_gate.py`, `test_security_hardening.py`, `test_sessions.py`, `test_steel_grain_size.py`, `test_supabase_persistence.py`.

---

## 4. Import Rewrites Map

When modules move to `src/nodiq/`, all imports across `src/`, `scripts/`, and `tests/` will be updated to absolute package imports under `nodiq.*`.

| Old Import Pattern | New Import Pattern |
|:---|:---|
| `import server` / `from server import ...` | `import nodiq.api.server as server` / `from nodiq.api.server import ...` |
| `import nodularity_pipeline` / `from nodularity_pipeline import ...` | `import nodiq.pipelines.nodularity_pipeline as nodularity_pipeline` / `from nodiq.pipelines.nodularity_pipeline import ...` |
| `import steel_grain_size_pipeline` / `from steel_grain_size_pipeline import ...` | `import nodiq.pipelines.steel_grain_size_pipeline as steel_grain_size_pipeline` / `from nodiq.pipelines.steel_grain_size_pipeline import ...` |
| `import analysis_child` / `from analysis_child import ...` | `import nodiq.pipelines.analysis_child as analysis_child` / `from nodiq.pipelines.analysis_child import ...` |
| `import analyze_with_recovery` / `from analyze_with_recovery import ...` | `import nodiq.pipelines.analyze_with_recovery as analyze_with_recovery` / `from nodiq.pipelines.analyze_with_recovery import ...` |
| `import report_builder` / `from report_builder import ...` | `import nodiq.reports.report_builder as report_builder` / `from nodiq.reports.report_builder import ...` |
| `import services.*` / `from services.* import ...` | `import nodiq.services.*` / `from nodiq.services.* import ...` |
| `import ai.*` / `from ai.* import ...` | `import nodiq.ai.*` / `from nodiq.ai.* import ...` |
| `import adapters.*` / `from adapters.* import ...` | `import nodiq.adapters.*` / `from nodiq.adapters.* import ...` |
| `import tools.*` / `from tools.* import ...` | `import scripts.tools.*` / `from scripts.tools.* import ...` |

### Package Packaging & Editable Install
We create `pyproject.toml` with `setuptools` src-layout:
```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "nodiq"
version = "1.6.0"
description = "NODIQ-X — AI-Powered Microstructure Intelligence"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    # mirrors requirements.txt
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src", "."]

[tool.ruff]
line-length = 100
```
Running `pip install -e .` allows `import nodiq` everywhere cleanly.

---

## 5. Path Updates and Centralized Core Configuration

We introduce `src/nodiq/core/config.py`:
```python
import os
from pathlib import Path

# Repository root (hi/)
REPO_ROOT = Path(os.environ.get("NODIQ_ROOT", Path(__file__).resolve().parents[3]))

# Core directories
DATA_DIR = Path(os.environ.get("NODIQ_DATA_DIR", REPO_ROOT / "data" / "raw" / "server_data"))
MODELS_DIR = Path(os.environ.get("NODIQ_MODELS_DIR", REPO_ROOT / "models"))
OUTPUTS_DIR = Path(os.environ.get("NODIQ_OUTPUTS_DIR", REPO_ROOT / "outputs"))
CONFIG_DIR = Path(os.environ.get("NODIQ_CONFIG_DIR", REPO_ROOT / "config"))
DOCS_DIR = Path(os.environ.get("NODIQ_DOCS_DIR", REPO_ROOT / "docs"))
LOGS_DIR = Path(os.environ.get("NODIQ_LOGS_DIR", REPO_ROOT / "logs"))
THIRD_PARTY_DIR = Path(os.environ.get("NODIQ_THIRD_PARTY_DIR", REPO_ROOT / "third_party"))
WEB_DIR = Path(os.environ.get("NODIQ_WEB_DIR", REPO_ROOT / "apps" / "web"))

# Key file paths
MODEL_CAPABILITIES_PATH = CONFIG_DIR / "model_capabilities.yaml"
SUMMARY_1000_CSV_PATH = REPO_ROOT / "data" / "raw" / "nodularity_1000_fixed" / "summary_1000_fixed.csv"

# Third-party repo locations
THIRD_PARTY_NODULARITY = THIRD_PARTY_DIR / "Nodularity"
THIRD_PARTY_ASTM = THIRD_PARTY_DIR / "ASTM-Grain-Size-Estimator"
THIRD_PARTY_GSAT = THIRD_PARTY_DIR / "grain-size-analysis-tools"
THIRD_PARTY_CARDE = THIRD_PARTY_DIR / "carde"
THIRD_PARTY_EG_PORE = THIRD_PARTY_DIR / "EG_Pore_Segmentation"
THIRD_PARTY_SMETALSEG = THIRD_PARTY_DIR / "S-metallograph-segmentation"
```

### Specific Path Changes in Code:
1. **`services/capabilities.py`**:
   Replace `ROOT / "model_capabilities.yaml"` with `MODEL_CAPABILITIES_PATH` from `nodiq.core.config`.
2. **`nodularity_pipeline.py` & `analyze_with_recovery.py`**:
   Replace `PROJECT_ROOT / "Nodularity-main"` with `THIRD_PARTY_NODULARITY` from `nodiq.core.config`.
3. **`services/grain_size/astm_estimator_adapter.py`**:
   Replace `ROOT / "ASTM-Grain-Size-Estimator-main"` with `THIRD_PARTY_ASTM`.
4. **`services/grain_size/gsat_adapter.py`**:
   Replace `ROOT / "grain-size-analysis-tools-main"` with `THIRD_PARTY_GSAT`.
5. **`services/white_cast_iron/carde_adapter.py`**:
   Replace `ROOT / "carde-main"` with `THIRD_PARTY_CARDE`.
6. **`services/gray_cast_iron/graphite_flake_adapter.py`**:
   Replace `ROOT / "EG_Pore_Segmentation-main"` with `THIRD_PARTY_EG_PORE`.
7. **`services/gray_cast_iron/s_metalseg_adapter.py`**:
   Replace `ROOT / "S-metallograph-segmentation-main"` with `THIRD_PARTY_SMETALSEG`.
8. **`server.py`**:
   - Replace `ROOT / "nodularity_1000_fixed" / "summary_1000_fixed.csv"` with `SUMMARY_1000_CSV_PATH`.
   - Replace `ROOT / "server_data"` with `DATA_DIR`.
   - Replace static dist `ROOT / "nodiq-x" / "dist"` with `WEB_DIR / "dist"`.
   - Replace public dataset `ROOT / "nodiq-x" / "public" / "dataset"` with `WEB_DIR / "public" / "dataset"`.
9. **`services/validation_lab.py`**:
   Replace `ROOT / "nodularity_1000_fixed" / "summary_1000_fixed.csv"` with `SUMMARY_1000_CSV_PATH`.
10. **`tests/test_audit_gray_cast_iron.py` & `tests/test_gray_cast_iron_lifecycle.py`**:
    Replace hardcoded `Path(r"D:\hackathons\hi\server_data\uploads\52f1fb7e8433136a.jpg")` with `DATA_DIR / "uploads" / "52f1fb7e8433136a.jpg"`.

---

## 6. Deployment Updates (`deploy/`)

### 6.1. `deploy/Dockerfile`
- **Frontend Stage:**
  ```dockerfile
  COPY apps/web/package.json apps/web/package-lock.json ./
  RUN npm ci
  COPY apps/web/ ./
  RUN rm -rf public/dataset && npm run build
  ```
- **Backend Stage:**
  ```dockerfile
  COPY requirements.txt pyproject.toml ./
  RUN pip install --no-cache-dir -r requirements.txt
  COPY src ./src
  RUN pip install --no-cache-dir -e .
  COPY third_party/grain-size-analysis-tools ./third_party/grain-size-analysis-tools
  COPY third_party/ASTM-Grain-Size-Estimator ./third_party/ASTM-Grain-Size-Estimator
  COPY config ./config
  COPY data/raw/nodularity_1000_fixed ./data/raw/nodularity_1000_fixed
  COPY --from=frontend /web/dist ./apps/web/dist
  COPY apps/web/public/dataset ./apps/web/public/dataset
  VOLUME ["/app/data/raw/server_data", "/app/models"]
  CMD ["sh", "-c", "exec gunicorn -w ${GUNICORN_WORKERS:-1} --threads ${GUNICORN_THREADS:-4} -t 120 -b 0.0.0.0:8001 nodiq.api.server:app"]
  ```

### 6.2. `deploy/docker-compose.yml`
- Build context set to `..` (repo root) with `dockerfile: deploy/Dockerfile`.
- Volume updated: `- nodiq_data:/app/data/raw/server_data`.
- Env file: `../.env`.

### 6.3. `deploy/render.yaml`
- Set `dockerfilePath: deploy/Dockerfile` and `dockerContext: .`.

---

## 7. Hygiene & Automation (`Phase 6`)

1. **`Makefile`**:
   - `make dev`: Concurrently runs Vite (`apps/web`), backend (`python -m nodiq.api.server`), camera agent (`python apps/camera-agent/agent_server.py`).
   - `make test`: Runs `pytest tests/ -q`.
   - `make lint`: Runs `ruff check .` and `npm run lint --prefix apps/web`.
   - `make run`: Runs backend alone (`python -m nodiq.api.server` or `gunicorn nodiq.api.server:app`).
   - `make docker-build`: Runs `docker build -f deploy/Dockerfile -t nodiq-x .`.
2. **`.github/workflows/ci.yml`**:
   - Install dependencies (`pip install -r requirements.txt && pip install -e .`).
   - Run Ruff check.
   - Run Pytest suite (`pytest tests/ -q`).
   - Build frontend (`npm ci --prefix apps/web && npm run build --prefix apps/web`).
3. **`docs/architecture.md`**:
   - Full documentation explaining directory structure, data flows, and configuration.
4. **`.env.example` Check**:
   - Verified to list every environment variable read by backend (`NODIQ_*`, `AI_*`, `GROQ_*`, `SUPABASE_*`, `SMTP_*`, etc.).

---

## 8. Detailed Phased Execution Plan

- **Phase 0: Inspection & Approval** *(Current step)*
  - Complete inventory of files, imports, paths, tests.
  - Present `MIGRATION_PLAN.md` and await user approval.
- **Phase 1: Safety & Clean Working Tree**
  - Commit pending work on branch `restructure`.
  - Verify clean working tree (`git status`).
- **Phase 2: Low-Risk Moves**
  - Move `logs/`, `backups/`, `docs/reports/`, `third_party/` (with `-main` stripped), `archive/` via `git mv`.
  - Update `.gitignore` to match new locations.
  - Verify tests. Commit: `restructure: phase 2 - low-risk moves (third_party, docs, logs, archive)`.
- **Phase 3: Data, Models, Outputs & Central Config**
  - Move `img_gray_iron`, `nodularity_1000_fixed`, `server_data` -> `data/raw/`.
  - Move `docker-models` -> `models/`.
  - Move `reports/` -> `outputs/`.
  - Create `src/nodiq/core/config.py`.
  - Replace all hardcoded path references in code and adapters.
  - Verify tests. Commit: `restructure: phase 3 - data, models, outputs and centralized core config`.
- **Phase 4: Python Code & Package Layout**
  - Move code into `src/nodiq/{api,pipelines,reports,adapters,ai,services}` via `git mv`.
  - Add `__init__.py` to all packages.
  - Create `pyproject.toml` (src layout, package `nodiq`).
  - Move scripts (`run_1000_fixed.py`, `migrate_to_supabase.py`, `tools/` -> `scripts/`).
  - Move `model_capabilities.yaml` -> `config/`.
  - Rewrite all imports to `nodiq.*`.
  - Categorize tests into `tests/unit/` and `tests/integration/`.
  - Install in editable mode: `pip install -e .`.
  - Run smoke import (`python -c "import nodiq; import nodiq.api.server"`) and test suite.
  - Commit: `restructure: phase 4 - python src layout and absolute nodiq imports`.
- **Phase 5: Applications & Deployment**
  - Move `nodiq-x/` -> `apps/web/`.
  - Move `nodiq-camera-agent/` -> `apps/camera-agent/`.
  - Move `Dockerfile`, `docker-compose.yml`, `render.yaml` -> `deploy/`.
  - Move root `package.json` / `package-lock.json` -> `archive/root-npm/`.
  - Update Dockerfile build stages, COPY commands, WORKDIR, CMD module paths, docker-compose volumes, render.yaml.
  - Verify Docker build (`docker build -f deploy/Dockerfile -t nodiq-x .`).
  - Verify frontend build (`npm run build --prefix apps/web`).
  - Commit: `restructure: phase 5 - apps and deployment configuration`.
- **Phase 6: Project Hygiene**
  - Add `Makefile`.
  - Add `.github/workflows/ci.yml`.
  - Add `docs/architecture.md`.
  - Update `README.md` with new folder layout and quickstart commands.
  - Add `.gitkeep` to empty folders.
  - Audit `.env.example`.
  - Run full test suite and smoke checks.
  - Commit: `restructure: phase 6 - project hygiene, makefile, ci, and documentation`.

---

## 9. Baseline Test & Pre-existing Issues Note

Baseline test run of the existing codebase (`pytest tests/ -q`):
- **476 passed**
- **3 failed** (pre-existing):
  1. `tests/test_cast_iron_new_modes.py:124`: `assert (repo_dir / "README.md").exists()` — `carde-main/README.md` was not in the repo root (only in `docs/README.md`).
  2. `tests/test_key_rotation.py:193`: `fake_post()` mock in unit test missing `stream` keyword argument added in recent commit to `ai/groq_provider.py`.
  3. `tests/test_key_rotation.py:210`: lambda mock in unit test missing `stream` keyword argument.
All other 476 tests passed. The restructure will preserve all 476 passing tests and the exact behavior of the system.

