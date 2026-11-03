# NODIQ-X System Architecture

## 1. Overview
NODIQ-X is an industrial-grade metallurgical microstructure intelligence platform designed for automated, standardized characterization of cast irons (ductile, gray, white) and structural steels per ISO 945, ASTM A247, and ASTM E112 standards.

The application follows an asynchronous client-server architecture serving both API endpoints and a compiled React single-page application (SPA) from the same origin.

---

## 2. Repository Structure & Folder Map

```
nodiq/
├── src/nodiq/                  # Core Python package root
│   ├── api/                    # Flask 3.1 REST API gateway & security controls (server.py)
│   ├── pipelines/              # Metallurgical analysis engines & worker subroutines
│   │   ├── nodularity_pipeline.py      # Validated nodularity analysis (1000/1000 verified)
│   │   ├── steel_grain_size_pipeline.py # ASTM E112 Heyn & Jeffries analysis
│   │   ├── analysis_child.py           # Independent worker subprocess entrypoint
│   │   └── analyze_with_recovery.py    # Robust multi-pass particle detection
│   ├── reports/                # Industrial certificate & report builders (PDF/CSV/JSON)
│   ├── adapters/               # Model & third-party compatibility layers
│   ├── ai/                     # AI Copilot provider chain & key rotation
│   ├── services/               # Database, auth, storage, validation, SPC, mailer
│   └── core/                   # Centralized configuration & path resolver (config.py)
├── apps/
│   ├── web/                    # React 19 + Vite 8 SPA frontend
│   └── camera-agent/           # Matrix Vision industrial microscope capture daemon
├── deploy/                     # Deployment configurations
│   ├── Dockerfile              # Multi-stage production container build
│   ├── docker-compose.yml      # Local multi-service composition with volume mounts
│   └── render.yaml             # Render Blueprint specification for cloud deployment
├── third_party/                # Cleanly unbundled upstream research repositories
│   ├── Nodularity/             # Baseline ductile iron nodularity detection algorithms
│   ├── ASTM-Grain-Size-Estimator/ # Deep learning Cellpose-SAM grain segmentation
│   ├── grain-size-analysis-tools/ # NIST GSAT classical boundary intercept tool
│   ├── carde/                  # White cast iron carbide segmentation
│   ├── EG_Pore_Segmentation/  # Cast iron graphite flake segmentation
│   └── S-metallograph-segmentation/ # Flake semantic segmentation
├── data/                       # Structured data directories
│   ├── raw/                    # Raw inputs and server runtime data (gitignored)
│   ├── samples/                # Tracked benchmark reference datasets & summaries
│   └── processed/              # Preprocessed evaluation data
├── models/                     # Deep learning checkpoints & Cellpose weights (gitignored)
├── outputs/                    # Exported charts, experiment metrics, and dumps (gitignored)
├── tests/                      # Comprehensive pytest test suite (unit, integration, security)
├── scripts/                    # Maintenance, migration, and benchmarking utilities
│   └── tools/                  # Ground truth annotation and verification scripts
├── docs/                       # Technical architecture, setup manuals, and audit reports
├── logs/                       # Application logs (gitignored)
├── backups/                    # Database and snapshot backups (gitignored)
├── archive/                    # Archived legacy configs and experiments (gitignored)
└── [Root files]                # pyproject.toml, Makefile, requirements.txt, README.md,
                                # VERSION, .env.example, .gitignore, .dockerignore
```

---

## 3. End-to-End Request Flow

