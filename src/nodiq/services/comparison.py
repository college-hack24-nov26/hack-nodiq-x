#!/usr/bin/env python3
"""
services/comparison.py — sample-vs-sample comparison engine (Phase 7).

Compares two stored analyses on measured quantities only. Percentage-point
deltas for shares/ratios; percent deltas for scales. Never claims causation.
"""
import numpy as np


def _mean_roundness(rows):
    vals = [r["roundness"] for r in rows if isinstance(r.get("roundness"),
                                                       (int, float))]
    return float(np.mean(vals)) if vals else None


def _irregular_fraction(rows):
    n = len(rows)
    if not n:
        return None
    ir = sum(1 for r in rows if r.get("iso_class") != "V/VI")
    return ir / n * 100.0


def _size_stats(rows):
    areas = [r["area_px"] for r in rows if isinstance(r.get("area_px"),
                                                      (int, float))]
    diams = [r["equiv_diameter_px"] for r in rows
             if isinstance(r.get("equiv_diameter_px"), (int, float))]
    return {
        "mean_area_px": float(np.mean(areas)) if areas else None,
        "mean_diameter_px": float(np.mean(diams)) if diams else None,
        "n": len(areas),
    }


def _size_distribution(rows, bins=(0, 200, 400, 800, 1600, 3200, 10 ** 9)):
    areas = [r["area_px"] for r in rows if isinstance(r.get("area_px"),
                                                      (int, float))]
    hist, _ = np.histogram(areas, bins=bins)
    labels = [f"{bins[i]}-{bins[i+1]}" for i in range(len(bins) - 1)]
    labels[-1] = f">={bins[-2]}"
    return {lab: int(c) for lab, c in zip(labels, hist)}


def compare_analyses(a, b, label_a="A", label_b="B"):
    """Compare analysis dicts (payloads from analyze_for_frontend_json or the
    stored full analyses). Returns absolute + relative changes.

    Percentage points (pp) are used for shares (nodularity %, irregular %);
    percent change (%) for scale quantities (count, sizes).
    """
    iso_a = a.get("iso_nodularity_pct")
    iso_b = b.get("iso_nodularity_pct")
    count_a = a.get("nodule_count")
    count_b = b.get("nodule_count")
    jis_a = a.get("jis_nodularity_pct")
    jis_b = b.get("jis_nodularity_pct")

    rows_a = a.get("nodules") or []
    rows_b = b.get("nodules") or []

    size_a, size_b = _size_stats(rows_a), _size_stats(rows_b)
    round_a, round_b = _mean_roundness(rows_a), _mean_roundness(rows_b)
    irr_a, irr_b = _irregular_fraction(rows_a), _irregular_fraction(rows_b)

    def delta_pp(x, y):
        return None if (x is None or y is None) else round(y - x, 2)

    def delta_pct(x, y):
        if x is None or y is None or x == 0:
            return None
        return round((y - x) / x * 100.0, 2)

    comparison = {
        "sample_a": {"id": a.get("analysis_id") or a.get("id") or label_a,
                     "filename": a.get("filename")},
        "sample_b": {"id": b.get("analysis_id") or b.get("id") or label_b,
                     "filename": b.get("filename")},
        "nodularity": {
            "a_pct": iso_a, "b_pct": iso_b,
            "change_pp": delta_pp(iso_a, iso_b),
        },
        "jis_nodularity": {
            "a_pct": jis_a, "b_pct": jis_b,
            "change_pp": delta_pp(jis_a, jis_b),
        },
        "irregular_fraction": {
            "a_pct": round(irr_a, 2) if irr_a is not None else None,
            "b_pct": round(irr_b, 2) if irr_b is not None else None,
            "change_pp": (round(irr_b - irr_a, 2)
                          if irr_a is not None and irr_b is not None else None),
        },
        "nodule_count": {
            "a": count_a, "b": count_b,
            "change": (count_b - count_a
                       if isinstance(count_a, (int, float))
                       and isinstance(count_b, (int, float)) else None),
            "change_pct": delta_pct(count_a, count_b),
        },
        "mean_roundness": {
            "a": round(round_a, 4) if round_a is not None else None,
            "b": round(round_b, 4) if round_b is not None else None,
            "change_pp": delta_pp(round_a * 100 if round_a else None,
                                  round_b * 100 if round_b else None),
        },
        "size": {
            "mean_area_px": {
                "a": (round(size_a["mean_area_px"], 1)
                      if size_a["mean_area_px"] else None),
                "b": (round(size_b["mean_area_px"], 1)
                      if size_b["mean_area_px"] else None),
                "change_pct": (delta_pct(size_a["mean_area_px"],
                                         size_b["mean_area_px"])),
            },
            "mean_diameter_px": {
                "a": (round(size_a["mean_diameter_px"], 1)
                      if size_a["mean_diameter_px"] else None),
                "b": (round(size_b["mean_diameter_px"], 1)
                      if size_b["mean_diameter_px"] else None),
                "change_pct": (delta_pct(size_a["mean_diameter_px"],
                                         size_b["mean_diameter_px"])),
            },
        },
        "size_distribution": {"a": _size_distribution(rows_a),
                              "b": _size_distribution(rows_b)},
        "border_touching": {
            "a": a.get("border_touching"), "b": b.get("border_touching"),
        },
        "quality": {
            "a": (a.get("quality") or {}).get("score"),
            "b": (b.get("quality") or {}).get("score"),
        },
        "self_check": {
            "a": (a.get("self_check") or {}).get("count_accuracy_pct"),
            "b": (b.get("self_check") or {}).get("count_accuracy_pct"),
        },
    }

    # headline narrative (measured facts only, no causation)
    pp = comparison["nodularity"]["change_pp"]
    if pp is not None:
        sample_a = comparison['sample_a']['id']
        if pp > 0:
            body = (f"{abs(pp):.1f} percentage points higher than sample "
                    f"{sample_a} ({iso_b:.1f}% vs {iso_a:.1f}%).")
        elif pp < 0:
            body = (f"{abs(pp):.1f} percentage points lower than sample "
                    f"{sample_a} ({iso_b:.1f}% vs {iso_a:.1f}%).")
        else:
            body = (f"equivalent to sample {sample_a} "
                    f"({iso_b:.1f}% vs {iso_a:.1f}%).")
        comparison["summary"] = (
            f"Sample {comparison['sample_b']['id']} ISO nodularity is {body}")
    return comparison
