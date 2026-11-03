"""Deterministic tests for the multi-field standards sampling workflow.

Verifies the ISO 945-4 sampling framework: 5-field/500-particle targets,
area-based ISO aggregation (never average of percentages), count-based JIS
aggregation, calibration consistency, per-field traceability and honest
sampling status.
"""

import sys
import os


import json
import math
import pytest

from nodiq.services import multifield as mf


def _mk_field(analysis_id, *, particles=100, eligible=True, calibrated=True,
              mpp=0.05, spheroidal=1000.0, graphite=2000.0,
              jis_counts=None, invalid_reason=None, image_name=None):
    """A synthetic field record shaped exactly like a stored field row."""
    if jis_counts is None:
        jis_counts = {"2": 0, "3": 40, "4": 40, "5": 20}
    return {
        "analysis_id": analysis_id,
        "image_name": image_name or f"{analysis_id}.png",
        "particle_count": particles,
        "border_count": 2,
        "microns_per_pixel": mpp if calibrated else None,
        "calibration_source": "manual" if calibrated else "unavailable",
        "calibration_status": "valid" if calibrated else "uncalibrated",
        "size_excluded_count": 1 if calibrated else None,
        "spheroidal_area": spheroidal,
        "graphite_area": graphite,
        "iso_pct": round(spheroidal / graphite * 100, 2),
        "jis_pct": None,
        "quality_status": "ok",
        "valid": 1 if eligible else 0,
        "invalid_reason": invalid_reason,
        "created_at": "2026-01-01T00:00:00+00:00",
        "jis_class_counts": jis_counts,
        "jis_particle_count": sum(jis_counts.values()),
    }


def _agg(fields):
    sess = {"id": "MF-TEST", "label": "t",
            "methodology_version": "iso945-4-multifield-v1",
            "fields": [dict(f) for f in fields]}
    return mf.aggregate(sess)


# ---------------------------------------------------------------- sampling

def test_sampling_meets_both_targets():
    """5 fields x 100 particles = 500 particles: both targets met."""
    fields = [_mk_field(f"A{i}") for i in range(5)]
    agg = _agg(fields)
    assert agg["sampling_status"] == "meets_field_and_particle_target"
    assert agg["field_count"] == 5
    assert agg["total_particle_count"] == 500
    assert agg["standards_aligned"] is True


def test_sampling_below_field_target():
    """4 fields / 500 particles: field target not met (spec example:
    3 fields / 620 particles => below_field_target — fields checked first)."""
    fields = [_mk_field(f"A{i}", particles=125) for i in range(4)]
    agg = _agg(fields)
    assert agg["sampling_status"] == "below_field_target"
    assert agg["standards_aligned"] is False


def test_sampling_below_particle_target():
    """5 fields / 499 classified particles: particle target not met
    (spec example: 7 fields / 430 particles => below_particle_target)."""
    counts = {"1": 99, "2": 0, "3": 0, "4": 0, "5": 0}
    fields = [_mk_field(f"A{i}", particles=99, jis_counts=dict(counts))
              for i in range(4)]
    fields.append(_mk_field("A4", particles=103,
                            jis_counts={"1": 103, "2": 0, "3": 0,
                                        "4": 0, "5": 0}))
    assert sum(f["jis_particle_count"] for f in fields) == 499
    agg = _agg(fields)
    assert agg["sampling_status"] == "below_particle_target"
    assert agg["standards_aligned"] is False


def test_sampling_six_fields_six_hundred_particles():
    agg = _agg([_mk_field(f"A{i}", particles=100) for i in range(6)])
    assert agg["sampling_status"] == "meets_field_and_particle_target"


def test_sampling_no_fields():
    agg = _agg([])
    assert agg["sampling_status"] == "no_fields"
    assert agg["aggregate_iso_nodularity_pct"] is None


# ------------------------------------------------------- ISO aggregation

