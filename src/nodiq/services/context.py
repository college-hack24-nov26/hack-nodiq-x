#!/usr/bin/env python3
"""
services/context.py — canonical scientific analysis contract (Phase 2) with
caching (Phase 37). One dict shape shared by the API, Copilot, reports and
analytics. Built ONLY from stored measured data; nothing is invented.
"""
import json
import os
import threading
import time
from pathlib import Path

import nodiq.services.db as db

from nodiq.core.config import DATA_DIR
FULL_DIR = Path(os.environ.get("NODIQ_FULL_DIR")
                or (DATA_DIR / "analyses_full"))
FULL_DIR.mkdir(parents=True, exist_ok=True)

_LOCK = threading.Lock()
_CACHE = {}          # analysis_id -> (timestamp, contract)
_CACHE_TTL = 300.0   # seconds


# ------------------------------------------------------------ full store ----
def save_full_analysis(analysis_id, payload):
    """Persist the complete analysis payload (minus bulky base64 masks).

    On the supabase backend the payload lives in the full_payloads table so
    it survives redeploys; the local-FS copy is kept as a warm cache either
    way (also serves the sqlite dev backend).
    """
    slim = {k: v for k, v in payload.items()
            if k not in ("mask_b64", "annotated_b64", "mask", "annotated")}
    slim["stored_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    blob = json.dumps(slim)
    if db.BACKEND == "supabase":
        db.init_db()   # fresh process (analysis child): open + schema first
        # db.init_db() leaves db._CONN schema-ensured for THIS process's
        # DB_PATH (tests redirect DB_PATH per fixture -> per-schema PG);
        # a fresh pooled connection could land in a different schema where
        # full_payloads was never created. Serialize behind db._LOCK like
        # every other db.py user of the shared connection.
        with db._LOCK:
            db._CONN.execute(
                "INSERT OR REPLACE INTO full_payloads (id, payload,"
                " stored_at) VALUES (?, ?, ?)",
                (analysis_id, blob, slim["stored_at"]))
            db._CONN.commit()
    # local mirror (cache on PG, primary on sqlite) — same call path as the
    # pre-migration behaviour so the FS cache routes keep working unchanged
    with _LOCK:
        (FULL_DIR / f"{analysis_id}.json").write_text(blob, encoding="utf-8")
    _CACHE.pop(analysis_id, None)


def load_full_analysis(analysis_id):
    """Return the stored full payload or None.

    supabase: the table is authoritative; the local file is only a cache.
    sqlite:   the local file IS the store (original behaviour).
    """
    if db.BACKEND == "supabase":
        db.init_db()
        for attempt in range(2):
            try:
                with db._LOCK:
                    row = db._CONN.execute(
                        "SELECT payload FROM full_payloads WHERE id = ?",
                        (analysis_id,)).fetchone()
                break
            except Exception as exc:
                # transient pooler/network hiccup: one re-ping + retry keeps
                # a completed analysis from being served as an empty payload
                print(f"[context] payload read error {analysis_id}: "
                      f"{type(exc).__name__}: {str(exc)[:120]}", flush=True)
                if attempt == 0:
                    try:
                        db._PG_POOL.reset()
                        db._CONN = None
                        db.init_db()
                    except Exception:
                        pass
                    continue
                row = None
                break
        if row:
            try:
                return json.loads(row["payload"])
            except Exception as exc:
                print(f"[context] payload JSON decode failed {analysis_id}: "
                      f"{str(exc)[:120]}", flush=True)
        if row is None:
            # Pooled-connection miss: the pooler idle-reaps sockets and a
            # half-dead pooled socket can serve empty reads WITHOUT raising
            # (observed in Docker E2E: `completed` with no payload while the
            # row verifiably exists). Verify once on a fresh, non-pooled
            # connection; if the row is really there, the pool was lying —
            # reset it so subsequent reads use healthy sockets.
            try:
                fresh = db.pgcompat.PGConnection(db._PG_POOL._dsn)
                try:
                    frow = fresh.execute(
                        "SELECT payload FROM full_payloads WHERE id = ?",
                        (analysis_id,)).fetchone()
                finally:
                    fresh.close()
            except Exception as exc:
                print(f"[context] fresh-conn verify failed {analysis_id}: "
                      f"{type(exc).__name__}: {str(exc)[:120]}", flush=True)
                frow = None
            if frow:
                try:
                    db._PG_POOL.reset()
                    db._CONN = None
                    db.init_db()
                except Exception:
                    pass
                print("[context] pooled-read miss but fresh-conn hit — "
                      "pool reset", flush=True)
                try:
                    return json.loads(frow["payload"])
                except Exception:
                    pass
        # table miss -> fall through to the local cache (pre-migration data)
    path = FULL_DIR / f"{analysis_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ----------------------------------------------------------- the contract ----
def build_contract(analysis_id, history_records=None, batch_records=None,
                   quality=None, calibration=None, comparison=None,
                   spc=None, anomalies=None, validation=None):
    """Assemble the canonical analysis contract (Phase 2 schema).

    Cached per analysis_id so Copilot turns don't recompute statistics.
    """
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(analysis_id)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]

    full = load_full_analysis(analysis_id)
    if full is None:
        return None

    rows = full.get("nodules") or []
    iso_rows = [r for r in rows if r.get("iso_class") == "V/VI"]
    jis_counts = {}
    for r in rows:
        b = r.get("jis_bucket")
        jis_counts[str(b)] = jis_counts.get(str(b), 0) + 1

    contract = {
        "sample": {
            "analysis_id": full.get("analysis_id"),
            "filename": full.get("filename"),
            "title": full.get("title"),
            "created_at": full.get("created_at") or full.get("stored_at"),
            "source_width": full.get("source_width"),
            "source_height": full.get("source_height"),
        },
        "image": {
            "working_width": 1920,
            "source_width": full.get("source_width"),
            "source_height": full.get("source_height"),
        },
        "quality": quality or full.get("quality") or {"status": "NOT_ASSESSED"},
        "calibration": (calibration.to_dict() if calibration is not None
                        and hasattr(calibration, "to_dict")
                        else (full.get("calibration") or calibration
                              or {"available": False,
                                  "source": "unavailable",
                                  "notes": "Scale unavailable"})),
        "detections": {
            "count": full.get("nodule_count"),
            "border_touching": full.get("border_touching"),
            "class_counts": full.get("class_counts"),
            "sources": _source_histogram(rows),
        },
        "nodules": rows,
        "morphology": _morphology(rows),
        # PRIMARY term: plain "nodularity" — the number the user asks for.
        # It equals the ISO 945-4 area-weighted value; "iso945" and "jis"
        # below remain the separate standard views.
        "nodularity": {
            "pct": full.get("iso_nodularity_pct"),
            "basis": "ISO 945-4 area-weighted (spheroidal area / "
                     "total graphite area)",
            "note": "When a user asks for nodularity without naming a "
                    "standard, report THIS value and call it nodularity; "
                    "mention the ISO/JIS views only when asked or when "
                    "they differ materially.",
        },
        "iso945": {
            "nodularity_pct": full.get("iso_nodularity_pct"),
            "nodularity_inframe_pct": full.get("iso_nodularity_inframe_pct"),
            "nodularity_size_qualified_pct": full.get(
                "iso_size_qualified_pct"),
            "round_class_count": len(iso_rows),
            "irregular_class_count": len(rows) - len(iso_rows),
            "size_filter": full.get("size_filter") or {
                "available": False,
                "threshold_um": 10.0,
                "applied": False,
                "excluded_count": None,
                "included_count": None,
                "reason": "Physical calibration unavailable",
            },
        },
        "jis": {
            "nodularity_pct": full.get("jis_nodularity_pct"),
            "class_counts": jis_counts,
        },
        # multi-field sampling context (None unless explicitly linked)
        "multifield": build_multifield_context(analysis_id),
        "self_check": full.get("self_check") or {},
        "warnings": full.get("warnings") or [],
        "comparison": comparison,
        "batch": batch_records,
        "spc": spc,
        "anomalies": anomalies,
        "validation": validation,
    }
    with _LOCK:
        _CACHE[analysis_id] = (now, contract)
    return contract


