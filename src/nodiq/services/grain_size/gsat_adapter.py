"""GSAT adapter — invokes the REAL NIST Grain Size Analysis Tools code.

The algorithm is deliberately NOT re-implemented here:

* Segmentation runs GSAT's own driver functions
  (``imppy3d_functions.ski_driver_functions.apply_driver_*``: non-local
  means denoise -> unsharp-mask sharpen -> hysteresis threshold ->
  morphological closing -> small-hole / small-island removal) — the same
  chain as ``ex_segmentation/*/batch_segment_single_image.py``.
* The ASTM E112 circle-and-line intercept measurement runs GSAT's own
  ``imppy3d_functions.grain_size_functions``
  (``find_intersections`` / ``measure_line_dist`` / ``measure_circular_dist``
  / ``mark_segments_on_image``) with the same pattern geometry as
  ``ex_grain_intercept/*/count_intersects_circle_pattern.py``.
* Crop / relative-density helpers come from ``cv_processing_wrappers`` and
  the boundary padding from ``volume_image_processing``.

License: GSAT is NIST-developed software (public-service statement in
``grain-size-analysis-tools-main/LICENSE.md``). Modified/adapted use must
carry the notice that changes were made and acknowledge NIST as the source —
this adapter file is that notice; the acknowledgement is also surfaced in the
result payload and in generated reports.

Everything returned here is measured by GSAT code on the actual image. When
an input precondition is not met (no segments found, no calibration), the
corresponding metric is simply absent and a warning explains why.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from nodiq.core.config import REPO_ROOT, THIRD_PARTY_GSAT

ROOT = REPO_ROOT
GSAT_DIR = THIRD_PARTY_GSAT
_GSAT_PKG_PARENT = str(GSAT_DIR)

ENGINE_ID = "gsat"
ENGINE_NAME = "GSAT — Grain Size Analysis Tools (NIST)"

# Default parameters mirror the values documented in GSAT's own
# ex_segmentation/optical_etched/batch_segment_single_image.py example.
DEFAULT_PARAMS: Dict[str, Any] = {
    "denoise": ["nl_means", 0.04, 5, 7],          # h, patch size, search dist
    "sharpen": ["unsharp_mask", 2, 0.3],           # radius, amount
    "threshold": ["hysteresis_threshold", 128, 200],  # low, high intensity
    "morph": [0, 1, 1],                            # closing, disk, radius 1
    "max_hole_sz": 4,                              # remove_small_holes (px^2)
    "min_feat_sz": 64,                             # remove_small_objects (px^2)
    "polarity": "auto",                            # auto | boundaries_white | boundaries_black
}

_MIN_INTERCEPT_SIDE = 64   # below this the E112 pattern is meaningless


def _ensure_gsat_path() -> None:
    os.environ.setdefault("MPLBACKEND", "Agg")   # headless-safe (GSAT imports pyplot)
    if _GSAT_PKG_PARENT not in sys.path:
        sys.path.insert(0, _GSAT_PKG_PARENT)


def _gsat_modules():
    """Import GSAT's modules (as the package they ship as)."""
    _ensure_gsat_path()
    from imppy3d_functions import ski_driver_functions as sdrv          # noqa: WPS433
    from imppy3d_functions import grain_size_functions as gsz           # noqa: WPS433
    from imppy3d_functions import cv_processing_wrappers as cwrap       # noqa: WPS433
    from imppy3d_functions import volume_image_processing as vol        # noqa: WPS433
    return sdrv, gsz, cwrap, vol


def engine_fingerprint() -> str:
    """Short sha256 of the GSAT modules actually executed (traceability)."""
    h = hashlib.sha256()
    pkg = GSAT_DIR / "imppy3d_functions"
    for name in ("ski_driver_functions.py", "grain_size_functions.py",
                 "cv_processing_wrappers.py", "volume_image_processing.py"):
        f = pkg / name
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()[:12]


