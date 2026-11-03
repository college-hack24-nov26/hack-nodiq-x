"""CARDE adapter — invokes the REAL Automated Carbide Detection repository code.

Source repository: ``carde-main/``
License: BSD-3-Clause (Till Korten, HZDR, t.korten@hzdr.de)
DOI: 10.5281/zenodo.17228177

What runs here, from the repository:
* Genuine classical segmentation: ``carde.image_processing.segment_otsu``
  (Discrete Gaussian denoise -> White Top-Hat background suppression ->
   Otsu threshold -> Binary fillhole -> ConnectedComponent -> RelabelComponent).
* Evaluation & morphology: Derived directly from the real labeled mask.

Pretrained model note:
Deep learning U-Net checkpoints were not bundled with the code repository
(must be acquired from Rodare at https://rodare.hzdr.de/record/4124). When deep
learning checkpoints are missing, the adapter accurately reports that status
and utilizes the genuine CARDE classical segmentation engine.

Target material metallurgical disclaimer:
CARDE was developed for scanning electron microscopy (SEM) of reactor pressure
vessel (RPV) steels. Application to white cast iron (ledeburite, eutectic/proeutectic
cementite) is EXPERIMENTAL AND UNVALIDATED. The adapter strictly reports directly
measured morphological features and never fabricates cementite stoichiometry or
ledeburite phase fractions.
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

from nodiq.core.config import REPO_ROOT, THIRD_PARTY_CARDE

ROOT = REPO_ROOT
REPO_DIR = THIRD_PARTY_CARDE
VENV_DIR = ROOT / ".venv-cast-iron"

ENGINE_ID = "carde"
ENGINE_NAME = "CARDE — Automated Carbide Detection (HZDR)"

_PYTHON_ENV = "NODIQ_CARDE_PYTHON"
_VENV_CARDE_CACHE: Dict[str, bool] = {}


def _venv_python() -> Optional[str]:
    """Interpreter hosting SimpleITK and CARDE dependencies."""
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
    # Check if current interpreter has SimpleITK
    if importlib.util.find_spec("SimpleITK") is not None:
        return sys.executable
    return None


def _venv_has_carde_deps(py: Optional[str]) -> bool:
    """Verify interpreter has SimpleITK, skimage, scipy, and numpy."""
    if not py:
        return False
    cached = _VENV_CARDE_CACHE.get(py)
    if cached is not None:
        return cached
    try:
        proc = subprocess.run(
            [
                py,
                "-c",
                "import importlib.util,sys; "
                "ok = bool(importlib.util.find_spec('SimpleITK') and "
                "importlib.util.find_spec('skimage') and "
                "importlib.util.find_spec('scipy') and "
                "importlib.util.find_spec('numpy')); "
                "sys.exit(0 if ok else 1)",
            ],
            timeout=30,
        )
        ok = proc.returncode == 0
    except Exception:
        ok = False
    _VENV_CARDE_CACHE[py] = ok
    return ok


def find_carde_repo() -> Optional[Path]:
    """Return local carde-main path if directory exists."""
    return REPO_DIR if REPO_DIR.is_dir() else None


def get_upstream_metadata() -> Dict[str, Any]:
    """Upstream licensing, copyright, and bibliographic metadata."""
    return {
        "name": "CARDE — Automated Carbide Detection",
        "license": "BSD-3-Clause",
        "attribution": "Till Korten (HZDR, t.korten@hzdr.de)",
        "doi": "10.5281/zenodo.17228177",
        "methods": ["classical_otsu", "unet"],
    }


def availability() -> Dict[str, Any]:
    """Honest availability and capability report for the CARDE engine."""
    info: Dict[str, Any] = {
        "available": False,
        "engine": ENGINE_ID,
        "engine_name": ENGINE_NAME,
        "license": "BSD-3-Clause",
        "author": "Till Korten (HZDR, t.korten@hzdr.de)",
        "citation": "Zenodo DOI: 10.5281/zenodo.17228177",
        "methods": ["classical_otsu", "unet"],
        "classical_method": "Gaussian Denoise + White Top-Hat Filter + Otsu Thresholding + Fillhole + Connected Components",
        "unet_weights_status": "Not pre-cached in repository; available from Rodare (https://rodare.hzdr.de/record/4124)",
        "weights": {
            "available": False,
            "note": "missing_checkpoint — U-Net weights must be acquired from Rodare",
        },
        "validation_status": "EXPERIMENTAL / UNVALIDATED on White Cast Iron",
        "missing": [],
    }

    if not REPO_DIR.is_dir():
        info["error"] = "carde-main/ directory not found in project"
        info["missing"].append("repository_dir")
        return info

    py = _venv_python()
    if not py or not _venv_has_carde_deps(py):
        info["missing"].append("SimpleITK_or_runtime")
        info["error"] = "SimpleITK runtime not found (configure .venv-cast-iron or NODIQ_CARDE_PYTHON)"
        return info

    info["available"] = True
    info["runtime"] = py
    return info


_CARDE_RUNNER_SCRIPT = r'''
import sys
import json
from pathlib import Path
import cv2
import numpy as np

repo_src = sys.argv[1]
img_path = sys.argv[2]
labels_out_path = sys.argv[3]
sigma = float(sys.argv[4])
radius = float(sys.argv[5])
minimum_size = int(sys.argv[6])

sys.path.insert(0, repo_src)
from carde.image_processing import segment_otsu

img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
if img is None:
    print(json.dumps({"ok": False, "error": "Could not read input image"}))
    sys.exit(1)

# Run genuine CARDE classical Otsu segmentation
labeled = segment_otsu(img, sigma=sigma, radius=radius, minimum_size=minimum_size)
labeled = np.asarray(labeled, dtype=np.int32)

# Save labeled mask
cv2.imwrite(labels_out_path, labeled.astype(np.uint16))
print(json.dumps({
    "ok": True,
    "max_label": int(labeled.max()),
    "shape": list(labeled.shape),
}))
'''


def _run_carde_segmentation(
    gray_img: np.ndarray,
    sigma: float = 1.0,
    radius: float = 30.0,
    minimum_size: int = 3,
) -> np.ndarray:
    """Execute CARDE segmentation either in-process or via the isolated runtime."""
    py = _venv_python()
    if not py:
        raise RuntimeError("CARDE Python runtime unavailable")

    repo_src = str(REPO_DIR / "src")

    # In-process execution if SimpleITK is directly available
    if py == sys.executable:
        if repo_src not in sys.path:
            sys.path.insert(0, repo_src)
        from carde.image_processing import segment_otsu
        labeled = segment_otsu(gray_img, sigma=sigma, radius=radius, minimum_size=minimum_size)
        return np.asarray(labeled, dtype=np.int32)

    # Isolated runtime execution via subprocess
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        inp_path = td_path / "input.png"
        out_path = td_path / "labels.png"
        runner_path = td_path / "runner.py"

        cv2.imwrite(str(inp_path), gray_img)
        runner_path.write_text(_CARDE_RUNNER_SCRIPT, encoding="utf-8")

        proc = subprocess.run(
            [
                py,
                str(runner_path),
                repo_src,
                str(inp_path),
                str(out_path),
                str(sigma),
                str(radius),
                str(minimum_size),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"CARDE runner exited with code {proc.returncode}: {(proc.stderr or proc.stdout)[-400:]}"
            )

        labels = cv2.imread(str(out_path), cv2.IMREAD_UNCHANGED)
        if labels is None:
            raise RuntimeError("CARDE runner did not generate a label map")
        return labels.astype(np.int32)


def run_carde_carbide_analysis(
    image: np.ndarray,
    calibration: Optional[float] = None,
    sigma: float = 1.0,
    radius: float = 30.0,
    minimum_size: int = 3,
) -> Dict[str, Any]:
    """Run genuine CARDE carbide analysis on a micrograph.

    Args:
        image: HxW or HxWx3 BGR/RGB image array.
        calibration: spatial calibration in um per pixel (optional).
        sigma: Gaussian smoothing variance.
        radius: Top-hat background suppression radius.
        minimum_size: Minimum pixel area to retain.

    Returns:
        Structured result dict with measurements, artifacts, warnings, and disclosures.
    """
    av = availability()
    if not av.get("available"):
        return {
            "status": "unavailable",
            "engine": ENGINE_ID,
            "engine_name": ENGINE_NAME,
            "error": av.get("error") or "CARDE dependencies unavailable",
            "measurements": {},
            "images": {},
            "warnings": [
                "CARDE runtime not available — install SimpleITK in the isolated runtime environment."
            ],
            "validation_status": av.get("validation_status"),
        }

    # Validate image dimensions and channels
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
        labeled = _run_carde_segmentation(
            gray, sigma=sigma, radius=radius, minimum_size=minimum_size
        )
    except Exception as exc:
        return {
            "status": "failed",
            "engine": ENGINE_ID,
            "engine_name": ENGINE_NAME,
            "error": f"CARDE segmentation failed: {type(exc).__name__}: {str(exc)}",
            "measurements": {},
            "images": {},
            "warnings": [],
        }

    max_label = int(labeled.max())
    binary_mask = (labeled > 0).astype(np.uint8) * 255

    # Compute overlay: CARDE combines segmentation with yellow overlay (RGB [255, 255, 0])
    overlay = rgb_disp.copy()
    overlay[labeled > 0] = [255, 255, 0]

    warnings: List[str] = [
        "Domain limitation: CARDE was developed for RPV steel SEM micrographs. Application to white cast iron is experimental and unvalidated.",
        "Microstructural note: Segmented high-contrast particles are detected image features, not phase-stoichiometric verifications of cementite (Fe3C).",
    ]

    if max_label <= 0:
        warnings.append("No carbide regions were detected in this micrograph using the selected segmentation parameters.")
        return {
            "status": "completed",
            "engine": ENGINE_ID,
            "engine_name": ENGINE_NAME,
            "carbide_count": 0,
            "measurements": {
                "carbide_count": 0,
                "total_carbide_area_px2": 0,
                "carbide_area_fraction_pct": 0.0,
                "mean_carbide_area_px2": None,
                "median_carbide_area_px2": None,
                "std_carbide_area_px2": None,
                "mean_equivalent_diameter_px": None,
            },
            "directly_measured_features": {
                "detected_regions": 0,
                "area_fraction_pct": 0.0,
            },
            "algorithm_predictions": {
                "algorithm": "CARDE segment_otsu",
                "otsu_thresholding_applied": True,
            },
            "experimental_interpretations": {
                "ledeburite_eutectic_identified": False,
                "cementite_stoichiometry_verified": False,
                "disclaimer": "Ledeburite identification and phase identification cannot be determined from binary segmentation alone.",
            },
            "unavailable_measurements": [
                "ledeburite_phase_fraction",
                "cementite_stoichiometry",
                "three_dimensional_carbide_thickness",
            ],
            "images": {
                "carde_mask": binary_mask,
                "carde_overlay": overlay,
            },
            "warnings": warnings,
            "validation_status": "EXPERIMENTAL / UNVALIDATED on White Cast Iron",
        }

    measurements = compute_carbide_measurements(
        labeled, calibration=calibration, total_image_pixels=total_image_pixels
    )
    calibrated = measurements.get("total_carbide_area_um2") is not None
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
        "carbide_count": max_label,
        "measurements": measurements,
        "directly_measured_features": {
            "region_count": max_label,
            "total_area_px2": measurements["total_area_px2"],
            "area_fraction_pct": measurements["area_fraction_pct"],
            "mean_area_px2": measurements["mean_area_px2"],
            "mean_equivalent_diameter_px": measurements["mean_equiv_diameter_px"],
        },
        "algorithm_predictions": {
            "algorithm": "CARDE segment_otsu",
            "otsu_sigma": sigma,
            "tophat_radius": radius,
            "minimum_size": minimum_size,
        },
        "experimental_interpretations": {
            "target_material": "White Cast Iron (Experimental evaluation)",
            "cementite_identification": "UNVALIDATED / NOT IDENTIFIED",
            "ledeburite_presence": "UNVALIDATED / NOT IDENTIFIED",
            "metallurgical_limitation_note": (
                "CARDE was trained on RPV steel SEM micrographs. The segmented particles "
                "represent high-contrast optical/electron features. Stoichiometric identification "
                "of cementite (Fe3C) versus alloy carbides and ledeburite eutectic quantification "
                "require dedicated microstructural standard validation and cannot be inferred "
                "from Otsu thresholding alone."
            ),
        },
        "unavailable_measurements": [
            "ledeburite_phase_fraction",
            "cementite_stoichiometry",
            "three_dimensional_carbide_thickness",
        ],
        "images": {
            "carde_mask": binary_mask,
            "carde_overlay": overlay,
        },
        "warnings": warnings,
        "validation_status": "EXPERIMENTAL / UNVALIDATED on White Cast Iron",
    }


def compute_carbide_measurements(
    labeled_or_mask: np.ndarray,
    calibration: Optional[float] = None,
    total_image_pixels: Optional[int] = None,
) -> Dict[str, Any]:
    """Calculate morphological measurements from a CARDE labeled or binary mask."""
    if labeled_or_mask is None or labeled_or_mask.size == 0:
        return {
            "total_regions": 0,
            "carbide_count": 0,
            "total_area_px2": 0,
            "total_carbide_area_px2": 0,
            "area_fraction_pct": 0.0,
            "carbide_area_fraction_pct": 0.0,
            "mean_equiv_diameter_px": None,
            "mean_solidity": None,
            "total_area_um2": None,
            "total_carbide_area_um2": None,
            "mean_area_um2": None,
            "mean_carbide_area_um2": None,
            "mean_equiv_diameter_um": None,
            "mean_equivalent_diameter_um": None,
        }
    if total_image_pixels is None:
        total_image_pixels = labeled_or_mask.size

    if labeled_or_mask.dtype == bool or np.max(labeled_or_mask) == 255:
        num_labels, labeled, stats, centroids = cv2.connectedComponentsWithStats(
            (labeled_or_mask > 0).astype(np.uint8), connectivity=8
        )
        max_label = num_labels - 1
        areas = stats[1:, cv2.CC_STAT_AREA] if max_label > 0 else np.array([])
    else:
        labeled = labeled_or_mask
        max_label = int(labeled.max())
        areas = np.bincount(labeled.ravel())[1:] if max_label > 0 else np.array([])

    if max_label <= 0 or len(areas) == 0:
        return {
            "total_regions": 0,
            "carbide_count": 0,
            "total_area_px2": 0,
            "total_carbide_area_px2": 0,
            "area_fraction_pct": 0.0,
            "carbide_area_fraction_pct": 0.0,
            "mean_equiv_diameter_px": None,
            "mean_solidity": None,
            "total_area_um2": None,
            "total_carbide_area_um2": None,
            "mean_area_um2": None,
            "mean_carbide_area_um2": None,
            "mean_equiv_diameter_um": None,
            "mean_equivalent_diameter_um": None,
        }

    total_carbide_area_px2 = int(np.sum(areas))
    area_fraction_pct = round((total_carbide_area_px2 / total_image_pixels) * 100.0, 3)
    mean_area_px = float(np.mean(areas))
    median_area_px = float(np.median(areas))
    std_area_px = float(np.std(areas))
    mean_equiv_diam_px = float(2.0 * np.sqrt(mean_area_px / np.pi))

    solidity_list = []
    aspect_ratios = []
    for lbl in range(1, min(max_label + 1, 500)):
        component = (labeled == lbl).astype(np.uint8)
        cnts, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            cnt = cnts[0]
            x, y, w_box, h_box = cv2.boundingRect(cnt)
            aspect_ratio = float(w_box) / max(1, float(h_box))
            aspect_ratios.append(aspect_ratio)
            hull = cv2.convexHull(cnt)
            hull_area = cv2.contourArea(hull)
            if hull_area > 0:
                solidity_list.append(float(areas[lbl - 1]) / hull_area)

    mean_aspect_ratio = round(float(np.mean(aspect_ratios)), 3) if aspect_ratios else None
    mean_solidity = round(float(np.mean(solidity_list)), 3) if solidity_list else None

    hist_counts, bin_edges = np.histogram(areas, bins=min(10, max(3, len(areas))))
    size_distribution = {
        "bins": [round(float(b), 1) for b in bin_edges],
        "counts": [int(c) for c in hist_counts],
        "bin_edges_px2": [round(float(b), 1) for b in bin_edges],
    }

    res: Dict[str, Any] = {
        "total_regions": max_label,
        "carbide_count": max_label,
        "total_area_px2": total_carbide_area_px2,
        "total_carbide_area_px2": total_carbide_area_px2,
        "area_fraction_pct": area_fraction_pct,
        "carbide_area_fraction_pct": area_fraction_pct,
        "mean_carbide_area_px2": round(mean_area_px, 2),
        "mean_area_px2": round(mean_area_px, 2),
        "median_carbide_area_px2": round(median_area_px, 2),
        "std_carbide_area_px2": round(std_area_px, 2),
        "mean_equiv_diameter_px": round(mean_equiv_diam_px, 2),
        "mean_equivalent_diameter_px": round(mean_equiv_diam_px, 2),
        "mean_aspect_ratio": mean_aspect_ratio,
        "mean_solidity": mean_solidity,
        "size_histogram_px2": size_distribution,
        "size_distribution_px2": size_distribution,
    }

    if isinstance(calibration, (int, float)) and calibration > 0:
        scale = float(calibration)
        scale2 = scale * scale
        res["total_area_um2"] = round(total_carbide_area_px2 * scale2, 2)
        res["total_carbide_area_um2"] = res["total_area_um2"]
        res["mean_area_um2"] = round(mean_area_px * scale2, 2)
        res["mean_carbide_area_um2"] = res["mean_area_um2"]
        res["median_carbide_area_um2"] = round(median_area_px * scale2, 2)
        res["mean_equiv_diameter_um"] = round(mean_equiv_diam_px * scale, 3)
        res["mean_equivalent_diameter_um"] = res["mean_equiv_diameter_um"]
        res["microns_per_pixel"] = round(scale, 4)
    else:
        res["total_area_um2"] = None
        res["total_carbide_area_um2"] = None
        res["mean_area_um2"] = None
        res["mean_carbide_area_um2"] = None
        res["mean_equiv_diameter_um"] = None
        res["mean_equivalent_diameter_um"] = None

    return res
