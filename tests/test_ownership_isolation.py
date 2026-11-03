#!/usr/bin/env python3
"""
tests/test_ownership_isolation.py — authorization regression tests.

One test per data-bearing route (or route family) proving that user A cannot
read, update, or delete user B's records, that every user id is derived from
the verified bearer token (never from the request), and that anonymous
callers cannot touch per-account data at all.
"""
import json
import sys
import time
from pathlib import Path

import pytest


import nodiq.services.auth as auth_svc
import nodiq.services.context as context_svc
import nodiq.services.db as store


@pytest.fixture(scope="module")
def api_env(tmp_path_factory):
    """Isolated server + DB, rate limiter off, deterministic AI provider."""
    import nodiq.api.server as server
    _rl_saved = server.RATE_LIMITS_ENABLED
    server.RATE_LIMITS_ENABLED = False

    root = tmp_path_factory.mktemp("ownership")
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

    server.ai_chat = lambda messages, **kw: {
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
def users(api_env):
    """Two fully independent accounts, each with one stored analysis."""
    client, _ = api_env

    def _mk(tag):
        email = f"own-{tag}-{time.time_ns()}@test.local"
        r = client.post("/api/auth/signup", json={
            "email": email, "password": "password1", "name": f"User {tag}"})
        assert r.status_code == 201, r.get_json()
        # Session token comes from the HttpOnly Set-Cookie header now
        # (never in the JSON body). Header-based auth is still supported
        # for API clients, which lets one client juggle A/B identities.
        token = r.headers.get("Set-Cookie", "").split(
            "nodiq_session=", 1)[1].split(";", 1)[0]
        headers = {"Authorization": f"Bearer {token}"}
        r = client.post("/api/analyze", json={
            "dataset_image": "micrograph_0001.png"}, headers=headers)
        assert r.status_code == 202, r.get_json()
        aid = r.get_json()["analysis_id"]
        # /api/analyze is async: poll the detail endpoint until the worker
        # finishes (same flow as the frontend) before asserting on records.
        # While processing the shape is {status, progress, ...}; once the
        # worker stores the payload it flips to the legacy {record, analysis}.
        deadline = time.time() + 60
        while time.time() < deadline:
            detail = client.get(f"/api/analyses/{aid}", headers=headers).get_json()
            status = detail.get("status") or detail.get("record", {}).get("status")
            if status != "processing":
                break
            time.sleep(0.2)
        assert status == "completed", detail
        me = client.get("/api/auth/me", headers=headers).get_json()["user"]
        return {"headers": headers, "aid": aid, "email": email,
                "password": "password1", "uid": me["id"],
                "role": me.get("role")}

    return {"A": _mk("a"), "B": _mk("b")}


def _post(client, path, payload, headers):
    return client.post(path, data=json.dumps(payload),
                       content_type="application/json", headers=headers)


# ------------------------------------------------------------------ analyses
def test_analysis_detail_is_private(api_env, users):
    client, _ = api_env
    assert client.get(f"/api/analyses/{users['B']['aid']}",
                      headers=users["A"]["headers"]).status_code == 404


# ------------------------------------------------------------------ artifacts
def test_artifacts_are_private(api_env, users):
    """Every artifact kind (original/annotated/mask) is 404 for another user
    and for anonymous callers — persistence-backend independent."""
    client, app = api_env
    # cookie-free client: the module client's jar still carries B's session
    fresh = app.app.test_client()
    for kind in ("original", "annotated", "mask"):
        assert client.get(
            f"/api/analyses/{users['B']['aid']}/artifact/{kind}",
            headers=users["A"]["headers"]).status_code == 404, kind
        assert fresh.get(
            f"/api/analyses/{users['B']['aid']}/artifact/{kind}",
        ).status_code == 404, kind


def test_artifacts_serve_own_records(api_env, users):
    """The owner receives real PNG bytes (status 200, image/png) for kinds
    the analysis child persisted — guards against a regression where the
    route serves arbitrary bytes or leaks a 500 on a missing file."""
    client, _ = api_env
    for kind in ("annotated", "mask"):
        r = client.get(
            f"/api/analyses/{users['A']['aid']}/artifact/{kind}",
            headers=users["A"]["headers"])
        assert r.status_code == 200, kind
        assert r.mimetype == "image/png", kind
        assert r.data[:8] == b"\x89PNG\r\n\x1a\n", kind


def test_artifact_kind_whitelist(api_env, users):
    """Only the three real artifact kinds resolve; anything else 404s."""
    client, _ = api_env
    r = client.get(
        f"/api/analyses/{users['A']['aid']}/artifact/report",
        headers=users["A"]["headers"])
    assert r.status_code == 404


def test_analyses_list_shows_only_own(api_env, users):
    client, _ = api_env
    ids_a = [a["id"] for a in client.get(
        "/api/analyses", headers=users["A"]["headers"]).get_json()["analyses"]]
    assert users["A"]["aid"] in ids_a and users["B"]["aid"] not in ids_a


def test_analysis_delete_is_private(api_env, users):
    client, _ = api_env
    r = client.delete(f"/api/analyses/{users['B']['aid']}",
                      headers=users["A"]["headers"])
    assert r.status_code == 404
    # B still has it
    assert client.get(f"/api/analyses/{users['B']['aid']}",
                      headers=users["B"]["headers"]).status_code == 200


def test_analysis_nodules_and_quality_are_private(api_env, users):
    client, _ = api_env
    for path in (f"/api/analyses/{users['B']['aid']}/nodules",
                 f"/api/quality/{users['B']['aid']}",
                 f"/api/analyses/{users['B']['aid']}/overlay",
                 f"/api/analyses/{users['B']['aid']}/image",
                 f"/api/analyses/{users['B']['aid']}/context"):
        assert client.get(path,
                          headers=users["A"]["headers"]).status_code == 404, path


def test_lot_and_review_updates_are_private(api_env, users):
    client, _ = api_env
    r = _post(client, f"/api/analyses/{users['B']['aid']}/lot",
              {"lot_id": "HIJACK"}, users["A"]["headers"])
    assert r.status_code == 404
    # Review is reviewer/admin-only (RBAC) AND owner-scoped. A is an
    # operator, so this case now exercises the RBAC layer (403); ownership
    # (404 for a foreign analysis) is covered by the reviewer case below.
    r = _post(client, f"/api/analyses/{users['B']['aid']}/review",
              {"status": "approved"}, users["A"]["headers"])
    assert r.status_code == 403
    # Promote A to reviewer so the ownership gate itself is exercised:
    # even with the required role, another user's analysis stays 404.
    import nodiq.services.auth as _auth
    _auth.set_role(users["A"]["uid"], "reviewer")
    r = _post(client, f"/api/analyses/{users['B']['aid']}/review",
              {"status": "approved"}, users["A"]["headers"])
    assert r.status_code == 404
    # B's record untouched
    rec = client.get(f"/api/analyses/{users['B']['aid']}",
                     headers=users["B"]["headers"]).get_json()["record"]
    assert rec.get("lot_id") in (None, "")
    assert rec.get("review") is None


# -------------------------------------------------------------- bulk reads
def test_stats_and_batch_are_per_user(api_env, users):
    client, _ = api_env
    stats_a = client.get("/api/analyses/stats",
                         headers=users["A"]["headers"]).get_json()
    assert stats_a["total_analyses"] >= 1
    # A's totals must not include B's analysis
    detail = client.get(f"/api/analyses/{users['B']['aid']}",
                        headers=users["B"]["headers"]).get_json()
    assert detail["record"]["id"] not in ("", None)
    ids_a = {a["id"] for a in client.get(
        "/api/analyses", headers=users["A"]["headers"]).get_json()["analyses"]}
    assert users["B"]["aid"] not in ids_a
    assert stats_a["total_analyses"] == len(ids_a)


def test_anomalies_for_foreign_analysis_is_404(api_env, users):
    client, _ = api_env
    assert client.get(f"/api/anomalies/{users['B']['aid']}",
                      headers=users["A"]["headers"]).status_code == 404


def test_compare_cannot_pull_foreign_analysis(api_env, users):
    client, _ = api_env
    r = _post(client, "/api/compare",
              {"analysis_a": users["A"]["aid"],
               "analysis_b": users["B"]["aid"]}, users["A"]["headers"])
    if r.status_code == 200:
        comp = r.get_json()
        dumped = json.dumps(comp)
        # B's id can appear only if B's data was actually included
        assert users["B"]["aid"] not in dumped or comp.get("analysis_b") is None
    # B's payload must never leak either way
    assert users["B"]["aid"] not in json.dumps(
        client.get("/api/analyses", headers=users["A"]["headers"]).get_json())


def test_decision_support_foreign_is_404(api_env, users):
    client, _ = api_env
    r = _post(client, "/api/decision-support",
              {"analysis_id": users["B"]["aid"]}, users["A"]["headers"])
    assert r.status_code == 404


def test_calibration_foreign_analysis_is_404(api_env, users):
    client, _ = api_env
    r = _post(client, "/api/calibration",
              {"analysis_id": users["B"]["aid"]}, users["A"]["headers"])
    assert r.status_code == 404


# ------------------------------------------------------------------- reports
def test_reports_are_per_user(api_env, users):
    client, _ = api_env
    r = _post(client, "/api/reports/generate",
              {"analysis_id": users["B"]["aid"]}, users["A"]["headers"])
    if r.status_code == 201:
        report = r.get_json()
        # generated from A's history, never B's analysis
        assert report.get("analysis_id") != users["B"]["aid"]
    rid_b = None
    r = _post(client, "/api/reports/generate", {"analysis_id": users["B"]["aid"]},
              users["B"]["headers"])
    assert r.status_code == 201
    rid_b = r.get_json()["id"]
    assert client.get(f"/api/reports/{rid_b}",
                      headers=users["A"]["headers"]).status_code == 404
    assert client.get(f"/api/reports/{rid_b}",
                      headers=users["B"]["headers"]).status_code == 200
    assert client.delete(f"/api/reports/{rid_b}",
                         headers=users["A"]["headers"]).status_code == 404
    assert client.get(f"/api/reports/{rid_b}/download",
                      headers=users["A"]["headers"]).status_code == 404
    for kind in ("original", "annotated"):
        assert client.get(f"/api/reports/{rid_b}/evidence/{kind}",
                          headers=users["A"]["headers"]).status_code == 404
    # cleanup for the module-shared store
    assert client.delete(f"/api/reports/{rid_b}",
                         headers=users["B"]["headers"]).status_code == 200


def test_ai_summary_foreign_is_404(api_env, users):
    client, _ = api_env
    r = _post(client, "/api/reports/ai-summary",
              {"analysis_id": users["B"]["aid"]}, users["A"]["headers"])
    assert r.status_code == 404


# ------------------------------------------------------------- work sessions
def test_work_sessions_are_private(api_env, users):
    client, _ = api_env
    r = client.get("/api/sessions", headers=users["B"]["headers"])
    sids = [s["id"] for s in r.get_json()["sessions"]]
    for sid in sids:
        assert client.get(f"/api/sessions/{sid}",
                          headers=users["A"]["headers"]).status_code == 404
        assert client.delete(f"/api/sessions/{sid}",
                             headers=users["A"]["headers"]).status_code == 404


# ------------------------------------------------------- multi-field sampling
def test_multifield_sessions_are_private(api_env, users):
    client, _ = api_env
    r = _post(client, "/api/multifield", {"label": "B private"},
              users["B"]["headers"])
    assert r.status_code == 201
    sid = r.get_json()["session_id"]
    assert client.get(f"/api/multifield/{sid}",
                      headers=users["A"]["headers"]).status_code == 404
    assert client.get(f"/api/multifield/{sid}/statistics",
                      headers=users["A"]["headers"]).status_code == 404
    assert _post(client, f"/api/multifield/{sid}/fields",
                 {"analysis_id": users["A"]["aid"]},
                 users["A"]["headers"]).status_code == 404
    assert client.delete(f"/api/multifield/{sid}",
                         headers=users["A"]["headers"]).status_code == 404
    # B can still use it
    assert client.get(f"/api/multifield/{sid}",
                      headers=users["B"]["headers"]).status_code == 200
    assert client.delete(f"/api/multifield/{sid}",
                         headers=users["B"]["headers"]).status_code == 200


def test_multifield_cannot_attach_foreign_analysis(api_env, users):
    client, _ = api_env
    r = _post(client, "/api/multifield", {"label": "A fields"},
              users["A"]["headers"])
    sid = r.get_json()["session_id"]
    r = _post(client, f"/api/multifield/{sid}/fields",
              {"analysis_id": users["B"]["aid"]}, users["A"]["headers"])
    assert r.status_code == 404
    client.delete(f"/api/multifield/{sid}", headers=users["A"]["headers"])


# ------------------------------------------------------------------- copilot
def test_copilot_memory_is_namespaced_per_user(api_env, users, tmp_path,
                                               monkeypatch):
    client, _ = api_env
    import nodiq.ai.memory as mem
    monkeypatch.setattr(mem, "SESSIONS_DIR", tmp_path)
    # A talks, then B replays A's session id — B must not receive A's context
    _post(client, "/api/copilot", {"message": "hello from A",
                                   "session_id": "shared-sid"},
          users["A"]["headers"])
    r = _post(client, "/api/copilot", {"message": "what did I just say?",
                                       "session_id": "shared-sid"},
              users["B"]["headers"])
    assert r.status_code == 200
    # distinct files per owner in the (patched) sessions dir
    names = [p.name for p in tmp_path.glob("*.json")]
    assert len(names) == 2 and all("--" in n for n in names)


def test_copilot_requires_auth(api_env):
    # fresh cookie-less client: module client's jar holds the session cookie
    import nodiq.api.server as _server
    anon = _server.app.test_client()
    assert _post(anon, "/api/copilot", {"message": "hi"},
                 {}).status_code == 401


# ------------------------------------------------------------- write guards
def test_analyses_post_cannot_hijack_foreign_id(api_env, users):
    client, _ = api_env
    r = _post(client, "/api/analyses",
              {"id": users["B"]["aid"], "title": "stolen",
               "iso_nodularity_pct": 1.0}, users["A"]["headers"])
    assert r.status_code == 409
    # B's record is intact and still B's
    rec = client.get(f"/api/analyses/{users['B']['aid']}",
                     headers=users["B"]["headers"]).get_json()["record"]
    assert rec["title"] != "stolen"


def test_analyses_post_allows_own_id_upsert(api_env, users):
    client, _ = api_env
    r = _post(client, "/api/analyses",
              {"id": users["A"]["aid"], "title": "renamed by owner"},
              users["A"]["headers"])
    assert r.status_code == 201
    rec = client.get(f"/api/analyses/{users['A']['aid']}",
                     headers=users["A"]["headers"]).get_json()["record"]
    assert rec["title"] == "renamed by owner"


def test_analyze_requires_auth(api_env):
    # fresh cookie-less client: module client's jar holds the session cookie
    import nodiq.api.server as _server
    anon = _server.app.test_client()
    r = _post(anon, "/api/analyze", {"dataset_image": "micrograph_0001.png"}, {})
    assert r.status_code == 401
    # ownerless rows are the exact bug this prevents
    assert anon.get("/api/analyses", headers={}).status_code == 401


def test_analyze_rejects_path_like_dataset_names(api_env, users):
    client, _ = api_env
    for bad in ("../server.py", "micrograph_0001.png%00.png",
                "sub/dir/micrograph_0001.png", "server.db"):
        r = _post(client, "/api/analyze", {"dataset_image": bad},
                  users["A"]["headers"])
        assert r.status_code in (400, 404), bad


# ------------------------------------------------- user id never from input
def test_no_user_id_in_request_inputs(api_env, users):
    client, _ = api_env
    # attempting to steer the account via body/query must not change
    # what A can see (the server derives identity from the token only)
    # Strict schema: client-supplied owner/user fields are REJECTED, not
    # silently ignored (mass-assignment hardening).
    r = _post(client, "/api/analyses",
              {"user_id": users["B"]["aid"], "id": "ANL-SPOOF1",
               "title": "x"}, users["A"]["headers"])
    assert r.status_code == 400, r.get_json()
    # identity still comes from the token alone: same id without the
    # spoofed field lands in A's account, never B's
    r = _post(client, "/api/analyses",
              {"id": "ANL-SPOOF1", "title": "x"}, users["A"]["headers"])
    assert r.status_code == 201, r.get_json()
    ids_a = [a["id"] for a in client.get(
        "/api/analyses", headers=users["A"]["headers"]).get_json()["analyses"]]
    assert "ANL-SPOOF1" in ids_a            # went to A, not to B
    ids_b = [a["id"] for a in client.get(
        "/api/analyses", headers=users["B"]["headers"]).get_json()["analyses"]]
    assert "ANL-SPOOF1" not in ids_b
    client.delete("/api/analyses/ANL-SPOOF1", headers=users["A"]["headers"])


def test_anonymous_reads_match_nothing(api_env):
    # fresh cookie-less client: module client's jar holds the session cookie
    import nodiq.api.server as _server
    anon = _server.app.test_client()
    assert anon.get("/api/analyses").status_code == 401
    assert anon.get("/api/analyses/ANL-ANYTHING").status_code == 404
    assert anon.get("/api/reports/RPT-ANYTHING").status_code == 404
    assert anon.get("/api/sessions").status_code == 401
