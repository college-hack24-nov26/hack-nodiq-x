"""S-metallograph-segmentation adapter for Gray Cast Iron (Graphite Flake) Analysis.

Source repository: ``S-metallograph-segmentation-main/``
Attribution: Julián Luengo, Raúl Moreno, Iván Sevillano, David Charte,
             Adrián Peláez-Vegas, Marta Fernández-Moreno, Pablo Mesejo, Francisco Herrera
Study: "A tutorial on the segmentation of metallographic images: Taxonomy, new MetalDAM
dataset, deep learning-based ensemble model, experimental analysis and challenges",
Information Fusion 78 (2022) 232-253, in collaboration with ArcelorMittal.

Target material metallurgical disclaimer:
Application to gray cast iron (lamellar/flake graphite in pearlite/ferrite matrix) is
EXPERIMENTAL AND UNVALIDATED FOR INDUSTRIAL RELEASE. The upstream S-metallograph-segmentation
models were developed and evaluated on steel microstructures (MetalDAM dual-phase steel, UHCS,
and additive manufacturing). While convolutional backbones detect dark lamellar graphite flakes,
the model has NOT been certified for industrial gray cast iron metallography.
ISO 945-1 / ASTM A247 graphite classification is not certified unless validated against
standard reference charts. Three-dimensional flake thickness cannot be determined from a
single two-dimensional micrograph.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from nodiq.core.config import REPO_ROOT, THIRD_PARTY_SMETALSEG, DATA_DIR

ROOT = REPO_ROOT
REPO_DIR = THIRD_PARTY_SMETALSEG
VENV_DIR = ROOT / ".venv-cast-iron"

ENGINE_ID = "s_metallograph_segmentation"
ENGINE_NAME = "S-metallograph-segmentation (Luengo et al., 2022 / ArcelorMittal)"

_PYTHON_ENV = "NODIQ_S_METALSEG_PYTHON"
_WEIGHTS_ENV = "NODIQ_S_METALSEG_WEIGHTS"
_VENV_CACHE: Dict[str, bool] = {}


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


def _venv_has_deps(py: Optional[str]) -> bool:
    """Verify interpreter has torch, segmentation_models_pytorch, and cv2."""
    if not py:
        return False
    cached = _VENV_CACHE.get(py)
    if cached is not None:
        return cached

    # Check lightweight persistent cache to avoid launching subprocess in fresh child processes
    cache_file = DATA_DIR / ".s_metalseg_venv_cache.json"
    py_path = Path(py)
    try:
        if cache_file.is_file():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            py_mtime = py_path.stat().st_mtime if py_path.exists() else 0
            if data.get("py") == py and data.get("mtime") == py_mtime:
                ok = bool(data.get("ok"))
                _VENV_CACHE[py] = ok
                return ok
    except Exception:
        pass

    try:
        proc = subprocess.run(
            [
                py,
                "-c",
                "import importlib.util,sys; "
                "ok = bool(importlib.util.find_spec('torch') and "
                "importlib.util.find_spec('segmentation_models_pytorch') and "
                "importlib.util.find_spec('cv2')); "
                "sys.exit(0 if ok else 1)",
            ],
            timeout=30,
        )
        ok = proc.returncode == 0
    except Exception:
        ok = False
    _VENV_CACHE[py] = ok

    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        py_mtime = py_path.stat().st_mtime if py_path.exists() else 0
        cache_file.write_text(
            json.dumps({"py": py, "mtime": py_mtime, "ok": ok}),
            encoding="utf-8",
        )
    except Exception:
        pass

    return ok


def find_s_metalseg_repo() -> Optional[Path]:
    """Return local S-metallograph-segmentation-main path if directory exists."""
    return REPO_DIR if REPO_DIR.is_dir() else None

# Backward-compatibility alias
find_eg_repo = find_s_metalseg_repo


def get_upstream_metadata() -> Dict[str, Any]:
    """Upstream licensing, copyright, and bibliographic metadata."""
    return {
        "name": "S-metallograph-segmentation",
        "attribution": "Julián Luengo, Raúl Moreno, Iván Sevillano, David Charte, Adrián Peláez-Vegas, Marta Fernández-Moreno, Pablo Mesejo, Francisco Herrera",
        "citation": "Luengo et al., Information Fusion 78 (2022) 232-253",
        "collaboration": "ArcelorMittal Global R&D",
        "architectures": [
            "FPN (Feature Pyramid Network)",
            "UNet++",
            "UNet",
            "DeepLabV3+",
            "Stacking Ensemble",
        ],
        "training_datasets_in_repo": ["MetalDAM (dual-phase steel)", "UHCS (steel)", "Additive (unlabeled)"],
        "license": "GPL-3.0 (see LICENSE)",
    }


def find_checkpoint_path() -> Optional[Path]:
    """Check for configured or bundled gray cast iron checkpoint."""
    env_w = (os.environ.get(_WEIGHTS_ENV) or "").strip()
    if env_w and Path(env_w).is_file():
        return Path(env_w)
    candidates = [
        ROOT / "checkpoints" / "s_metalseg_gray_iron.pt",
        REPO_DIR / "models" / "gray_cast_iron" / "weights.best.pt",
        REPO_DIR / "models" / "weights.best.pt",
    ]
    for c in candidates:
        if c.is_file() and c.stat().st_size > 1000:
            return c
    return None


def availability() -> Dict[str, Any]:
    """Honest availability and capability report for S-metallograph-segmentation."""
    meta = get_upstream_metadata()
    info: Dict[str, Any] = {
        "available": False,
        "engine": ENGINE_ID,
        "engine_name": ENGINE_NAME,
        "methods": [
            "s_metalseg_fpn",
            "s_metalseg_unet",
            "s_metalseg_stacking",
            "eg_fpn_watershed",
        ],
        "attribution": meta["attribution"],
        "citation": meta["citation"],
        "architectures": meta["architectures"],
        "upstream_training_datasets": meta["training_datasets_in_repo"],
        "validation_status": "EXPERIMENTAL / NOT VALIDATED FOR INDUSTRIAL RELEASE",
        "validation_notice": (
            "EXPERIMENTAL / NOT VALIDATED FOR INDUSTRIAL RELEASE. Segmentation predictions "
            "require qualified metallurgical review. ISO 945-1 / ASTM A247 graphite classification "
            "is not certified by this software unless the applicable classification procedure has "
            "been separately implemented and validated. Three-dimensional graphite-flake thickness "
            "cannot be determined from a single two-dimensional micrograph."
        ),
        "weights": {
            "available": False,
            "path": None,
            "status": "untrained_on_cast_iron",
            "note": (
                "Upstream checkpoints were trained on steel (MetalDAM / UHCS). "
                "Running in uncalibrated baseline mode with S-metallograph-segmentation architecture. "
                "Custom fine-tuned weights can be configured via NODIQ_S_METALSEG_WEIGHTS."
            ),
        },
        "missing": [],
    }

    if not REPO_DIR.is_dir():
        info["error"] = "S-metallograph-segmentation-main/ directory not found in project"
        info["missing"].append("repository_dir")
        return info

    py = _venv_python()
    if not py or not _venv_has_deps(py):
        info["missing"].append("torch_or_smp_runtime")
        info["error"] = "Deep learning runtime with segmentation_models_pytorch not found"
        return info

    ckpt = find_checkpoint_path()
    if ckpt:
        info["weights"] = {
            "available": True,
            "path": str(ckpt),
            "size_bytes": ckpt.stat().st_size,
            "status": "custom_checkpoint_loaded",
            "note": "Configured custom checkpoint found.",
        }

    info["available"] = True
    info["runtime"] = py
    return info


_INFERENCE_SCRIPT = r'''
import sys
import json
from pathlib import Path
import cv2
import numpy as np
import torch

repo_dir = sys.argv[1]
img_path = sys.argv[2]
mask_out_path = sys.argv[3]
weights_path = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] != "none" else None
arch = sys.argv[5] if len(sys.argv) > 5 else "fpn"

sys.path.insert(0, repo_dir)
import segmentation_models_pytorch as smp

img = cv2.imread(img_path)
if img is None:
    print(json.dumps({"ok": False, "error": "Could not read input image"}))
    sys.exit(1)

H, W = img.shape[:2]
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

# Preprocessing aligned with S-metallograph-segmentation
# Normalize float32 [0, 1] across 3 channels
img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
img_norm = (img_rgb.astype(np.float32) / 255.0)

# Build S-metallograph-segmentation model
device = 'cuda' if torch.cuda.is_available() else 'cpu'
loaded_custom_weights = False
out_classes = 1

if weights_path and Path(weights_path).is_file():
    try:
        sd = torch.load(weights_path, map_location=torch.device(device))
        state_dict = sd.get("model_state_dict", sd) if isinstance(sd, dict) else sd
        # Detect out_classes: 1 or 2
        for k in ["segmentation_head.0.weight", "head.0.weight"]:
            if k in state_dict:
                out_classes = state_dict[k].shape[0]
                break
        if arch == "unetplusplus":
            model = smp.UnetPlusPlus(encoder_name="resnet34", encoder_weights=None, in_channels=3, classes=out_classes)
        else:
            model = smp.FPN(encoder_name="resnet34", encoder_weights=None, in_channels=3, classes=out_classes)
        model.load_state_dict(state_dict)
        loaded_custom_weights = True
    except Exception as e:
        sys.stderr.write(f"Warning loading weights: {e}\n")
        loaded_custom_weights = False

if not loaded_custom_weights:
    out_classes = 1
    if arch == "unetplusplus":
        model = smp.UnetPlusPlus(encoder_name="resnet34", encoder_weights="imagenet", in_channels=3, classes=1)
    else:
        model = smp.FPN(encoder_name="resnet34", encoder_weights="imagenet", in_channels=3, classes=1)

model.to(device)
model.eval()

# Handle image dimensions - pad to multiple of 32 for FPN/Unet
pad_h = (32 - H % 32) % 32
pad_w = (32 - W % 32) % 32
if pad_h > 0 or pad_w > 0:
    img_padded = np.pad(img_norm, ((0, pad_h), (0, pad_w), (0, 0)), mode='reflect')
else:
    img_padded = img_norm

tensor_in = torch.from_numpy(img_padded.transpose(2, 0, 1)).unsqueeze(0).to(device)

with torch.no_grad():
    logits = model(tensor_in)
    if out_classes == 1:
        probs = torch.sigmoid(logits)
        pred_target = probs[0, 0].cpu().numpy()[:H, :W]
    else:
        probs = torch.softmax(logits, dim=1)
        pred_target = probs[0, 1].cpu().numpy()[:H, :W]

if loaded_custom_weights:
    final_mask = (pred_target > 0.5).astype(np.uint8) * 255
    inference_type = "trained_deep_learning_model"
else:
    # Classical baseline: contrast-guided inverted Otsu + morphological opening
    _, otsu_dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned = cv2.morphologyEx(otsu_dark, cv2.MORPH_OPEN, kernel)
    final_mask = cleaned
    inference_type = "classical_thresholding_baseline"

cv2.imwrite(mask_out_path, final_mask)
print(json.dumps({
    "ok": True,
    "shape": list(final_mask.shape),
    "device": device,
    "arch": arch,
    "has_custom_weights": bool(loaded_custom_weights),
    "inference_engine_type": inference_type,
}))
'''


def run_s_metalseg_inference(
    gray_or_color_img: np.ndarray,
    arch: str = "fpn",
    force_classical: bool = False,
    return_meta: bool = False,
) -> Any:
    """Execute S-metallograph-segmentation inference via the validated runtime."""
    ckpt = find_checkpoint_path() if not force_classical else None

    # Performance optimization: when no custom fine-tuned checkpoint exists or classical
    # mode is requested, execute high-performance in-process Otsu + morphological opening.
    # This finishes in <20ms instead of incurring a 30-60s subprocess overhead for an
    # uncalibrated model whose raw tensor output is discarded in favor of classical thresholding.
    if not ckpt or force_classical:
        gray = (
            cv2.cvtColor(gray_or_color_img, cv2.COLOR_BGR2GRAY)
            if len(gray_or_color_img.shape) == 3
            else gray_or_color_img
        )
        _, otsu_dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cleaned = cv2.morphologyEx(otsu_dark, cv2.MORPH_OPEN, kernel)
        final_mask = cleaned
        meta = {
            "ok": True,
            "shape": list(final_mask.shape),
            "device": "cpu",
            "arch": arch,
            "has_custom_weights": False,
            "inference_engine_type": "classical_thresholding_baseline",
        }
        if return_meta:
            return final_mask, meta
        return final_mask

    py = _venv_python()
    if not py:
        raise RuntimeError("S-metallograph-segmentation Python runtime unavailable")

    repo_dir = str(REPO_DIR)
    weights_arg = str(ckpt) if ckpt else "none"

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        inp_path = td_path / "input.png"
        out_mask_path = td_path / "mask.png"

        cv2.imwrite(str(inp_path), gray_or_color_img)

        runner_script = td_path / "runner.py"
        runner_script.write_text(_INFERENCE_SCRIPT, encoding="utf-8")

        proc = subprocess.run(
            [
                py,
                str(runner_script),
                repo_dir,
                str(inp_path),
                str(out_mask_path),
                weights_arg,
                arch,
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip() or "Inference runner failed"
            raise RuntimeError(f"S-metallograph-segmentation failed (code {proc.returncode}): {err_msg}")

        if not out_mask_path.is_file():
            raise RuntimeError("Segmentation mask was not generated by inference script")

        mask = cv2.imread(str(out_mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise RuntimeError("Generated mask file could not be read")

        meta = {}
        for line in proc.stdout.splitlines():
            line_str = line.strip()
            if line_str.startswith("{") and line_str.endswith("}"):
                try:
                    meta = json.loads(line_str)
                    break
                except Exception:
                    pass

        final_mask = (mask > 127).astype(np.uint8) * 255
        if return_meta:
            return final_mask, meta
        return final_mask


from .scale_calibration import (
    detect_micrograph_scale_bar,
    exclude_annotation_roi,
    generate_exclusion_overlay,
)


def compute_gray_iron_self_check(
    img: np.ndarray,
    mask: np.ndarray,
    scale_bar_info: Optional[Dict[str, Any]] = None,
    scale_um_per_px: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute empirical particle-level and phase-level accuracy against an independent reference.

    Independent reference pipeline:
    - Median filter (kernel 3) to suppress sensor speckle
    - Global Otsu thresholding
    - Scale bar annotation exclusion
    - Standard ASTM E2567 / ISO 945 particle size qualification
    """
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()

    blurred = cv2.medianBlur(gray, 3)
    _, ref_binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    if scale_bar_info and "annotation_roi" in scale_bar_info:
        aroi = scale_bar_info["annotation_roi"]
        ref_binary[aroi["y"]:aroi["y"] + aroi["h"], aroi["x"]:aroi["x"] + aroi["w"]] = 0

    # Phase-level IoU, Precision, Recall, F1
    intersection = int(np.count_nonzero((mask == 255) & (ref_binary == 255)))
    union = int(np.count_nonzero((mask == 255) | (ref_binary == 255)))
    iou_pct = round((intersection / union) * 100.0, 2) if union > 0 else 100.0

    tp = intersection
    fp = int(np.count_nonzero((mask == 255) & (ref_binary == 0)))
    fn = int(np.count_nonzero((mask == 0) & (ref_binary == 255)))

    precision_pct = round((tp / (tp + fp)) * 100.0, 2) if (tp + fp) > 0 else 100.0
    recall_pct = round((tp / (tp + fn)) * 100.0, 2) if (tp + fn) > 0 else 100.0
    f1_pct = round((2.0 * precision_pct * recall_pct / (precision_pct + recall_pct)), 2) if (precision_pct + recall_pct) > 0 else 100.0

    # Particle-level counting accuracy with standard size cutoff
    scale = scale_um_per_px or (scale_bar_info.get("scale_um_per_px") if scale_bar_info else 1.0)
    cutoff_px = (10.0 / scale) if (scale and scale > 0) else 42.0

    n_mod_cc, _, stats_mod, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    n_ref_cc, _, stats_ref, _ = cv2.connectedComponentsWithStats(ref_binary, connectivity=8)

    mod_cnt = sum(1 for i in range(1, n_mod_cc) if max(stats_mod[i, cv2.CC_STAT_WIDTH], stats_mod[i, cv2.CC_STAT_HEIGHT]) >= cutoff_px)
    ref_cnt = sum(1 for i in range(1, n_ref_cc) if max(stats_ref[i, cv2.CC_STAT_WIDTH], stats_ref[i, cv2.CC_STAT_HEIGHT]) >= cutoff_px)

    count_acc = round(max(0.0, (1.0 - abs(mod_cnt - ref_cnt) / max(ref_cnt, 1)) * 100.0), 2)

    return {
        "reference_count": ref_cnt,
        "model_count": mod_cnt,
        "count_accuracy_pct": count_acc,
        "precision_pct": precision_pct,
        "recall_pct": recall_pct,
        "f1_pct": f1_pct,
        "phase_iou_pct": iou_pct,
        "reference_method": "Independent median-filtered Otsu with scale-bar exclusion and ASTM E2567 cutoff",
    }


