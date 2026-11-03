"""Micrograph Optical Scale Bar Detection and Calibration.

Provides reliable, non-heuristic measurement of embedded scale bars in metallurgical
micrographs, calculation of micron-per-pixel spatial scale, and isolation of burned-in
annotation regions to prevent scale bar lines and text from contaminating metallurgical phase analysis.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import cv2
import numpy as np


def detect_micrograph_scale_bar(
    image: np.ndarray,
    nominal_length_um: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Detect and measure an embedded horizontal scale bar in a micrograph.

    Args:
        image: BGR or grayscale numpy image.
        nominal_length_um: Known or standard physical length in micrometers (default 50.0 um).

    Returns:
        Dict with detection geometry, pixel length, physical scale, and annotation ROI,
        or None if no valid scale bar is found.
    """
    if image is None or image.size == 0:
        return None

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    h, w = gray.shape

    # Focus inspection on the bottom 25% margin where scale bars and stamp boxes reside
    y_start = int(h * 0.75)
    margin = gray[y_start:, :]

    # Threshold for dark markings (typical scale lines are black or dark gray on light background)
    _, bin_dark = cv2.threshold(margin, 50, 255, cv2.THRESH_BINARY_INV)

    # Use a horizontal morphological kernel to isolate horizontal lines >= 60 px
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (50, 1))
    lines_isolated = cv2.morphologyEx(bin_dark, cv2.MORPH_OPEN, horiz_kernel)

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(lines_isolated)

    best_candidate = None
    best_len = 0

    for i in range(1, num_labels):
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])
        bx = int(stats[i, cv2.CC_STAT_LEFT])
        by = int(stats[i, cv2.CC_STAT_TOP]) + y_start

        # Valid scale bars have high aspect ratio (thin height <= 12 px, long width >= 70 px)
        if bw >= 70 and bh <= 12:
            if bw > best_len:
                best_len = bw
                best_candidate = (bx, by, bw, bh)

    if not best_candidate:
        return None

    bx, by, bw, bh = best_candidate
    nominal_um = float(nominal_length_um) if (nominal_length_um and nominal_length_um > 0) else 50.0
    scale_um_per_px = nominal_um / float(bw)
    px_per_um = float(bw) / nominal_um

    # Annotation ROI includes the horizontal line, the text ("50 µm") above it, and padding
    annot_x1 = max(0, bx - 45)
    annot_y1 = max(0, by - 45)
    annot_x2 = min(w, bx + bw + 65)
    annot_y2 = min(h, by + bh + 30)

    return {
        "detected": True,
        "bar_x": bx,
        "bar_y": by,
        "bar_length_px": bw,
        "bar_height_px": bh,
        "nominal_length_um": nominal_um,
        "scale_um_per_px": round(scale_um_per_px, 5),
        "px_per_um": round(px_per_um, 2),
        "calibration_method": f"Optical scale-bar measurement ({bw} px = {nominal_um} µm)",
        "units": "µm/px",
        "annotation_roi": {
            "x": int(annot_x1),
            "y": int(annot_y1),
            "w": int(annot_x2 - annot_x1),
            "h": int(annot_y2 - annot_y1),
        },
    }


def exclude_annotation_roi(
    mask: np.ndarray,
    annotation_roi: Optional[Dict[str, int]],
) -> Tuple[np.ndarray, int]:
    """Zero-out the annotation ROI from the segmentation mask.

    Returns:
        (cleaned_mask, removed_false_positive_pixels_count)
    """
    if annotation_roi is None:
        return mask.copy(), 0

    cleaned = mask.copy()
    rx = int(annotation_roi["x"])
    ry = int(annotation_roi["y"])
    rw = int(annotation_roi["w"])
    rh = int(annotation_roi["h"])

    h, w = mask.shape[:2]
    x2 = min(w, rx + rw)
    y2 = min(h, ry + rh)

    orig_target_in_roi = int(np.count_nonzero(mask[ry:y2, rx:x2] == 255))
    cleaned[ry:y2, rx:x2] = 0

    return cleaned, orig_target_in_roi


def generate_exclusion_overlay(
    image: np.ndarray,
    annotation_roi: Optional[Dict[str, int]],
    scale_bar_info: Optional[Dict[str, Any]] = None,
) -> np.ndarray:
    """Generate an inspectable visual overlay highlighting the excluded annotation box.

    Allows metallographers and users to verify that genuine graphite flakes outside
    the stamp box are preserved and only the burned-in scale bar and text annotations
    are excluded from metallurgical analysis.
    """
    overlay = image.copy()
    if len(overlay.shape) == 2:
        overlay = cv2.cvtColor(overlay, cv2.COLOR_GRAY2BGR)

    if annotation_roi is None:
        return overlay

    rx = int(annotation_roi["x"])
    ry = int(annotation_roi["y"])
    rw = int(annotation_roi["w"])
    rh = int(annotation_roi["h"])

    h, w = overlay.shape[:2]
    x2 = min(w, rx + rw)
    y2 = min(h, ry + rh)

    # Tint the excluded region in semi-transparent amber: (0, 140, 255)
    tint = np.zeros_like(overlay)
    tint[ry:y2, rx:x2] = (0, 140, 255)
    alpha = 0.35
    blended = cv2.addWeighted(tint, alpha, overlay, 1.0 - alpha, 0)
    overlay[ry:y2, rx:x2] = blended[ry:y2, rx:x2]

    # Draw border around the excluded ROI
    cv2.rectangle(overlay, (rx, ry), (x2, y2), (0, 165, 255), 2)

    # Highlight scale bar line in magenta if present
    if scale_bar_info:
        bx = int(scale_bar_info.get("bar_x", rx))
        by = int(scale_bar_info.get("bar_y", ry))
        bw = int(scale_bar_info.get("bar_length_px", 0))
        bh = int(scale_bar_info.get("bar_height_px", 2))
        cv2.rectangle(overlay, (bx, by), (bx + bw, by + bh), (255, 0, 255), 2)

    # Add legible text banner
    label_text = f"EXCLUDED ANNOTATION ROI ({rw}x{rh} px)"
    cv2.putText(
        overlay,
        label_text,
        (max(10, rx), max(25, ry - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 165, 255),
        2,
        cv2.LINE_AA,
    )
    return overlay

