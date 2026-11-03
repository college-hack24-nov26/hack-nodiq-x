"""Shared pytest configuration.

Under the supabase backend the per-fixture DB_PATH redirect (sqlite tmp
files) maps to isolated Postgres schemas, so fixtures get fresh databases
exactly like on sqlite and no cross-test truncation is needed. This hook
only guards the shared public schema: anything left over from earlier
non-test runs is cleared once before each full pytest invocation, so fixed
emails (s1@test.local...) never collide with stale rows. Under the sqlite
backend it is a no-op.

Session-scoped Test Data Directory Isolation:
Before any tests or nodiq packages are imported, NODIQ_DATA_DIR (and
NODIQ_DB_PATH) are pointed at an isolated session-scoped temporary directory.
This guarantees that tests creating users, analyses, or SQLite rows never
contaminate the real runtime directory (data/raw/server_data).

Documented Opt-Out:
Set NODIQ_USE_REAL_DATA=1 in the environment to skip redirection and run
against the actual data/raw/server_data directory (e.g. for production data
inspections or manual migration smoke tests).

Usage:
    pytest                                # sqlite (default, isolated in temp dir)
    NODIQ_USE_REAL_DATA=1 pytest          # sqlite against real data/raw/server_data
    NODIQ_BACKEND=supabase DATABASE_URL=... pytest
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Session-scoped temp data directory setup (runs before any nodiq imports)
# ---------------------------------------------------------------------------
_SESSION_TEMP_DATA_DIR = None

if not os.environ.get("NODIQ_USE_REAL_DATA"):
    os.environ.setdefault("VITE_FIREBASE_API_KEY", "test-mock-firebase-key")
    if not os.environ.get("NODIQ_DATA_DIR"):
        _SESSION_TEMP_DATA_DIR = tempfile.mkdtemp(prefix="nodiq_test_session_")
        os.environ["NODIQ_DATA_DIR"] = _SESSION_TEMP_DATA_DIR
        os.environ["NODIQ_DB_PATH"] = str(Path(_SESSION_TEMP_DATA_DIR) / "nodiq.db")
        for sub in ("analyses_full", "uploads", "copilot_sessions", "storage"):
            (Path(_SESSION_TEMP_DATA_DIR) / sub).mkdir(parents=True, exist_ok=True)

        # Seed essential test fixture micrograph(s) so test_audit_gray_cast_iron
        # and test_gray_cast_iron_lifecycle can run without writing to real data.
        _fixture_src = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "raw"
            / "server_data"
            / "uploads"
            / "52f1fb7e8433136a.jpg"
        )
        if _fixture_src.is_file():
            shutil.copy2(_fixture_src, Path(_SESSION_TEMP_DATA_DIR) / "uploads" / "52f1fb7e8433136a.jpg")

        def _cleanup_session_temp():
            global _SESSION_TEMP_DATA_DIR
            if _SESSION_TEMP_DATA_DIR and os.path.exists(_SESSION_TEMP_DATA_DIR):
                shutil.rmtree(_SESSION_TEMP_DATA_DIR, ignore_errors=True)
                _SESSION_TEMP_DATA_DIR = None

        atexit.register(_cleanup_session_temp)


def pytest_configure(config):
    if os.environ.get("NODIQ_BACKEND", "").strip().lower() != "supabase":
        os.environ.setdefault("NODIQ_STORAGE_BACKEND", "local")
        os.environ.pop("SUPABASE_URL", None)
        os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
        return
    _truncate_public()


def _truncate_public():
    import nodiq.services.db as store
    store.init_db()
    tables = ("analyses", "reports", "feedback", "calibrations", "sessions",
              "full_payloads", "users", "revoked_tokens", "resets")
    with store._LOCK:
        conn = store._connect()
        conn.execute("TRUNCATE " + ", ".join(tables))
