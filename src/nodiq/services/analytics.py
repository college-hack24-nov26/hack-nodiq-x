#!/usr/bin/env python3
"""
services/analytics.py — batch intelligence (Phase 8) + SPC (Phase 9).

All statistics computed from stored analysis records. SPC control limits are
only produced when there is enough data (>= 8 points); otherwise the API says
so honestly instead of inventing limits.
"""
import numpy as np


# ------------------------------------------------------- batch analytics ----
def _series(records, key):
    return [r[key] for r in records
            if isinstance(r.get(key), (int, float))]


def batch_statistics(records, iso_accept_threshold=80.0):
    """Aggregate stats over analysis history records.

    Records need at minimum: iso_nodularity_pct. Optional: nodule_count,
    accuracy_pct/confidence_pct, created_at.
    """
    iso = _series(records, "iso_nodularity_pct")
    counts = _series(records, "nodule_count")
    acc = _series(records, "accuracy_pct") or _series(records,
                                                      "confidence_pct")

    def dist(values):
        if not values:
            return None
        return {
            "min": round(float(np.min(values)), 2),
            "p25": round(float(np.percentile(values, 25)), 2),
            "median": round(float(np.median(values)), 2),
            "p75": round(float(np.percentile(values, 75)), 2),
            "max": round(float(np.max(values)), 2),
            "mean": round(float(np.mean(values)), 2),
            "std": round(float(np.std(values, ddof=1)) if len(values) > 1
                         else 0.0, 2),
            "cv_pct": (round(float(np.std(values, ddof=1))
                             / float(np.mean(values)) * 100.0, 2)
                       if len(values) > 1 and np.mean(values) else None),
        }

    passed = sum(1 for v in iso if v >= iso_accept_threshold)
    return {
        "samples": len(records),
        "iso_accept_threshold": iso_accept_threshold,
        "pass_rate_pct": round(passed / len(iso) * 100.0, 2) if iso else None,
        "fail_rate_pct": (round((len(iso) - passed) / len(iso) * 100.0, 2)
                          if iso else None),
        "nodularity": dist(iso),
        "nodule_count": dist(counts),
        "self_check_accuracy": dist(acc),
        "histogram_iso": _histogram(iso),
    }


def _histogram(values, bins=None):
    if not values:
        return None
    values = list(values)
    lo = float(np.floor(min(values) / 10) * 10)
    hi = float(np.ceil(max(values) / 10) * 10) or lo + 10
    if bins is None:
        bins = list(np.arange(lo, hi + 10, 10.0))
    hist, edges = np.histogram(values, bins=bins)
    return {"bins": [round(e, 1) for e in edges],
            "counts": [int(c) for c in hist]}


def distribution_by_metric(records):
    """Distributions tracked for the batch intelligence view."""
    return {
        "nodularity": _histogram(_series(records, "iso_nodularity_pct")),
        "count": _histogram(_series(records, "nodule_count")),
    }


# ------------------------------------------------------------------ SPC ----
# Western-Electric-style rules (simplified, statistically defensible):
#   Rule 1: any point beyond 3 sigma (UCL/LCL)
#   Rule 2: two of three consecutive points beyond 2 sigma (same side)
#   Rule 3: eight consecutive points on one side of the center line

def spc(values, metric="nodularity_pct", target=None, min_points=8):
    """Statistical process control summary for a metric series.

    Returns control limits only when len(values) >= min_points.
    """
    vals = [v for v in values if isinstance(v, (int, float))]
    n = len(vals)
    if n < min_points:
        return {
            "metric": metric,
            "n": n,
            "sufficient_data": False,
            "note": (f"only {n} data points; at least {min_points} required "
                     "before control limits are meaningful"),
            "values": vals,
        }
    arr = np.asarray(vals, dtype=float)
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    ucl, lcl = mean + 3 * std, mean - 3 * std
    two_hi, two_lo = mean + 2 * std, mean - 2 * std

    outliers = []
    for i, v in enumerate(vals):
        if v > ucl or v < lcl:
            outliers.append({"index": i, "value": round(v, 2),
                             "reason": "beyond 3-sigma control limit",
                             "z": round((v - mean) / std, 2) if std else None})

    # Rule 2
    for i in range(2, n):
        w = arr[i - 2:i + 1]
        hi = np.sum(w > two_hi)
        lo = np.sum(w < two_lo)
        if hi >= 2:
            outliers.append({"index": i, "value": round(float(arr[i]), 2),
                             "reason": "2 of 3 consecutive points above 2-sigma",
                             "z": round((arr[i] - mean) / std, 2) if std else None})
        elif lo >= 2:
            outliers.append({"index": i, "value": round(float(arr[i]), 2),
                             "reason": "2 of 3 consecutive points below 2-sigma",
                             "z": round((arr[i] - mean) / std, 2) if std else None})

    # Rule 3
    side = np.sign(arr - mean)
    run = 1
    for i in range(1, n):
        run = run + 1 if side[i] == side[i - 1] and side[i] != 0 else 1
        if run == 8:
            outliers.append({"index": i, "value": round(float(arr[i]), 2),
                             "reason": ("8 consecutive points "
                                        + ("above" if side[i] > 0 else "below")
                                        + " center line"), "z": None})

    # dedupe by (index, reason)
    seen = set()
    dedup = []
    for o in outliers:
        k = (o["index"], o["reason"])
        if k not in seen:
            seen.add(k)
            dedup.append(o)

    trend = "stable"
    if n >= 10:
        x = np.arange(n)
        slope = float(np.polyfit(x, arr, 1)[0])
        if std > 0 and abs(slope) > 0.1 * std:
            trend = "increasing" if slope > 0 else "decreasing"

    return {
        "metric": metric,
        "n": n,
        "sufficient_data": True,
        "mean": round(mean, 2),
        "std": round(std, 2),
        "ucl": round(ucl, 2),
        "lcl": round(lcl, 2),
        "target": target if target is not None else round(mean, 2),
        "trend": trend,
        "outliers": dedup,
        "violations": len(dedup),
        "values": vals,
    }