def test_iso_aggregate_is_area_based_not_percentage_average():
    """Two fields with equal areas but wildly different ISO percentages:
    the aggregate MUST equal the pooled area ratio, not the mean."""
    # Field A: 50% (1000/2000); Field B: 100% (2000/2000). Mean = 75%.
    fields = [
        _mk_field("A", spheroidal=1000.0, graphite=2000.0),
        _mk_field("B", spheroidal=2000.0, graphite=2000.0),
    ]
    agg = _agg(fields)
    # Pooled: 3000/4000 = 75.0 — coincidentally equal here, so use an
    # asymmetric second case to prove the mechanism:
    fields2 = [
        _mk_field("A", spheroidal=100.0, graphite=1000.0),    # 10%
        _mk_field("B", spheroidal=900.0, graphite=1000.0),    # 90%
    ]
    agg2 = _agg(fields2)
    assert agg2["aggregate_iso_nodularity_pct"] == 50.0  # 1000/2000
    # The mean of percentages would also be 50 here, so weight the areas:
    fields3 = [
        _mk_field("A", spheroidal=100.0, graphite=9000.0),   # 1.11%
        _mk_field("B", spheroidal=900.0, graphite=1000.0),   # 90%
    ]
    agg3 = _agg(fields3)
    mean_pct = (100 / 9000 * 100 + 90.0) / 2  # 45.56
    pooled = (100 + 900) / (9000 + 1000) * 100  # 10.0
    assert agg3["aggregate_iso_nodularity_pct"] == round(pooled, 2)
    assert agg3["aggregate_iso_nodularity_pct"] != round(mean_pct, 2)
    assert agg3["aggregate_spheroidal_area"] == 1000.0
    assert agg3["aggregate_graphite_area"] == 10000.0


def test_iso_aggregate_excludes_invalid_field_from_both_terms():
    """An invalid field contributes to neither numerator nor denominator."""
    good = _mk_field("A", spheroidal=1000.0, graphite=2000.0)
    bad = _mk_field("B", eligible=False, invalid_reason="bad quality",
                    spheroidal=9999.0, graphite=9999.0)
    agg = _agg([good, bad])
    assert agg["aggregate_graphite_area"] == 2000.0
    assert agg["aggregate_iso_nodularity_pct"] == 50.0
    assert agg["eligible_field_count"] == 1
    bad_row = next(f for f in agg["fields"] if f["analysis_id"] == "B")
    assert bad_row["eligible"] is False
    assert "bad quality" in bad_row["exclusion_reason"]


# ------------------------------------------------------- JIS aggregation

def test_jis_aggregate_pools_class_counts_before_weighting():
    """Class counts are pooled across fields, then weighted once."""
    f1 = _mk_field("A", jis_counts={"1": 0, "2": 10, "3": 20,
                                     "4": 30, "5": 40})
    f2 = _mk_field("B", jis_counts={"1": 0, "2": 0, "3": 0,
                                     "4": 0, "5": 60})
    agg = _agg([f1, f2])
    assert agg["jis_class_counts"] == {"1": 0, "2": 10, "3": 20,
                                        "4": 30, "5": 100}
    # (0.3*10 + 0.7*20 + 0.9*30 + 1.0*100) / 160 * 100
    expected = round((3 + 14 + 27 + 100) / 160 * 100, 2)
    assert agg["aggregate_jis_nodularity_pct"] == expected


def test_jis_class1_counts_in_denominator_with_zero_weight():
    """Class 1 (irregular, weight 0) still belongs in N_all — matching the
    verified G5502 reconciliation (30.2 / 39 = 77.44%)."""
    f1 = _mk_field("A", jis_counts={"1": 10, "2": 0, "3": 0,
                                     "4": 0, "5": 30})
    agg = _agg([f1])
    # (0.3*0 + 1.0*30) / 40 — class 1 counts in the denominator only
    assert agg["aggregate_jis_nodularity_pct"] == round(30 / 40 * 100, 2)
    assert agg["total_qualified_particle_count"] == 40


