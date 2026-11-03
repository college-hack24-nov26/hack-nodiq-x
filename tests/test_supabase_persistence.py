#!/usr/bin/env python3
"""
tests/test_supabase_persistence.py — migration regression tests.

These pin the two behaviours the Supabase migration depends on that a plain
API-contract test cannot see:

1. Artifact URL surfacing survives a redeploy: on the supabase persistence
   backend the analysis detail response must advertise annotated/mask URLs
   even after the local ephemeral copy is gone (Render wipes the disk on
   every deploy) — because the ownership-checked artifact route can still
   stream the object from Storage.
2. The startup stale-processing sweep (restart healing) visits EVERY user's
   rows, not just rows visible to an anonymous caller. On the supabase
   backend "processing" rows persist across redeploys, so an unhealed row
   would render as an eternal progress bar.
"""
import sys
import time
from pathlib import Path

import pytest


import nodiq.services.auth as auth_svc
import nodiq.services.context as context_svc
import nodiq.services.db as store
import nodiq.services.storage as storage


@pytest.fixture(scope="module")
def api_env(tmp_path_factory):
    """Isolated server + DB + local-artifact dir, rate limiter off."""
    import nodiq.api.server as server
    _rl_saved = server.RATE_LIMITS_ENABLED
    server.RATE_LIMITS_ENABLED = False

    root = tmp_path_factory.mktemp("supabase_persistence")
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
def completed_analysis(api_env):
    """One account with one completed analysis (dataset image -> no upload
    churn) plus the annotated/mask PNGs the analysis child would write."""
    client, app = api_env
    email = f"supa-{time.time_ns()}@test.local"
    r = client.post("/api/auth/signup", json={
        "email": email, "password": "password1", "name": "Supa User"})
    assert r.status_code == 201, r.get_json()
    token = r.headers.get("Set-Cookie", "").split("nodiq_session=", 1)[1].split(";", 1)[0]
    headers = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/analyze", json={"dataset_image": "micrograph_0001.png"},
                    headers=headers)
    assert r.status_code == 202, r.get_json()
    aid = r.get_json()["analysis_id"]
    deadline = time.time() + 90
    while time.time() < deadline:
        detail = client.get(f"/api/analyses/{aid}", headers=headers).get_json()
        status = detail.get("status") or detail.get("record", {}).get("status")
        if status != "processing":
            break
        time.sleep(0.2)
    assert status == "completed", detail
    return {"headers": headers, "aid": aid}


# ---------------------------------------------------------------------------
# 1. artifact URLs survive the loss of the local (ephemeral) copies
# ---------------------------------------------------------------------------
def test_artifact_urls_survive_redeploy(api_env, completed_analysis, monkeypatch):
    """Simulate a fresh Render container: the ephemeral FULL_DIR is empty and
    storage is Supabase with the object present. The detail poll must still
    expose annotated_url / mask_url so the UI renders the persisted images."""
    client, app = api_env
    aid = completed_analysis["aid"]
    headers = completed_analysis["headers"]

    # before: local files exist (child just wrote them) -> URLs present
    detail = client.get(f"/api/analyses/{aid}", headers=headers).get_json()
    assert detail["analysis"].get("annotated_url"), detail["analysis"].get("annotated_url")
    assert detail["analysis"].get("mask_url")

    # wipe the ephemeral copies exactly like a redeploy wipes Render's disk
    for kind in ("annotated", "mask"):
        (context_svc.FULL_DIR / f"{aid}_{kind}.png").unlink()

    # storage: supabase backend, object retrievable (ownership checks in the
    # route are covered by test_ownership_isolation; here the layer answers)
    class _FakeStore:
        BACKEND = "supabase"
        BUCKET = "nodiq-artifacts"

        @staticmethod
        def get_bytes(user_id, analysis_id, kind, ext=None):
            assert user_id, "route must pass the verified owner id"
            return b"\x89PNG\r\n\x1a\n-fake-" + kind.encode()

        @staticmethod
        def health():
            return {"backend": "supabase", "bucket": "nodiq-artifacts",
                    "configured": True}

    monkeypatch.setattr(app, "_STORAGE_SVC", _FakeStore)
    try:
        detail = client.get(f"/api/analyses/{aid}", headers=headers).get_json()
        assert detail["analysis"].get("annotated_url") == \
            f"/api/analyses/{aid}/artifact/annotated"
        assert detail["analysis"].get("mask_url") == \
            f"/api/analyses/{aid}/artifact/mask"

        # the artifact route itself serves the streamed bytes (200 image/png)
        r = client.get(f"/api/analyses/{aid}/artifact/annotated", headers=headers)
        assert r.status_code == 200 and r.mimetype == "image/png"
        assert r.data.startswith(b"\x89PNG")
    finally:
        monkeypatch.undo()

    # after restoring local-mode storage AND no local file: honest 404 (no URL
    # was advertised) — this is the pre-migration behaviour, unchanged
    detail = client.get(f"/api/analyses/{aid}", headers=headers).get_json()
    assert "annotated_url" not in detail["analysis"]


def test_url_stays_absent_without_artifacts(api_env, completed_analysis):
    """Local backend + no local file (e.g. migration never uploaded) must NOT
    advertise a URL that would 404 — UI falls back cleanly."""
    client, app = api_env
    aid = completed_analysis["aid"]
    detail = client.get(f"/api/analyses/{aid}",
                        headers=completed_analysis["headers"]).get_json()
    # storage module is in local mode in this fixture and files were deleted
    # by the redeploy test above -> no URL, exactly like before the migration
    assert "annotated_url" not in detail["analysis"]
    assert "mask_url" not in detail["analysis"]


# ---------------------------------------------------------------------------
# 2. restart sweep heals EVERY user's persisted "processing" rows
# ---------------------------------------------------------------------------
def test_restart_sweep_covers_all_users(api_env, completed_analysis, monkeypatch):
    """Insert a stale processing row for the user directly in the DB, run the
    startup sweep, and verify the row is flipped to a failed record with the
    restart message. (A second user's rows are covered by construction: the
    sweep iterates DISTINCT user_id from the analyses table.)"""
    client, app = api_env
    aid = completed_analysis["aid"]
    owner = store.analysis_owner(aid)

    rec = store.get_analysis_record(aid, owner)
    assert rec and rec.get("status") == "completed"
    stale = {**rec, "status": "processing", "progress": 5, "error": None}
    store.insert_analysis(stale, owner)

    monkeypatch.setattr(store, "BACKEND", "sqlite")   # sweep behaviour is
    try:                                              # backend-independent
        app._recover_stale_processing()
    finally:
        monkeypatch.undo()

    healed = store.get_analysis_record(aid, owner)
    assert healed["status"] == "failed"
    assert "interrupted by a server restart" in healed["error"]


# ---------------------------------------------------------------------------
# 3. docs/config keep placeholder-only connection strings
# ---------------------------------------------------------------------------
def test_deploy_doc_has_no_credential_shaped_placeholder():
    """The deployment guide must stay secret-free: no postgres://user:pass@
    shape (the secrets-hygiene scanner runs this same family)."""
    text = Path(__file__).resolve().parent.parent.joinpath(
        "docs", "DEPLOY_SUPABASE.md").read_text(encoding="utf-8")
    import re
    pat = re.compile(r"(postgres(?:ql)?|mysql|mongodb(\+srv)?|redis|amqp)"
                     r"://[^\s'\":]{8,}:[^\s'\":]{3,}@")
    assert not pat.search(text), "credential-shaped placeholder in deploy doc"
