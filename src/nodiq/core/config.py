"""
nodiq.core.config — Centralized path and configuration resolution.

Provides canonical paths for data, models, outputs, configuration, third-party
repositories, and apps across local development, testing, and containerized runtime.
All paths are resolved using pathlib.Path with environment variable overrides.
No hardcoded absolute paths.
"""
import os
from pathlib import Path

# Repository root (d:\hackathons\hi)
REPO_ROOT = Path(
    os.environ.get("NODIQ_ROOT")
    or Path(__file__).resolve().parents[3]
)

# Core top-level directories
CONFIG_DIR = Path(os.environ.get("NODIQ_CONFIG_DIR") or (REPO_ROOT / "config"))
DATA_DIR_BASE = Path(os.environ.get("NODIQ_DATA_BASE_DIR") or (REPO_ROOT / "data"))
DATA_RAW_DIR = Path(os.environ.get("NODIQ_DATA_RAW_DIR") or (DATA_DIR_BASE / "raw"))
DATA_PROCESSED_DIR = DATA_DIR_BASE / "processed"
DATA_SAMPLES_DIR = DATA_DIR_BASE / "samples"
MODELS_DIR = Path(os.environ.get("NODIQ_MODELS_DIR") or (REPO_ROOT / "models"))
OUTPUTS_DIR = Path(os.environ.get("NODIQ_OUTPUTS_DIR") or (REPO_ROOT / "outputs"))
DOCS_DIR = Path(os.environ.get("NODIQ_DOCS_DIR") or (REPO_ROOT / "docs"))
LOGS_DIR = Path(os.environ.get("NODIQ_LOGS_DIR") or (REPO_ROOT / "logs"))
THIRD_PARTY_DIR = Path(os.environ.get("NODIQ_THIRD_PARTY_DIR") or (REPO_ROOT / "third_party"))
APPS_DIR = REPO_ROOT / "apps"
WEB_DIR = Path(os.environ.get("NODIQ_WEB_DIR") or (APPS_DIR / "web"))

# Runtime / Server state directory (server_data)
DATA_DIR = Path(
    os.environ.get("NODIQ_DATA_DIR")
    or (DATA_RAW_DIR / "server_data")
)
SERVER_DATA_DIR = DATA_DIR

# Key datasets and references
SUMMARY_1000_CSV_PATH = DATA_SAMPLES_DIR / "summary_1000_fixed.csv"
MODEL_CAPABILITIES_PATH = CONFIG_DIR / "model_capabilities.yaml"
GRAY_CAST_IRON_RAW_DIR = DATA_RAW_DIR / "gray_cast_iron_raw"
IMG_GRAY_IRON_DIR = DATA_RAW_DIR / "img_gray_iron"

# Third-party repositories
THIRD_PARTY_NODULARITY = THIRD_PARTY_DIR / "Nodularity"
THIRD_PARTY_ASTM = THIRD_PARTY_DIR / "ASTM-Grain-Size-Estimator"
THIRD_PARTY_GSAT = THIRD_PARTY_DIR / "grain-size-analysis-tools"
THIRD_PARTY_CARDE = THIRD_PARTY_DIR / "carde"
THIRD_PARTY_EG_PORE = THIRD_PARTY_DIR / "EG_Pore_Segmentation"
THIRD_PARTY_SMETALSEG = THIRD_PARTY_DIR / "S-metallograph-segmentation"

