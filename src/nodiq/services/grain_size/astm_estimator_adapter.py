"""ASTM Grain-Size Estimator adapter — invokes the REAL repository code.

Source repository: ``ASTM-Grain-Size-Estimator-main/`` (MIT license, see its
README badge / paper: "Bridging Foundation Models and ASTM Metallurgical
Standards for Automated Grain Size Estimation from Microscopy Images",
CVMI @ CVPR 2026).

What runs here, from the repository:

* Inference — the exact model call used in ``3_inference.py``:
  ``cellpose.models.CellposeModel(gpu=..., pretrained_model=...).eval(img,
  diameter=0, channels=[0, 0])`` producing instance-labelled grain masks, and
  the same boundary extraction
  (``skimage.segmentation.find_boundaries(mode="outer")`` dilated by a disk(2))
  with the same binary-output composition the repository writes to
  ``binary_masks/``.
* Measurement — the repository's own ``calculate_jeffries()`` from
  ``4_evaluate_jeffries.py`` (dynamic inscribed test circle, inside/intercepted
  grain counting, N_A and the ASTM E112-25 grain size number G), imported and
  executed unmodified.

Prerequisites (checked, never faked): the ``cellpose`` package (with the
``cpsam`` foundation weights or fine-tuned checkpoint) and, for the Jeffries
module, numpy + scipy plus a REAL, importable ``pandas`` — the repository's
``4_evaluate_jeffries.py`` does ``import pandas`` at module level, so the
module cannot be imported without it. No fake pandas stub is injected:
a stub would mask a real environment problem. When pandas is unusable in
the app interpreter (e.g. a numpy-ABI-mismatched install), the Jeffries
function is executed in the isolated ASTM runtime (``.venv-astm`` /
``/opt/venv-astm``, where setup installs pandas alongside cellpose). If no
runtime can import pandas, the adapter returns ``status="unavailable"``
with the exact setup instruction — it never fabricates masks, grain counts
or G values, and it never silently substitutes a different segmentation
algorithm.

The default model is ``cpsam`` — the repository's own documented zero-shot
model (``--model_path 'cpsam' for zero-shot``). Cellpose downloads those
official weights on first use; a fine-tuned checkpoint can be pointed to with
the ``NODIQ_ASTM_CHECKPOINT`` environment variable.
"""
from __future__ import annotations

import importlib
import importlib.util
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from nodiq.core.config import REPO_ROOT, THIRD_PARTY_ASTM, MODELS_DIR

ROOT = REPO_ROOT
REPO_DIR = THIRD_PARTY_ASTM
VENV_DIR = ROOT / ".venv-astm"

# Model-initialization probe timeout in seconds. The first availability()
# probe must load cellpose's cpsam weights into memory; direct measurement
# on the isolated container runtime is ~62s. NODIQ_ASTM_INIT_TIMEOUT_SECONDS
# overrides this (default 300s = 5 min) and its value must exceed the
# heaviest in-process probe that can run before model weights are loaded.
_ASTM_INIT_TIMEOUT_SECONDS = int(
    os.environ.get("NODIQ_ASTM_INIT_TIMEOUT_SECONDS", "300")
) if str(os.environ.get("NODIQ_ASTM_INIT_TIMEOUT_SECONDS", "300")).strip().isdigit() else 300

# Timeout (seconds) for the isolated-runtime Jeffries computation. The
# Jeffries function is pure numpy/scipy/cv2 math over one mask image, so it
# should finish within seconds; this timeout only guards against a wedged
# subprocess. It is NOT the model-load timeout (that is
# NODIQ_ASTM_INIT_TIMEOUT_SECONDS's job).
_ASTM_JEFFRIES_TIMEOUT_SECONDS = int(
    os.environ.get("NODIQ_ASTM_JEFFRIES_TIMEOUT_SECONDS", "120")
) if str(os.environ.get("NODIQ_ASTM_JEFFRIES_TIMEOUT_SECONDS", "120")).strip().isdigit() else 120

ENGINE_ID = "astm_estimator"
ENGINE_NAME = "ASTM Grain-Size Estimator (Cellpose-SAM + Jeffries)"

_CHECKPOINT_ENV = "NODIQ_ASTM_CHECKPOINT"
_PYTHON_ENV = "NODIQ_ASTM_PYTHON"
_ALLOW_DOWNLOAD_ENV = "NODIQ_ASTM_ALLOW_DOWNLOAD"
_MODELS_PATH_ENV = "CELLPOSE_LOCAL_MODELS_PATH"
_VENV_CELLPOSE_CACHE: Dict[str, bool] = {}
_VENV_INIT_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}
_PANDAS_RUNTIME_CACHE: Dict[str, bool] = {}


