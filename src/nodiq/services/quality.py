#!/usr/bin/env python3
"""
services/quality.py — image quality gate for micrographs (Phase 3).

Everything here is MEASURED from pixels. No learned models, no randomness.
The gate never rejects unnecessarily: REJECT only when the image cannot
plausibly contain analyzable graphite (blank, pure noise, mostly dark
non-micrograph, or resolution so low that particles are sub-pixel).

Usage:
    from nodiq.services.quality import assess_quality
    report = assess_quality(gray, source_width, source_height)
"""
import cv2
import numpy as np

# minimum plausible working width for meaningful nodule statistics
MIN_WORKING_WIDTH = 600


def _res_score(src_w, src_h):
    """Resolution adequacy: working pixels vs the ~600px minimum."""
    if src_w <= 0 or src_h <= 0:
        return 0.0
    return float(min(100.0, src_w / MIN_WORKING_WIDTH * 100.0))


def _sharpness_score(gray):
    """Focus proxy: variance of the Laplacian, normalized on the micrograph
    domain (measured: polished scans sit at lap_var ~2 at 1920px; synthetic
    hard-edged images ~500; blank/defocused <1)."""
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    var = float(lap.var())
    score = 100.0 * min(1.0, np.log1p(var) / np.log1p(50.0))
    return score, var


def _contrast_score(gray):
    """RMS contrast: std of intensities (0-255 -> 0-100)."""
    std = float(gray.std())
    return float(min(100.0, std / 60.0 * 100.0)), std


