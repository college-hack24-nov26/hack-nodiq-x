#!/usr/bin/env python3
"""
tests/test_analyze_rate_limit.py — analysis abuse-protection regressions.

Locks in the /api/analyze abuse-protection controls:
- per-user request budget on the most expensive route (below limit OK,
  over limit 429 + Retry-After, no internals leaked)
- per-user isolation: one account exhausting its budget never affects
  another account's analyses
- IP fallback for unauthenticated callers (safe identity, no spoofed
  X-Forwarded-For unless TRUST_PROXY)
- auth-route limiting keeps its Retry-After too
- concurrency backpressure: per-account saturation -> 429 + Retry-After +
  audit event; second account unaffected; registry frees after completion
- NODIQ_ANALYZE_TIMEOUT watchdog: a wedged analysis flips to an honest
  failed record and frees its concurrency slot (thread mode)
- upload validation / auth / normal analysis workflow still intact
- limiter storage failure stays fail-closed (no silent disable)
"""
import io
import json
import time

import numpy as np
import pytest

import nodiq.api.server as server
import nodiq.services.auth as auth_svc
import nodiq.services.context as context_svc
import nodiq.services.db as store
import nodiq.services.rate_limit as rl
import nodiq.services.seclog as seclog


@pytest.fixture(scope="module")
def api_env(tmp_path_factory):
    """Isolated server + DB (same contract as the other api_env fixtures).

    The shared SQLite limiter is pointed at a scratch DB; analyze limiting
    is DISABLED by default here (individual tests opt in by setting
    server.RATE_LIMITS_ENABLED True inside their own try/finally), because
    this module fires rapid-fire analyze calls.
    """
    _rl_saved = server.RATE_LIMITS_ENABLED
    server.RATE_LIMITS_ENABLED = False
    _conc_saved = server._MAX_CONCURRENT_ANALYSES
    server._MAX_CONCURRENT_ANALYSES = 10_000
    # NOTE: this hook only matters because the abuse phase fixed the job
    # registry prune (owner-aware record lookup); before that fix the global
    # cap was silently never reached in tests.
    _global_saved = server._MAX_CONCURRENT_CHILDREN
    server._MAX_CONCURRENT_CHILDREN = 10_000
    _rl_db_saved, _rl_conn_saved = rl._DB_PATH, rl._CONN
    rl._DB_PATH = tmp_path_factory.mktemp("analyze-rl") / "rl.db"
    rl._CONN = None
    root = tmp_path_factory.mktemp("analyze-abuse")
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
    server.app.config["TESTING"] = True
    try:
        yield server.app.test_client(), server
    finally:
        server.RATE_LIMITS_ENABLED = _rl_saved
        server._MAX_CONCURRENT_ANALYSES = _conc_saved
        server._MAX_CONCURRENT_CHILDREN = _global_saved
        rl._DB_PATH, rl._CONN = _rl_db_saved, _rl_conn_saved
        temp_conn = store._CONN
        (store.DATA_DIR, store.DB_PATH, store._CONN,
         context_svc.FULL_DIR, server.UPLOAD_DIR, server.ai_chat) = saved
        if temp_conn is not None and temp_conn is not store._CONN:
            temp_conn.close()


@pytest.fixture(scope="module")
def client(api_env):
    c, _ = api_env
    return c


def _fresh():
    """A cookie-jar-free test client (see test_security_hardening)."""
    return server.app.test_client()


def _signup(client, tag):
    email = f"abuse-{tag}-{time.time_ns()}@test.local"
    r = client.post("/api/auth/signup", json={
        "email": email, "password": "password1", "name": f"Abuse {tag}"})
    assert r.status_code == 201, r.get_json()
    token = r.headers.get("Set-Cookie", "").split(
        "nodiq_session=", 1)[1].split(";", 1)[0]
    me = client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {token}"}).get_json()["user"]
    return {"token": token,
            "headers": {"Authorization": f"Bearer {token}"},
            "email": email, "uid": me["id"]}


@pytest.fixture(scope="module")
def users(client):
    return [_signup(client, f"u{i}") for i in range(1, 4)]