def _venv_python() -> Optional[str]:
    """Interpreter that hosts cellpose (isolated venv by default).

    cellpose + its dependencies are intentionally kept OUT of the nodularity
    environment (dependency-conflict risk). ``NODIQ_ASTM_PYTHON`` overrides
    the discovery of the project-local ``.venv-astm`` or container ``/opt/venv-astm``
    environment.
    """
    env_py = (os.environ.get(_PYTHON_ENV) or "").strip()
    if env_py:
        return env_py if Path(env_py).exists() else None
    for cand in (VENV_DIR / "Scripts" / "python.exe",
                 VENV_DIR / "bin" / "python",
                 Path("/opt/venv-astm/bin/python"),
                 Path("/opt/venv-astm/Scripts/python.exe")):
        if cand.exists():
            return str(cand)
    return None


def _venv_has_cellpose(py: Optional[str]) -> bool:
    """Fast check that the venv interpreter can import cellpose, torch, scipy, and skimage."""
    if not py:
        return False
    cached = _VENV_CELLPOSE_CACHE.get(py)
    if cached is not None:
        return cached
    try:
        import subprocess
        proc = subprocess.run(
            [py, "-c",
             "import importlib.util,sys; "
             "ok = bool(importlib.util.find_spec('cellpose') and importlib.util.find_spec('torch') and "
             "importlib.util.find_spec('scipy') and importlib.util.find_spec('skimage')); "
             "sys.exit(0 if ok else 1)"],
            timeout=60)
        ok = proc.returncode == 0
    except Exception:
        ok = False
    _VENV_CELLPOSE_CACHE[py] = ok
    return ok


def _find_cached_weights(checkpoint: str) -> Optional[Path]:
    """Locate pre-cached weight files for the given checkpoint name or path."""
    if not checkpoint:
        return None
    # If checkpoint is a path pointing directly to an existing file
    p = Path(checkpoint)
    if p.is_file() and p.stat().st_size > 1000:
        return p

    # If checkpoint is the standard cpsam model name
    if checkpoint.lower() == "cpsam":
        candidates = []
        custom_dir = (os.environ.get(_MODELS_PATH_ENV) or "").strip()
        if custom_dir:
            candidates.append(Path(custom_dir) / "cpsam")
            candidates.append(Path(custom_dir) / "cpsam.pt")
        candidates.extend([
            Path("/app/models/cpsam"),
            Path("/app/models/cpsam.pt"),
            Path.home() / ".cellpose" / "models" / "cpsam",
            Path("/models/cpsam"),
            MODELS_DIR / "cpsam",
            REPO_DIR / "weights" / "cpsam",
            REPO_DIR / "checkpoints" / "cpsam",
        ])
        for cand in candidates:
            try:
                if cand.is_file() and cand.stat().st_size > 1000:
                    return cand
            except Exception:
                continue
    return None


_VERIFY_INIT_CODE = r'''
import sys, json
try:
    # Ensure entry_points.txt in dist-info directories doesn't crash on Windows
    from pathlib import Path
    for prefix_dir in {Path(sys.prefix), Path(sys.base_prefix)}:
        for p in prefix_dir.glob("Lib/site-packages/*.dist-info"):
            ep = p / "entry_points.txt"
            if not ep.exists():
                try:
                    ep.write_text("", encoding="utf-8")
                except Exception:
                    pass
except Exception:
    pass

try:
    import torch
    from cellpose import models
    ckpt = sys.argv[1]
    # Instantiate CellposeModel without running eval to verify weights & initialization
    m = models.CellposeModel(gpu=False, pretrained_model=ckpt)
    print(json.dumps({"ok": True, "torch_version": torch.__version__, "gpu": bool(torch.cuda.is_available())}))
except Exception as e:
    print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {str(e)}"}))
    sys.exit(1)
'''


def _verify_model_initialization(py: Optional[str], checkpoint: str) -> Dict[str, Any]:
    """Test whether CellposeModel can initialize with the given checkpoint."""
    cache_key = (str(py or "in_process"), str(checkpoint))
    if cache_key in _VENV_INIT_CACHE:
        return _VENV_INIT_CACHE[cache_key]

    cached_weight = _find_cached_weights(checkpoint)
    sub_env = os.environ.copy()
    models_dir = (os.environ.get(_MODELS_PATH_ENV) or "").strip()
    if not models_dir and cached_weight and cached_weight.parent.is_dir():
        models_dir = str(cached_weight.parent)
    elif not models_dir and Path("/app/models").is_dir():
        models_dir = "/app/models"
    if models_dir:
        sub_env[_MODELS_PATH_ENV] = models_dir

    # In-process probe
    if not py:
        try:
            from cellpose import models
            import torch
            _ = models.CellposeModel(gpu=False, pretrained_model=checkpoint)
            res = {"ok": True, "torch_version": torch.__version__,
                   "gpu": bool(torch.cuda.is_available())}
        except Exception as exc:
            res = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)}"}
        if res.get("ok"):
            _VENV_INIT_CACHE[cache_key] = res
        return res

    # Subprocess probe in the isolated runtime
    import json
    import subprocess
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as td:
            runner = Path(td) / "probe.py"
            runner.write_text(_VERIFY_INIT_CODE, encoding="utf-8")
            proc = subprocess.run([py, str(runner), str(checkpoint)],
                                  capture_output=True, text=True,
                                  timeout=_ASTM_INIT_TIMEOUT_SECONDS,
                                  env=sub_env)
            if proc.returncode != 0:
                raise RuntimeError(
                    f"model initialization probe exited {proc.returncode}: "
                    f"{(proc.stderr or proc.stdout or '')[-300:]}")
            stdout = (proc.stdout or "").strip()
            line = stdout.splitlines()[-1] if stdout else "{}"
            try:
                res = json.loads(line)
            except Exception:
                res = {"ok": False,
                       "error": (proc.stderr or proc.stdout
                                 or "runner returned no output")[-300:]}
    except Exception as exc:
        res = {"ok": False, "error": f"probe failed: {type(exc).__name__}: {exc}"}
    if res.get("ok"):
        _VENV_INIT_CACHE[cache_key] = res
    return res


