"""Multi-field analysis sessions (ISO 945-4 sampling framework).

ISO 945-4 asks for at least 5 fields of view and at least 500 graphite
particles when evaluating nodularity.  NODIQ-X's single-image engine stays
untouched; this module adds an additive session layer that:

* stores every field independently (each field keeps its own analysis id,
  per-field metrics and calibration metadata — nothing is flattened),
* aggregates the UNDERLYING AREAS for the multi-field ISO value
  (never an average of per-field percentages) and the UNDERLYING CLASS
  COUNTS for the multi-field JIS value,
* reports explicit sampling status against the 5-field / 500-particle
  targets,
* never fabricates calibration: fields without a physical scale are
  excluded from the standards-aligned aggregate and the status explains
  why.

Formal conformity additionally depends on specimen preparation, microscope
acquisition, calibration traceability and field selection — software alone
cannot certify that.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone

from nodiq.services import db
from nodiq.services.context import load_full_analysis

# ISO 945-4 sampling targets.
FIELD_TARGET = 5
PARTICLE_TARGET = 500

# JIS G5502 class weights (verified in the methodology audit — do not change).
_JIS_WEIGHTS = {2: 0.3, 3: 0.7, 4: 0.9, 5: 1.0}

SAMPLING_STATUSES = (
    "no_fields",
    "below_field_target",
    "below_particle_target",
    "meets_field_and_particle_target",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sid() -> str:
    return "MF-" + secrets.token_hex(4).upper()


# --------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS multifield_sessions (
    id                  TEXT PRIMARY KEY,
    seq                 BIGSERIAL,   -- PG insertion-order proxy for rowid
    user_id             TEXT NOT NULL,
    label               TEXT,
    methodology_version TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mf_sessions_user
    ON multifield_sessions(user_id, created_at);

CREATE TABLE IF NOT EXISTS multifield_fields (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    seq                 BIGSERIAL,
    session_id          TEXT NOT NULL,
    user_id             TEXT NOT NULL,
    analysis_id         TEXT NOT NULL,
    image_name          TEXT,
    particle_count      INTEGER,
    border_count        INTEGER,
    microns_per_pixel   REAL,
    calibration_source  TEXT,
    calibration_status  TEXT,
    size_excluded_count INTEGER,
    spheroidal_area     REAL,
    graphite_area       REAL,
    iso_pct             REAL,
    jis_pct             REAL,
    jis_class_counts    TEXT,
    jis_particle_count  INTEGER,
    quality_status      TEXT,
    valid               INTEGER NOT NULL DEFAULT 1,
    invalid_reason      TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE(session_id, analysis_id)
);
CREATE INDEX IF NOT EXISTS idx_mf_fields_session
    ON multifield_fields(session_id);
CREATE INDEX IF NOT EXISTS idx_mf_fields_analysis
    ON multifield_fields(analysis_id);
"""

_ENSURED = set()


def _conn():
    """A connection with the multi-field schema guaranteed present.

    The schema is created once per database path; missing columns are
    added for databases created before a column existed (mirrors the
    db._ensure_column pattern).
    """
    con = db._connect()
    path = str(getattr(db, "DB_PATH", ""))
    if path not in _ENSURED:
        con.executescript(_SCHEMA)
        cols = {r["name"] for r in con.execute(
            "PRAGMA table_info(multifield_fields)").fetchall()}
        for name, decl in (("jis_class_counts", "TEXT"),
                           ("jis_particle_count", "INTEGER")):
            if name not in cols:
                con.execute(
                    f"ALTER TABLE multifield_fields ADD COLUMN {name} "
                    f"{decl}")
        con.commit()
        _ENSURED.add(path)
    return con


def create_session(user_id, label=None):
    """Create a multi-field session; returns its dict."""
    sid = _sid()
    now = _now()
    with _conn() as con:
        con.execute(
            "INSERT INTO multifield_sessions (id, user_id, label, "
            "methodology_version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, user_id, label or "Multi-field session",
             "iso945-4-multifield-v1", now, now))
    return get_session(sid, user_id)


