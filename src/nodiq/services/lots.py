#!/usr/bin/env python3
"""
services/lots.py — heat/lot traceability (Advancement).

Groups stored analyses by their `lot_id` tag and computes per-lot acceptance:
sample count, pass/fail rates, mean/std nodularity, SPC stats. Pure
aggregation over the SQLite store — no data is invented.
"""
import numpy as np

import nodiq.services.db as store

DEFAULT_ACCEPT = 80.0


def _records_for(lot_id, user_id):
    recs = store.list_analyses(user_id)
    return [r for r in recs
            if (r.get("lot_id") or "").strip() == lot_id
            and isinstance(r.get("iso_nodularity_pct"), (int, float))]


def lot_summary(lot_id, user_id=None, accept=DEFAULT_ACCEPT):
    """Per-lot acceptance summary: counts, rates, mean/std, min/max."""
    recs = _records_for(lot_id, user_id)
    if not recs:
        return {"lot_id": lot_id, "available": False, "samples": 0}
    vals = np.array([r["iso_nodularity_pct"] for r in recs], dtype=float)
    passing = int((vals >= accept).sum())
    chronological = sorted(recs, key=lambda r: r.get("created_at") or "")
    return {
        "lot_id": lot_id,
        "available": True,
        "samples": len(recs),
        "pass_count": passing,
        "fail_count": len(recs) - passing,
        "pass_rate_pct": round(passing / len(recs) * 100.0, 1),
        "mean_nodularity_pct": round(float(vals.mean()), 1),
        "std_nodularity_pct": round(float(vals.std()), 1),
        "min_nodularity_pct": round(float(vals.min()), 1),
        "max_nodularity_pct": round(float(vals.max()), 1),
        "accept_threshold_pct": accept,
        "sample_ids": [r.get("id") for r in chronological],
        "values_chronological": [round(float(v), 1) for v in
                                 sorted(vals.tolist())]
        if False else [round(r["iso_nodularity_pct"], 1)
                       for r in chronological],
    }


def list_lots(user_id=None, accept=DEFAULT_ACCEPT):
    """All tagged lots for a user, worst pass rate first."""
    tags = {}
    for r in store.list_analyses(user_id):
        lot = (r.get("lot_id") or "").strip()
        if lot and isinstance(r.get("iso_nodularity_pct"), (int, float)):
            tags.setdefault(lot, 0)
            tags[lot] += 1
    lots = [lot_summary(lot, user_id, accept) for lot in tags]
    lots.sort(key=lambda s: (s.get("pass_rate_pct", 0), -s.get("samples", 0)))
    return lots