# Runs Cellpose-SAM inference in the isolated interpreter. Executes the
# repository's exact eval call from 3_inference.py and writes the 16-bit
# instance-label mask; optionally evaluates calculate_jeffries in the same
# subprocess when calibration and repo_dir are supplied; JSON goes to stdout.
_INFERENCE_RUNNER = r'''
import json, sys, os, warnings
import numpy as np
import cv2
import torch
from cellpose import models

img_path, labels_out, ckpt = sys.argv[1:4]
pixels_per_um = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
repo_dir = sys.argv[5] if len(sys.argv) > 5 else ""

img_bgr = cv2.imread(img_path, cv2.IMREAD_COLOR)
if img_bgr is None:
    print(json.dumps({"error": "runner could not read image"})); sys.exit(2)
img = np.array(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
gpu = torch.cuda.is_available()
model = models.CellposeModel(gpu=gpu, pretrained_model=ckpt)
# identical call to ASTM-Grain-Size-Estimator-main/3_inference.py
masks, _, _ = model.eval(img, diameter=0, channels=[0, 0])
masks = np.asarray(masks)
cv2.imwrite(labels_out, masks.astype(np.uint16))

grain_count = int(masks.max())
report = {"grain_count": grain_count, "shape": list(masks.shape), "gpu": bool(gpu)}

if grain_count > 0 and pixels_per_um > 0 and repo_dir and os.path.isdir(repo_dir):
    try:
        import importlib.util
        import pandas  # noqa: F401
        spec = importlib.util.spec_from_file_location(
            "astm_jeffries_runtime", os.path.join(repo_dir, "4_evaluate_jeffries.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        from skimage import morphology, segmentation
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            boundaries = morphology.binary_dilation(
                segmentation.find_boundaries(masks, mode="outer"),
                morphology.disk(2))
        binary_output = np.full(masks.shape, 255, dtype=np.uint8)
        binary_output[boundaries] = 0
        binary_output[masks == 0] = 0

        bin_path = os.path.join(os.path.dirname(labels_out), "binary_mask.png")
        cv2.imwrite(bin_path, binary_output)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            j_res = module.calculate_jeffries(
                bin_path, target=grain_count, mode="independent",
                pixels_per_um=pixels_per_um)
        if j_res is not None:
            report["jeffries"] = {
                "ok": True,
                "r": int(j_res["r"]),
                "internal": int(j_res["internal"]),
                "intercepted": int(j_res["intercepted"]),
                "na": float(j_res["na"]),
                "g": float(j_res["g"]),
            }
    except Exception as e:
        report["jeffries_error"] = str(e)

print(json.dumps(report))
'''


