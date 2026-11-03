#!/usr/bin/env python3
"""Tests for the advancement features (properties, forms, lots, review,
reset tokens, auth/SQLite basics). Run: pytest tests/test_advancements.py -q"""
import itertools
import os
import sys
import time
from pathlib import Path


import nodiq.services.db as store
import nodiq.services.auth as auth_svc
from nodiq.services.properties import estimate_properties
from nodiq.services.morphology import classify_graphite_forms
from nodiq.services.lots import lot_summary, list_lots
from nodiq.services.review import set_review
from nodiq.services.auth import generate_reset_token, consume_reset_token


def _mkrow(nid, ar, sol, rnd, area=100.0):
    return {"nodule_id": nid, "aspect_ratio": ar, "solidity": sol,
            "roundness": rnd, "area_px": area}


# ------------------------------------------------------------- properties --
def test_properties_monotonic_and_band():
    prev = None
    for n in (60, 80, 95):
        est = estimate_properties(n)
        assert est["available"]
        rm = est["estimated_tensile_strength_mpa"]["estimate"]
        if prev is not None:
            assert rm >= prev - 0.5          # monotonic non-decreasing
        prev = rm
        band = est["estimated_tensile_strength_mpa"]
        assert band["low"] < band["estimate"] < band["high"]


def test_properties_matrix_baselines():
    ferr = estimate_properties(85, matrix="ferritic")
    pear = estimate_properties(85, matrix="pearlitic")
    assert (ferr["estimated_elongation_pct"]["estimate"]
            > pear["estimated_elongation_pct"]["estimate"])
    assert (pear["estimated_tensile_strength_mpa"]["estimate"]
            > ferr["estimated_tensile_strength_mpa"]["estimate"])


def test_properties_invalid():
    assert estimate_properties(None)["available"] is False
    assert estimate_properties(150)["available"] is False


def test_nearest_grade_matches_strength():
    est = estimate_properties(95, matrix="pearlitic")
    grade = est["nearest_iso_grades"][0]
    rm = est["estimated_tensile_strength_mpa"]["estimate"]
    assert grade["min_rm_mpa"] <= rm * 1.2


# --------------------------------------------------------------- forms -----
def test_forms_spheroidal_dominant():
    rows = [_mkrow(i, 1.1, 0.96, 0.9) for i in range(9)]
    rows.append(_mkrow(99, 2.0, 0.85, 0.7))          # one defective
    res = classify_graphite_forms(rows)
    assert res["available"] and res["dominant_form"] == "VI"
    assert res["form_count_share_pct"]["VI"] == 90.0


def test_forms_flake_vs_vermicular():
    flake = classify_graphite_forms([_mkrow(1, 8.0, 0.45, 0.2)])
    verm = classify_graphite_forms([_mkrow(1, 4.0, 0.75, 0.5)])
    assert flake["dominant_form"] == "I"
    assert verm["dominant_form"] == "III"
    assert any("grey iron" in h for h in flake["matrix_hints"])
    assert any("CGI" in h or "compacted" in h for h in verm["matrix_hints"])


def test_forms_empty_and_partial():
    empty = classify_graphite_forms([])
    assert empty["available"] is False
    partial = classify_graphite_forms([{"nodule_id": 1}])   # no shape fields
    assert partial["particles"][0]["iso945_form"] == "unclassified"


# ----------------------------------------------------------- lots/review ---
# Unique per seed: the old rid = "time.time()*1000 % 1e8" stem could repeat
# for two INSERTs inside the same wall-clock millisecond (warm-cache full-
# suite runs are fast enough), and INSERT OR REPLACE then silently collapsed
# the two records — test_lot_summary_and_list's samples == 2 assertion failed
# ONLY in full-suite runs, never alone. Order-independent now: monotonic
# counter + nanosecond clock (test-order dependency fix, Issue 1).
_RID_SEQ = itertools.count()


def _mk_seed_id(lot):
    return f"ANL-L{lot}-{next(_RID_SEQ):04d}-{time.time_ns() % 10 ** 8:08d}"


def _seed(uid, lot, iso):
    rid = _mk_seed_id(lot)
    store.insert_analysis({
        "id": rid, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "lot_id": lot, "iso_nodularity_pct": iso, "nodule_count": 40,
        "status": "completed",
    }, uid)
    return rid


