#!/usr/bin/env python3
"""
services/anomalies.py — anomaly detection (Phase 10) + metallurgical
decision-support (Phase 11). Deterministic and fully explainable: every
anomaly carries reasons[]. The LLM may EXPLAIN these later — never fabricate.

Evidence levels used in outputs:
  MEASURED      — direct engine output
  OBSERVED      — derived statistics
  INTERPRETATION— rule-based morphology reading (uncertainty stated)
  RECOMMENDATION— verification steps (never a cause claim)
"""
import numpy as np

from nodiq.services.analytics import batch_statistics

ISO_ACCEPT = 80.0
ACC_GATE = 95.0


def _fmt(x, nd=1):
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "—"


def assess_analysis(record, batch_records, full=None):
    """Score one analysis against the batch/history. Returns the anomaly card.

    record: history row (iso_nodularity_pct, nodule_count, accuracy_pct...)
    full:   stored full payload (nodules rows, quality, self_check) — optional
    """
    signals = []
    reasons = []

    iso = record.get("iso_nodularity_pct")
    count = record.get("nodule_count")
    acc = record.get("accuracy_pct")

    # -- threshold-based signals (absolute) ----------------------------------
    if isinstance(iso, (int, float)):
        if iso < ISO_ACCEPT:
            signals.append(("low_nodularity", 60.0))
            reasons.append(
                f"Measured ISO nodularity {iso:.1f}% is below the {ISO_ACCEPT:.0f}% "
                "acceptance threshold")

    if isinstance(acc, (int, float)) and acc < ACC_GATE:
        signals.append(("low_self_check", 50.0))
        reasons.append(
            f"Self-check accuracy {acc:.1f}% is below the {ACC_GATE:.0f}% gate — "
            "detections may not be reliable for this image")

    # -- batch-relative signals (z-scores) -----------------------------------
    batch = batch_statistics([r for r in batch_records
                              if r is not record]) if batch_records else None
    nod = (batch or {}).get("nodularity") or {}
    if isinstance(iso, (int, float)) and nod.get("mean") is not None \
            and nod.get("std"):
        z = (iso - nod["mean"]) / nod["std"]
        if z <= -2.0:
            signals.append(("batch_deviation_low", min(90.0, 40 + abs(z) * 15)))
            reasons.append(
                f"Nodularity is {abs(z):.1f} standard deviations below the "
                f"batch mean ({nod['mean']:.1f}%)")
        elif z >= 2.0:
            signals.append(("batch_deviation_high", min(70.0, 30 + z * 12)))
            reasons.append(
                f"Nodularity is {z:.1f} standard deviations above the batch "
                f"mean — verify sample identity/processing")

    cnt_stats = (batch or {}).get("nodule_count") or {}
    if isinstance(count, (int, float)) and cnt_stats.get("mean") is not None \
            and cnt_stats.get("std"):
        zc = (count - cnt_stats["mean"]) / cnt_stats["std"]
        if abs(zc) >= 2.5:
            signals.append(("abnormal_count", min(75.0, 35 + abs(zc) * 10)))
            reasons.append(
                f"Nodule count {_fmt(count, 0)} deviates {abs(zc):.1f} sigma "
                f"from batch mean {_fmt(cnt_stats['mean'], 0)}")

    # -- morphology-distribution signals (needs full payload) ----------------
    if full:
        rows = full.get("nodules") or []
        n = len(rows)
        if n:
            irr = sum(1 for r in rows if r.get("iso_class") != "V/VI") / n * 100
            if irr > 60:
                signals.append(("irregular_dominant", 45.0))
                reasons.append(
                    f"Irregular graphite fraction is {irr:.1f}% of particles")
            areas = [r["area_px"] for r in rows
                     if isinstance(r.get("area_px"), (int, float))]
            if areas:
                big = sum(1 for a in areas if a > 4 * float(np.median(areas)))
                if big / len(areas) > 0.15:
                    signals.append(("unusual_size_distribution", 35.0))
                    reasons.append(
                        f"{big}/{len(areas)} particles are >4x the median size")
            rounds = [r["roundness"] for r in rows
                      if isinstance(r.get("roundness"), (int, float))]
            if rounds and np.std(rounds) > 0.18:
                signals.append(("unusual_roundness_spread", 30.0))
                reasons.append(
                    "Roundness distribution is unusually wide "
                    f"(std {float(np.std(rounds)):.2f})")
        quality = (full.get("quality") or {}).get("score")
        if isinstance(quality, (int, float)) and quality < 50:
            signals.append(("poor_image_quality", 40.0))
            reasons.append(f"Image quality score {quality}/100 is poor")
        border = full.get("border_touching")
        if isinstance(border, (int, float)) and n and border / n > 0.4:
            signals.append(("high_border_fraction", 30.0))
            reasons.append(
                f"{border}/{n} particles touch the image border — field of "
                "view may be cropped unusually tight")

    if not signals:
        return {
            "analysis_id": record.get("id"),
            "anomaly_score": 0,
            "severity": "NONE",
            "is_anomaly": False,
            "reasons": [],
            "signals": [],
        }

    strengths = sorted((s for _, s in signals), reverse=True)
    score = min(100.0, strengths[0] + 0.15 * sum(strengths[1:]))
    severity = ("HIGH" if score >= 70 else "MEDIUM" if score >= 40
                else "LOW")
    return {
        "analysis_id": record.get("id"),
        "anomaly_score": round(score),
        "severity": severity,
        "is_anomaly": True,
        "reasons": reasons,
        "signals": sorted({name for name, _ in signals}),
    }


