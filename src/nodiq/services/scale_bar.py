"""services/scale_bar.py — Automatic Optical Micrograph Scale Bar Detector.

Detects embedded horizontal microscope calibration scale bars, measures their
pixel width (W_px), and estimates/determines spatial calibration (um/px)
without requiring external hardware or heavy OCR packages.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import cv2
import numpy as np


# Standard physical scale bar increments commonly stamped on metallurgical micrographs
# across Olympus, Zeiss, Leica, Keyence, Nikon, and Phenom microscopes.
STANDARD_SCALE_LENGTHS_UM = [10.0, 20.0, 25.0, 50.0, 100.0, 200.0, 250.0, 400.0, 500.0, 1000.0]


def detect_scale_bar_from_image(img_bgr: np.ndarray) -> Dict[str, Any]:
    """Search for horizontal scale bar in micrograph and determine calibration.

    Returns dict with keys:
    - detected (bool)
    - bar_width_px (int)
    - physical_length (float, in um)
    - unit (str, 'µm')
    - um_per_px (float)
    - confidence (float, 0.0 - 1.0)
    - bbox (dict: x, y, w, h in image coordinates)
    - options (list of candidate length calibrations)
    - reason (str if not detected)
    """
    if img_bgr is None or not isinstance(img_bgr, np.ndarray) or img_bgr.size == 0:
        return {"detected": False, "reason": "Invalid or empty image"}

    h, w = img_bgr.shape[:2]
    if h < 64 or w < 64:
        return {"detected": False, "reason": "Image too small for scale bar search"}

    # Metallurgical micrographs predominantly embed scale bars in the bottom 25%
    # (or in the bottom-right/bottom-left quadrant).
    roi_h = int(h * 0.25)
    roi_top = h - roi_h
    roi = img_bgr[roi_top:, :]
    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    min_bar_w = max(35, int(w * 0.03))
    max_bar_w = int(w * 0.50)  # scale bar cannot be > 50% image width

    candidates: List[Dict[str, Any]] = []

    # Test multiple horizontal morphological line kernels
    kernel_lengths = [35, 50, 75, 100, 140, 180, 240, 300]

    for k_len in kernel_lengths:
        if k_len > max_bar_w:
            continue
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k_len, 1))

        # Check dark bar on bright background (common in printed / etched borders)
        _, bin_inv = cv2.threshold(gray_roi, 130, 255, cv2.THRESH_BINARY_INV)
        morph_inv = cv2.morphologyEx(bin_inv, cv2.MORPH_OPEN, kernel)
        cnts_inv, _ = cv2.findContours(morph_inv, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts_inv:
            bx, by, bw, bh = cv2.boundingRect(c)
            if min_bar_w <= bw <= max_bar_w and 2 <= bh <= 28 and (bw / max(bh, 1)) >= 3.8:
                # verify solid horizontal line profile
                sub = morph_inv[by:by + bh, bx:bx + bw]
                fill_ratio = float(np.count_nonzero(sub)) / float(sub.size)
                if fill_ratio >= 0.55:
                    candidates.append({
                        "bw": bw, "bh": bh, "bx": bx, "by": by + roi_top,
                        "polarity": "dark", "fill": fill_ratio
                    })

        # Check bright bar on dark background / overlay
        _, bin_w = cv2.threshold(gray_roi, 195, 255, cv2.THRESH_BINARY)
        morph_w = cv2.morphologyEx(bin_w, cv2.MORPH_OPEN, kernel)
        cnts_w, _ = cv2.findContours(morph_w, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts_w:
            bx, by, bw, bh = cv2.boundingRect(c)
            if min_bar_w <= bw <= max_bar_w and 2 <= bh <= 28 and (bw / max(bh, 1)) >= 3.8:
                sub = morph_w[by:by + bh, bx:bx + bw]
                fill_ratio = float(np.count_nonzero(sub)) / float(sub.size)
                if fill_ratio >= 0.55:
                    candidates.append({
                        "bw": bw, "bh": bh, "bx": bx, "by": by + roi_top,
                        "polarity": "light", "fill": fill_ratio
                    })

    if not candidates:
        return {"detected": False, "reason": "No horizontal scale bar line found in bottom quadrant"}

    # Deduplicate and sort by width & fill ratio
    candidates = sorted(candidates, key=lambda c: (c["bw"], c["fill"]), reverse=True)
    best = candidates[0]
    bar_width_px = int(best["bw"])

    # Attempt to parse text in the adjacent region (above or below bar)
    detected_length: Optional[float] = None
    confidence = 0.88

    # Search for text in the 45px strip above or below the bar
    bx = best["bx"]
    by = best["by"]
    text_y1 = max(0, by - 45)
    text_y2 = min(h, by + best["bh"] + 45)
    text_x1 = max(0, bx - 30)
    text_x2 = min(w, bx + bar_width_px + 30)
    text_roi = img_bgr[text_y1:text_y2, text_x1:text_x2]

    # If pytesseract happens to be installed, use it for exact text reading
    try:
        import pytesseract
        ocr_text = pytesseract.image_to_string(text_roi, config="--psm 6")
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:µm|um|pm|mm)", ocr_text, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            unit_str = match.group(0).lower()
            if "mm" in unit_str:
                val *= 1000.0
            if 5.0 <= val <= 5000.0:
                detected_length = val
                confidence = 0.98
    except Exception:
        pass

    # If no OCR matched, use metallography standard scale matching
    # In optical metallography at 100x to 500x magnification:
    # A bar of width ~100-350px typically represents 100 um, 200 um, or 400 um (1.0 to 3.0 um/px).
    if detected_length is None:
        best_candidate = 400.0 if bar_width_px > 160 else 100.0
        # Check standard increments that yield realistic optical microscope scale (0.5 to 3.5 um/px)
        for cand_len in STANDARD_SCALE_LENGTHS_UM:
            ratio = cand_len / float(bar_width_px)
            if 1.0 <= ratio <= 2.8:
                best_candidate = cand_len
                confidence = 0.93
                break
        detected_length = best_candidate

    um_per_px = round(detected_length / float(bar_width_px), 3)

    # Build options for quick user selection/switching in UI
    options = []
    for std_len in STANDARD_SCALE_LENGTHS_UM:
        scale_ratio = std_len / float(bar_width_px)
        if 0.2 <= scale_ratio <= 6.0:
            options.append({
                "length": float(std_len),
                "um_per_px": round(scale_ratio, 3),
                "label": f"{int(std_len)} µm ({round(scale_ratio, 3)} µm/px)"
                         + (" — Auto-Matched" if std_len == detected_length else "")
            })

    return {
        "detected": True,
        "bar_width_px": bar_width_px,
        "physical_length": float(detected_length),
        "unit": "µm",
        "um_per_px": um_per_px,
        "confidence": round(confidence, 2),
        "polarity": best["polarity"],
        "bbox": {
            "x": int(best["bx"]),
            "y": int(best["by"]),
            "w": int(best["bw"]),
            "h": int(best["bh"])
        },
        "options": options,
        "source": "auto_scale_bar_detector"
    }


def detect_scale_bar_from_bytes(data: bytes) -> Dict[str, Any]:
    """Decode bytes and execute scale bar detection."""
    try:
        arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            return {"detected": False, "reason": "Failed to decode image bytes"}
        return detect_scale_bar_from_image(arr)
    except Exception as exc:
        return {"detected": False, "reason": f"Scale bar detection exception: {str(exc)[:200]}"}