```
[ Operator Browser / Camera ]
             │
             ▼
[ React 19 SPA (apps/web) ]
             │  POST /api/analyze (multipart/form-data or JSON with dataset reference)
             ▼
[ Flask API Gateway (src/nodiq/api/server.py) ]
             │
             ├─ 1. CSRF & Origin Verification (_csrf_protect)
             ├─ 2. Tenancy & Auth Authentication (HttpOnly nodiq_session cookie / Bearer token)
             ├─ 3. Account-Level Analysis Rate Limiting (_analyze_limited)
             ├─ 4. Magic-Byte Image Validation & Dimension Guarding (_check_image)
             ├─ 5. Insert Database Record with status: "processing"
             │
             ├───────────────────────────────────────────────────────┐
             │ Immediate HTTP 202 Accepted {"analysis_id": "...",    │
             │                              "poll_url": "/api/analyses/<id>"}
             ▼                                                       ▼
[ Client Poll Loop (GET /api/analyses/<id>) ]       [ Asynchronous Worker Dispatcher ]
             │                                                       │
             │                                       NODIQ_EXEC_MODE=child
             │                                                       ▼
             │                                    [ analysis_child Subprocess ]
             │                                                       │
             │                                   ┌───────────────────┴───────────────────┐
             │                                   ▼                                       ▼
             │                        [ Nodularity Pipeline ]                 [ Steel / Grain Size ]
             │                                   │                                       │
             │                                   └───────────────────┬───────────────────┘
             │                                                       ▼
             │                                       [ Enrichment & Calculations ]
             │                                       - ISO 945 & JIS Nodularity %
             │                                       - ASTM E112 Grain Size Number G
             │                                       - Quality Gate & Calibration Scaling
             │                                                       │
             │                                                       ▼
             │                                       [ Persistence & Storage ]
             │                                       - Update DB status: "completed"
             │                                       - Save full JSON payload
             │                                       - Save annotated & mask artifacts
             │                                                       │
             ▼                                                       ▼
[ Terminal State Reached: HTTP 200 OK ] ◄────────────────────────────┘
- Displays nodule count & ISO/JIS percentages
- Visualizes interactive particle overlays & histograms
- Generates downloadable ASTM / ISO compliance reports
```

---

## 4. Analysis Child Execution & Crash Isolation

To guarantee web server resilience against heavy image processing and third-party memory leaks, NODIQ-X provides process isolation:

### Spawn Mechanism
When configured with `NODIQ_EXEC_MODE=child` (recommended for production environments with >=2GB RAM):
1. **Command**:
   ```bash
   [sys.executable, "-m", "nodiq.pipelines.analysis_child",
    analysis_id, user_id, image_path, filename, manual_mpp, scale_cap, analysis_type, method]
   ```
2. **Environment Inheritance**:
   The parent exports its storage routing (`NODIQ_DATA_DIR`, `NODIQ_DB_PATH`, `NODIQ_FULL_DIR`) into the child's environment, ensuring both processes target identical storage without shared in-memory references.
3. **Process Decoupling**:
   Spawned via `subprocess.Popen` with `start_new_session=True` and `stdin/stdout` directed to `DEVNULL`.

### Crash Isolation & Watchdog Guard
A background watchdog thread tracks the spawned process:
- **Normal Completion**: The child writes the finalized records to the database and exits with code 0.
- **OOM Kill / Hard Crash (e.g. exit code 137 / SIGKILL)**:
  If the child is abruptly terminated by the operating system OOM killer:
  - The web server process remains completely unaffected and healthy.
  - The watchdog detects non-zero exit or termination without output.
  - The pending analysis status in the database is automatically flipped to `"failed"` with an actionable, user-friendly error message (`"Analysis process was interrupted (OOM or crash)"`).

---

## 5. Storage Topology Per Environment

NODIQ-X dynamically routes database state, full JSON payloads, and binary artifacts based on environment configuration:

| Data Asset | Local Development (`NODIQ_BACKEND=sqlite`) | Docker Container (`deploy/Dockerfile`) | Cloud / Render (`NODIQ_BACKEND=supabase`) |
| :--- | :--- | :--- | :--- |
| **Relational Database** | `data/raw/server_data/nodiq.db` (SQLite WAL) | `/app/server_data/nodiq.db` (Volume-mounted) | Remote Supabase PostgreSQL (`DATABASE_URL`) |
| **Full JSON Payloads** | `data/raw/server_data/analyses_full/<id>.json` | `/app/server_data/analyses_full/<id>.json` | Supabase `full_payloads` table / persistent storage |
| **Artifacts (Masks/PDFs)**| `data/raw/server_data/storage/` (Local filesystem) | `/app/server_data/storage/` (Volume-mounted) | Private Supabase Storage Bucket (`nodiq-artifacts`) |
| **Temporary Uploads** | `data/raw/server_data/uploads/` | `/app/server_data/uploads/` | Ephemeral container storage |
| **Copilot Chat Memory** | `data/raw/server_data/copilot_sessions/` | `/app/server_data/copilot_sessions/` | Ephemeral or database persistence |

In containerized deployments, setting `NODIQ_DATA_DIR=/app/server_data` maps all filesystem state directly into Docker volumes (`VOLUME ["/app/server_data"]`), guaranteeing complete data survival across container restarts and rebuilds.