def get_session(session_id, user_id):
    """Full aggregate state for one session, or None."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM multifield_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id)).fetchone()
        fields = con.execute(
            "SELECT * FROM multifield_fields WHERE session_id = ? "
            "ORDER BY rowid", (session_id,)).fetchall()
    if not row:
        return None
    sess = dict(row)
    sess["fields"] = []
    for f in fields:
        d = dict(f)
        # jis_class_counts is stored as a JSON string
        if isinstance(d.get("jis_class_counts"), str):
            try:
                d["jis_class_counts"] = json.loads(d["jis_class_counts"])
            except Exception:
                d["jis_class_counts"] = None
        sess["fields"].append(d)
    return sess


def list_sessions(user_id):
    """All of the user's multi-field sessions, newest first."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM multifield_sessions WHERE user_id = ? "
            "ORDER BY created_at DESC, rowid DESC", (user_id,)).fetchall()
        # index access (not dict(rows)): row objects expose columns by
        # position on both sqlite3.Row and the PG facade
        counts = {_r[0]: _r[1] for _r in con.execute(
            "SELECT session_id, COUNT(*) FROM multifield_fields "
            "WHERE user_id = ? GROUP BY session_id",
            (user_id,)).fetchall()}
    out = []
    for r in rows:
        d = dict(r)
        d["field_count"] = int(counts.get(d["id"], 0))
        out.append(d)
    return out


def delete_session(session_id, user_id):
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM multifield_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id))
        if cur.rowcount:
            con.execute(
                "DELETE FROM multifield_fields WHERE session_id = ?",
                (session_id,))
    return True


def get_session_for_analysis(analysis_id, user_id=None):
    """The multi-field session containing this analysis, or None.

    Used by the Copilot context: returns the real stored session summary
    plus per-field traceability for this analysis.  Never invents values.
    """
    with _conn() as con:
        row = con.execute(
            "SELECT session_id, user_id FROM multifield_fields "
            "WHERE analysis_id = ? LIMIT 1", (analysis_id,)).fetchone()
    if not row:
        return None
    sess = get_session(row["session_id"], row["user_id"])
    if not sess:
        return None
    agg = aggregate(sess)
    agg["this_field"] = next(
        (f for f in agg["fields"] if f["analysis_id"] == analysis_id),
        None)
    return agg


def add_field(session_id, user_id, analysis_id):
    """Attach a completed single-image analysis as a field of the session.

    The analysis must already exist and belong to the same user.  Returns
    (field dict, error string) — error is None on success.
    """
    sess = get_session(session_id, user_id)
    if not sess:
        return None, "session not found"
    record = db.get_analysis_record(analysis_id, user_id)
    if not record:
        return None, "analysis not found"
    if any(f["analysis_id"] == analysis_id for f in sess["fields"]):
        return None, "analysis already attached to this session"
    if len(sess["fields"]) >= 64:
        return None, "session field limit (64) reached"

    full = load_full_analysis(analysis_id) or {}
    field = {
        "session_id": session_id,
        "analysis_id": analysis_id,
        "image_name": record.get("filename") or record.get("image_name"),
        "particle_count": int(record.get("nodule_count") or 0),
        "border_count": 0,
        "microns_per_pixel": None,
        "calibration_source": "unavailable",
        "calibration_status": "uncalibrated",
        "size_excluded_count": None,
        "spheroidal_area": None,
        "graphite_area": None,
        "iso_pct": record.get("iso_nodularity_pct"),
        "jis_pct": record.get("jis_nodularity_pct"),
        "quality_status": record.get("quality_status"),
        "valid": 1,
        "invalid_reason": None,
        "created_at": _now(),
    }
    _extract_field_metrics(field, full, record)

    with _conn() as con:
        con.execute(
            "INSERT INTO multifield_fields (session_id, user_id, "
            "analysis_id, image_name, particle_count, border_count, "
            "microns_per_pixel, calibration_source, calibration_status, "
            "size_excluded_count, spheroidal_area, graphite_area, "
            "iso_pct, jis_pct, jis_class_counts, jis_particle_count, "
            "quality_status, valid, invalid_reason, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?, ?, ?)",
            (field["session_id"], user_id, field["analysis_id"],
             field["image_name"], field["particle_count"],
             field["border_count"], field["microns_per_pixel"],
             field["calibration_source"], field["calibration_status"],
             field["size_excluded_count"], field["spheroidal_area"],
             field["graphite_area"], field["iso_pct"], field["jis_pct"],
             json.dumps(field.get("jis_class_counts"))
             if field.get("jis_class_counts") is not None else None,
             field.get("jis_particle_count"),
             field["quality_status"], field["valid"],
             field["invalid_reason"], field["created_at"]))
        con.execute(
            "UPDATE multifield_sessions SET updated_at = ? WHERE id = ?",
            (_now(), session_id))
    return get_session(session_id, user_id), None


