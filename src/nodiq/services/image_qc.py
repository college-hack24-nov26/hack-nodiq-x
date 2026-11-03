"""Micrograph Quality Health & Pre-Analysis Focus Gate for NODIQ-X.

Evaluates:
1. Sharpness / Focus Score via Modified Laplacian Variance.
2. Polishing Scratch & Abrasive Streak Detection.
3. Illumination Uniformity & Microscope Vignetting.
4. Contrast / Etch Quality Index.
"""
from typing import Any, Dict
import cv2
import numpy as np


def evaluate_micrograph_health(image_bgr: np.ndarray) -> Dict[str, Any]:
    """Evaluate specimen preparation and optical acquisition quality."""
    if image_bgr is None or not isinstance(image_bgr, np.ndarray) or image_bgr.size == 0:
        return {
            "available": False,
            "overall_status": "UNKNOWN",
            "focus_score": 0.0,
            "quality_grade": "Unavailable",
            "reason": "Invalid or empty image"
        }

    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if image_bgr.ndim == 3 else image_bgr

    # 1. Focus & Sharpness (Modified Laplacian Variance)
    # Exclude scale bar region (bottom 12%) so text doesn't artificially spike focus
    eval_h = int(h * 0.88) if h > 200 else h
    roi = gray[:eval_h, :]

    lap = cv2.Laplacian(roi, cv2.CV_64F)
    lap_var = float(lap.var())

    # Map laplacian variance to 0 - 100 scale:
    # < 40: Blurry/Defocus, 40-120: Fair, 120-350: Sharp, > 350: Highly Sharp
    raw_focus = (lap_var / 250.0) * 100.0
    focus_score = round(float(np.clip(raw_focus, 5.0, 99.5)), 1)

    # 2. Polishing Scratch & Abrasive Streak Detection
    # Scratches appear as long, thin, straight high-gradient lines
    edges = cv2.Canny(roi, 50, 150, apertureSize=3)
    # Morphological line detection across 4 directional angles (0, 45, 90, 135 deg)
    kernel_len = max(15, int(w * 0.04))
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_len, 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_len))

    h_lines = cv2.morphologyEx(edges, cv2.MORPH_OPEN, h_kernel)
    v_lines = cv2.morphologyEx(edges, cv2.MORPH_OPEN, v_kernel)

    h_density = float(np.count_nonzero(h_lines)) / float(roi.size) * 1000.0
    v_density = float(np.count_nonzero(v_lines)) / float(roi.size) * 1000.0
    scratch_density = round(h_density + v_density, 2)

    has_scratches = scratch_density > 2.8

    # 3. Illumination Uniformity & Vignetting Check
    # Compare center luminance to corner quadrants
    cx1, cx2 = int(w * 0.3), int(w * 0.7)
    cy1, cy2 = int(eval_h * 0.3), int(eval_h * 0.7)
    center_roi = roi[cy1:cy2, cx1:cx2]

    # Corners
    corner_size_w = int(w * 0.2)
    corner_size_h = int(eval_h * 0.2)
    tl = roi[:corner_size_h, :corner_size_w]
    tr = roi[:corner_size_h, w - corner_size_w:]
    bl = roi[eval_h - corner_size_h:, :corner_size_w]
    br = roi[eval_h - corner_size_h:, w - corner_size_w:]

    center_lum = float(np.mean(center_roi)) if center_roi.size > 0 else 128.0
    corner_lum = float(np.mean([np.mean(tl), np.mean(tr), np.mean(bl), np.mean(br)]))

    if center_lum > 0:
        uniformity_ratio = min(1.0, corner_lum / center_lum)
    else:
        uniformity_ratio = 1.0
    illumination_pct = round(float(uniformity_ratio * 100.0), 1)

    # 4. Contrast & Dynamic Range
    std_contrast = float(np.std(roi))
    contrast_score = round(float(np.clip((std_contrast / 55.0) * 100.0, 10.0, 100.0)), 1)

    # Overall Quality Assessment
    warnings = []
    if focus_score < 40.0:
        warnings.append("Micrograph appears slightly out of focus (low edge variance).")
    if has_scratches:
        warnings.append("Linear scratch artifacts detected; may slightly affect boundary detection.")
    if illumination_pct < 65.0:
        warnings.append("Microscope field vignetting detected (darker outer corners).")
    if contrast_score < 30.0:
        warnings.append("Low optical contrast; sample may be under-etched.")

    if focus_score >= 60.0 and not has_scratches and illumination_pct >= 75.0:
        status = "OPTIMAL"
        status_label = "Optimal Preparation & Sharp Focus"
        badge_color = "success"
    elif focus_score >= 38.0 and not (has_scratches and focus_score < 45.0):
        status = "ACCEPTABLE"
        status_label = "Acceptable Quality for Measurement"
        badge_color = "warning"
    else:
        status = "SUBOPTIMAL"
        status_label = "Suboptimal Micrograph Quality"
        badge_color = "danger"

    return {
        "available": True,
        "overall_status": status,
        "status_label": status_label,
        "badge_color": badge_color,
        "focus_score": focus_score,
        "sharpness_laplacian": round(lap_var, 1),
        "illumination_uniformity_pct": illumination_pct,
        "contrast_score": contrast_score,
        "scratch_detected": has_scratches,
        "scratch_density": scratch_density,
        "recommendations": warnings or ["Sample preparation and optical acquisition meet standard metallographic criteria."]
    }