def _illumination_score(gray):
    """Illumination uniformity from the BACKGROUND field, not the particles.

    A morphological opening with a large kernel removes dark particles and
    leaves the slowly-varying background/illumination field; uneven
    illumination then shows as a smooth brightness gradient. Particle-scale
    structure no longer affects the metric (real micrographs have graphite
    everywhere, which is not an illumination problem).
    """
    # Robust background estimate: per-block 90th percentile. The matrix is
    # the brightest phase in nearly every block, so this tracks the
    # illumination field regardless of graphite density. Uneven illumination
    # = a large smooth PLANE component; texture that survives the plane fit
    # is matrix structure, not a lighting problem.
    h, w = gray.shape
    bs = max(8, min(h, w) // 32)
    hb, wb = h // bs, w // bs
    if hb < 4 or wb < 4:
        return 100.0, 0.0
    blocks = gray[:hb * bs, :wb * bs].reshape(hb, bs, wb, bs).astype(np.float32)
    bg = np.percentile(blocks, 90, axis=(1, 3))
    mean_v = float(bg.mean())
    if mean_v < 1.0:
        return 0.0, mean_v                     # near-black: darkness check fires
    yy, xx = np.mgrid[0:hb, 0:wb]
    A = np.stack([xx.ravel(), yy.ravel(), np.ones(hb * wb)], axis=1)
    coef, *_ = np.linalg.lstsq(A, bg.ravel(), rcond=None)
    plane = (A @ coef).reshape(hb, wb)
    ampl = float(plane.max() - plane.min()) / mean_v   # relative plane swing
    # measured scale: flat ~0.02, real scans 0.07-0.30, gross gradient >1.0
    return float(max(0.0, 100.0 - max(0.0, ampl - 0.10) * 200.0)), ampl


def _darkness_metrics(gray):
    """Fraction of very dark pixels; micrograph matrix is light."""
    frac = float((gray < 40).mean())
    return frac


def _noise_score(gray):
    """Noise estimate: robust median absolute deviation of the laplacian.

    High-frequency sensor noise shows as heavy laplacian tails.
    """
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    mad = float(np.median(np.abs(lap - np.median(lap))))
    # typical clean micrograph: MAD < 10; noisy: > 30
    return float(max(0.0, 100.0 - mad * 4.0)), mad


def _saturation_metrics(bgr_or_none):
    """Color saturation stats; grayscale images report None."""
    if bgr_or_none is None or bgr_or_none.ndim < 3:
        return None, None
    hsv = cv2.cvtColor(bgr_or_none, cv2.COLOR_BGR2HSV)
    sat = hsv[:, :, 1]
    return float(sat.mean()), float((sat > 150).mean())


def _artifact_indicators(gray):
    """Cheap artifact checks: clipping (over/under-exposure) and a crude
    text/graphics heuristic (many tiny high-contrast components)."""
    over = float((gray > 250).mean())
    under = float((gray < 5).mean())
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    n, _, stats, _ = cv2.connectedComponentsWithStats(th.astype(np.uint8))
    small = int(np.sum((stats[1:, cv2.CC_STAT_AREA] > 0)
                       & (stats[1:, cv2.CC_STAT_AREA] < 20))) if n > 1 else 0
    return {"overexposed_frac": over, "underexposed_frac": under,
            "tiny_components": small}


def assess_quality(gray, source_width=0, source_height=0, bgr=None):
    """Full quality report. All values measured from the image."""
    h, w = gray.shape
    res = _res_score(source_width or w, source_height or h)
    sharp, lap_var = _sharpness_score(gray)
    contrast, std = _contrast_score(gray)
    illum, mean_brightness = _illumination_score(gray)
    dark_frac = _darkness_metrics(gray)
    noise, noise_mad = _noise_score(gray)
    sat_mean, sat_high_frac = _saturation_metrics(bgr)
    artifacts = _artifact_indicators(gray)

    checks = {}
    warnings = []

    def check(name, score, warn_below=50.0, reject_below=15.0, msg=""):
        if score >= warn_below:
            checks[name] = "PASS"
        elif score >= reject_below:
            checks[name] = "WARNING"
            if msg:
                warnings.append(msg)
        else:
            checks[name] = "REJECT"
            if msg:
                warnings.append(msg)
        return checks[name]

    check("resolution", res, msg=(
        f"input width {int(source_width or w)}px is low; smallest particles "
        "may be below resolution"))
    check("blur", sharp, warn_below=35.0, reject_below=10.0,
          msg="low high-frequency content: image looks soft or is a very "
              "smooth scan; shape metrics less reliable")
    check("contrast", contrast, msg="low contrast; thresholding may be unstable")
    check("brightness", illum, warn_below=70.0, reject_below=25.0,
          msg="uneven illumination across the field of view")
    check("noise", noise, msg="high sensor noise; consider denoising or re-scan")

    # darkness / not-a-micrograph guard (uses measured dark fraction)
    if dark_frac > 0.6:
        checks["graphite_presence"] = "WARNING"
        warnings.append("image is mostly dark: does not look like a polished "
                        "ductile-iron micrograph")
    else:
        checks["graphite_presence"] = "PASS"
    if artifacts["overexposed_frac"] > 0.15 or artifacts["underexposed_frac"] > 0.15:
        checks["exposure"] = "WARNING"
        warnings.append("large clipped regions (over/under-exposure)")
    else:
        checks["exposure"] = "PASS"

    # overall score: weighted mean of the numeric metrics
    weights = {"resolution": 0.25, "focus": 0.2, "contrast": 0.2,
               "illumination": 0.15, "noise": 0.2}
    score = (res * weights["resolution"] + sharp * weights["focus"]
             + contrast * weights["contrast"] + illum * weights["illumination"]
             + noise * weights["noise"])

    n_reject = sum(1 for v in checks.values() if v == "REJECT")
    n_warn = sum(1 for v in checks.values() if v == "WARNING")
    if n_reject or score < 30:
        status = "REJECT"
    elif n_warn or score < 65:
        status = "WARNING"
    else:
        status = "PASS"

    metrics = {
        "resolution": round(res, 1),
        "focus": round(float(sharp), 1),
        "contrast": round(contrast, 1),
        "illumination": round(float(illum), 1),
        "noise": round(noise, 1),
    }
    return {
        "status": status,               # PASS | WARNING | REJECT
        "score": int(round(score)),     # 0-100
        "checks": checks,
        "metrics": metrics,
        "warnings": warnings,
        "measurements": {
            "source_width": int(source_width or w),
            "source_height": int(source_height or h),
            "working_width": int(w),
            "laplacian_variance": round(lap_var, 2),
            "contrast_std": round(std, 2),
            "mean_brightness": round(float(mean_brightness), 2),
            "dark_fraction": round(dark_frac, 4),
            "noise_mad": round(noise_mad, 2),
            "mean_saturation": (round(sat_mean, 2)
                                if sat_mean is not None else None),
            "artifacts": {k: round(v, 4) if isinstance(v, float) else v
                          for k, v in artifacts.items()},
        },
        # the engine always runs; the gate informs interpretation only
        "engine_ran": True,
    }