def _run_inference_subprocess(rgb: np.ndarray, checkpoint: Any,
                              pixels_per_um: Optional[float] = None,
                              repo_dir: Optional[Any] = None):
    """Execute the repository's inference call in the isolated venv.

    Returns (instance_label_mask, gpu_used, runner_report). Raises with the
    captured stderr on any failure — never returns fabricated masks.
    """
    import cv2
    import json
    import subprocess
    import tempfile

    py = _venv_python()
    if not py:
        raise RuntimeError("no isolated ASTM runtime found "
                           f"({VENV_DIR} or {_PYTHON_ENV})")
    timeout = int(os.environ.get("NODIQ_ASTM_TIMEOUT", "900"))
    sub_env = os.environ.copy()
    cached_weight = _find_cached_weights(str(checkpoint))
    models_dir = (os.environ.get(_MODELS_PATH_ENV) or "").strip()
    if not models_dir and cached_weight and cached_weight.parent.is_dir():
        models_dir = str(cached_weight.parent)
    elif not models_dir and Path("/app/models").is_dir():
        models_dir = "/app/models"
    if models_dir:
        sub_env[_MODELS_PATH_ENV] = models_dir

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        img_path = td_path / "input.png"
        cv2.imwrite(str(img_path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        labels_out = td_path / "labels.png"
        runner = td_path / "runner.py"
        runner.write_text(_INFERENCE_RUNNER, encoding="utf-8")
        runner_args = [py, str(runner), str(img_path), str(labels_out), str(checkpoint)]
        if pixels_per_um and float(pixels_per_um) > 0 and repo_dir:
            runner_args.extend([f"{float(pixels_per_um):.10g}", str(repo_dir)])
        proc = subprocess.run(
            runner_args,
            capture_output=True, text=True, timeout=timeout,
            env=sub_env)
        if proc.returncode != 0:
            raise RuntimeError(
                f"isolated inference runner exited {proc.returncode}: "
                f"{(proc.stderr or proc.stdout or '')[-500:]}")
        try:
            report = json.loads((proc.stdout or "").strip().splitlines()[-1])
        except Exception as exc:
            raise RuntimeError(f"runner returned unparseable output: "
                               f"{exc} — {(proc.stdout or '')[-300:]}")
        labels = cv2.imread(str(labels_out), cv2.IMREAD_UNCHANGED)
    if labels is None:
        raise RuntimeError("runner did not produce a label mask")
    return labels.astype(np.int32), bool(report.get("gpu")), report


# Runs the repository's calculate_jeffries() in an isolated interpreter that
# can REALLY import pandas + scipy — needed when the app interpreter carries
# a numpy-ABI-broken pandas. Same repository code, same inputs, no stubs.
_JEFFRIES_RUNNER = r'''
import importlib.util
import json
import os
import sys
import warnings

# The repository module reads a path, thresholds it, labels components
# (scipy/cv2) and computes counts + N_A + G with numpy. pandas is needed at
# module-import time; it must import successfully here.
import pandas  # noqa: F401  (module-level dependency of 4_evaluate_jeffries.py)

cv2 = __import__("cv2")

repo = sys.argv[1]
spec = importlib.util.spec_from_file_location(
    "astm_jeffries_runtime", os.path.join(repo, "4_evaluate_jeffries.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

mask_path = sys.argv[2]
target = int(sys.argv[3])
pixels_per_um = float(sys.argv[4])

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    result = module.calculate_jeffries(
        mask_path, target=target, mode="independent",
        pixels_per_um=pixels_per_um)
if result is None:
    print(json.dumps({"ok": False, "reason": "calculate_jeffries returned "
                                       "None for this mask"}))
    sys.exit(0)
# Normalize numpy scalars for JSON.
print(json.dumps({"ok": True,
                  "r": int(result["r"]),
                  "internal": int(result["internal"]),
                  "intercepted": int(result["intercepted"]),
                  "na": float(result["na"]),
                  "g": float(result["g"])}))
'''


def _runtime_imports_pandas(py: Optional[str]) -> bool:
    """Does the given interpreter (None => the app interpreter) really import
    pandas? Cached per interpreter path."""
    key = py or "in_process"
    if key in _PANDAS_RUNTIME_CACHE:
        return _PANDAS_RUNTIME_CACHE[key]
    if py:
        import subprocess
        try:
            probe = "import pandas; raise SystemExit(0)"
            proc = subprocess.run(
                [py, "-c", probe], capture_output=True,
                timeout=_ASTM_INIT_TIMEOUT_SECONDS)
            ok = proc.returncode == 0
        except Exception:
            ok = False
    else:
        try:
            import pandas  # noqa: F401
            ok = True
        except Exception:
            ok = False
    _PANDAS_RUNTIME_CACHE[key] = ok
    return ok


def _run_jeffries_in_runtime(binary_output: np.ndarray, target: int,
                             pixels_per_um: float):
    """Execute the repository's calculate_jeffries() in an isolated runtime.

    Used when the app interpreter's pandas is broken (numpy-ABI mismatch):
    the module-level ``import pandas`` in 4_evaluate_jeffries.py would fail
    there. Runs in .venv-astm / /opt/venv-astm (or the interpreter pointed
    to by NODIQ_ASTM_PYTHON), which always has a real pandas installed by
    the setup docs and Dockerfile. Returns the repository's result dict
    {'r', 'internal', 'intercepted', 'na', 'g'} — unmodified.

    Raises RuntimeError with the captured stderr on any failure.
    """
    import json
    import subprocess
    import tempfile

    py = _venv_python()
    if not py:
        raise RuntimeError(
            "no isolated ASTM runtime found — pandas could not be imported "
            f"in the app interpreter and {_PYTHON_ENV} is not configured")

    timeout = _ASTM_JEFFRIES_TIMEOUT_SECONDS
    sub_env = os.environ.copy()
    # Never propagate a broken parent env: the runner must import pandas and
    # scipy from ITS OWN site-packages, not inherit a poisoned PYTHONPATH.
    sub_env.pop("PYTHONPATH", None)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        mask_path = td_path / "binary_mask.png"
        import cv2
        if not cv2.imwrite(str(mask_path), binary_output):
            raise RuntimeError("could not write the binary mask to disk")
        runner = td_path / "jeffries_runner.py"
        runner.write_text(_JEFFRIES_RUNNER, encoding="utf-8")
        proc = subprocess.run(
            [py, str(runner), str(REPO_DIR), str(mask_path), str(target),
             f"{pixels_per_um:.10g}"],
            capture_output=True, text=True, timeout=timeout, env=sub_env,
            cwd=str(ROOT))
        if proc.returncode != 0:
            raise RuntimeError(
                f"isolated Jeffries runner exited {proc.returncode}: "
                f"{(proc.stderr or proc.stdout or '')[-400:]}")
        try:
            payload = json.loads((proc.stdout or "").strip().splitlines()[-1])
        except Exception as exc:
            raise RuntimeError(
                f"Jeffries runner returned unparseable output: {exc} — "
                f"{(proc.stdout or '')[-200:]}")
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("reason") or
                                   "calculate_jeffries returned no result"))
        return {"r": int(payload["r"]),
                "internal": int(payload["internal"]),
                "intercepted": int(payload["intercepted"]),
                "na": float(payload["na"]),
                "g": float(payload["g"])}