def availability() -> Dict[str, Any]:
    """Honest availability report — no engine is ever claimed without a
    successful import of its real implementation."""
    if not GSAT_DIR.is_dir():
        return {
            "available": False,
            "engine": ENGINE_ID,
            "engine_name": ENGINE_NAME,
            "error": "grain-size-analysis-tools-main/ not found next to the "
                     "application root",
        }
    try:
        _gsat_modules()
    except Exception as exc:
        return {
            "available": False,
            "engine": ENGINE_ID,
            "engine_name": ENGINE_NAME,
            "error": f"GSAT dependency import failed: "
                     f"{type(exc).__name__}: {exc}",
            "install_hint": "pip install -r "
                            "grain-size-analysis-tools-main/dependencies/"
                            "requirements_py310.txt",
        }
    return {
        "available": True,
        "engine": ENGINE_ID,
        "engine_name": ENGINE_NAME,
        "license": "NIST software licensing statement "
                   "(grain-size-analysis-tools-main/LICENSE.md); NIST "
                   "acknowledged as the source",
        "implementation_fingerprint": engine_fingerprint(),
    }


# --------------------------------------------------------------------------- #
# segmentation
# --------------------------------------------------------------------------- #

def _normalize_boundary_polarity(mask: np.ndarray, mode: str
                                 ) -> Tuple[np.ndarray, str]:
    """Grain boundaries must be WHITE for GSAT's intercept code.

    The threshold stage segments whatever is bright; on etched optical
    micrographs the boundaries can be either bright or dark. Grain-boundary
    pixels are a thin minority, so the polarity with the smaller white
    fraction is the boundary polarity. The choice is recorded in the payload.
    """
    white_frac = float(np.count_nonzero(mask)) / float(mask.size)
    if mode == "boundaries_white":
        return mask, "manual: boundaries treated as bright"
    if mode == "boundaries_black":
        return 255 - mask, "manual: boundaries treated as dark (mask inverted)"
    if white_frac <= 0.5:
        return mask, f"auto: bright-pixel fraction {white_frac:.3f} kept as " \
                     "boundaries"
    return 255 - mask, f"auto: bright-pixel fraction {white_frac:.3f} — " \
                       "inverted so thin dark lines become white boundaries"