def _extract_field_metrics(field, full, record):
    """Fill per-field metrics from the stored analysis (never invents).

    Uses ONLY the keys actually stored by the engine/server:
      rows: nodule_id, area_px, feret_diameter_px/um, roundness,
            iso_class ("V/VI"|"irregular"), jis_bucket (1..5),
            touches_border, size_filter_status (when the filter ran)
      full: size_filter {applied, excluded_count, ...},
            calibration {um_per_px, source, ...}, quality {status}
    """
    from nodiq.services.calibration import validate_um_per_px

    rows = full.get("nodules") or []
    sf = full.get("size_filter") or {}
    cal = full.get("calibration") or {}
    quality = full.get("quality") or {}

    applied = bool(sf.get("applied"))
    mpp = validate_um_per_px(
        cal.get("um_per_px") if isinstance(cal, dict) else None) \
        if applied else None
    if applied and mpp is not None:
        field["microns_per_pixel"] = mpp
        field["calibration_source"] = (cal.get("source") or "manual")
        field["calibration_status"] = "valid"
        field["size_excluded_count"] = sf.get("excluded_count")
    else:
        field["microns_per_pixel"] = None
        field["calibration_source"] = (cal.get("source") or "unavailable")
        field["calibration_status"] = "uncalibrated"
        field["size_excluded_count"] = None

    # Underlying areas, in-frame (ISO 945-4 excludes border particles).
    sph_area = 0.0
    total_area = 0.0
    border_count = 0
    jis_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    used_rows = False
    size_gate = applied and mpp is not None
    for r in rows:
        if r.get("touches_border"):
            border_count += 1
        b = r.get("jis_bucket")
        if isinstance(b, int) and 1 <= b <= 5:
            jis_counts[b] += 1
        area = r.get("area_px")
        if not isinstance(area, (int, float)) or area <= 0:
            continue
        if r.get("touches_border"):
            continue
        if size_gate:
            status = r.get("size_filter_status")
            if status == "excluded_below_10um":
                continue
            if status != "included":
                # calibrated field but row lacks a size verdict -> the
                # 10 um rule cannot be confirmed for it; do not guess
                field["valid"] = 0
                field["invalid_reason"] = (
                    "stored particle rows lack size-filter verdicts; the "
                    "ISO 945-4 10 um rule cannot be confirmed")
                return
        else:
            # Field has no calibration -> cannot be part of the
            # standards-aligned aggregate areas.
            field["valid"] = 0
            field["invalid_reason"] = (
                "Physical calibration unavailable; the ISO 945-4 10 um "
                "exclusion could not be evaluated")
            field["border_count"] = border_count
            field["jis_class_counts"] = {str(k): v for k, v in
                                         jis_counts.items()}
            field["jis_particle_count"] = sum(jis_counts.values())
            return
        used_rows = True
        total_area += float(area)
        is_round = (r.get("iso_class") == "V/VI"
                    if r.get("iso_class") is not None
                    else float(r.get("roundness") or 0.0) >= 0.6)
        if is_round:
            sph_area += float(area)

    field["border_count"] = border_count or int(
        full.get("border_touching") or 0)
    field["jis_class_counts"] = {str(k): v for k, v in jis_counts.items()}
    field["jis_particle_count"] = sum(jis_counts.values())
    if used_rows:
        field["spheroidal_area"] = round(sph_area, 2)
        field["graphite_area"] = round(total_area, 2)
        # in-frame ISO recomputed from the same rows (matches the engine's
        # iso_inframe_pct definition); falls back to the stored headline
        n_in = total_area
        field["iso_pct"] = (round(sph_area / n_in * 100, 2)
                            if n_in else record.get("iso_nodularity_pct"))
    elif field["valid"]:
        field["valid"] = 0
        if rows and all(r.get("size_filter_status") == "excluded_below_10um"
                        for r in rows
                        if isinstance(r.get("area_px"), (int, float))
                        and not r.get("touches_border")):
            field["invalid_reason"] = (
                "all particles excluded by the 10 um size rule under this "
                "field's calibration; no qualifying graphite area remains")
        else:
            field["invalid_reason"] = (
                "no usable per-particle area rows stored")

    field["quality_status"] = quality.get(
        "status") or record.get("quality_status")