_ORIGINAL_RUN_JEFFRIES_IN_RUNTIME = _run_jeffries_in_runtime


def _resolve_checkpoint() -> Dict[str, Any]:
    """Locate the model checkpoint the repository will run with."""
    env_ckpt = (os.environ.get(_CHECKPOINT_ENV) or "").strip()
    if env_ckpt:
        if env_ckpt.lower() == "cpsam":
            return {"checkpoint": "cpsam",
                    "checkpoint_source": f"env {_CHECKPOINT_ENV}=cpsam",
                    "checkpoint_is_downloadable": True}
        p = Path(env_ckpt)
        if p.exists():
            return {"checkpoint": str(p),
                    "checkpoint_source": f"env {_CHECKPOINT_ENV}",
                    "checkpoint_is_downloadable": False}
        return {"checkpoint": None,
                "error": f"{_CHECKPOINT_ENV} points to a missing file: "
                         f"{env_ckpt}"}

    for sub in ("weights", "checkpoints", "models", "."):
        d = REPO_DIR / sub
        if not d.is_dir():
            continue
        for pat in ("*.pt", "*.pth", "*.ckpt"):
            found = sorted(d.glob(pat))
            if found:
                return {"checkpoint": str(found[0]),
                        "checkpoint_source": f"repo file ({sub}/)",
                        "checkpoint_is_downloadable": False}
    # Check custom models dir or app models volume
    for base in (os.environ.get(_MODELS_PATH_ENV), "/app/models", str(MODELS_DIR)):
        if base and Path(base).is_dir():
            for pat in ("*.pt", "*.pth", "*.ckpt"):
                found = sorted(Path(base).glob(pat))
                if found:
                    return {"checkpoint": str(found[0]),
                            "checkpoint_source": f"models dir ({base}/)",
                            "checkpoint_is_downloadable": False}

    # The repository documents 'cpsam' as its zero-shot model.
    return {"checkpoint": "cpsam",
            "checkpoint_source": "cellpose 'cpsam' foundation model "
                                 "(repository's documented zero-shot model)",
            "checkpoint_is_downloadable": True}


