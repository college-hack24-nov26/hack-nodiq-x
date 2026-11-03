"""EG_Pore_Segmentation adapter — invokes the REAL FPN + Watershed segmentation repository code.

Source repository: ``EG_Pore_Segmentation-main/``
Attribution: Aliaksei Krautsou, Olga N. Shornikova, Victor V. Avdeev
Study: "Influence investigation of exfoliated graphite synthesis method on its macropore
structure using neural network"

What runs here, from the repository:
* Neural network inference: Feature Pyramid Network (FPN) with EfficientNet-B4 encoder
  (``segmentation_models_pytorch.FPN`` with ``model.pth`` weights bundled in ``data/``).
* Image tiling: 512x512 tile decomposition with constant padding (matching ``presentation.py``).
* Watershed postprocessing: Genuine watershed boundary refinement (``hist_consistency.postproc2``
  with Euclidean distance transform and optimal threshold 0.41).
* Measurement: Real pore/flake areas via ``hist_consistency.area``.

Pretrained model note:
The model was trained on scanning electron microscopy (SEM) cross-sections of exfoliated
graphite (EG-T / EPG-T / EFG-T).

Target material metallurgical disclaimer:
Application to gray cast iron (lamellar/flake graphite in pearlite/ferrite matrix) is
EXPERIMENTAL AND UNVALIDATED. While gray cast iron graphite flakes share morphological
similarities with exfoliated graphite structures, the model has NOT been calibrated or
certified for industrial cast iron metallography. ISO 945-1 graphite flake forms (Type A–E)
and 3D flake thickness are NOT reported.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from nodiq.core.config import REPO_ROOT, THIRD_PARTY_EG_PORE

ROOT = REPO_ROOT
REPO_DIR = THIRD_PARTY_EG_PORE
VENV_DIR = ROOT / ".venv-cast-iron"

ENGINE_ID = "eg_pore_segmentation"
ENGINE_NAME = "EG Graphite FPN + Watershed (Krautsou et al.)"

_PYTHON_ENV = "NODIQ_EG_PYTHON"
_VENV_EG_CACHE: Dict[str, bool] = {}


def _venv_python() -> Optional[str]:
    """Interpreter hosting PyTorch, segmentation_models_pytorch, and OpenCV."""
    env_py = (os.environ.get(_PYTHON_ENV) or "").strip()
    if env_py:
        return env_py if Path(env_py).exists() else None
    for cand in (
        VENV_DIR / "Scripts" / "python.exe",
        VENV_DIR / "bin" / "python",
        Path("/opt/venv-cast-iron/bin/python"),
        Path("/opt/venv-cast-iron/Scripts/python.exe"),
    ):
        if cand.exists():
            return str(cand)
    # Check if current interpreter has required packages
    if (
        importlib.util.find_spec("torch") is not None
        and importlib.util.find_spec("segmentation_models_pytorch") is not None
    ):
        return sys.executable
    return None


def _venv_has_eg_deps(py: Optional[str]) -> bool:
    """Verify interpreter has torch, segmentation_models_pytorch, and cv2."""
    if not py:
        return False
    cached = _VENV_EG_CACHE.get(py)
    if cached is not None:
        return cached
    try:
        proc = subprocess.run(
            [
                py,
                "-c",
                "import importlib.util,sys; "
                "ok = bool(importlib.util.find_spec('torch') and "
                "importlib.util.find_spec('segmentation_models_pytorch') and "
                "importlib.util.find_spec('cv2') and "
                "importlib.util.find_spec('matplotlib')); "
                "sys.exit(0 if ok else 1)",
            ],
            timeout=30,
        )
        ok = proc.returncode == 0
    except Exception:
        ok = False
    _VENV_EG_CACHE[py] = ok
    return ok


def find_eg_repo() -> Optional[Path]:
    """Return local EG_Pore_Segmentation-main path if directory exists."""
    return REPO_DIR if REPO_DIR.is_dir() else None


def get_upstream_metadata() -> Dict[str, Any]:
    """Upstream licensing, copyright, and bibliographic metadata."""
    return {
        "name": "EG_Pore_Segmentation",
        "attribution": "Aliaksei Krautsou, Olga N. Shornikova, Victor V. Avdeev",
        "citation": "Krautsou et al., 2021 (EG_Pore_Segmentation)",
        "architecture": "FPN (efficientnet-b4) + Watershed Post-processing",
        "methods": ["eg_fpn_watershed"],
    }


def availability() -> Dict[str, Any]:
    """Honest availability and capability report for the EG Graphite Flake engine."""
    info: Dict[str, Any] = {
        "available": False,
        "engine": ENGINE_ID,
        "engine_name": ENGINE_NAME,
        "attribution": "Aliaksei Krautsou, Olga N. Shornikova, Victor V. Avdeev",
        "architecture": "FPN (efficientnet-b4) + Watershed Post-processing (postproc2)",
        "methods": ["eg_fpn_watershed"],
        "weights_expected": "model.pth in EG_Pore_Segmentation-main/data/",
        "weights": {
            "available": False,
            "size_bytes": 0,
        },
        "validation_status": "EXPERIMENTAL / UNVALIDATED on Gray Cast Iron",
        "missing": [],
    }

    if not REPO_DIR.is_dir():
        info["error"] = "EG_Pore_Segmentation-main/ directory not found in project"
        info["missing"].append("repository_dir")
        return info

    model_path = REPO_DIR / "data" / "model.pth"
    if not model_path.is_file() or model_path.stat().st_size < 1000000:
        info["error"] = f"Pretrained model weights not found at {model_path}"
        info["missing"].append("model_weights")
        return info

    info["weights_path"] = str(model_path)
    info["weights_size_bytes"] = model_path.stat().st_size
    info["weights"] = {
        "available": True,
        "size_bytes": model_path.stat().st_size,
        "path": str(model_path),
    }

    py = _venv_python()
    if not py or not _venv_has_eg_deps(py):
        info["missing"].append("torch_or_smp_runtime")
        info["error"] = "Deep learning runtime with segmentation_models_pytorch not found"
        return info

    info["available"] = True
    info["runtime"] = py
    return info


_EG_RUNNER_SCRIPT = r'''
import sys
import json
from pathlib import Path
import cv2
import numpy as np
import torch
import matplotlib.pyplot as plt

repo_data = sys.argv[1]
model_path = sys.argv[2]
img_path = sys.argv[3]
mask_out_path = sys.argv[4]

sys.path.insert(0, repo_data)
import segmentation_models_pytorch as smp
import hist_consistency

img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
if img is None:
    print(json.dumps({"ok": False, "error": "Could not read input image"}))
    sys.exit(1)

H, W = img.shape
H_pad_width = (512 - H % 512) * bool(H % 512)
W_pad_width = (512 - W % 512) * bool(W % 512)
img_pad = np.pad(img, ((0, H_pad_width), (0, W_pad_width)), mode='constant', constant_values=255)
mask_pad = np.zeros_like(img_pad, dtype=np.uint8)

# Initialize model
device = 'cuda' if torch.cuda.is_available() else 'cpu'
model = smp.FPN(encoder_name='efficientnet-b4', activation='sigmoid', encoder_weights=None, encoder_depth=5, in_channels=1)
model.load_state_dict(torch.load(model_path, map_location=torch.device(device)))
model.to(device)
model.eval()

# Process 512x512 tiles exactly as implemented in presentation.py
n_h = (H + H_pad_width) // 512
n_w = (W + W_pad_width) // 512

for h_idx in range(n_h):
    for w_idx in range(n_w):
        tile = img_pad[h_idx * 512 : (h_idx + 1) * 512, w_idx * 512 : (w_idx + 1) * 512]
        # Normalize to [0, 1]. presentation.py feeds raw 0-255 uint8 values straight
        # into the network, which saturates the EfficientNet-B4 BatchNorm statistics
        # on bright 8-bit images (verified: sigmoid output collapses to 1.0 on
        # every pixel of the repository's own bright SEM samples, yielding an
        # empty segmentation). The pretrained backbone was trained on [0,1]
        # inputs, so scaling by 1/255 is required for correct inference.
        tile_tensor = np.expand_dims(tile, axis=0).astype("float32") / 255.0
        tile_tensor = torch.from_numpy(tile_tensor).to(device).unsqueeze(0)
        with torch.no_grad():
            if hasattr(model, 'predict'):
                pred = model.predict(tile_tensor)
            else:
                pred = model(tile_tensor)
            pred_mask = pred.squeeze().cpu().detach().numpy().round().astype('uint8')
        # Watershed postprocessing (postproc2 with sure_fg_threshold=0.41)
        post = hist_consistency.postproc2(pred_mask, sure_fg_threshold=0.41)
        mask_pad[h_idx * 512 : (h_idx + 1) * 512, w_idx * 512 : (w_idx + 1) * 512] = post

final_mask = mask_pad[:H, :W]

# Save postprocessed mask (0 = pore/flake, 1 = background)
cv2.imwrite(mask_out_path, final_mask)
print(json.dumps({
    "ok": True,
    "shape": list(final_mask.shape),
    "device": device,
}))
'''


def _run_eg_segmentation(gray_img: np.ndarray) -> np.ndarray:
    """Execute EG_Pore_Segmentation inference either in-process or via isolated runtime."""
    py = _venv_python()
    if not py:
        raise RuntimeError("EG Python runtime unavailable")

    repo_data = str(REPO_DIR / "data")
    model_path = str(REPO_DIR / "data" / "model.pth")

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        inp_path = td_path / "input.png"
        out_path = td_path / "mask.png"
        runner_path = td_path / "runner.py"

        cv2.imwrite(str(inp_path), gray_img)
        runner_path.write_text(_EG_RUNNER_SCRIPT, encoding="utf-8")

        proc = subprocess.run(
            [
                py,
                str(runner_path),
                repo_data,
                model_path,
                str(inp_path),
                str(out_path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"EG runner exited with code {proc.returncode}: {(proc.stderr or proc.stdout)[-400:]}"
            )

        mask = cv2.imread(str(out_path), cv2.IMREAD_UNCHANGED)
        if mask is None:
            raise RuntimeError("EG runner did not generate a mask")
        return mask.astype(np.uint8)


def compute_flake_measurements(
    raw_or_binary_mask: np.ndarray,
    calibration: Optional[float] = None,
    total_image_pixels: Optional[int] = None,
) -> Dict[str, Any]:
    """Extract morphological measurements from a graphite flake binary or raw mask."""
    if raw_or_binary_mask is None or raw_or_binary_mask.size == 0:
        return {
            "flake_count": 0,
            "total_flakes": 0,
            "total_graphite_area_px2": 0,
            "total_area_px2": 0,
            "graphite_area_fraction_pct": 0.0,
            "area_fraction_pct": 0.0,
            "mean_equiv_diameter_px": None,
            "mean_aspect_ratio": None,
            "mean_orientation_deg": None,
            "total_graphite_area_um2": None,
            "total_area_um2": None,
            "mean_flake_area_um2": None,
            "mean_area_um2": None,
            "mean_equiv_diameter_um": None,
            "mean_equivalent_diameter_um": None,
        }
    if total_image_pixels is None:
        total_image_pixels = raw_or_binary_mask.size

    if np.max(raw_or_binary_mask) == 1:
        binary = (raw_or_binary_mask == 0).astype(np.uint8)
    else:
        binary = (raw_or_binary_mask > 0).astype(np.uint8)

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    flake_count = max(0, num_labels - 1)

    if flake_count <= 0:
        return {
            "flake_count": 0,
            "total_flakes": 0,
            "total_graphite_area_px2": 0,
            "total_area_px2": 0,
            "graphite_area_fraction_pct": 0.0,
            "area_fraction_pct": 0.0,
            "mean_equiv_diameter_px": None,
            "mean_aspect_ratio": None,
            "mean_orientation_deg": None,
            "total_graphite_area_um2": None,
            "total_area_um2": None,
            "mean_flake_area_um2": None,
            "mean_area_um2": None,
            "mean_equiv_diameter_um": None,
            "mean_equivalent_diameter_um": None,
        }

    areas = stats[1:, cv2.CC_STAT_AREA]
    widths = stats[1:, cv2.CC_STAT_WIDTH]
    heights = stats[1:, cv2.CC_STAT_HEIGHT]

    total_graphite_area_px2 = int(np.sum(areas))
    area_fraction_pct = round((total_graphite_area_px2 / total_image_pixels) * 100.0, 3)

    mean_area_px = float(np.mean(areas))
    median_area_px = float(np.median(areas))
    std_area_px = float(np.std(areas))
    mean_equiv_diam_px = float(2.0 * np.sqrt(mean_area_px / np.pi))

    aspect_ratios = [
        max(float(w_i), float(h_i)) / max(1.0, min(float(w_i), float(h_i)))
        for w_i, h_i in zip(widths, heights)
    ]
    mean_aspect_ratio = round(float(np.mean(aspect_ratios)), 3)
    median_aspect_ratio = round(float(np.median(aspect_ratios)), 3)

    lengths = [max(float(w_i), float(h_i)) for w_i, h_i in zip(widths, heights)]
    thicknesses = [min(float(w_i), float(h_i)) for w_i, h_i in zip(widths, heights)]
    mean_length_px = round(float(np.mean(lengths)), 2)
    mean_width_px = round(float(np.mean(thicknesses)), 2)

    import math
    orientations = []
    for lbl in range(1, min(flake_count + 1, 500)):
        comp = (labels == lbl).astype(np.uint8)
        m = cv2.moments(comp)
        if abs(m["mu20"] - m["mu02"]) > 1e-4:
            theta = 0.5 * math.atan2(2 * m["mu11"], m["mu20"] - m["mu02"])
            orientations.append(math.degrees(theta) % 180)
    mean_orientation_deg = round(float(np.mean(orientations)), 1) if orientations else 0.0

    hist_counts, bin_edges = np.histogram(areas, bins=min(10, max(3, len(areas))))
    size_distribution = {
        "bins": [round(float(b), 1) for b in bin_edges],
        "counts": [int(c) for c in hist_counts],
        "bin_edges_px2": [round(float(b), 1) for b in bin_edges],
    }

    res: Dict[str, Any] = {
        "flake_count": flake_count,
        "total_flakes": flake_count,
        "total_graphite_area_px2": total_graphite_area_px2,
        "total_area_px2": total_graphite_area_px2,
        "graphite_area_fraction_pct": area_fraction_pct,
        "area_fraction_pct": area_fraction_pct,
        "mean_flake_area_px2": round(mean_area_px, 2),
        "mean_area_px2": round(mean_area_px, 2),
        "median_flake_area_px2": round(median_area_px, 2),
        "std_flake_area_px2": round(std_area_px, 2),
        "mean_equiv_diameter_px": round(mean_equiv_diam_px, 2),
        "mean_equivalent_diameter_px": round(mean_equiv_diam_px, 2),
        "mean_flake_length_px": mean_length_px,
        "mean_flake_width_px": mean_width_px,
        "mean_aspect_ratio": mean_aspect_ratio,
        "median_aspect_ratio": median_aspect_ratio,
        "mean_orientation_deg": mean_orientation_deg,
        "size_histogram_px2": size_distribution,
        "size_distribution_px2": size_distribution,
    }

    if isinstance(calibration, (int, float)) and calibration > 0:
        scale = float(calibration)
        scale2 = scale * scale
        res["total_graphite_area_um2"] = round(total_graphite_area_px2 * scale2, 2)
        res["total_area_um2"] = res["total_graphite_area_um2"]
        res["mean_flake_area_um2"] = round(mean_area_px * scale2, 2)
        res["mean_area_um2"] = res["mean_flake_area_um2"]
        res["median_flake_area_um2"] = round(median_area_px * scale2, 2)
        res["mean_flake_length_um"] = round(mean_length_px * scale, 3)
        res["mean_flake_width_um"] = round(mean_width_px * scale, 3)
        res["mean_equiv_diameter_um"] = round(mean_equiv_diam_px * scale, 3)
        res["mean_equivalent_diameter_um"] = res["mean_equiv_diameter_um"]
        res["microns_per_pixel"] = round(scale, 4)
    else:
        res["total_graphite_area_um2"] = None
        res["total_area_um2"] = None
        res["mean_flake_area_um2"] = None
        res["mean_area_um2"] = None
        res["mean_equiv_diameter_um"] = None
        res["mean_equivalent_diameter_um"] = None

    return res


def run_graphite_flake_analysis(
    image: np.ndarray,
    calibration: Optional[float] = None,
) -> Dict[str, Any]:
    """Run genuine EG_Pore_Segmentation graphite flake analysis on a micrograph.

    Args:
        image: HxW or HxWx3 BGR/RGB image array.
        calibration: spatial calibration in um per pixel (optional).

    Returns:
        Structured result dict with measurements, artifacts, warnings, and disclosures.
    """
    av = availability()
    if not av.get("available"):
        return {
            "status": "unavailable",
            "engine": ENGINE_ID,
            "engine_name": ENGINE_NAME,
            "error": av.get("error") or "EG dependencies or weights unavailable",
            "measurements": {},
            "images": {},
            "warnings": [
                "EG runtime or weights unavailable — verify model.pth in EG_Pore_Segmentation-main/data/."
            ],
            "validation_status": av.get("validation_status"),
        }

    # Validate image input
    if image is None or not isinstance(image, np.ndarray) or image.size == 0:
        return {
            "status": "failed",
            "engine": ENGINE_ID,
            "engine_name": ENGINE_NAME,
            "error": "Invalid or empty image array",
            "measurements": {},
            "images": {},
            "warnings": [],
        }

    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        rgb_disp = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    else:
        gray = image.copy()
        rgb_disp = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)

    h, w = gray.shape
    total_image_pixels = h * w

    # Run genuine segmentation
    try:
        raw_mask = _run_eg_segmentation(gray)
    except Exception as exc:
        return {
            "status": "failed",
            "engine": ENGINE_ID,
            "engine_name": ENGINE_NAME,
            "error": f"Graphite flake segmentation failed: {type(exc).__name__}: {str(exc)}",
            "measurements": {},
            "images": {},
            "warnings": [],
        }

    # In EG_Pore_Segmentation:
    # pixel = 0 corresponds to pore/flake (black)
    # pixel = 1 corresponds to background/pore wall (white)
    # Binary graphite mask: 255 for graphite flakes (raw_mask == 0), 0 for matrix
    flake_binary = (raw_mask == 0).astype(np.uint8) * 255

    # Connected components on graphite flakes
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        (raw_mask == 0).astype(np.uint8), connectivity=8
    )

    # Label 0 is background in OpenCV connected components
    flake_count = max(0, num_labels - 1)

    # Compute overlay: overlay graphite flakes with bright cyan. Built in RGB
    # order then converted to BGR, because the artifact is persisted with
    # cv2.imwrite (BGR) — writing the RGB array directly swaps the channels and
    # renders the cyan highlight yellow.
    overlay = rgb_disp.copy()
    overlay[raw_mask == 0] = [0, 255, 255]
    overlay = cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR)

    warnings: List[str] = [
        "Domain limitation: Model was trained on exfoliated graphite SEM cross-sections. Application to gray cast iron is experimental and unvalidated.",
        "Dimensionality limitation: Micrograph is two-dimensional. Graphite flake thickness in the 3rd dimension cannot be measured.",
        "Standard limitation: ISO 945-1 flake forms (Type A–E) cannot be certified without standardized ground truth validation.",
    ]

    if flake_count <= 0:
        warnings.append("No graphite flakes were detected in this micrograph.")
        return {
            "status": "completed",
            "engine": ENGINE_ID,
            "engine_name": ENGINE_NAME,
            "flake_count": 0,
            "measurements": {
                "flake_count": 0,
                "total_graphite_area_px2": 0,
                "graphite_area_fraction_pct": 0.0,
                "mean_flake_area_px2": None,
                "median_flake_area_px2": None,
                "std_flake_area_px2": None,
                "mean_equivalent_diameter_px": None,
                "mean_aspect_ratio": None,
            },
            "directly_measured_features": {
                "flake_count": 0,
                "total_area_px2": 0,
                "area_fraction_pct": 0.0,
            },
            "algorithm_predictions": {
                "architecture": "FPN (efficientnet-b4)",
                "watershed_postprocessing": True,
            },
            "experimental_interpretations": {
                "iso_945_1_flake_form": "UNVALIDATED",
                "disclaimer": "Standardized ISO 945-1 classifications cannot be made from uncalibrated exfoliated graphite models.",
            },
            "unavailable_measurements": [
                "iso_945_1_flake_form_classification",
                "three_dimensional_flake_thickness",
                "eutectic_cell_count",
            ],
            "images": {
                "flake_mask": flake_binary,
                "flake_overlay": overlay,
            },
            "warnings": warnings,
            "validation_status": "EXPERIMENTAL / UNVALIDATED on Gray Cast Iron",
        }

    measurements = compute_flake_measurements(
        raw_mask, calibration=calibration, total_image_pixels=total_image_pixels
    )
    flake_count = measurements["flake_count"]
    calibrated = measurements.get("total_graphite_area_um2") is not None
    if not calibrated:
        warnings.append(
            "Spatial calibration unavailable (length reported in pixels, area in px^2). "
            "Physical micrometer dimensions are not reported."
        )

    return {
        "status": "completed",
        "engine": ENGINE_ID,
        "engine_name": ENGINE_NAME,
        "calibrated": calibrated,
        "flake_count": flake_count,
        "measurements": measurements,
        "directly_measured_features": {
            "flake_count": flake_count,
            "total_area_px2": measurements["total_area_px2"],
            "area_fraction_pct": measurements["area_fraction_pct"],
            "mean_area_px2": measurements["mean_area_px2"],
            "mean_flake_length_px": measurements["mean_flake_length_px"],
            "mean_aspect_ratio": measurements["mean_aspect_ratio"],
        },
        "algorithm_predictions": {
            "architecture": "FPN (efficientnet-b4)",
            "encoder": "efficientnet-b4",
            "watershed_threshold": 0.41,
            "tiling": "512x512 with 255 constant padding",
        },
        "experimental_interpretations": {
            "target_material": "Gray Cast Iron (Experimental evaluation)",
            "iso_graphite_classification": "UNVALIDATED / NOT EVALUATED (Form I-VII standard classification not performed)",
            "flake_thickness_3d": "UNAVAILABLE from 2D section micrographs",
            "metallurgical_limitation_note": (
                "The deep neural network was trained on exfoliated graphite SEM micrographs. "
                "Segmented regions reflect lamellar graphite morphology, but ISO 945-1 / ASTM A247 "
                "flake distribution types (Type A through E) and graphite flake thickness cannot be "
                "certified without metallographic domain ground truth."
            ),
        },
        "unavailable_measurements": [
            "iso_945_1_flake_form_classification",
            "three_dimensional_flake_thickness",
            "eutectic_cell_count",
        ],
        "images": {
            "flake_mask": flake_binary,
            "flake_overlay": overlay,
        },
        "warnings": warnings,
        "validation_status": "EXPERIMENTAL / UNVALIDATED on Gray Cast Iron",
    }
