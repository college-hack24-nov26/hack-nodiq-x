"""Import the repository's Jeffries planimetric module as-is.

``4_evaluate_jeffries.py`` performs a module-level ``import pandas``. That
import must SUCCEED — this loader never injects a stub or a shim; failure is
surfaced to the caller. Nothing in this module alters the repository code.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, List, Tuple


def load_repository_jeffries_module(repo_dir: Path
                                    ) -> Tuple[Any, List[str]]:
    """Import ``<repo_dir>/4_evaluate_jeffries.py`` unmodified.

    Returns ``(module, anomalies)``; ``anomalies`` lists any non-fatal
    deviations observed during the import. Raises ImportFailure if the
    module itself cannot be imported (e.g. pandas missing), because that is
    a real environment problem the caller must surface.
    """
    anomalies: List[str] = []

    # A previous failed run may have left a fake "pandas" in sys.modules.
    # If a REAL pandas is importable, purge that fake entry first so the
    # repository module sees the genuine library, not the impostor. If a
    # real pandas is NOT importable, surface the problem instead of masking it.
    try:
        import pandas  # noqa: F401
    except Exception:
        existing = sys.modules.get("pandas")
        if isinstance(existing, types.ModuleType) and not getattr(
                existing, "__spec__", None):
            anomalies.append(
                "a fake \"pandas\" module without-installed origin was "
                "present in sys.modules and was removed before import.")
            sys.modules.pop("pandas", None)
            importlib.invalidate_caches()
        try:
            import pandas  # noqa: F401
        except Exception as exc:
            raise ImportError(
                "the repository's 4_evaluate_jeffries.py requires a real, "
                "importable pandas at module level "
                f"(import error: {type(exc).__name__}: {exc}); no stub is "
                "injected. Install a pandas version compatible with this "
                "environment's numpy, or configure an isolated node "
                "runtime (NODIQ_ASTM_PYTHON) where pandas works.") from exc

    path = Path(repo_dir) / "4_evaluate_jeffries.py"
    if not path.is_file():
        raise ImportError(
            f"the Jeffries planimetric module was not found at {path}")

    try:
        spec = importlib.util.spec_from_file_location("astm_jeffries", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"could not build an import spec for {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("astm_jeffries", module)
        spec.loader.exec_module(module)
    except BaseException as exc:  # noqa: B902 - re-raise real import errors
        sys.modules.pop("astm_jeffries", None)
        raise ImportError(
            f"importing {path.name} failed with "
            f"{type(exc).__name__}: {str(exc)[:200]}") from exc

    required = ("calculate_jeffries",)
    for attr in required:
        if not hasattr(module, attr):
            raise ImportError(
                f"imported Jeffries module {path.name} does not define "
                f"{attr}()")
    return module, anomalies