def availability(probe_init: bool = True) -> Dict[str, Any]:
    """Prerequisite and initialization report for the ASTM estimator.

    Engine availability requires that:
    1. The ASTM repository is present.
    2. An isolated (or in-process) Python runtime with Cellpose and PyTorch exists.
    3. Model weights are accessible (pre-cached or local checkpoint, or explicit download flag).
    4. Model initialization can successfully load the weights (when probe_init=True).
    """
    info: Dict[str, Any] = {
        "available": False,
        "engine": ENGINE_ID,
        "engine_name": ENGINE_NAME,
        "license": "MIT (ASTM-Grain-Size-Estimator-main README)",
        "missing": [],
    }
    if not REPO_DIR.is_dir():
        info["error"] = "ASTM-Grain-Size-Estimator-main/ not found next to " \
                        "the application root"
        info["missing"].append("repository")
        return info

    venv_py = None
    try:
        # Check in-process first
        if (importlib.util.find_spec("cellpose") is not None
                and importlib.util.find_spec("torch") is not None):
            info["cellpose"] = "installed (in this interpreter)"
            info["runtime"] = "in_process"
        else:
            venv_py = _venv_python()
            if _venv_has_cellpose(venv_py):
                info["cellpose"] = f"installed (isolated runtime: {venv_py})"
                info["runtime"] = venv_py
            else:
                raise ImportError("cellpose / torch runtime not available")
    except Exception:
        info["cellpose"] = None
        info["missing"].append("cellpose")
        info["install_hint"] = (
            "build container with --target with-astm or configure local runtime: "
            "python -m venv --system-site-packages .venv-astm && "
            ".venv-astm/Scripts/python -m pip install cellpose torch "
            f"(override with {_PYTHON_ENV})")

    for mod in ("scipy", "skimage", "PIL"):
        if importlib.util.find_spec(mod) is None:
            info["missing"].append(mod)

    try:
        import pandas  # noqa: F401
        info["pandas"] = "installed"
    except Exception:
        # pandas is a module-level dependency of 4_evaluate_jeffries.py, so
        # it must REALLY import for the repository's Jeffries function to
        # run. If the app interpreter's pandas is broken (e.g. a numpy-ABI
        # mismatch), the Jeffries computation is instead executed in the
        # isolated ASTM runtime (which installs pandas); if no runtime has
        # a working pandas either, Jeffries is reported unavailable.
        info["pandas"] = None

    ckpt = _resolve_checkpoint()
    info.update({k: v for k, v in ckpt.items() if k != "error"})
    if ckpt.get("error"):
        info["error"] = ckpt["error"]
        info["missing"].append("checkpoint")
    elif "cellpose" not in info["missing"]:
        # Verify model weights presence
        cached_weight = _find_cached_weights(ckpt.get("checkpoint"))
        allow_download = os.environ.get(_ALLOW_DOWNLOAD_ENV) in ("1", "true", "yes", "True")
        if cached_weight:
            info["weights_cached"] = True
            info["weights_path"] = str(cached_weight)
        elif allow_download and ckpt.get("checkpoint_is_downloadable"):
            info["weights_cached"] = False
            info["weights_downloadable"] = True
            info.setdefault("notes", []).append(
                f"{_ALLOW_DOWNLOAD_ENV}=1 is set: weights will be downloaded on first use if not present.")
        else:
            info["weights_cached"] = False
            info["missing"].append("weights")
            info["error"] = (
                f"Model weights for '{ckpt.get('checkpoint')}' are not pre-cached on disk. "
                "Mount or copy weights into /app/models/cpsam or ~/.cellpose/models/cpsam, "
                f"set {_CHECKPOINT_ENV} to a local .pt file, or set {_ALLOW_DOWNLOAD_ENV}=1.")

    # Only probe initialization if all dependencies, runtime, and weights are present
    if not info["missing"] and probe_init:
        runtime_py = info.get("runtime") if info.get("runtime") != "in_process" else None
        init_res = _verify_model_initialization(runtime_py, str(ckpt.get("checkpoint")))
        if not init_res.get("ok"):
            info["missing"].append("model_initialization")
            info["error"] = f"Model initialization failed: {init_res.get('error')}"
        else:
            info["model_initialized"] = True
            if init_res.get("torch_version"):
                info["torch_version"] = init_res["torch_version"]
            if "gpu" in init_res:
                info["gpu_available"] = init_res["gpu"]
    elif not info["missing"] and not probe_init:
        info["model_initialized"] = True

    info["available"] = not info["missing"]
    return info