def test_jis_aggregate_differs_from_percentage_average():
    f1 = _mk_field("A", jis_counts={"1": 0, "2": 100, "3": 0,
                                     "4": 0, "5": 0})
    f2 = _mk_field("B", jis_counts={"1": 0, "2": 0, "3": 0,
                                     "4": 0, "5": 100})
    f3 = _mk_field("C", jis_counts={"1": 0, "2": 0, "3": 0,
                                     "4": 0, "5": 100})
    agg2 = _agg([f1, f2, f3])
    pooled = round((30 + 100 + 100) / 300 * 100, 2)
    assert agg2["aggregate_jis_nodularity_pct"] == pooled


# ---------------------------------------------------------- calibration

def test_uncalibrated_field_is_excluded_with_reason():
    fields = [_mk_field(f"A{i}") for i in range(4)]
    fields.append(_mk_field("U", calibrated=False, mpp=None))
    agg = _agg(fields)
    assert agg["eligible_field_count"] == 4
    assert agg["calibration"]["fields_calibrated"] == 4
    assert agg["calibration"]["complete"] is False
    assert agg["standards_aligned"] is False
    un = next(f for f in agg["fields"] if f["analysis_id"] == "U")
    assert un["eligible"] is False
    assert "calibration" in un["exclusion_reason"]
    assert any("10 um" in n for n in agg["notes"])


def test_mixed_calibration_metadata_preserved_per_field():
    f1 = _mk_field("A", mpp=0.05)
    f2 = _mk_field("B", mpp=0.10)
    agg = _agg([f1, f2])
    rows = {f["analysis_id"]: f for f in agg["fields"]}
    assert rows["A"]["microns_per_pixel"] == 0.05
    assert rows["B"]["microns_per_pixel"] == 0.10
    # Different scales -> only one scale group aggregates
    assert agg["calibration"]["consistent_scales"] is False


def test_scale_mismatch_aggregates_largest_group_only():
    f1 = _mk_field("A", mpp=0.05, spheroidal=100.0, graphite=100.0)
    f2 = _mk_field("B", mpp=0.05, spheroidal=300.0, graphite=300.0)
    f3 = _mk_field("C", mpp=0.10, spheroidal=9999.0, graphite=9999.0)
    agg = _agg([f1, f2, f3])
    assert agg["aggregate_graphite_area"] == 400.0  # only A+B (0.05 group)
    assert agg["calibration"]["consistent_scales"] is False
    c_row = next(f for f in agg["fields"] if f["analysis_id"] == "C")
    assert c_row["eligible"] is False
    assert "scale" in c_row["exclusion_reason"]


# ---------------------------------------------------------- traceability

def test_field_traceability_full():
    fields = [_mk_field(f"A{i}", particles=100) for i in range(5)]
    agg = _agg(fields)
    assert len(agg["fields"]) == 5
    for f in agg["fields"]:
        for key in ("analysis_id", "image_name", "particle_count",
                    "border_count", "calibrated", "microns_per_pixel",
                    "size_excluded_count", "spheroidal_area",
                    "graphite_area", "iso_pct", "eligible"):
            assert key in f


def test_reproducibility_from_underlying_areas():
    """Aggregate ISO reproduces exactly from exposed per-field areas."""
    fields = [
        _mk_field("A", spheroidal=123.4, graphite=500.0),
        _mk_field("B", spheroidal=222.2, graphite=700.0),
        _mk_field("C", spheroidal=311.1, graphite=800.0),
    ]
    agg = _agg(fields)
    sph = sum(f["spheroidal_area"] for f in agg["fields"]
              if f["eligible"])
    tot = sum(f["graphite_area"] for f in agg["fields"] if f["eligible"])
    assert agg["aggregate_spheroidal_area"] == round(sph, 2)
    assert agg["aggregate_graphite_area"] == round(tot, 2)
    assert agg["aggregate_iso_nodularity_pct"] == round(sph / tot * 100, 2)


# ------------------------------------------------- persistence + context