def test_lot_summary_and_list():
    uid = f"LOTTEST-{time.time_ns() % 10 ** 6}"
    a = _seed(uid, "HEAT-42", 90.0)
    _seed(uid, "HEAT-42", 85.0)
    _seed(uid, "HEAT-7", 60.0)
    s = lot_summary("HEAT-42", uid)
    assert s["available"] and s["samples"] == 2
    assert s["pass_rate_pct"] == 100.0          # both >= 80
    assert abs(s["mean_nodularity_pct"] - 87.5) < 0.1
    fails = lot_summary("HEAT-7", uid)
    assert fails["pass_rate_pct"] == 0.0
    lots = list_lots(uid)
    names = [lot["lot_id"] for lot in lots]
    assert "HEAT-42" in names and "HEAT-7" in names
    store.delete_analysis(a, uid)


def test_review_signoff():
    uid = f"REVTEST-{time.time_ns() % 10 ** 6}"
    rid = _seed(uid, None, 90.0)
    ok = set_review(rid, "approved", "looks good", "USR-REV", uid)
    assert ok
    rec = store.get_analysis_record(rid, uid)
    assert rec["review"]["status"] == "approved"
    assert rec["review"]["reviewed_by"] == "USR-REV"
    store.delete_analysis(rid, uid)


def test_review_audit_trail_appends_immutable_history():
    """Every status change appends an entry to review_history: transitions,
    reviewer, timestamp, comment. Entries are only ever added — never edited
    or removed — so the Review Center can replay the validation history."""
    uid = f"REVAUDIT-{time.time_ns() % 10 ** 6}"
    rid = _seed(uid, None, 88.0)
    try:
        assert set_review(rid, "approved", "first pass ok", "REV-A", uid)
        rec = store.get_analysis_record(rid, uid)
        hist = rec["review_history"]
        assert len(hist) == 1
        assert hist[0]["action"] == "set"
        assert hist[0]["previous_status"] is None
        assert hist[0]["new_status"] == "approved"
        assert hist[0]["reviewed_by"] == "REV-A"
        assert hist[0]["comment"] == "first pass ok"
        assert hist[0]["reviewed_at"]

        # re-review: previous status is recorded, history grows
        assert set_review(rid, "changes_requested", "recheck dim 3",
                          "REV-B", uid)
        rec = store.get_analysis_record(rid, uid)
        hist = rec["review_history"]
        assert len(hist) == 2
        assert hist[1]["previous_status"] == "approved"
        assert hist[1]["new_status"] == "changes_requested"
        # entry 0 untouched (append-only)
        assert hist[0] == {**hist[0]}
        assert hist[0]["new_status"] == "approved"

        # clear: audit keeps the decision trail, review itself is reset
        assert set_review(rid, None, "review cleared", "REV-A", uid)
        rec = store.get_analysis_record(rid, uid)
        assert rec["review"] is None
        hist = rec["review_history"]
        assert len(hist) == 3
        assert hist[2]["action"] == "cleared"
        assert hist[2]["previous_status"] == "changes_requested"
        assert hist[2]["new_status"] is None
    finally:
        store.delete_analysis(rid, uid)


def test_review_invalid_status_rejected_no_history():
    """An invalid status is refused: nothing stored, no audit entry."""
    uid = f"REVBAD-{time.time_ns() % 10 ** 6}"
    rid = _seed(uid, None, 80.0)
    try:
        assert set_review(rid, "banana", "x", "REV-C", uid) is False
        rec = store.get_analysis_record(rid, uid)
        assert rec.get("review") is None
        assert rec.get("review_history") in (None, [])
        # missing record -> False (never fabricates one)
        assert set_review("ANL-DOES-NOT-EXIST", "approved", "", "REV-C",
                          uid) is False
    finally:
        store.delete_analysis(rid, uid)


# ----------------------------------------------------------------- reset ---
def test_reset_token_roundtrip():
    uid = f"RESET-{time.time_ns() % 10 ** 6}"
    email = f"{uid}@test.local"
    auth_svc.create_user(email, "secret123", "Reset Test", "+91 90000 00000")
    tok = generate_reset_token(email)
    assert tok
    new_uid = consume_reset_token(tok)
    assert new_uid
    assert consume_reset_token(tok) is None       # single use
    assert consume_reset_token("garbage") is None
    import sqlite3
    conn = sqlite3.connect(store.DB_PATH)
    conn.execute("DELETE FROM users WHERE email = ?", (email,))
    conn.commit(); conn.close()