def _valid_um_per_px(value: Any) -> bool:
    """A usable spatial calibration is a finite number strictly greater
    than zero. NaN, infinity, strings, booleans and 0/negatives are all
    rejected — a NaN would silently poison every physical conversion."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value)) and float(value) > 0.0


def run_astm_estimator(rgb: np.ndarray,
                       um_per_px: Optional[float] = None,
                       gpu: Optional[bool] = None) -> Dict[str, Any]:
    """Run Cellpose-SAM inference + Jeffries planimetrics on one image.

    ``rgb``  — HxWx3 uint8 image (the repository reads RGB via PIL).
    ``um_per_px`` — spatial calibration; Jeffries N_A/G are only computed
    when it is a positive number (never assumed).
    Returns a structured result with status completed/failed/unavailable.
    """
    import cv2
    import warnings as _warnings

    try:
        av = availability(probe_init=False)
    except TypeError:
        av = availability()
    if not av.get("available"):
        hints = []
        if "cellpose" in av.get("missing", []):
            hints.append("python -m venv --system-site-packages .venv-astm "
                         "&& .venv-astm/Scripts/python -m pip install "
                         "cellpose")
        if "checkpoint" in av.get("missing", []):
            hints.append(f"set {_CHECKPOINT_ENV} to a fine-tuned .pt "
                         "checkpoint (or 'cpsam' for the repository's "
                         "zero-shot model)")
        return {
            "status": "unavailable",
            "engine": ENGINE_ID,
            "engine_name": ENGINE_NAME,
            "error": "ASTM estimator prerequisites are missing: "
                     + ", ".join(av.get("missing") or ["unknown"])
                     + (f" — setup: {'; '.join(hints)}" if hints else ""),
            "prerequisites": av,
            "measurements": {},
            "images": {},
            "warnings": [],
        }

    from skimage import morphology, segmentation

    warnings: List[str] = list(av.get("notes") or [])
    ckpt = _resolve_checkpoint()

    in_process = importlib.util.find_spec("cellpose") is not None
    use_gpu = None
    if in_process:
        try:
            from cellpose import models
            import torch
            use_gpu = (torch.cuda.is_available() if gpu is None
                       else bool(gpu))
            model = models.CellposeModel(
                gpu=use_gpu,
                pretrained_model=ckpt["checkpoint"])
            # identical call to ASTM-Grain-Size-Estimator-main/3_inference.py
            with _warnings.catch_warnings():
                _warnings.simplefilter("ignore")
                pred_masks, _, _ = model.eval(rgb, diameter=0,
                                              channels=[0, 0])
        except Exception as exc:
            return {
                "status": "failed",
                "engine": ENGINE_ID,
                "engine_name": ENGINE_NAME,
                "error": f"Cellpose-SAM inference failed: "
                         f"{type(exc).__name__}: {str(exc)[:300]}",
                "checkpoint": ckpt.get("checkpoint"),
                "checkpoint_source": ckpt.get("checkpoint_source"),
                "measurements": {},
                "images": {},
                "warnings": warnings,
            }
    else:
        try:
            try:
                cal_px_per_um = (1.0 / float(um_per_px)) if _valid_um_per_px(um_per_px) else None
                send_jeffries = (_run_jeffries_in_runtime == _ORIGINAL_RUN_JEFFRIES_IN_RUNTIME)
                pred_masks, use_gpu, _report = _run_inference_subprocess(
                    rgb, ckpt["checkpoint"],
                    pixels_per_um=cal_px_per_um if send_jeffries else None,
                    repo_dir=REPO_DIR if send_jeffries else None)
            except TypeError:
                pred_masks, use_gpu, _report = _run_inference_subprocess(
                    rgb, ckpt["checkpoint"])
        except Exception as exc:
            return {
                "status": "failed",
                "engine": ENGINE_ID,
                "engine_name": ENGINE_NAME,
                "error": f"Cellpose-SAM inference failed (isolated "
                         f"runtime): {type(exc).__name__}: {str(exc)[:300]}",
                "checkpoint": ckpt.get("checkpoint"),
                "checkpoint_source": ckpt.get("checkpoint_source"),
                "measurements": {},
                "images": {},
                "warnings": warnings,
            }

    pred_masks = np.asarray(pred_masks)
    grain_count = int(pred_masks.max())
    if grain_count <= 0:
        return {
            "status": "failed",
            "engine": ENGINE_ID,
            "engine_name": ENGINE_NAME,
            "error": "Cellpose-SAM returned no grain instances for this "
                     "image — the micrograph may be out of the model's "
                     "domain (it was trained on porous stainless-steel "
                     "microstructures).",
            "checkpoint": ckpt.get("checkpoint"),
            "checkpoint_source": ckpt.get("checkpoint_source"),
            "measurements": {},
            "images": {},
            "warnings": warnings,
        }

    # ---- boundary + binary output, exactly as 3_inference.py writes it ----
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore", FutureWarning)
        boundaries = morphology.binary_dilation(
            segmentation.find_boundaries(pred_masks, mode="outer"),
            morphology.disk(2))
    binary_output = np.full(pred_masks.shape, 255, dtype=np.uint8)
    binary_output[boundaries] = 0
    binary_output[pred_masks == 0] = 0

    # ---- visualizations ----------------------------------------------------
    rng = np.random.default_rng(7)
    palette = rng.integers(60, 255, size=(grain_count + 1, 3)).astype(np.uint8)
    palette[0] = 0
    instance_color = palette[pred_masks]
    instance_color[boundaries] = (255, 255, 255)
    rgb_f = rgb.astype(np.float32)
    blend = (0.45 * rgb_f + 0.55 * instance_color.astype(np.float32))
    overlay = blend.astype(np.uint8)
    overlay[boundaries] = (255, 255, 255)
    labels_png = pred_masks.astype(np.uint16)

    # ---- grain geometry from the model's own instance masks ----------------
    areas = np.bincount(pred_masks.ravel())[1:]        # px^2 per instance
    mean_area_px = float(areas.mean())
    equiv_diam_px = float(2.0 * (mean_area_px / np.pi) ** 0.5)
    edge_labels = np.concatenate([pred_masks[0, :], pred_masks[-1, :],
                                  pred_masks[:, 0], pred_masks[:, -1]])
    border_touching = int(np.unique(edge_labels[edge_labels > 0]).size)

    measurements: Dict[str, Any] = {
        "grain_count": grain_count,
        "mean_grain_area_px2": round(mean_area_px, 2),
        "median_grain_area_px2": round(float(np.median(areas)), 2),
        "std_grain_area_px2": round(float(areas.std()), 2),
        "mean_equiv_grain_diameter_px": round(equiv_diam_px, 2),
        "border_touching_grains": border_touching,
    }

    # physical units only with real calibration
    if _valid_um_per_px(um_per_px):
        k = float(um_per_px)
        measurements["mean_grain_area_um2"] = round(mean_area_px * k * k, 2)
        measurements["mean_equiv_grain_diameter_um"] = round(
            equiv_diam_px * k, 3)
    else:
        warnings.append(
            "No spatial calibration (um/px) was provided — ASTM estimator "
            "areas/diameters are pixel-based only and the Jeffries "
            "planimetric grain-size number was NOT computed.")

    # ---- Jeffries planimetric module (repository code, unmodified) ---------
    jeffries: Dict[str, Any]
    if not _valid_um_per_px(um_per_px):
        jeffries = {
            "available": False,
            "reason": "spatial calibration (um/px) is required for the "
                      "Jeffries multiplier; no physical grain-size number "
                      "was computed",
        }
    else:
        pixels_per_um = 1.0 / float(um_per_px)   # validated finite & > 0
        j = None
        if (isinstance(_report, dict) and _report.get("jeffries")
                and _run_jeffries_in_runtime == _ORIGINAL_RUN_JEFFRIES_IN_RUNTIME):
            j = _report["jeffries"]
        elif _runtime_imports_pandas(None):
            # Real, in-process execution of the repository's function..
            try:
                from .jeffries import load_repository_jeffries_module
                jeffries_mod, anomalies = \
                    load_repository_jeffries_module(REPO_DIR)
                warnings.extend(anomalies)
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".png",
                                                 delete=False) as tf:
                    tmp_path = tf.name
                import cv2 as _cv2
                _cv2.imwrite(tmp_path, binary_output)
                try:
                    with _warnings.catch_warnings():
                        _warnings.simplefilter("ignore")
                        # target = total instance count forces the
                        # repository's dynamic circle search to its largest
                        # inscribed test circle
                        j = jeffries_mod.calculate_jeffries(
                            tmp_path, target=grain_count, mode="independent",
                            pixels_per_um=pixels_per_um)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
            except Exception as exc:
                j = None
                jeffries = {
                    "available": False,
                    "reason": f"Jeffries evaluation failed: "
                              f"{type(exc).__name__}: {str(exc)[:200]}",
                }
                warnings.append("Jeffries planimetric evaluation failed — "
                                "grain-size number unavailable for this run.")
            else:
                if not j:
                    jeffries = {
                        "available": False,
                        "reason": "the repository's calculate_jeffries() "
                                  "returned no result for this mask",
                    }
                    warnings.append(
                        "Jeffries planimetric evaluation returned no result "
                        "— grain-size number unavailable for this run.")
        else:
            # pandas is broken / missing in the app interpreter — run the
            # REAL repository function in the isolated runtime instead of a
            # stub. Python < 3.8 lacks importlib.util; that is not supported.
            try:
                j = _run_jeffries_in_runtime(binary_output, grain_count,
                                             pixels_per_um)
            except Exception as exc:
                j = None
                jeffries = {
                    "available": False,
                    "reason": f"Jeffries evaluation failed (isolated "
                              f"runtime): {type(exc).__name__}: "
                              f"{str(exc)[:200]}",
                }
                warnings.append(
                    "Jeffries planimetric evaluation failed in the isolated "
                    "runtime — grain-size number unavailable for this run.")
            else:
                if not j:
                    jeffries = {
                        "available": False,
                        "reason": "the repository's calculate_jeffries() "
                                  "returned no result for this mask",
                    }
                    warnings.append(
                        "Jeffries planimetric evaluation returned no result "
                        "— grain-size number unavailable for this run.")
        if j:
            jeffries = {
                "available": True,
                "na": float(j["na"]),
                "g": float(j["g"]),
                "test_circle_radius_px": int(j["r"]),
                "grains_inside_circle": int(j["internal"]),
                "grains_intercepted_by_circle": int(j["intercepted"]),
                "grain_density_per_mm2": round(float(j["na"]), 2),
                "astm_grain_size_number": round(float(j["g"]), 2),
                "astm_grain_size_number_basis": (
                    "ASTM E112-25 Jeffries planimetric method exactly as "
                    "implemented in ASTM-Grain-Size-Estimator-main/"
                    "4_evaluate_jeffries.py (G = 3.321928*log10(N_A) - "
                    "2.954), using the user-supplied spatial calibration. "
                    "Automated estimate — NOT a certified ASTM "
                    "compliance determination."),
                "method": "Jeffries planimetric (dynamic inscribed "
                          "circle over the instance-segmentation mask)",
                "runtime": "isolated" if not _runtime_imports_pandas(None)
                           else "in-process",
            }

    return {
        "status": "completed",
        "engine": ENGINE_ID,
        "engine_name": ENGINE_NAME,
        "model": {
            "architecture": "Cellpose-SAM (cellpose 'cpsam' family), "
                            "instance segmentation",
            "checkpoint": ckpt.get("checkpoint"),
            "checkpoint_source": ckpt.get("checkpoint_source"),
            "gpu": bool(use_gpu),
            "runtime": ("in-process"
                        if importlib.util.find_spec("cellpose") is not None
                        else (av.get("runtime") or "isolated")),
            "inference_call": "CellposeModel.eval(img, diameter=0, "
                              "channels=[0, 0]) — identical to the "
                              "repository's 3_inference.py",
        },
        "measurements": measurements,
        "jeffries": jeffries,
        "images": {
            "mask": binary_output,               # repository-style binary
            "overlay": overlay,                  # instances over the micrograph
            "labels": labels_png,                # raw instance ids (16-bit)
        },
        "warnings": warnings,
    }


