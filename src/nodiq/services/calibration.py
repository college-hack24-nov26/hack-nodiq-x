#!/usr/bin/env python3
"""
services/calibration.py — scale-bar detection + physical calibration (Phase 4).

Automatic detection looks for a microscope scale bar: a solid high-contrast
horizontal bar with a numeric label, near a bottom corner. Detection is
deliberately conservative — an uncertain match returns "unavailable" rather
than a wrong µm/px.

Manual calibration: pass pixels_per_um (or bar_length_um + bar_length_px).

All physical conversions go through micrometers_per_pixel; without a
calibration, NO µm value is ever produced (px only, explicitly labeled).
"""
import math
import re
from dataclasses import dataclass, asdict

import cv2
import numpy as np

# ISO 945-4:2019 clause 6.3: "Particles with a maximum Feret diameter less
# than 10 um shall be excluded from the evaluation." Applied ONLY when a
# valid physical calibration exists; never faked when it does not.
ISO_MIN_FERET_UM = 10.0


def validate_um_per_px(value):
    """Validate a microns-per-pixel scale; return float or None.

    Rejects None, NaN, +/-Infinity, zero and negative values — an invalid
    scale is treated as "no calibration" rather than silently accepted.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v) or v <= 0:
        return None
    return v


def make_calibration(um_per_px, source="manual", notes=""):
    """Build a Calibration from a validated microns-per-pixel value.

    Returns an unavailable Calibration when the value fails validation —
    callers can rely on `.available` without re-checking.
    """
    v = validate_um_per_px(um_per_px)
    if v is None:
        return Calibration(notes="invalid or missing microns-per-pixel "
                                 "value; calibration rejected")
    return Calibration(um_per_px=v, source=source, notes=notes)


def feret_size_status(feret_px, microns_per_pixel):
    """ISO 945-4 clause 6.3 size-qualification for one particle.

    Returns one of:
      "included"                — calibrated and feret_um >= 10.0
      "excluded_below_10um"     — calibrated and feret_um <  10.0
      "not_evaluable"           — no valid physical calibration

    The comparison is strictly `< 10.0` (a particle at exactly 10.0 um is
    INCLUDED, per "less than 10 um shall be excluded").
    """
    mpp = validate_um_per_px(microns_per_pixel)
    if mpp is None or feret_px is None:
        return "not_evaluable"
    try:
        feret_um = float(feret_px) * mpp
    except (TypeError, ValueError):
        return "not_evaluable"
    if math.isnan(feret_um) or math.isinf(feret_um):
        return "not_evaluable"
    return "excluded_below_10um" if feret_um < ISO_MIN_FERET_UM else "included"


def size_filter_metadata(microns_per_pixel, excluded_count, included_count):
    """Canonical, explicit metadata about the 10 um exclusion state."""
    mpp = validate_um_per_px(microns_per_pixel)
    if mpp is None:
        return {
            "available": False,
            "threshold_um": ISO_MIN_FERET_UM,
            "applied": False,
            "excluded_count": None,
            "included_count": None,
            "reason": "Physical calibration unavailable",
        }
    return {
        "available": True,
        "threshold_um": ISO_MIN_FERET_UM,
        "applied": True,
        "excluded_count": int(excluded_count),
        "included_count": int(included_count),
        "reason": None,
    }


@dataclass
class Calibration:
    """micrometers-per-pixel calibration for one image."""
    um_per_px: float | None = None
    source: str = "unavailable"     # auto_scalebar | manual | unavailable
    bar_length_um: float | None = None
    bar_length_px: float | None = None
    notes: str = ""

    @property
    def available(self):
        return self.um_per_px is not None and self.um_per_px > 0

    @property
    def microns_per_pixel(self):
        """Canonical conversion direction: microns = pixels * this value."""
        return self.um_per_px

    def to_dict(self):
        d = asdict(self)
        d["available"] = self.available
        d["microns_per_pixel"] = self.um_per_px
        return d


# ----------------------------------------------------------------- auto ----
_BAR_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(µm|um|μm|nm|mm)")

# scale bars typically sit within these bands; search bottom strip primarily
_SEARCH_BANDS = [
    (0.86, 1.00),   # bottom 14%
    (0.72, 0.88),   # above it
    (0.00, 0.14),   # top (rare but happens)
]


def _find_text_label(gray, x0, x1, y0, y1):
    """Locate a 'NN um' style label inside a band; returns (value_um, box)."""
    band = gray[y0:y1, x0:x1]
    if band.size == 0:
        return None
    _, th = cv2.threshold(band, 0, 255,
                          cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # digits are usually small thin components — dilate to merge into words
    th = cv2.dilate(th, np.ones((2, 2), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(th)
    boxes = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if 4 <= h <= band.shape[0] * 0.55 and 2 <= w <= band.shape[1] * 0.5:
            boxes.append((x, y, w, h))
    if not boxes:
        return None
    # group boxes into a single line cluster (leftmost..rightmost)
    xs = [b[0] for b in boxes]
    ys = [b[1] for b in boxes]
    xe = [b[0] + b[2] for b in boxes]
    ye = [b[1] + b[3] for b in boxes]
    gx0, gx1 = min(xs), max(xe)
    gy0, gy1 = min(ys), max(ye)
    if gx1 - gx0 < 8:
        return None
    # OCR is unavailable; we cannot read the number -> can't auto-calibrate
    # from text alone. Return the box so the bar-finder can use it as a hint.
    crop = band[gy0:gy1, gx0:gx1]
    return {"value_um": None, "box": (gx0 + x0, gy0 + y0,
                                      gx1 - gx0, gy1 - gy0), "crop": crop}


def _find_solid_bar(gray, y0, y1, x0, x1):
    """Find a solid horizontal dark (or bright) bar in the region.

    Returns its pixel length and thickness, or None.
    """
    region = gray[y0:y1, x0:x1]
    if region.size == 0:
        return None
    # a scale bar is a long thin run of extreme intensity
    for polarity in (cv2.THRESH_BINARY_INV, cv2.THRESH_BINARY):
        _, th = cv2.threshold(region, 0, 255, polarity + cv2.THRESH_OTSU)
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((2, 6), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(th)
        best = None
        for i in range(1, n):
            x, y, w, h, a = stats[i]
            if h > 40 or w < 30:
                continue
            fill = a / float(w * h)
            aspect = w / float(h)
            if fill > 0.55 and 6.0 <= aspect <= 60.0:
                if best is None or w > best[2]:
                    best = (x, y, w, h)
        if best:
            return {"length_px": float(best[2]),
                    "thickness_px": float(best[3]),
                    "box_abs": (x0 + best[0], y0 + best[1], best[2], best[3])}
    return None


def detect_scale_bar(gray):
    """Attempt automatic scale-bar detection.

    Without OCR we cannot read the labeled length, so automatic calibration
    only succeeds when a known bar-length declaration is provided (e.g. the
    acquisition metadata). This function finds and measures the BAR and any
    label region; callers with metadata can pair the measured bar length with
    the declared physical length.
    """
    h, w = gray.shape
    found = {"bar": None, "label_hint": None, "region": None}
    for fy0, fy1 in _SEARCH_BANDS:
        y0, y1 = int(h * fy0), int(h * fy1)
        bar = _find_solid_bar(gray, y0, y1, 0, w)
        if bar:
            bx, by, bw, bh = bar["box_abs"]
            label = _find_text_label(gray,
                                     max(0, bx - int(bw * 1.5)),
                                     min(w, bx + bw + int(bw * 3)),
                                     max(0, by - bh - 8),
                                     min(h, by + bh + 8))
            found.update(bar=bar, label_hint=label,
                         region=f"y {y0}-{y1}")
            return found
    return found


def auto_calibrate(gray, declared_bar_um=None):
    """Calibrate from a detected scale bar.

    declared_bar_um: the physical length of the scale bar, from trusted
    acquisition metadata. Without it (no OCR), automatic calibration is NOT
    possible and we return unavailable — never a guess.
    """
    det = detect_scale_bar(gray)
    bar = det.get("bar")
    if not bar or not declared_bar_um or declared_bar_um <= 0:
        return Calibration(notes="no trusted scale-bar length available")
    return Calibration(
        um_per_px=float(declared_bar_um) / bar["length_px"],
        source="auto_scalebar",
        bar_length_um=float(declared_bar_um),
        bar_length_px=bar["length_px"],
        notes=f"bar detected at {det.get('region')}")


def manual_calibrate(bar_length_px, bar_length_um):
    """Manual calibration from a user-measured bar (Phase 4 fallback)."""
    if not bar_length_px or not bar_length_um or bar_length_px <= 0 \
            or bar_length_um <= 0:
        return Calibration(notes="invalid manual calibration inputs")
    return Calibration(um_per_px=float(bar_length_um) / float(bar_length_px),
                       source="manual",
                       bar_length_um=float(bar_length_um),
                       bar_length_px=float(bar_length_px),
                       notes="manual calibration")


UNAVAILABLE = Calibration(notes="Scale unavailable")

# ------------------------------------------------------------- conversion ----


def convert_lengths(px_values, cal):
    """px values -> µm; returns (None-s if unavailable, unit)."""
    if not cal.available:
        return [None] * len(px_values), "px"
    return [v * cal.um_per_px for v in px_values], "µm"


def convert_areas(px2_values, cal):
    """px² values -> µm² (scale factor squared); None-s if unavailable."""
    if not cal.available:
        return [None] * len(px2_values), "px²"
    return [v * (cal.um_per_px ** 2) for v in px2_values], "µm²"