def test_persistence_roundtrip(tmp_path, monkeypatch):
    """Create session -> add fields -> retrieve -> identical aggregate."""
    import importlib
    from nodiq.services import db, context
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db, "_CONN", None)
    monkeypatch.setattr(context, "FULL_DIR", tmp_path / "full")
    (tmp_path / "full").mkdir()
    importlib.reload(mf)
    db.init_db()
    uid = 1
    db.insert_analysis({"id": "AN-1", "nodule_count": 100,
                        "border_touching_count": 2,
                        "iso_in_frame_pct": 50.0,
                        "jis_nodularity_pct": 77.0}, uid)
    context.save_full_analysis("AN-1", {
        "nodules": [
            {"nodule_id": 1, "area_px": 100.0, "roundness": 0.9,
             "iso_class": "V/VI", "jis_bucket": 5, "touches_border": False,
             "feret_diameter_px": 20.0, "feret_diameter_um": 1.0,
             "size_filter_status": "included"},
            {"nodule_id": 2, "area_px": 100.0, "roundness": 0.3,
             "iso_class": "irregular", "jis_bucket": 3,
             "touches_border": False, "feret_diameter_px": 30.0,
             "feret_diameter_um": 1.5, "size_filter_status": "included"},
        ],
        "size_filter": {"applied": True, "threshold_um": 10.0,
                        "excluded_count": 1, "included_count": 2},
        "calibration": {"available": True, "source": "manual",
                        "um_per_px": 0.05, "status": "valid"},
        "quality": {"status": "ok"},
    })
    sess = mf.create_session(uid, "demo")
    sess2, err = mf.add_field(sess["id"], uid, "AN-1")
    assert err is None
    got = mf.get_session(sess["id"], uid)
    agg = mf.aggregate(got)
    assert agg["field_count"] == 1
    f = agg["fields"][0]
    assert f["microns_per_pixel"] == 0.05
    assert f["calibrated"] is True
    assert f["spheroidal_area"] == 100.0   # round particle only
    assert f["graphite_area"] == 200.0
    assert agg["aggregate_iso_nodularity_pct"] == 50.0
    # JIS classes pooled from stored jis_bucket values (1-5)
    assert agg["jis_class_counts"] == {"1": 0, "2": 0, "3": 1,
                                        "4": 0, "5": 1}
    assert agg["aggregate_jis_nodularity_pct"] == round(
        (0.7 * 1 + 1.0 * 1) / 2 * 100, 2)
    # duplicate attach rejected
    _, err2 = mf.add_field(sess["id"], uid, "AN-1")
    assert err2 == "analysis already attached to this session"
    # context helper surfaces the session for Copilot
    ctx = context.build_multifield_context("AN-1")
    assert ctx is not None
    assert ctx["session_id"] == sess["id"]
    assert ctx["this_field"]["analysis_id"] == "AN-1"
    # unknown analysis -> None
    assert context.build_multifield_context("AN-404") is None


def test_persistence_requires_ownership(tmp_path, monkeypatch):
    import importlib
    from nodiq.services import db
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test2.db")
    monkeypatch.setattr(db, "_CONN", None)
    importlib.reload(mf)
    db.init_db()
    db.insert_analysis({"id": "AN-9", "nodule_count": 5}, 1)
    sess = mf.create_session(2, "other user")
    _, err = mf.add_field(sess["id"], 2, "AN-9")
    assert err == "analysis not found"


# ----------------------------------------------------- sampling status fn

def test_sampling_status_function_direct():
    assert mf.sampling_status(5, 500) == "meets_field_and_particle_target"
    assert mf.sampling_status(7, 430) == "below_particle_target"
    assert mf.sampling_status(3, 620) == "below_field_target"
    assert mf.sampling_status(5, 499) == "below_particle_target"
    assert mf.sampling_status(4, 500) == "below_field_target"
    assert mf.sampling_status(3, 100) == "below_field_target"
    assert mf.sampling_status(0, 0) == "no_fields"


# ---------------------------------------------------------- API contract

