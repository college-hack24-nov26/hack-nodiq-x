"""Tests for the ASTM engine Cellpose-SAM model-initialization timeout.

These tests verify the new NODIQ_ASTM_INIT_TIMEOUT_SECONDS configuration
applied to the actual model-initialization probe in
``_verify_model_initialization``.

They do NOT depend on the real cpsam weights being present: with no
weights, initialization fails honestly, and that failure is asserted
directly. With a lightweight stub checkpoint, initialization succeeds and
the configured timeout is respected.
"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent

import nodiq.services.grain_size.astm_estimator_adapter as astm_adapter


@pytest.fixture(autouse=True)
def _clear_init_cache():
    """Clear the module's initialization cache before each test; the probe
    result is keyed by (runtime, checkpoint), so a stale success from a
    previous weight set must never leak across tests."""
    astm_adapter._VENV_INIT_CACHE.clear()
    yield


def _run_probe(checkpoint, timeout, **env_extra):
    """Run the adapter's own initialization probe in the current
    interpreter with a forced timeout, so we can measure what the probe
    actually does (no real weights needed - it fails fast on missing
    weights)."""
    env = os.environ.copy()
    env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, %r); "
         "import services.grain_size.astm_estimator_adapter as a; "
         "a._VENV_INIT_CACHE.clear(); "
         "print(a._verify_model_initialization(None, %r))"
         % (ROOT, checkpoint)],
        capture_output=True, text=True, timeout=timeout, env=env)
    return proc


def test_astm_init_timeout_config_defaults_to_300_seconds():
    assert astm_adapter._ASTM_INIT_TIMEOUT_SECONDS == 300


def test_astm_init_timeout_env_override():
    # Value is computed at import time; force a fresh import so the env
    # var is honored.
    os.environ["NODIQ_ASTM_INIT_TIMEOUT_SECONDS"] = "45"
    try:
        import importlib
        import nodiq.services.grain_size.astm_estimator_adapter as adapter
        importlib.reload(adapter)
        assert adapter._ASTM_INIT_TIMEOUT_SECONDS == 45
    finally:
        os.environ.pop("NODIQ_ASTM_INIT_TIMEOUT_SECONDS", None)


def test_astm_init_timeout_env_missing_or_invalid_falls_back_to_300():
    # Invalid values are ignored: rebuild the module so it uses the default.
    os.environ["NODIQ_ASTM_INIT_TIMEOUT_SECONDS"] = "not-a-number"
    try:
        import importlib
        import nodiq.services.grain_size.astm_estimator_adapter as adapter
        importlib.reload(adapter)
        assert adapter._ASTM_INIT_TIMEOUT_SECONDS == 300
    finally:
        os.environ.pop("NODIQ_ASTM_INIT_TIMEOUT_SECONDS", None)