def scan_history(records, full_lookup=None):
    """Anomaly-scan the whole history. Returns list sorted by score."""
    out = []
    for r in records:
        full = full_lookup(r.get("id")) if full_lookup else None
        card = assess_analysis(r, records, full=full)
        out.append(card)
    out.sort(key=lambda c: -c["anomaly_score"])
    return out


# ------------------------------------------- decision support (Phase 11) ----

def decision_support(record, full=None, comparison=None):
    """MEASURED -> OBSERVED -> INTERPRETATION -> RECOMMENDATION chain.

    Deterministic rules; explicitly hedged interpretations; the image never
    'proves' a process cause.
    """
    iso = record.get("iso_nodularity_pct")
    steps = {"measured": [], "observed": [], "interpretation": [],
             "recommendation": []}

    if isinstance(iso, (int, float)):
        steps["measured"].append(f"ISO nodularity {_fmt(iso)}%")
    jis = record.get("jis_nodularity_pct")
    if isinstance(jis, (int, float)):
        steps["measured"].append(f"JIS nodularity {_fmt(jis)}%")
    cnt = record.get("nodule_count")
    if isinstance(cnt, (int, float)):
        steps["measured"].append(f"{int(cnt)} graphite particles detected")

    irr = None
    if full:
        rows = full.get("nodules") or []
        n = len(rows)
        if n:
            irr = sum(1 for r in rows if r.get("iso_class") != "V/VI") / n * 100
            steps["observed"].append(
                f"Irregular-particle fraction is {irr:.1f}% of detected "
                "particles")
            rounds = [r["roundness"] for r in rows
                      if isinstance(r.get("roundness"), (int, float))]
            if rounds:
                steps["observed"].append(
                    f"Median particle roundness {_fmt(float(np.median(rounds)), 2)} "
                    f"(range {_fmt(min(rounds), 2)}–{_fmt(max(rounds), 2)})")

    if comparison:
        pp = (comparison.get("nodularity") or {}).get("change_pp")
        if pp is not None:
            steps["observed"].append(
                f"Versus comparison sample: nodularity changed {pp:+.1f} "
                "percentage points")
            irr_change = (comparison.get("irregular_fraction") or {}) \
                .get("change_pp")
            if irr_change is not None and irr_change > 5:
                steps["interpretation"].append(
                    "The combination of lower nodularity and a higher "
                    "irregular-particle fraction indicates a shift in graphite "
                    "morphology between the two samples")

    if isinstance(iso, (int, float)):
        if iso < ISO_ACCEPT:
            steps["interpretation"].append(
                "Measured nodularity is below the common 80% acceptance "
                "criterion; the micrograph shows predominantly non-spheroidal "
                "graphite under the configured classification rules")
        else:
            steps["interpretation"].append(
                "Measured nodularity meets the common 80% acceptance "
                "criterion under the configured classification rules")

    steps["recommendation"].append(
        "The image alone cannot establish the metallurgical cause; verify "
        "against melt treatment (Mg/RE residual), inoculation records and "
        "section size / cooling data before drawing process conclusions")
    if irr is not None and irr > 40:
        steps["recommendation"].append(
            "Consider re-sampling additional fields: a single field may not "
            "represent the bulk microstructure")
    acc = record.get("accuracy_pct")
    if isinstance(acc, (int, float)) and acc < ACC_GATE:
        steps["recommendation"].append(
            "Self-check accuracy is below gate for this image — re-acquire at "
            "higher resolution before sign-off")
    return steps
