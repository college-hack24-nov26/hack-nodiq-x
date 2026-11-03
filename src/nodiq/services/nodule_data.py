#!/usr/bin/env python3
"""
services/nodule_data.py — per-nodule explainable enrichment (Phase 5).

Reuses the ENGINE's own numbers (never recomputes shape measures that could
disagree with the pipeline) and adds:
  * perimeter / circularity / solidity / aspect ratio measured from the same
    stored contour (pure geometry, deterministic, consistent by construction
    because they derive from the engine's final contours)
  * an honest per-nodule confidence: shape certainty (how close the nodule's
    measured roundness is to the class boundary) combined with the image-level
    detection confidence (self-check F1). Clearly documented as a heuristic —
    not a fabricated probability.
"""
import cv2
import numpy as np


def _geometry(cnt):
    area = cv2.contourArea(cnt)
    per = cv2.arcLength(cnt, True)
    circularity = (4.0 * np.pi * area / (per * per)) if per > 0 else 0.0
    hull = cv2.convexHull(cnt)
    hull_area = cv2.contourArea(hull)
    solidity = (area / hull_area) if hull_area > 0 else 0.0
    x, y, w, h = cv2.boundingRect(cnt)
    aspect = (max(w, h) / min(w, h)) if min(w, h) > 0 else 1.0
    return {
        "perimeter_px": round(float(per), 1),
        "circularity": round(float(circularity), 4),
        "solidity": round(float(solidity), 4),
        "aspect_ratio": round(float(aspect), 3),
    }


def nodule_confidence(row, image_f1_pct, iso_threshold=0.6):
    """Honest per-nodule confidence (heuristic, documented).

    Components:
      * shape certainty: how far the measured roundness sits from the ISO
        V/VI boundary (0.6). A roundness of 0.95 is clearly round (certain);
        0.61 is borderline (uncertain).
      * image-level detection confidence: the engine's self-check F1.
    """
    r = row.get("roundness", 0.0)
    shape_certainty = min(1.0, abs(r - iso_threshold) / 0.4)
    detection = (image_f1_pct / 100.0
                 if isinstance(image_f1_pct, (int, float)) else 0.5)
    conf = 0.6 * shape_certainty + 0.4 * detection
    return round(float(min(1.0, max(0.0, conf))), 3)


def enrich_rows(rows, contours, image_f1_pct=None):
    """Add geometry + confidence to the engine's per-nodule rows.

    `rows` and `contours` come straight from analyze_image() so every number
    traces to the measurement authority.
    """
    f1 = image_f1_pct
    if f1 is None:
        f1 = 100.0
    out = []
    for i, row in enumerate(rows):
        enriched = dict(row)
        if i < len(contours):
            enriched.update(_geometry(contours[i]))
        enriched["confidence"] = nodule_confidence(row, f1)
        out.append(enriched)
    return out


def get_nodule(analysis_payload, nodule_id, calibration=None):
    """Single-nodule inspection payload (Phase 5 API backing)."""
    rows = analysis_payload.get("nodules") or analysis_payload.get("rows") or []
    for row in rows:
        if row.get("nodule_id") == nodule_id:
            out = dict(row)
            cal_available = bool(calibration and calibration.available)
            if cal_available:
                k = calibration.um_per_px
                out["area_um2"] = round(row["area_px"] * k * k, 2)
                out["equiv_diameter_um"] = round(
                    row["equiv_diameter_px"] * k, 2)
                if "perimeter_px" in out:
                    out["perimeter_um"] = round(out["perimeter_px"] * k, 2)
            out["calibration_available"] = cal_available
            return out
    return None