def build_multifield_context(analysis_id):
    """Multi-field session context for one analysis, or None.

    Returns the real stored values only — field counts, particle counts,
    calibration coverage, sampling status and the session's aggregate
    areas/percentages.  Never invents data; returns None when the analysis
    is not part of any multi-field session.
    """
    try:
        from nodiq.services import multifield
        return multifield.get_session_for_analysis(analysis_id)
    except Exception:
        return None


def _source_histogram(rows):
    hist = {}
    for r in rows:
        s = r.get("source", "unknown")
        hist[s] = hist.get(s, 0) + 1
    return hist


def _morphology(rows):
    import numpy as np
    if not rows:
        return {}
    areas = [r["area_px"] for r in rows if isinstance(r.get("area_px"), (int, float))]
    rounds = [r["roundness"] for r in rows if isinstance(r.get("roundness"), (int, float))]
    diams = [r["equiv_diameter_px"] for r in rows
             if isinstance(r.get("equiv_diameter_px"), (int, float))]
    def pack(v, nd=2):
        if not v:
            return None
        return {"mean": round(float(np.mean(v)), nd),
                "median": round(float(np.median(v)), nd),
                "std": round(float(np.std(v)), nd),
                "min": round(float(np.min(v)), nd),
                "max": round(float(np.max(v)), nd)}
    return {"area_px": pack(areas, 1), "equiv_diameter_px": pack(diams),
            "roundness": pack(rounds, 3)}
