#!/usr/bin/env python3
"""ai/config.py — AI configuration for NODIQ-X.

Environment variables are loaded from the project root .env file and the
runtime environment. Groq is the active Copilot default because it is the
most reliable hosted provider for the app's real-time assistance flow.
"""
import os
import sys
import threading
import time as _time
from pathlib import Path

from nodiq.core.config import REPO_ROOT
_ROOT = REPO_ROOT

_env_lock = threading.Lock()


def _read_env_file():
    """Return {KEY: VALUE} parsed from the project .env, or {}."""
    env_path = _ROOT / ".env"
    if not env_path.exists():
        return {}
    out = {}
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        pass
    return out


_DOTENV_INJECTED = set()   # keys we placed into os.environ from .env


def _load_dotenv():
    """Load KEY=VALUE lines from the project .env without extra dependencies."""
    for key, value in _read_env_file().items():
        if key not in os.environ:
            os.environ[key] = value
            _DOTENV_INJECTED.add(key)


def _env_file_mtime():
    try:
        return (_ROOT / ".env").stat().st_mtime
    except OSError:
        return None


def refresh_env_from_dotenv(max_age_s: float = 5.0) -> bool:
    """Hot-reload .env values that are NOT already set in the environment.

    Called lazily by get_config() so a running server picks up .env edits
    (new GROQ_API_KEY, model change, …) without a restart. os.environ always
    wins — real environment variables are never overwritten. Cheap: at most
    one file stat per call, one re-read per max_age_s.

    Disabled under pytest for the same isolation reason as the import-time
    seeding above: this path would inject live .env credentials into the
    test process the first time get_config() runs.
    """
    if "pytest" in sys.modules:
        return False
    global _last_env_check
    now = _time.monotonic()
    with _env_lock:
        if _last_env_check[0] is not None and now - _last_env_check[0] < max_age_s:
            return False
        _last_env_check[0] = now
    mtime = _env_file_mtime()
    if mtime is None or mtime == _last_env_check[1]:
        return False
    _last_env_check[1] = mtime
    changed = False
    for key, value in _read_env_file().items():
        if not value:
            continue
        # update keys the file originally injected (so .env EDITS such as a
        # new GROQ_MODEL take effect without a restart); real environment
        # variables set outside .env always win
        if key not in os.environ or key in _DOTENV_INJECTED:
            if os.environ.get(key) != value:
                os.environ[key] = value
                changed = True
            _DOTENV_INJECTED.add(key)
    return changed


_last_env_check = [None, None]   # [monotonic_ts_of_last_check, last_mtime]

# Import-time .env seeding is for local dev (`python server.py`). Under
# pytest it is DISABLED: tests collected from the whole suite import `server`
# (alphabetically before most modules) and would otherwise pull every real
# .env value — live Supabase credentials included — into the test process,
# silently flipping module-level backend flags (services.storage.BACKEND)
# and breaking test isolation. pytest fixtures set exactly the env they need.
if "pytest" not in sys.modules:
    _load_dotenv()


def _bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in (
        "1", "true", "yes", "on")


class AIConfig:
    def __init__(self):
        self.provider = os.environ.get("AI_PROVIDER", "groq").strip().lower()
        self.model = os.environ.get("AI_MODEL", "").strip()
        self.api_key = os.environ.get("AI_API_KEY", "").strip()
        self.base_url = os.environ.get("AI_BASE_URL", "").strip()
        self.groq_api_key = os.environ.get("GROQ_API_KEY", "").strip()
        # Copilot key-rotation queue (limit-reached fails over to the
        # next key): GROQ_API_KEY_2 … GROQ_API_KEY_6, or one
        # comma-separated GROQ_API_KEYS list.
        self.groq_queue_keys = [k for k in (
            os.environ.get(n, "").strip() for n in (
                "GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4",
                "GROQ_API_KEY_5", "GROQ_API_KEY_6")) if k]
        self.groq_model = os.environ.get("GROQ_MODEL", "").strip()
        self.offline_mode = _bool("OFFLINE_MODE", False)
        self.request_timeout = float(os.environ.get("AI_TIMEOUT", "25"))

        self.enable_copilot = _bool("ENABLE_COPILOT", True)
        self.enable_quality_gate = _bool("ENABLE_QUALITY_GATE", True)
        self.enable_calibration = _bool("ENABLE_CALIBRATION", True)
        self.enable_batch_analytics = _bool("ENABLE_BATCH_ANALYTICS", True)
        self.enable_spc = _bool("ENABLE_SPC", True)
        self.enable_anomaly_detection = _bool("ENABLE_ANOMALY_DETECTION", True)
        self.enable_ai_reports = _bool("ENABLE_AI_REPORTS", True)

    @property
    def groq_base_url(self):
        return self.base_url or "https://api.groq.com/openai/v1"

    @property
    def groq_default_model(self):
        return self.groq_model or self.model or "llama-3.3-70b-versatile"

    @property
    def ollama_base_url(self):
        return self.base_url or "http://127.0.0.1:11434/v1"

    @property
    def ollama_default_model(self):
        return self.model or "llama3.2"

    @property
    def gemini_base_url(self):
        return self.base_url or "https://generativelanguage.googleapis.com/v1beta"

    @property
    def gemini_default_model(self):
        return self.model or "gemini-2.0-flash-lite"

    @property
    def openai_base_url(self):
        return self.base_url or "https://api.openai.com/v1"

    @property
    def openai_default_model(self):
        return self.model or "gpt-4o-mini"


_config = None


def get_config():
    global _config
    # Pick up .env edits without a server restart (e.g. a GROQ_API_KEY pasted
    # in after the server started) and rebuild the cached snapshot when the
    # environment actually changed.
    if refresh_env_from_dotenv() or _config is None:
        _config = AIConfig()
    return _config


def reload_config():
    global _config
    _config = AIConfig()
    return _config