def segment_gsat(bgr: np.ndarray, params: Optional[Dict[str, Any]] = None
                 ) -> Dict[str, Any]:
    """Run GSAT's segmentation chain; returns boundary mask + diagnostics."""
    import warnings as _warnings

    import cv2
    from skimage import morphology as morph
    from skimage.util import img_as_bool, img_as_ubyte

    sdrv, _gsz, cwrap, _vol = _gsat_modules()

    p = {**DEFAULT_PARAMS, **(params or {})}
    warnings: List[str] = []

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    img = gray.copy()
    # skimage deprecation chatter from GSAT's calls is suppressed here only
    # (it is upstream code we must not modify)
    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore", FutureWarning)
        img = sdrv.apply_driver_denoise(img, list(p["denoise"]), quiet_in=True)
        img = sdrv.apply_driver_sharpen(img, list(p["sharpen"]), quiet_in=True)
        preprocessed = img.copy()      # diagnostic image (post filter, pre threshold)
        img = sdrv.apply_driver_thresholding(img, list(p["threshold"]), quiet_in=True)
        img = sdrv.apply_driver_morph(img, list(p["morph"]), quiet_in=True)

        img_bool = img_as_bool(img)
        img_bool = morph.remove_small_holes(img_bool, int(p["max_hole_sz"]),
                                            connectivity=1)
        img_bool = morph.remove_small_objects(img_bool, int(p["min_feat_sz"]),
                                              connectivity=1)
    mask = img_as_ubyte(img_bool)

    mask, polarity_note = _normalize_boundary_polarity(mask,
                                                       str(p["polarity"]))
    rel_density = float(cwrap.calc_rel_density(mask, quiet_in=True))
    white_frac = rel_density
    if white_frac < 0.002:
        warnings.append(
            "GSAT segmentation found almost no grain-boundary pixels "
            f"({white_frac * 100:.2f}% of the image). The etch/contrast of "
            "this micrograph may be too weak for boundary segmentation — "
            "intercept measurements below may be unreliable or empty.")
    elif white_frac > 0.5:
        warnings.append(
            "GSAT boundary segmentation covers a large share of the image "
            f"({white_frac * 100:.1f}%). Check the polarity setting "
            "(boundaries bright vs dark) for this micrograph.")

    return {
        "mask": mask,
        "preprocessed": preprocessed,
        "parameters": {
            "denoise": p["denoise"],
            "sharpen": p["sharpen"],
            "threshold": p["threshold"],
            "morphology": p["morph"],
            "max_hole_sz": p["max_hole_sz"],
            "min_feat_sz": p["min_feat_sz"],
            "polarity": p["polarity"],
            "polarity_decision": polarity_note,
        },
        "boundary_density_pct": round(rel_density * 100.0, 3),
        "warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# ASTM E112 intercept measurement (GSAT implementation)
# --------------------------------------------------------------------------- #

def _continuous_trace(coords, is_circle, gsz, mask):
    rc = np.transpose(np.vstack((coords[0], coords[1])))
    if is_circle:
        rc = gsz.make_continuous_circle(rc)
        rc = gsz.find_new_start_on_circle(rc, mask)
    else:
        rc = gsz.make_continuous_line(rc)
    return rc


def e112_intercept_gsat(boundary_mask: np.ndarray,
                        color_bgr: Optional[np.ndarray] = None,
                        um_per_px: Optional[float] = None
                        ) -> Dict[str, Any]:
    """GSAT's ASTM E112 circle-and-line intercept measurement.

    Reproduces the geometry of GSAT's count_intersects_circle_pattern.py:
    four straight lines (horizontal, vertical, two diagonals) plus three
    concentric circles inscribed in the center square of the segmented image.
    Segment lengths come from GSAT's own measurement functions.
    """
    import cv2
    from skimage import draw as skidraw

    _sdrv, gsz, cwrap, vol = _gsat_modules()

    warnings: List[str] = []
    h, w = boundary_mask.shape[:2]
    side = int(min(h, w))
    if side < _MIN_INTERCEPT_SIDE:
        return {
            "available": False,
            "reason": f"image side {side} px is below the minimum "
                      f"{_MIN_INTERCEPT_SIDE} px for the E112 intercept "
                      "pattern",
            "warnings": ["Image too small for the intercept pattern — no "
                         "intercept measurements were made."],
        }

    # Center square crop (GSAT crop_img) with a coordinate ramp so every
    # pattern pixel can later be mapped back onto the original image.
    crop_mask = cwrap.crop_img(boundary_mask, (side, side), quiet_in=True)
    ramp = np.arange(h * w, dtype=np.int32).reshape(h, w)
    crop_ramp = cwrap.crop_img(ramp, (side, side), quiet_in=True)

    # GSAT pads the boundary by one black pixel before tracing (so pattern
    # pixels at the very edge still see a border transition).
    padded = vol.pad_image_boundary(crop_mask, cval_in=0, n_pad_in=1,
                                    quiet_in=True)
    # bookkeeping-only pad of the coordinate ramp (GSAT's pad helper is
    # uint8-bound; the -1 sentinel marks the padding ring)
    padded_ramp = np.pad(crop_ramp, 1, mode="constant", constant_values=-1)
    n_row2, n_col2 = padded.shape

    margin = int(np.round(0.05 * side))
    r_center = int(np.floor(n_row2 / 2.0))
    c_center = int(np.floor(n_col2 / 2.0))
    max_diam = int(np.amin(padded.shape))

    circ_r = [int(np.round(0.7958 * max_diam / 2.0)),
              int(np.round(0.5305 * max_diam / 2.0)),
              int(np.round(0.2653 * max_diam / 2.0))]

    line_defs = [
        ("horizontal", False, (n_row2 - 1 - margin, 0),
                        (n_row2 - 1 - margin, n_col2 - 1)),
        ("vertical", False, (0, margin), (n_row2 - 1, margin)),
        ("diagonal_tl_br", False, (0, 0), (n_row2 - 1, n_col2 - 1)),
        ("diagonal_tr_bl", False, (0, n_col2 - 1), (n_row2 - 1, 0)),
    ]

    traces = []          # (label, kind, rc coords, measured distances)
    total_dists: List[float] = []
    total_intersections = 0

    for label, is_circle, p0, p1 in line_defs:
        rr, cc = skidraw.line(p0[0], p0[1], p1[0], p1[1])
        rc = _continuous_trace((rr, cc), is_circle, gsz, padded)
        traces.append((label, "line", rc))

    for i, rad in enumerate(circ_r):
        rr, cc = skidraw.circle_perimeter(r_center, c_center, rad)
        rc = _continuous_trace((rr, cc), True, gsz, padded)
        traces.append((f"circle_{i + 1}", "circle", rc))

    marked = padded.copy()
    per_trace = []
    for idx, (label, kind, rc) in enumerate(traces, start=1):
        rr = rc[:, 0].astype(int)
        cc = rc[:, 1].astype(int)
        rr = np.clip(rr, 0, n_row2 - 1)
        cc = np.clip(cc, 0, n_col2 - 1)
        sampled = padded[rr, cc].astype(np.int16)
        segs = gsz.find_intersections(sampled)
        if segs.size:
            if kind == "line":
                dists = gsz.measure_line_dist(segs, rc)
            else:
                dists = gsz.measure_circular_dist(segs, rc)
            marked = gsz.mark_segments_on_image(marked, segs, rc)
        else:
            dists = np.zeros(0)
        intersections = int(np.count_nonzero(sampled[1:] != sampled[:-1]))
        total_intersections += intersections
        dist_list = [float(d) for d in np.atleast_1d(dists)]
        total_dists.extend(dist_list)
        per_trace.append({
            "trace_id": idx,
            "label": label,
            "kind": kind,
            "trace_length_px": int(rc.shape[0]),
            "grain_segments": len(dist_list),
            "boundary_intersections": intersections,
            "mean_segment_px": (round(float(np.mean(dist_list)), 3)
                                if dist_list else None),
        })

    if not total_dists:
        return {
            "available": False,
            "reason": "no grain-boundary intersections found along the E112 "
                      "intercept pattern",
            "per_trace": per_trace,
            "boundary_intersections": total_intersections,
            "warnings": ["GSAT found zero grain segments on the intercept "
                         "pattern — the segmentation mask likely contains "
                         "no (or only noise) boundaries. Grain-size number "
                         "not computed."],
            "images": {"intercept": marked},
        }

    arr = np.asarray(total_dists, dtype=np.float64)
    measurements: Dict[str, Any] = {
        "grain_segments": int(arr.size),
        "boundary_intersections": int(total_intersections),
        "mean_lineal_intercept_px": round(float(arr.mean()), 3),
        "median_lineal_intercept_px": round(float(np.median(arr)), 3),
        "std_lineal_intercept_px": round(float(arr.std()), 3),
        "min_lineal_intercept_px": round(float(arr.min()), 3),
        "max_lineal_intercept_px": round(float(arr.max()), 3),
        "per_trace": per_trace,
    }

    if isinstance(um_per_px, (int, float)) and um_per_px > 0:
        mean_um = measurements["mean_lineal_intercept_px"] * float(um_per_px)
        measurements["mean_lineal_intercept_um"] = round(mean_um, 3)
        mean_mm = mean_um / 1000.0
        if mean_mm > 0:
            import math
            g_value = -6.643856 * math.log10(mean_mm) - 3.288
            measurements["astm_grain_size_number"] = round(g_value, 2)
            measurements["astm_grain_size_number_basis"] = (
                "ASTM E112 intercept-method relation "
                "G = -6.643856*log10(mean intercept in mm) - 3.288, applied "
                "to the calibrated GSAT mean lineal intercept. Automated "
                "estimate — NOT a certified ASTM compliance determination; "
                "formal determinations also depend on specimen preparation, "
                "etching, calibration traceability and the complete "
                "standard's requirements.")
    else:
        warnings.append(
            "No spatial calibration (um/px) was available — GSAT "
            "intercept measurements are reported in pixels only and no "
            "ASTM grain-size number was computed.")

    # ---- overlays -----------------------------------------------------------
    # 1) GSAT's own native marked-image output (square padded mask, chord
    #    segments marked gray at intensity 150, boundaries white).
    images = {"intercept": marked}

    # 2) The same pattern + marked chords mapped back onto the original
    #    micrograph, with the boundary mask overlaid.
    if color_bgr is not None:
        overlay = color_bgr.copy()
        boundary_colored = np.zeros_like(overlay)
        boundary_colored[boundary_mask > 0] = (0, 200, 80)
        overlay = cv2.addWeighted(overlay, 1.0, boundary_colored, 0.55, 0)
        for label, kind, rc in traces:
            cols = padded_ramp[rc[:, 0].astype(int), rc[:, 1].astype(int)]
            valid = cols >= 0
            ys, xs = np.divmod(cols[valid].astype(np.int64), w)
            color = (255, 170, 40) if kind == "line" else (255, 80, 200)
            for x, y in zip(xs.tolist(), ys.tolist()):
                overlay[y, x] = color
        images["overlay"] = overlay

    return {
        "available": True,
        "pattern": "ASTM E112 circle-and-line intercept pattern (GSAT): "
                   "4 straight lines + 3 concentric circles inscribed in the "
                   "center square of the segmented image",
        "measurements": measurements,
        "warnings": warnings,
        "images": images,
    }
