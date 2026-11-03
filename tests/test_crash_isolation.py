"""Regression tests: the heavy analysis runs in an ISOLATED child process
(analysis_child.py). If the child is OOM-killed or crashes hard, the web
server must survive and the pending analysis record must flip to an honest
"failed" state — instead of taking the whole container down (crash-loop →
502s → wiped sessions on Render's ephemeral free-tier disk)."""
import io
import sys
import time
from pathlib import Path

import numpy as np
import pytest


import nodiq.services.auth as auth_svc
import nodiq.services.context as context_svc
import nodiq.services.db as store


@pytest.fixture(scope="module")
def api_env(tmp_path_factory):
    import nodiq.api.server as server
    _rl_saved = server.RATE_LIMITS_ENABLED
    server.RATE_LIMITS_ENABLED = False
    root = tmp_path_factory.mktemp("crash-isolation")
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
    email = f"crash-iso-{time.time_ns()}@test.local"
    response = client.post("/api/auth/signup", json={
        "email": email, "password": "password1", "name": "Crash Iso User",
    })
    assert response.status_code == 201
    token = response.headers.get("Set-Cookie", "").split(
        "nodiq_session=", 1)[1].split(";", 1)[0]
    return {"headers": {"Authorization": f"Bearer {token}"}}


def _png_bytes():
    import cv2
    rng = np.random.RandomState(11)
    img = np.full((240, 240), 200, np.uint8)
    img += rng.randint(-8, 9, img.shape).astype(np.uint8)
    for cy, cx, r in ((70, 70, 16), (160, 120, 12), (120, 180, 10)):
        cv2.circle(img, (cx, cy), r, 30, -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def _wait_terminal(client, headers, analysis_id, seconds=30):
    deadline = time.time() + seconds
    status, detail = None, None
    while time.time() < deadline:
        detail = client.get(f"/api/analyses/{analysis_id}",
                            headers=headers).get_json()
        status = (detail or {}).get("status") or \
                 ((detail or {}).get("record") or {}).get("status")
        if status in ("completed", "failed"):
            return status, detail
        time.sleep(0.2)
    return status, detail


def test_child_crash_marks_analysis_failed_and_server_survives(
        api_env, account):
    """Stub the child entrypoint with a script that exits 137 (128+SIGKILL,
    the parent-visible signature of an OOM kill) WITHOUT writing anything.
    The parent must flip the pending record to failed with a user-facing
    message — and keep serving traffic."""
    client, mod = api_env
    crashed = Path(store.DATA_DIR) / "crash_stub.py"
    crashed.write_text(
        "import sys\n"
        "sys.stderr.write('simulated OOM kill\\n')\n"
        "sys.exit(137)\n"
    )
    original_entry = mod._CHILD_ENTRYPOINT
    mod._CHILD_ENTRYPOINT = crashed
    # force child execution mode: the crash simulation stubs the child
    # process entrypoint, which thread mode (default) never spawns
    original_mode = mod._EXEC_MODE
    mod._EXEC_MODE = "child"
    try:
        resp = client.post("/api/analyze", data={
            "image": (io.BytesIO(_png_bytes()), "synthetic.png"),
        }, headers=account["headers"], content_type="multipart/form-data")
        assert resp.status_code == 202, resp.get_json()
        analysis_id = resp.get_json()["analysis_id"]
        status, detail = _wait_terminal(client, account["headers"],
                                        analysis_id)
        assert status == "failed", detail
        rec = (detail or {}).get("record") or detail or {}
        assert "interrupted" in str(rec.get("error", "")).lower()
        # ...and the web server is still alive:
        assert client.get("/api/health").status_code == 200
    finally:
        mod._CHILD_ENTRYPOINT = original_entry
        mod._EXEC_MODE = original_mode


def test_child_success_path_completes_via_real_entrypoint(api_env, account):
    """The real child protocol end to end in-process: spawn -> heavy pass ->
    completed record + full payload, all values internally consistent."""
    client, _ = api_env
    resp = client.post("/api/analyze",
                       json={"dataset_image": "micrograph_0001.png"},
                       headers=account["headers"])
    assert resp.status_code == 202, resp.get_json()
    analysis_id = resp.get_json()["analysis_id"]
    status, detail = _wait_terminal(client, account["headers"], analysis_id,
                                    seconds=90)
    assert status == "completed", detail
    payload = (detail or {}).get("analysis") or {}
    assert payload.get("analysis_id") == analysis_id
    assert payload.get("nodule_count") == len(payload.get("nodules") or [])
    assert 0 <= payload.get("iso_nodularity_pct", -1) <= 100
    assert 0 <= payload.get("jis_nodularity_pct", -1) <= 100