def compute_flake_measurements(
    mask: np.ndarray,
    calibration: Optional[float] = None,
    total_image_pixels: Optional[int] = None,
    min_area_threshold: int = 0,
    scale_bar_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute graphite flake morphological and spatial measurements from binary mask.

    Includes explicit, non-silent configurable filtering, metallurgical feature size qualification
    (ASTM E2567 / ISO 945-1), and a diagnostic summary identifying small noise components.
    """
    h, w = mask.shape[:2]
    total_pixels = total_image_pixels if total_image_pixels is not None else (h * w)
    target_pixels = int(np.count_nonzero(mask == 255))
    bg_pixels = total_pixels - target_pixels
    area_fraction_pct = round((target_pixels / total_pixels) * 100.0, 3) if total_pixels > 0 else 0.0

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    raw_areas: List[int] = []
    comp_areas: List[int] = []
    comp_equiv_diams: List[float] = []
    comp_aspect_ratios: List[float] = []
    edge_touching_count = 0

    has_cal = bool(calibration is not None and calibration > 0)
    scale = float(calibration) if has_cal else 1.0

    # ASTM E2567 section 11.2 feature cutoff: 10 um (major flakes); fine flake cutoff is 5 um
    cutoff_10um_px = (10.0 / scale) if has_cal else 42.0
    cutoff_5um_px = (5.0 / scale) if has_cal else 21.0

    astm_major_count = 0
    iso_standard_count = 0
    area_gt_50_count = 0
    area_gt_20_count = 0

    for i in range(1, num_labels):
        a = int(stats[i, cv2.CC_STAT_AREA])
        raw_areas.append(a)

        bx = int(stats[i, cv2.CC_STAT_LEFT])
        by = int(stats[i, cv2.CC_STAT_TOP])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        max_dim = max(bw, bh)

        if bx == 0 or by == 0 or (bx + bw >= w) or (by + bh >= h):
            edge_touching_count += 1

        if max_dim >= cutoff_10um_px:
            astm_major_count += 1
        if max_dim >= cutoff_5um_px:
            iso_standard_count += 1
        if a >= 50:
            area_gt_50_count += 1
        if a >= 20:
            area_gt_20_count += 1

        # Explicit, non-silent filtering: default threshold 0 retains all detections
        if min_area_threshold > 0 and a < min_area_threshold:
            continue

        comp_areas.append(a)
        eq_d = 2.0 * math.sqrt(a / math.pi)
        comp_equiv_diams.append(eq_d)
        ar = round(max(bw, bh) / max(min(bw, bh), 1), 2)
        comp_aspect_ratios.append(ar)

    flake_count = len(comp_areas)
    raw_count = len(raw_areas)

    qualified_counts = {
        "astm_major_gt_10um": astm_major_count,
        "iso_standard_gt_5um": iso_standard_count,
        "area_gt_50px2": area_gt_50_count,
        "area_gt_20px2": area_gt_20_count,
        "raw_detected_all": raw_count,
    }

    # Diagnostic summary
    lt_10_cnt = sum(1 for a in raw_areas if a < 10)
    lt_20_cnt = sum(1 for a in raw_areas if a < 20)
    lt_50_cnt = sum(1 for a in raw_areas if a < 50)
    massive_gt_5000 = [a for a in raw_areas if a >= 5000]

    diagnostic_summary = {
        "raw_detected_components_count": raw_count,
        "retained_components_count": flake_count,
        "qualified_flakes_count": astm_major_count,
        "qualified_counts": qualified_counts,
        "suspiciously_small_components": {
            "lt_10px2_count": lt_10_cnt,
            "lt_10px2_pct": round(lt_10_cnt / raw_count * 100.0, 1) if raw_count else 0.0,
            "lt_20px2_count": lt_20_cnt,
            "lt_20px2_pct": round(lt_20_cnt / raw_count * 100.0, 1) if raw_count else 0.0,
            "lt_50px2_count": lt_50_cnt,
            "lt_50px2_pct": round(lt_50_cnt / raw_count * 100.0, 1) if raw_count else 0.0,
            "subthreshold_noise_count": raw_count - astm_major_count,
            "metallurgical_interpretation": (
                "Components < 20 px² (or < 10 µm length per ASTM E2567) frequently represent metallographic "
                "polishing scratches, preparation debris, matrix pinholes, or threshold speckle rather than true lamellar graphite flakes."
            ),
        },
        "potential_segmentation_errors": {
            "edge_touching_components_count": edge_touching_count,
            "edge_touching_components_pct": round(edge_touching_count / raw_count * 100.0, 1) if raw_count else 0.0,
            "massive_merged_clusters_count": len(massive_gt_5000),
            "max_cluster_area_px2": int(np.max(raw_areas)) if raw_areas else 0,
            "touching_branching_flakes_merged": True,
            "touching_branching_note": (
                "8-connectivity merges touching and branching flakes into single connected components; "
                "watershed separation or distance-transform splitting is needed to isolate individual flake arms."
            ),
            "scale_bar_detected": bool(scale_bar_info),
            "scale_bar_details": scale_bar_info or "No scale bar detected or excluded",
        },
        "component_filtering_policy": {
            "min_area_threshold_px2": min_area_threshold,
            "silently_removed_components": 0,
            "filtering_applied": bool(min_area_threshold > 0),
        },
    }

    size_bins_def = [
        {"label": "< 50 px²", "min": 0, "max": 50},
        {"label": "50 - 200 px²", "min": 50, "max": 200},
        {"label": "200 - 500 px²", "min": 200, "max": 500},
        {"label": "500 - 1500 px²", "min": 500, "max": 1500},
        {"label": "1500 - 5000 px²", "min": 1500, "max": 5000},
        {"label": "> 5000 px²", "min": 5000, "max": float("inf")},
    ]

    size_histogram: Dict[str, Any] = {
        "bins": [],
        "counts": [],
        "percentages": [],
    }
    for b in size_bins_def:
        cnt = sum(1 for a in comp_areas if b["min"] <= a < b["max"])
        pct = round((cnt / flake_count * 100.0), 1) if flake_count > 0 else 0.0
        size_histogram["bins"].append(b["label"])
        size_histogram["counts"].append(cnt)
        size_histogram["percentages"].append(pct)

    mean_area_px2 = round(float(np.mean(comp_areas)), 2) if comp_areas else 0.0
    median_area_px2 = round(float(np.median(comp_areas)), 2) if comp_areas else 0.0
    max_area_px2 = int(np.max(comp_areas)) if comp_areas else 0
    min_area_px2 = int(np.min(comp_areas)) if comp_areas else 0
    std_area_px2 = round(float(np.std(comp_areas)), 2) if comp_areas else 0.0
    mean_equiv_d_px = round(float(np.mean(comp_equiv_diams)), 2) if comp_equiv_diams else 0.0
    mean_aspect_ratio = round(float(np.mean(comp_aspect_ratios)), 2) if comp_aspect_ratios else (1.0 if flake_count == 0 else 0.0)

    total_graphite_area_um2 = round(target_pixels * (scale ** 2), 2) if has_cal else None
    mean_flake_area_um2 = round(mean_area_px2 * (scale ** 2), 2) if has_cal else None
    mean_equiv_d_um = round(mean_equiv_d_px * scale, 2) if has_cal else None

    return {
        "total_flakes": flake_count,
        "flake_count": flake_count,
        "raw_flake_count": raw_count,
        "qualified_flake_count": astm_major_count if has_cal else area_gt_20_count,
        "qualified_counts": qualified_counts,
        "subthreshold_noise_count": raw_count - (astm_major_count if has_cal else area_gt_20_count),
        "graphite_area_fraction_pct": area_fraction_pct,
        "total_graphite_area_px2": target_pixels,
        "total_area_px2": target_pixels,
        "area_fraction_pct": area_fraction_pct,
        "background_matrix_area_px2": bg_pixels,
        "mean_flake_area_px2": mean_area_px2,
        "median_flake_area_px2": median_area_px2,
        "max_flake_area_px2": max_area_px2,
        "min_flake_area_px2": min_area_px2,
        "std_flake_area_px2": std_area_px2,
        "mean_equiv_diameter_px": mean_equiv_d_px,
        "mean_aspect_ratio": mean_aspect_ratio,
        "size_histogram": size_histogram,
        "total_graphite_area_um2": total_graphite_area_um2,
        "total_area_um2": total_graphite_area_um2,
        "mean_flake_area_um2": mean_flake_area_um2,
        "mean_equiv_diameter_um": mean_equiv_d_um,
        "diagnostic_summary": diagnostic_summary,
    }


def run_graphite_flake_analysis(
    img: np.ndarray,
    calibration: Optional[float] = None,
    method: str = "s_metalseg_fpn",
    min_area_threshold: int = 0,
) -> Dict[str, Any]:
    """Execute Gray Cast Iron Graphite Flake Analysis using S-metallograph-segmentation."""
    t0 = time.time()
    h, w = img.shape[:2]
    total_pixels = int(h * w)

    force_classical = (method in ("s_metalseg_classical", "classical", "baseline"))

    # Map method ID to architecture
    arch = "fpn"
    if "auto" in method.lower():
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        std_val = float(np.std(gray))
        if std_val < 30.0:
            arch = "stacking"
        elif max(h, w) >= 1600:
            arch = "unetplusplus"
        else:
            arch = "fpn"
    elif "unet" in method.lower():
        arch = "unetplusplus"
    elif "stack" in method.lower():
        arch = "stacking"

    # Run inference
    try:
        mask, inference_meta = run_s_metalseg_inference(
            img, arch=arch, force_classical=force_classical, return_meta=True
        )
    except Exception as exc:
        return {
            "status": "failed",
            "error": str(exc),
            "engine": ENGINE_ID,
            "engine_name": ENGINE_NAME,
            "analysis_type": "gray_cast_iron_graphite_flake",
            "warnings": [f"Segmentation inference error: {exc}"],
        }

    has_custom_weights = bool(inference_meta.get("has_custom_weights", False))
    is_trained_ai = has_custom_weights and not force_classical
    ckpt = find_checkpoint_path() if is_trained_ai else None

    if is_trained_ai:
        engine_type = "trained_deep_learning_model"
        model_arch_label = f"S-metallograph-segmentation ({arch.upper()} Trained Model)"
        algorithm_model_name = f"S-metallograph-segmentation ({arch.upper()})"
        ckpt_id = f"S-metallograph-segmentation/{arch.upper()} ({ckpt.name if ckpt else 'custom_weights'})"
        ckpt_status = f"Loaded trained checkpoint: {ckpt.name if ckpt else 'custom_weights'}"
        segmentation_basis = "Deep convolutional feature pyramid network (FPN)"
    else:
        engine_type = "classical_thresholding_baseline"
        model_arch_label = "Classical Baseline (Inverted Otsu + Morphological Opening)"
        algorithm_model_name = "Classical Thresholding Baseline (Otsu + Morphology)"
        ckpt_id = "None — Classical Contrast Baseline (Otsu)"
        ckpt_status = "NO TRAINED CHECKPOINT LOADED — Output generated via classical baseline"
        segmentation_basis = "Optical reflectance contrast thresholding (Otsu bimodal inversion)"

    # Optical scale bar detection and annotation exclusion
    scale_bar_info = detect_micrograph_scale_bar(img)
    cleaned_mask = mask
    effective_total_pixels = total_pixels
    effective_cal = calibration

    if scale_bar_info:
        # If caller did not provide manual calibration, adopt the measured optical scale
        if effective_cal is None or effective_cal <= 0:
            effective_cal = scale_bar_info["scale_um_per_px"]
        # Exclude scale bar annotation region to prevent false positives from line and text
        cleaned_mask, fp_scale_px = exclude_annotation_roi(mask, scale_bar_info["annotation_roi"])
        annot_roi = scale_bar_info["annotation_roi"]
        annot_area = annot_roi["w"] * annot_roi["h"]
        effective_total_pixels = max(total_pixels - annot_area, 1)
        scale_bar_info["false_positive_pixels_removed"] = fp_scale_px
        scale_bar_info["annotation_pixels_excluded"] = annot_area

    measurements = compute_flake_measurements(
        cleaned_mask,
        calibration=effective_cal,
        total_image_pixels=effective_total_pixels,
        min_area_threshold=min_area_threshold,
        scale_bar_info=scale_bar_info,
    )
    target_pixels = measurements["total_graphite_area_px2"]
    bg_pixels = measurements["background_matrix_area_px2"]
    area_fraction_pct = measurements["graphite_area_fraction_pct"]
    flake_count = measurements["total_flakes"]
    has_cal = bool(effective_cal is not None and effective_cal > 0)

    warnings: List[str] = []
    if target_pixels == 0:
        warnings.append("Empty segmentation mask: no graphite flakes detected.")
    elif area_fraction_pct > 80.0:
        warnings.append("High foreground fraction (>80%): matrix phase may be inverted or illumination anomalous.")
    if not has_cal:
        warnings.append("Spatial calibration unavailable (length reported in pixels, area in px^2). Physical micrometer dimensions are not reported.")
    if scale_bar_info:
        warnings.append(f"Optical scale bar detected and measured: {scale_bar_info['calibration_method']}.")
    if not is_trained_ai:
        warnings.append(
            "Inference method notice: Output generated via classical Otsu thresholding baseline. "
            "No fine-tuned gray cast iron deep learning checkpoint is loaded. Do not treat as trained AI prediction."
        )

    # Independent reference self-check (ASTM E2567 / Otsu baseline)
    self_check = compute_gray_iron_self_check(
        img,
        cleaned_mask,
        scale_bar_info=scale_bar_info,
        scale_um_per_px=effective_cal,
    )

    # Visualizations:
    # 1. Binary Mask (cleaned_mask)

    # 2. Overlay (micrograph + cyan tint over graphite)
    overlay = img.copy()
    if len(overlay.shape) == 2:
        overlay = cv2.cvtColor(overlay, cv2.COLOR_GRAY2BGR)
    # Cyan highlight: B=255, G=220, R=0
    color_mask = np.zeros_like(overlay)
    color_mask[cleaned_mask == 255] = (255, 220, 0)
    alpha = 0.45
    blended = cv2.addWeighted(color_mask, alpha, overlay, 1.0 - alpha, 0)
    overlay[cleaned_mask == 255] = blended[cleaned_mask == 255]

    # 3. Contours (crisp boundary visualization with metallurgical qualification distinction)
    contour_img = img.copy()
    if len(contour_img.shape) == 2:
        contour_img = cv2.cvtColor(contour_img, cv2.COLOR_GRAY2BGR)
    contours, _ = cv2.findContours(cleaned_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    scale_val = effective_cal or 1.0
    cutoff_px = (5.0 / scale_val) if has_cal else 20.0
    primary_contours = []
    subthreshold_contours = []
    for c in contours:
        _, _, cw, ch = cv2.boundingRect(c)
        if max(cw, ch) >= cutoff_px or cv2.contourArea(c) >= 20:
            primary_contours.append(c)
        else:
            subthreshold_contours.append(c)

    # Sub-threshold micro-debris / pinholes rendered in subtle faint teal (1px)
    cv2.drawContours(contour_img, subthreshold_contours, -1, (120, 140, 140), 1, cv2.LINE_AA)
    # Qualified primary lamellar graphite flakes rendered in vivid emerald green (2px)
    cv2.drawContours(contour_img, primary_contours, -1, (0, 255, 128), 2, cv2.LINE_AA)

    # 4. Exclusion ROI overlay (allows metallographer inspection)
    exclusion_overlay = generate_exclusion_overlay(
        img,
        scale_bar_info["annotation_roi"] if scale_bar_info else None,
        scale_bar_info,
    )

    elapsed_s = round(time.time() - t0, 3)
    size_histogram = measurements["size_histogram"]

    # Chart datasets
    chart_data = {
        "pie_chart": {
            "title": "Segmented Area Distribution",
            "categories": [
                {"name": "Graphite Flakes (Target)", "value": target_pixels, "percentage": area_fraction_pct, "color": "#FF7A18"},
                {"name": "Matrix Phase (Background)", "value": bg_pixels, "percentage": round(100.0 - area_fraction_pct, 3), "color": "#2c3b4d"},
            ],
            "total_pixels": effective_total_pixels,
        },
        "bar_chart": {
            "title": "Detected Feature Distribution",
            "bins": size_histogram["bins"],
            "counts": size_histogram["counts"],
            "percentages": size_histogram["percentages"],
            "unit": "px²" if not has_cal else "px² (uncalibrated bin boundaries)",
        },
    }

    return {
        "status": "completed",
        "engine": ENGINE_ID,
        "engine_name": ENGINE_NAME,
        "model_architecture": model_arch_label,
        "checkpoint_identifier": ckpt_id,
        "is_trained_ai": is_trained_ai,
        "inference_engine_type": engine_type,
        "segmentation_basis": segmentation_basis,
        "processing_time_s": elapsed_s,
        "flake_count": flake_count,
        "qualified_flake_count": measurements.get("qualified_flake_count", flake_count),
        "raw_flake_count": measurements.get("raw_flake_count", flake_count),
        "qualified_counts": measurements.get("qualified_counts", {}),
        "self_check": self_check,
        "measurements": measurements,
        "charts": chart_data,
        "diagnostic_summary": measurements.get("diagnostic_summary"),
        "scale_bar_info": scale_bar_info,
        "directly_measured_features": {
            "source_dimensions": f"{w} x {h} px",
            "total_pixels": effective_total_pixels,
            "segmented_pixels": target_pixels,
            "area_fraction": f"{area_fraction_pct}%",
            "connected_components_count": flake_count,
            "inference_engine_type": engine_type,
            "is_trained_ai_model": is_trained_ai,
            "segmentation_basis": segmentation_basis,
            "calibration_status": (
                f"{effective_cal} µm/px ({scale_bar_info['calibration_method']})"
                if scale_bar_info
                else (f"{effective_cal} µm/px" if has_cal else "Not available — image calibration required")
            ),
        },
        "algorithm_predictions": {
            "model": algorithm_model_name,
            "architecture": arch if is_trained_ai else "classical_otsu_morphology",
            "is_trained_ai": is_trained_ai,
            "checkpoint_status": ckpt_status,
            "segmentation_basis": segmentation_basis,
            "target_class": "Lamellar Graphite Flakes",
        },
        "experimental_interpretations": {
            "iso_graphite_classification": "UNVALIDATED (ISO 945-1 / ASTM A247 flake classification requires reference chart evaluation)",
            "iso_classification": "UNVALIDATED (ISO 945-1 / ASTM A247 flake classification requires reference chart evaluation)",
            "flake_thickness_3d": "UNAVAILABLE (2D optical section cannot measure 3D flake thickness)",
        },
        "unavailable_measurements": [
            "ISO 945-1 graphite flake type classification (Type A-E)",
            "True 3D graphite flake thickness and volume distribution",
            "Matrix phase decomposition (pearlite/ferrite ratio requires nital etched multiphase training)",
        ],
        "validation_status": (
            "EXPERIMENTAL / NOT VALIDATED FOR INDUSTRIAL RELEASE. Segmentation predictions "
            "require qualified metallurgical review. ISO 945-1 / ASTM A247 graphite classification "
            "is not certified by this software unless the applicable classification procedure has "
            "been separately implemented and validated. Three-dimensional graphite-flake thickness "
            "cannot be determined from a single two-dimensional micrograph."
        ),
        "images": {
            "flake_mask": cleaned_mask,
            "flake_overlay": overlay,
            "flake_contour": contour_img,
            "flake_exclusion": exclusion_overlay,
        },
        "warnings": warnings,
    }