# --------------------------------------------------------------------------
# validation + aggregation
# --------------------------------------------------------------------------

def _validate_field(field):
    """Return (is_valid, reason) for aggregation eligibility."""
    if not field.get("valid"):
        return False, field.get("invalid_reason") or "field marked invalid"
    areas = (field.get("spheroidal_area"), field.get("graphite_area"))
    if not all(isinstance(a, (int, float)) and a >= 0 for a in areas):
        return False, "missing eligible area data"
    if field.get("calibration_status") != "valid":
        return False, "field lacks valid physical calibration"
    return True, None


def calibration_consistency(fields):
    """Group field scales; returns (consistent, groups, note).

    Fields with different valid physical scales are not interchangeable
    for area aggregation — each field's areas are in its own µm².  Sizes
    may still be filtered per field (each converts its own Feret), but the
    aggregate area ratio is only meaningful when all eligible fields share
    one scale.
    """
    groups = {}
    for f in fields:
        ok, _ = _validate_field(f)
        if not ok:
            continue
        key = round(float(f["microns_per_pixel"]), 6)
        groups.setdefault(key, []).append(f["analysis_id"])
    consistent = len(groups) <= 1
    note = None
    if not consistent:
        note = ("Fields use different physical scales; the aggregate area "
                "ratio is not meaningful across scales and only fields "
                "sharing the largest scale group are aggregated")
    return consistent, groups, note


def sampling_status(field_count, total_particles):
    """Explicit ISO 945-4 sampling status (both targets must be met)."""
    meets_fields = field_count >= FIELD_TARGET
    meets_particles = total_particles >= PARTICLE_TARGET
    # Precedence per the ISO 945-4 sampling framework: the field target is
    # checked first, then the particle target — a session is only fully
    # sampled when BOTH are satisfied.
    if field_count == 0:
        return "no_fields"
    if not meets_fields:
        return "below_field_target"
    if not meets_particles:
        return "below_particle_target"
    return "meets_field_and_particle_target"


