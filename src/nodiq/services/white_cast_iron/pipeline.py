"""White Cast Iron Carbide Analysis Pipeline.

Orchestrates input image validation, spatial calibration verification,
CARDE adapter execution, artifact tracking, and structured payload generation.
Strictly separated from graphite nodularity and steel grain size pipelines.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional

import cv2
import numpy as np

from . import carde_adapter

SUPPORTED_ANALYSIS_TYPES = ["white_cast_iron_carbide"]
ANALYSIS_METHODS = ["carde_otsu"]
METHOD_LABELS = {
    "carde_otsu": "CARDE Classical Carbide Segmentation (Otsu + Top-Hat)",
}

ANALYSIS_ARTIFACT_LABELS = {
    "carde_mask": "CARDE Carbide Binary Mask",
    "carde_overlay": "CARDE Carbide Segmentation Overlay",
}


def engines_availability() -> Dict[str, Any]:
    """Report availability of the White Cast Iron analysis engines."""
    carde_av = carde_adapter.availability()
    return {
        "analysis_type": "white_cast_iron_carbide",
        "methods": ANALYSIS_METHODS,
        "default_method": "carde_otsu",
        "carde": carde_av,
    }


def validate_calibration(scale: Any) -> Optional[float]:
    """Validate spatial scale in microns per pixel.

    Rejects non-numeric, zero, negative, NaN, and infinite values.
    """
    if scale is None or scale == "":
        return None
    try:
        val = float(scale)
    except (ValueError, TypeError):
        raise ValueError("Calibration must be a valid positive number.")
    if math.isnan(val) or math.isinf(val) or val <= 0:
        raise ValueError("Calibration must be a finite positive number greater than 0.")
    return val


def analyze_image(
    image_input: Any,
    calibration: Optional[float] = None,
    method: str = "carde_otsu",
    progress_cb: Optional[Callable[[int], None]] = None,
) -> Dict[str, Any]:
    """Execute White Cast Iron Carbide Analysis on a micrograph.

    Args:
        image_input: bytes, bytearray, or numpy ndarray of the micrograph.
        calibration: scale in um/px (optional).
        method: analysis method ('carde_otsu').
        progress_cb: progress callback receiving percentage (0-100).

    Returns:
        Structured analysis payload conforming to NODIQ-X storage and reporting contracts.
    """
    if progress_cb:
        progress_cb(10)

    # Validate method
    if method not in ANALYSIS_METHODS:
        raise ValueError(
            f"Unsupported method '{method}' for white cast iron. Expected one of {ANALYSIS_METHODS}"
        )

    # Validate calibration
    scale_um_per_px = validate_calibration(calibration)

    # Validate and decode image
    if isinstance(image_input, (bytes, bytearray)):
        nparr = np.frombuffer(image_input, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return {
                "status": "failed",
                "error": "Input bytes could not be decoded as an image.",
                "analysis_type": "white_cast_iron_carbide",
                "warnings": ["Image decoding failed."],
            }
    elif isinstance(image_input, np.ndarray):
        img = image_input
    else:
        return {
            "status": "failed",
            "error": "Invalid image input type. Expected bytes or numpy ndarray.",
            "analysis_type": "white_cast_iron_carbide",
            "warnings": ["Unsupported image input."],
        }

    h, w = img.shape[:2]
    if h < 32 or w < 32:
        return {
            "status": "failed",
            "error": f"Image dimensions ({w}x{h}) are too small for microstructure analysis.",
            "analysis_type": "white_cast_iron_carbide",
            "warnings": ["Image too small."],
        }

    if progress_cb:
        progress_cb(35)

    # Run CARDE carbide analysis
    res = carde_adapter.run_carde_carbide_analysis(
        img,
        calibration=scale_um_per_px,
    )

    if progress_cb:
        progress_cb(80)

    status = res.get("status", "completed")
    images = res.get("images", {})
    meas = res.get("measurements", {})
    warnings = list(res.get("warnings") or [])

    cal_dict = {
        "available": bool(scale_um_per_px is not None and scale_um_per_px > 0),
        "um_per_px": scale_um_per_px,
        "units": "um/px" if scale_um_per_px else "px",
        "notes": (
            f"Calibrated scale: {scale_um_per_px} um/px"
            if scale_um_per_px
            else "Scale unavailable — length in pixels, area in px^2, physical units not reported"
        ),
    }

    artifacts_meta = []
    for k, label in ANALYSIS_ARTIFACT_LABELS.items():
        if k in images:
            artifacts_meta.append({"kind": k, "label": label})

    payload = {
        "status": status,
        "analysis_type": "white_cast_iron_carbide",
        "method": method,
        "method_label": METHOD_LABELS.get(method, method),
        "source_width": w,
        "source_height": h,
        "calibration": cal_dict,
        "white_cast_iron": {
            "engine": res.get("engine"),
            "engine_name": res.get("engine_name"),
            "carbide_count": res.get("carbide_count", 0),
            "measurements": meas,
            "directly_measured_features": res.get("directly_measured_features", {}),
            "algorithm_predictions": res.get("algorithm_predictions", {}),
            "experimental_interpretations": res.get("experimental_interpretations", {}),
            "unavailable_measurements": res.get("unavailable_measurements", []),
            "validation_status": res.get("validation_status"),
        },
        "artifacts": artifacts_meta,
        "images": images,
        "warnings": warnings,
    }

    if status == "failed":
        payload["error"] = res.get("error", "Carbide analysis failed")

    if progress_cb:
        progress_cb(100)

    return payload