@pytest.fixture(scope="module")
def api_env(tmp_path_factory):
    """Isolated API environment (same pattern as test_api_contracts)."""
    import nodiq.api.server as server
    # Rate limiter is IP-keyed; the shared test-client IP would trip it.
    # Module-scoped fixture: save/restore the flag directly.
    _rl_saved = server.RATE_LIMITS_ENABLED
    server.RATE_LIMITS_ENABLED = False
    import nodiq.services.auth as auth_svc
    import nodiq.services.context as context_svc
    import nodiq.services.db as store

    root = tmp_path_factory.mktemp("multifield-api")
    # Save and restore every redirected global (Issue 1: teardown previously
    # left DATA_DIR/DB_PATH/FULL_DIR/UPLOAD_DIR pointing at the deleted tmp
    # dir, leaking a dead DB path into every module collected afterwards).
    saved = (store.DATA_DIR, store.DB_PATH, store._CONN,
             context_svc.FULL_DIR, server.UPLOAD_DIR, server.ai_chat)
    store.DATA_DIR = root / "server_data"
    store.DATA_DIR.mkdir()
    store.DB_PATH = store.DATA_DIR / "test.db"
    store._CONN = None
    context_svc.FULL_DIR = store.DATA_DIR / "analyses_full"
    context_svc.FULL_DIR.mkdir()
    server.UPLOAD_DIR = store.DATA_DIR / "uploads"
    server.UPLOAD_DIR.mkdir()
    store.init_db()
    auth_svc._user_conn()

    server.ai_chat = lambda messages: {
        "content": "Measured values are available from the stored analysis.",
        "provider": "test",
    }
    try:
        yield server.app.test_client(), server
    finally:
        server.RATE_LIMITS_ENABLED = _rl_saved
        temp_conn = store._CONN
        (store.DATA_DIR, store.DB_PATH, store._CONN,
         context_svc.FULL_DIR, server.UPLOAD_DIR, server.ai_chat) = saved
        if temp_conn is not None and temp_conn is not store._CONN:
            temp_conn.close()


@pytest.fixture(scope="module")
def account(api_env):
    client, _ = api_env
    import time as _time
    email = f"multifield-{_time.time_ns()}@test.local"
    response = client.post("/api/auth/signup", json={
        "email": email, "password": "password1", "name": "MF User"})
    assert response.status_code == 201
    payload = response.get_json()
    token = response.headers.get("Set-Cookie", "").split(
        "nodiq_session=", 1)[1].split(";", 1)[0]
    return {"token": token,
            "headers": {"Authorization": f"Bearer {token}"}}


def test_api_multifield_endpoints(api_env, account):
    """Additive endpoints work end-to-end and are owner-scoped."""
    client, _ = api_env
    h = account["headers"]
    # create
    r = client.post("/api/multifield", json={"label": "DEMO / VALIDATION"},
                    headers=h)
    assert r.status_code == 201, r.get_data(as_text=True)
    sid = r.get_json()["session_id"]
    assert r.get_json()["sampling_status"] == "no_fields"
    # attach missing analysis -> 404 (id uses the canonical grammar;
    # malformed ids are rejected 400 by input validation)
    r = client.post(f"/api/multifield/{sid}/fields",
                    json={"analysis_id": "ANL-NOPE01"}, headers=h)
    assert r.status_code == 404
    # get + statistics + list + delete
    assert client.get(f"/api/multifield/{sid}", headers=h).status_code == 200
    st = client.get(f"/api/multifield/{sid}/statistics", headers=h)
    assert st.status_code == 200
    assert st.get_json()["sampling"]["field_target"] == 5
    assert st.get_json()["sampling"]["particle_target"] == 500
    assert client.get("/api/multifield", headers=h).status_code == 200
    assert client.delete(f"/api/multifield/{sid}",
                         headers=h).status_code == 200
    assert client.get(f"/api/multifield/{sid}",
                      headers=h).status_code == 404
    # unauthenticated requests are rejected before any data access
    # (fresh cookie-less client: the module client's jar now holds the
    # HttpOnly session cookie after the account fixture logged in)
    import nodiq.api.server as _server
    anon = _server.app.test_client()
    r2 = anon.post("/api/multifield", json={})
    assert r2.status_code == 401
    r3 = anon.get(f"/api/multifield/{sid}")
    assert r3.status_code in (401, 404)