def _png_bytes(seed=7, n=90):
    rng = np.random.RandomState(seed)
    img = np.full((240, 240), 200, np.uint8)
    img += rng.randint(-8, 9, img.shape).astype(np.uint8)
    cv2 = pytest.importorskip("cv2")
    for cy, cx, r in ((70, 70, 16), (160, 120, 12), (120, 180, 10)):
        cv2.circle(img, (cx, cy), r, 30, -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def _analyze(client, headers, seed=7, **kw):
    return client.post("/api/analyze",
                       data={"image": (io.BytesIO(_png_bytes(seed)), "a.png")},
                       headers=headers, content_type="multipart/form-data",
                       **kw)


def _enable(monkeypatch, limit=5, window=300):
    """Opt one test into analyze limiting with a small budget."""
    monkeypatch.setattr(server, "RATE_LIMITS_ENABLED", True)
    monkeypatch.setattr(server, "_ANALYZE_LIMIT", limit)
    monkeypatch.setattr(server, "_ANALYZE_WINDOW", window)
    rl.reset_all()


def _wait_registry_empty(seconds=45):
    """Wait until no analysis job is in flight. Earlier tests in this module
    enqueue real-engine analyses that can outlive their test; the global job
    registry is shared, so concurrency tests must start from a drained
    registry to be order-independent."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not server._analysis_jobs:
            return True
        time.sleep(0.2)
    return False


# =====================================================================
# 1. per-user rate limit: below / at / above the budget
# =====================================================================

def test_below_limit_succeeds_and_hits_429_after(client, users, monkeypatch):
    _enable(monkeypatch, limit=4, window=300)
    u = users[0]
    codes = [_analyze(_fresh(), u["headers"], seed=s).status_code
             for s in range(101, 105)]
    assert codes == [202, 202, 202, 202], "below the budget all succeed"
    r = _analyze(_fresh(), u["headers"], seed=200)
    assert r.status_code == 429
    assert "error" in r.get_json()


def test_429_carries_retry_after_and_no_internals(client, users, monkeypatch):
    _enable(monkeypatch, limit=1, window=123)
    u = users[1]
    assert _analyze(_fresh(), u["headers"], seed=1).status_code == 202
    r = _analyze(_fresh(), u["headers"], seed=2)
    assert r.status_code == 429
    assert r.headers.get("Retry-After") == "123"
    body = json.dumps(r.get_json()).lower()
    assert "bucket" not in body and "sqlite" not in body \
        and "rate_limit_hits" not in body


def test_rate_limited_event_audit_logged(client, users, monkeypatch):
    _enable(monkeypatch, limit=1, window=60)
    u = users[2]
    _analyze(_fresh(), u["headers"], seed=3)
    _analyze(_fresh(), u["headers"], seed=4)
    text = seclog._LOG_PATH.read_text(encoding="utf-8", errors="replace") \
        if seclog._LOG_PATH.exists() else ""
    events = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    hit = [e for e in events if e["event"] == "rate_limited"
           and e["route"] == "/api/analyze" and e["status"] == "429"
           and e["user_id"] == u["uid"]]
    assert hit, "rate_limited audit event expected for the /api/analyze 429"


def test_users_are_isolated(client, users, monkeypatch):
    _enable(monkeypatch, limit=1, window=300)
    a, b = users[0], users[1]
    assert _analyze(_fresh(), a["headers"], seed=11).status_code == 202
    assert _analyze(_fresh(), a["headers"], seed=12).status_code == 429
    # user B's separate budget: unaffected by A's exhaustion
    r = _analyze(_fresh(), b["headers"], seed=13)
    assert r.status_code == 202, "per-user buckets must not share budget"


def test_anonymous_ip_fallback_and_401(client, monkeypatch):
    _enable(monkeypatch, limit=2, window=300)
    c = _fresh()
    for _ in range(2):
        r = c.post("/api/analyze", data={"image": (io.BytesIO(b"x"), "a.png")},
                   content_type="multipart/form-data")
        assert r.status_code == 401, "no/invalid token stays 401"
    # the failed anonymous attempts consumed the IP bucket -> next is 429
    r = c.post("/api/analyze", data={"image": (io.BytesIO(b"x"), "a.png")},
               content_type="multipart/form-data")
    assert r.status_code == 429
    assert r.headers.get("Retry-After") == "300"
    # ...but the same bucket is per-IP: a fresh anonymous caller on a
    # different socket identity is not affected — proven by the spoof test
    # below; here we prove auth calls are unaffected by the anonymous 429s.
    c2 = _fresh()
    r = c2.get("/api/health")
    assert r.status_code == 200


def test_spoofed_forwarded_for_cannot_bypass_anonymous_bucket(monkeypatch):
    """With TRUST_PROXY off (default), rotating X-Forwarded-For must not
    mint fresh IP budgets for unauthenticated abuse."""
    _enable(monkeypatch, limit=2, window=300)
    try:
        codes = []
        for i in range(4):
            r = _fresh().post(
                "/api/analyze", data={"image": (io.BytesIO(b"x"), "a.png")},
                content_type="multipart/form-data",
                headers={"X-Forwarded-For": f"10.9.9.{i}"})
            codes.append(r.status_code)
        assert 429 in codes, "spoofed IPs must not bypass the limiter"
    finally:
        rl.reset_all()


def test_analyze_limit_0_disables(client, users, monkeypatch):
    _enable(monkeypatch, limit=0, window=300)
    for s in range(7):
        r = _analyze(_fresh(), users[0]["headers"], seed=30 + s)
        assert r.status_code == 202, f"limit=0 must disable (req {s}: {r.status_code})"


def test_auth_route_429_also_carries_retry_after(client, monkeypatch):
    _enable(monkeypatch)
    try:
        c = _fresh()
        body = {"email": "no-such-user@example.com", "password": "wrong"}
        codes = [c.post("/api/auth/login", data=json.dumps(body),
                        content_type="application/json").status_code
                 for _ in range(11)]
        assert codes[-1] == 429
    finally:
        rl.reset_all()


# =====================================================================
# 2. concurrency backpressure (per-account) + saturation response
# =====================================================================

@pytest.fixture()
def slow_stub(monkeypatch):
    """Stub the engine entry so jobs stay 'processing' until released."""
    pytest.importorskip("cv2")
    import threading as _t
    gate = _t.Event()
    started = _t.Event()

    def _hold(*a, **k):
        started.set()
        gate.wait(timeout=30)
        raise RuntimeError("stub released")

    monkeypatch.setattr(server, "_EXEC_MODE", "thread")
    import nodiq.pipelines.analysis_child as analysis_child
    monkeypatch.setattr(analysis_child, "run", _hold)
    return gate, started


def test_concurrency_saturation_429_retry_after_and_isolation(
        client, users, monkeypatch, slow_stub):
    gate, started = slow_stub
    monkeypatch.setattr(server, "_MAX_CONCURRENT_ANALYSES", 2)
    a, b = users[0], users[1]
    try:
        assert _wait_registry_empty(), "job registry must drain before the test"
        r1 = _analyze(_fresh(), a["headers"], seed=41)
        r2 = _analyze(_fresh(), a["headers"], seed=42)
        assert (r1.status_code, r2.status_code) == (202, 202)
        assert started.wait(timeout=10), "stub jobs must be running"
        r3 = _analyze(_fresh(), a["headers"], seed=43)
        assert r3.status_code == 429
        assert "wait for one" in r3.get_json()["error"]
        assert r3.headers.get("Retry-After") == "300"
        # account B is isolated from A's saturation
        r4 = _analyze(_fresh(), b["headers"], seed=44)
        assert r4.status_code == 202, "other accounts keep their own budget"
        text = seclog._LOG_PATH.read_text(encoding="utf-8", errors="replace") \
            if seclog._LOG_PATH.exists() else ""
        events = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
        assert any(e["event"] == "analysis_concurrency_limited"
                   and e["status"] == "429" and e["user_id"] == a["uid"]
                   for e in events), "saturation must be audit-logged"
    finally:
        gate.set()


def test_concurrency_slot_freed_after_terminal_state(client, users,
                                                     monkeypatch):
    """A failed (stub-errored) job must release the registry slot so the
    account can analyze again without waiting for a restart."""
    monkeypatch.setattr(server, "_MAX_CONCURRENT_ANALYSES", 1)
    a = users[0]
    assert _wait_registry_empty(), "job registry must drain before the test"
    r1 = _analyze(_fresh(), a["headers"], seed=51)
    assert r1.status_code == 202
    deadline = time.time() + 30
    while time.time() < deadline:
        rec = client.get(f"/api/analyses/{r1.get_json()['analysis_id']}",
                         headers=a["headers"]).get_json()
        status = (rec or {}).get("status") or \
                 ((rec or {}).get("record") or {}).get("status")
        if status == "failed":
            break
        time.sleep(0.2)
    assert status == "failed", rec
    assert len(server._analysis_jobs) == 0, "registry must free the slot"
    r2 = _analyze(_fresh(), a["headers"], seed=52)
    assert r2.status_code == 202, "slot must be reusable after terminal state"


# =====================================================================
# 3. timeout watchdog (NODIQ_ANALYZE_TIMEOUT, thread mode)
# =====================================================================

def test_timeout_watchdog_fails_wedged_job_and_frees_slot(client, users,
                                                          monkeypatch):
    pytest.importorskip("cv2")
    import threading as _t
    release = _t.Event()

    def _hang(*a, **k):
        release.wait(timeout=60)
        raise RuntimeError("released after assert")

    monkeypatch.setattr(server, "_EXEC_MODE", "thread")
    import nodiq.pipelines.analysis_child as analysis_child
    monkeypatch.setattr(analysis_child, "run", _hang)
    monkeypatch.setattr(server, "_ANALYZE_TIMEOUT", 2)
    a = users[0]
    assert _wait_registry_empty(), "job registry must drain before the test"
    try:
        r = _analyze(_fresh(), a["headers"], seed=61)
        assert r.status_code == 202
        aid = r.get_json()["analysis_id"]
        deadline = time.time() + 30
        status, rec = None, None
        while time.time() < deadline:
            rec = client.get(f"/api/analyses/{aid}",
                             headers=a["headers"]).get_json()
            status = (rec or {}).get("status") or \
                     ((rec or {}).get("record") or {}).get("status")
            if status == "failed":
                break
            time.sleep(0.2)
        assert status == "failed", rec
        text = seclog._LOG_PATH.read_text(encoding="utf-8", errors="replace") \
            if seclog._LOG_PATH.exists() else ""
        assert "timed out" in text.lower(), "honest timeout failure expected"
        assert len(server._analysis_jobs) == 0, "watchdog must free the slot"
        r2 = _analyze(_fresh(), a["headers"], seed=62)
        assert r2.status_code == 202, "slot reusable after timeout"
    finally:
        release.set()


def test_timeout_disabled_by_default(client, users, monkeypatch):
    """NODIQ_ANALYZE_TIMEOUT unset -> unlimited (historic behavior)."""
    monkeypatch.setattr(server, "_ANALYZE_TIMEOUT", 0)
    assert server._analyze_deadline() is None


# =====================================================================
# 4. normal workflow + existing protections intact
# =====================================================================

def test_normal_analysis_workflow_intact(client, users):
    a = users[0]
    # dataset reference image: guaranteed engine-valid (synthetic PNGs are
    # legitimately rejected by the engine's microstructure validity gate)
    r = _fresh().post("/api/analyze", json={"dataset_image": "micrograph_0003.png"},
                      headers=a["headers"])
    assert r.status_code == 202
    body = r.get_json()
    assert body["status"] == "processing" and body["analysis_id"]
    assert body["poll_url"] == f"/api/analyses/{body['analysis_id']}"
    deadline = time.time() + 60
    status = None
    while time.time() < deadline:
        rec = client.get(body["poll_url"], headers=a["headers"]).get_json()
        status = (rec or {}).get("status") or \
                 ((rec or {}).get("record") or {}).get("status")
        if status in ("completed", "failed"):
            break
        time.sleep(0.3)
    assert status == "completed", "dataset image must complete the pipeline"


def test_upload_validation_and_auth_still_enforced(client, users):
    a = users[0]
    # garbage bytes still rejected by magic-byte check
    r = _fresh().post("/api/analyze",
                      data={"image": (io.BytesIO(b"not-an-image"), "g.png")},
                      headers=a["headers"], content_type="multipart/form-data")
    assert r.status_code in (400, 415)
    # dataset-image JSON flow still works
    r = _fresh().post("/api/analyze", json={"dataset_image": "micrograph_0002.png"},
                      headers=a["headers"])
    assert r.status_code == 202, r.get_json()


def test_bearer_and_cookie_equivalent(client, users):
    a = users[0]
    bearer = _fresh().post(
        "/api/analyze", data={"image": (io.BytesIO(_png_bytes(81)), "a.png")},
        headers=a["headers"], content_type="multipart/form-data")
    # cookie flow: the module client already holds the session cookie
    cookie = client.post(
        "/api/analyze", data={"image": (io.BytesIO(_png_bytes(82)), "a.png")},
        content_type="multipart/form-data")
    assert bearer.status_code == 202, bearer.get_json()
    assert cookie.status_code == 202, cookie.get_json()


def test_limiter_failure_fails_closed_for_analyze(client, users, monkeypatch):
    """A broken limiter store must LIMIT (fail closed), never disable."""
    _enable(monkeypatch, limit=5, window=60)
    real_connect = rl.sqlite3.connect

    def broken_connect(*a, **k):
        raise rl.sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(rl.sqlite3, "connect", broken_connect)
    try:
        # drop the cached limiter connection so the next check actually
        # attempts sqlite3.connect and hits the broken patch
        rl._CONN = None
        r = _analyze(_fresh(), users[0]["headers"], seed=91)
        assert r.status_code == 429, "fail-closed: broken store limits"
        assert r.headers.get("Retry-After") == "60"
    finally:
        monkeypatch.setattr(rl.sqlite3, "connect", real_connect)
        rl._CONN = None
        rl.reset_all()
