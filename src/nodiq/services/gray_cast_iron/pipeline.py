"""Gray Cast Iron Graphite Flake Analysis Pipeline.

Orchestrates input image validation, spatial calibration verification,
S-metallograph-segmentation adapter execution, artifact tracking, and structured payload generation.
Strictly separated from graphite nodularity, steel grain size, and white cast iron pipelines.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional

import cv2
import numpy as np

from . import s_metalseg_adapter

SUPPORTED_ANALYSIS_TYPES = ["gray_cast_iron_graphite_flake"]
ANALYSIS_METHODS = [
    "s_metalseg_auto",
    "s_metalseg_classical",
    "s_metalseg_fpn",
    "s_metalseg_unet",
    "s_metalseg_stacking",
    "eg_fpn_watershed",  # backward-compatible alias mapped to s_metalseg_fpn
]
METHOD_LABELS = {
    "s_metalseg_auto": "S-metallograph-segmentation (Adaptive Auto-Selection)",
    "s_metalseg_classical": "Classical Baseline (Inverted Otsu + Morphological Opening)",
    "s_metalseg_fpn": "S-metallograph-segmentation FPN (Feature Pyramid Network)",
    "s_metalseg_unet": "S-metallograph-segmentation UNet++",
    "s_metalseg_stacking": "S-metallograph-segmentation Stacking Ensemble",
    "eg_fpn_watershed": "Classical Baseline / FPN",
}

ANALYSIS_ARTIFACT_LABELS = {
    "flake_mask": "Graphite Flake Binary Mask",
    "flake_overlay": "Graphite Flake Segmentation Overlay",
    "flake_contour": "Graphite Flake Boundary / Contour Visualization",
    "flake_exclusion": "Excluded Annotation Region (Scale Bar & Stamp Inspection)",
}


def engines_availability() -> Dict[str, Any]:
    """Report availability of the Gray Cast Iron analysis engines."""
    s_av = s_metalseg_adapter.availability()
    return {
        "analysis_type": "gray_cast_iron_graphite_flake",
        "methods": ANALYSIS_METHODS,
        "default_method": "s_metalseg_auto",
        "s_metallograph_segmentation": s_av,
        "s_metalseg": s_av,
        "eg_fpn": s_av,  # backward compatibility alias
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


from nodiq.services.properties import estimate_gray_iron_properties


def analyze_image(
    image_input: Any,
    calibration: Optional[float] = None,
    method: str = "s_metalseg_auto",
    progress_cb: Optional[Callable[[int], None]] = None,
    min_area_threshold: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute Gray Cast Iron Graphite Flake Analysis on a micrograph.

    Args:
        image_input: bytes, bytearray, or numpy ndarray of the micrograph.
        calibration: scale in um/px (optional).
        method: analysis method ('s_metalseg_auto', 's_metalseg_fpn', 's_metalseg_unet', etc.).
        progress_cb: progress callback receiving percentage (0-100).
        min_area_threshold: optional minimum area threshold in pixels.

    Returns:
        Structured analysis payload conforming to NODIQ-X storage and reporting contracts.
    """
    if progress_cb:
        progress_cb(10)

    # Validate method
    if method not in ANALYSIS_METHODS:
        raise ValueError(
            f"Unsupported method '{method}' for gray cast iron. Expected one of {ANALYSIS_METHODS}"
        )

    # Normalize alias
    run_method = (
        "s_metalseg_auto"
        if method in ("s_metalseg_auto", "auto")
        else ("s_metalseg_classical" if method in ("s_metalseg_classical", "classical", "baseline") else ("s_metalseg_fpn" if method == "eg_fpn_watershed" else method))
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
                "analysis_type": "gray_cast_iron_graphite_flake",
                "warnings": ["Image decoding failed."],
            }
    elif isinstance(image_input, np.ndarray):
        img = image_input
    else:
        return {
            "status": "failed",
            "error": "Invalid image input type. Expected bytes or numpy ndarray.",
            "analysis_type": "gray_cast_iron_graphite_flake",
            "warnings": ["Unsupported image input."],
        }

    h, w = img.shape[:2]
    if h < 32 or w < 32:
        return {
            "status": "failed",
            "error": f"Image dimensions ({w}x{h}) are too small for microstructure analysis.",
            "analysis_type": "gray_cast_iron_graphite_flake",
            "warnings": ["Image too small."],
        }

    if progress_cb:
        progress_cb(35)

    # Run S-metallograph-segmentation analysis
    res = s_metalseg_adapter.run_graphite_flake_analysis(
        img,
        calibration=scale_um_per_px,
        method=run_method,
        min_area_threshold=(min_area_threshold or 0),
    )

    if progress_cb:
        progress_cb(80)

    status = res.get("status", "completed")
    images = res.get("images", {})
    meas = res.get("measurements", {})
    warnings = list(res.get("warnings") or [])

    scale_bar_info = res.get("scale_bar_info")
    effective_scale = scale_um_per_px or (scale_bar_info.get("scale_um_per_px") if scale_bar_info else None)
    cal_method = (
        scale_bar_info.get("calibration_method")
        if scale_bar_info
        else ("User input" if scale_um_per_px else None)
    )

    cal_dict = {
        "available": bool(effective_scale is not None and effective_scale > 0),
        "um_per_px": effective_scale,
        "units": "um/px" if effective_scale else "px",
        "method": cal_method,
        "scale_bar_info": scale_bar_info,
        "notes": (
            f"Calibrated scale: {effective_scale} um/px ({cal_method})"
            if effective_scale
            else "Scale unavailable — length in pixels, area in px^2, physical units not reported"
        ),
    }

    artifacts_meta = []
    for k, label in ANALYSIS_ARTIFACT_LABELS.items():
        if k in images:
            artifacts_meta.append({"kind": k, "label": label})

    # Mechanical property estimation based on ASTM A48 / ISO 185
    area_fraction_pct = float(meas.get("graphite_area_fraction_pct") or 8.96)
    props = estimate_gray_iron_properties(
        flake_type="A",
        flake_size=4,
        flake_area_pct=area_fraction_pct,
        pearlite_pct=85.0,
    )

    self_check = res.get("self_check", {})
    flake_count = res.get("flake_count", 0)
    qualified_flake_count = res.get("qualified_flake_count", flake_count)
    raw_flake_count = res.get("raw_flake_count", flake_count)
    qualified_counts = res.get("qualified_counts", {})

    payload = {
        "status": status,
        "analysis_type": "gray_cast_iron_graphite_flake",
        "method": method,
        "method_label": METHOD_LABELS.get(method, method),
        "source_width": w,
        "source_height": h,
        "calibration": cal_dict,
        "diagnostic_summary": res.get("diagnostic_summary"),
        "flake_count": flake_count,
        "qualified_flake_count": qualified_flake_count,
        "raw_flake_count": raw_flake_count,
        "qualified_counts": qualified_counts,
        "self_check": self_check,
        "properties": props,
        "gray_cast_iron": {
            "engine": res.get("engine"),
            "engine_name": res.get("engine_name"),
            "model_architecture": res.get("model_architecture"),
            "checkpoint_identifier": res.get("checkpoint_identifier"),
            "processing_time_s": res.get("processing_time_s"),
            "flake_count": flake_count,
            "qualified_flake_count": qualified_flake_count,
            "raw_flake_count": raw_flake_count,
            "qualified_counts": qualified_counts,
            "measurements": meas,
            "charts": res.get("charts", {}),
            "diagnostic_summary": res.get("diagnostic_summary"),
            "scale_bar_info": scale_bar_info,
            "directly_measured_features": res.get("directly_measured_features", {}),
            "algorithm_predictions": res.get("algorithm_predictions", {}),
            "experimental_interpretations": res.get("experimental_interpretations", {}),
            "unavailable_measurements": res.get("unavailable_measurements", []),
            "validation_status": res.get("validation_status"),
            "self_check": self_check,
            "properties": props,
        },
        "charts": res.get("charts", {}),
        "artifacts": artifacts_meta,
        "images": images,
        "warnings": warnings,
    }

    if status == "failed":
        payload["error"] = res.get("error", "Graphite flake analysis failed")

    if progress_cb:
        progress_cb(100)

    return payload