def aggregate(session):
    """Compute the full aggregate for a session dict from get_session().

    ISO  : Σ spheroidal area / Σ eligible graphite area   (area-weighted,
           border-excluded, size-qualified, single-scale group)
    JIS  : Σ weighted class counts / Σ particles          (count-based)
    Neither is ever an average of per-field percentages.
    """
    fields = session.get("fields", [])
    total_particles = sum(int(f["particle_count"] or 0) for f in fields)

    # ---- per-field validation -------------------------------------------
    for f in fields:
        ok, reason = _validate_field(f)
        f["eligible"] = 1 if ok else 0
        f["exclusion_reason"] = reason

    consistent, groups, cal_note = calibration_consistency(fields)
    # Aggregate only the largest single-scale group when scales differ.
    eligible = fields
    if not consistent and groups:
        best = max(groups.values(), key=len)
        eligible = [f for f in fields if f["analysis_id"] in best]
        for f in fields:
            if f not in eligible:
                f["eligible"] = 0
                f["exclusion_reason"] = (
                    "physical scale differs from the aggregated scale group")

    eligible = [f for f in eligible if f.get("eligible")]

    # ---- ISO area aggregation -------------------------------------------
    sph = sum(float(f["spheroidal_area"]) for f in eligible)
    tot = sum(float(f["graphite_area"]) for f in eligible)
    iso = round(sph / tot * 100.0, 2) if tot > 0 else None

    # ---- JIS class-count aggregation ------------------------------------
    # Classes 1-5 are pooled; class 1 carries weight 0 but still counts in
    # the N_all denominator (verified JIS G5502 convention: the reported
    # 77.44% example divided 30.2 by all 39 particles).
    counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    jis_particles = 0
    for f in eligible:
        c = f.get("jis_class_counts")
        if isinstance(c, dict):
            for k in counts:
                counts[k] += int(c.get(str(k), 0) or 0)
            jis_particles += int(f.get("jis_particle_count") or 0)
    jis_all = sum(counts.values())
    jis = None
    if jis_all > 0:
        jis = round(sum(_JIS_WEIGHTS[k] * counts[k] for k in _JIS_WEIGHTS)
                    / jis_all * 100.0, 2)

    # ---- calibration coverage -------------------------------------------
    calibrated = [f for f in fields if f.get("calibration_status") == "valid"]
    calibration_complete = bool(fields) and len(calibrated) == len(fields)

    # Sampling status tracks ATTACHED fields (the spec examples count
    # fields analyzed, not merely eligible ones); eligibility and
    # calibration gaps are reported separately via eligible_field_count,
    # calibration coverage, notes and standards_aligned.
    status = sampling_status(len(fields), jis_all if jis_all else total_particles)
    standards_aligned = (
        status == "meets_field_and_particle_target"
        and calibration_complete
        and iso is not None)

    notes = []
    if not fields:
        notes.append("No fields attached yet")
    if not calibration_complete and fields:
        notes.append(
            "One or more fields lack physical calibration; the 10 um "
            "exclusion could not be evaluated for those fields")
    if cal_note:
        notes.append(cal_note)
    if status != "meets_field_and_particle_target":
        notes.append(
            f"Sampling target not reached: {len(eligible)}/{FIELD_TARGET} "
            f"eligible fields, "
            f"{jis_all if jis_all else total_particles}/{PARTICLE_TARGET} "
            "particles")

    return {
        "session_id": session["id"],
        "label": session.get("label"),
        "methodology_version": session.get("methodology_version"),
        "field_count": len(fields),
        "eligible_field_count": len(eligible),
        "total_particle_count": total_particles,
        "total_qualified_particle_count": jis_all or None,
        "aggregate_spheroidal_area": round(sph, 2) if eligible else None,
        "aggregate_graphite_area": round(tot, 2) if eligible else None,
        "aggregate_iso_nodularity_pct": iso,
        "aggregate_jis_nodularity_pct": jis,
        # Particles in the aggregate JIS denominator (all classified
        # particles of eligible fields, classes 1-5).
        "jis_class_counts": {str(k): v for k, v in counts.items()}
        if jis_all else None,
        "calibration": {
            "fields_calibrated": len(calibrated),
            "fields_total": len(fields),
            "consistent_scales": consistent,
            "complete": calibration_complete,
        },
        "sampling_status": status,
        "standards_aligned": standards_aligned,
        "notes": notes,
        "fields": [
            {
                "analysis_id": f["analysis_id"],
                "image_name": f.get("image_name"),
                "particle_count": f.get("particle_count"),
                "border_count": f.get("border_count"),
                "calibrated": f.get("calibration_status") == "valid",
                "calibration_source": f.get("calibration_source"),
                "microns_per_pixel": f.get("microns_per_pixel"),
                "size_excluded_count": f.get("size_excluded_count"),
                "spheroidal_area": f.get("spheroidal_area"),
                "graphite_area": f.get("graphite_area"),
                "iso_pct": f.get("iso_pct"),
                "jis_pct": f.get("jis_pct"),
                "quality_status": f.get("quality_status"),
                "eligible": bool(f.get("eligible")),
                "exclusion_reason": f.get("exclusion_reason"),
            }
            for f in session.get("fields", [])
        ],
    }
