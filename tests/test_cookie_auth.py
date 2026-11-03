#!/usr/bin/env python3
"""
tests/test_cookie_auth.py — HttpOnly-cookie session + CSRF regressions.

Locks in the cookie-authentication pass:
- login/signup/firebase set the session as an HttpOnly SameSite=Lax cookie;
  the token NEVER appears in a JSON body
- /me authenticates via the cookie; logout revokes server-side AND clears
  the cookie with matching attributes
- stolen cookie value is dead after logout (re-presentation -> 401)
- expired / revoked / forged / reset-family tokens presented as the cookie
  are all rejected (401)
- Secure flag: auto over https, absent over http, forced via COOKIE_SECURE
- CSRF posture: state-changing endpoints require JSON content type
  (cross-site form posts cannot produce it) and no GET mutates state
- the session cookie value never leaks into security-event logs
"""
import json
import time

import pytest

import nodiq.services.auth as auth_svc
import nodiq.services.context as context_svc
import nodiq.services.seclog as seclog
import nodiq.services.db as store
import nodiq.api.server as server


@pytest.fixture(scope="module")
def api_env(tmp_path_factory):
    """Same isolation contract as the other api_env fixtures: rate limits
    disabled for the module, DB/full-payload/upload globals redirected to a
    tmp dir, and every redirected global restored on teardown."""
    _rl_saved = server.RATE_LIMITS_ENABLED
    server.RATE_LIMITS_ENABLED = False
    root = tmp_path_factory.mktemp("cookie-auth")
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
    server.app.config["TESTING"] = True
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
def client(api_env):
    c, _ = api_env
    return c


@pytest.fixture(scope="module")
def acct(client):
    email = f"cookie-{time.time_ns()}@test.local"
    r = client.post("/api/auth/signup", json={
        "email": email, "password": "password1", "name": "Cookie Auth"})
    assert r.status_code == 201, r.get_json()
    return {"email": email, "password": "password1"}


def _cookie_token(resp):
    """Extract the session token from the HttpOnly Set-Cookie header."""
    sc = resp.headers.get("Set-Cookie", "")
    assert "nodiq_session=" in sc, sc
    return sc.split("nodiq_session=", 1)[1].split(";", 1)[0]


# --------------------------------------------------------------- set-cookie --

def test_login_sets_httponly_cookie_and_no_token_in_body(client, acct):
    c = server.app.test_client()
    r = c.post("/api/auth/login", json={
        "email": acct["email"], "password": acct["password"]})
    assert r.status_code == 200
    body = r.get_json()
    assert "token" not in body and body.get("user"), body
    sc = r.headers.get("Set-Cookie", "")
    assert "nodiq_session=" in sc
    assert "HttpOnly" in sc
    assert "SameSite=Lax" in sc
    assert "Path=/" in sc
    assert "Max-Age=604800" in sc          # matches the 7-day token TTL
    # plain http (test client) -> no Secure flag, auto mode
    assert "Secure" not in sc


def test_signup_sets_cookie_and_no_token_in_body(client):
    c = server.app.test_client()
    email = f"cookie-su-{time.time_ns()}@test.local"
    r = c.post("/api/auth/signup", json={
        "email": email, "password": "password1", "name": "SU"})
    assert r.status_code == 201
    assert "token" not in (r.get_json() or {})
    assert "nodiq_session=" in r.headers.get("Set-Cookie", "")


def test_me_authenticates_via_cookie_only(client, acct):
    c = server.app.test_client()
    c.post("/api/auth/login", json={
        "email": acct["email"], "password": acct["password"]})
    r = c.get("/api/auth/me")            # cookie jar carries it automatically
    assert r.status_code == 200
    assert "token" not in (r.get_json() or {})
    # and a cookie-less client is rejected
    r2 = server.app.test_client().get("/api/auth/me")
    assert r2.status_code == 401


# -------------------------------------------------------------------- logout --

def test_logout_clears_cookie_and_revokes_stolen_value(client, acct):
    c = server.app.test_client()
    r = c.post("/api/auth/login", json={
        "email": acct["email"], "password": acct["password"]})
    token = _cookie_token(r)
    assert c.get("/api/auth/me").status_code == 200
    lo = c.post("/api/auth/logout")
    assert lo.status_code == 200
    # cookie cleared with matching attributes (expired)
    sc = lo.headers.get("Set-Cookie", "")
    assert "nodiq_session=" in sc and ("Max-Age=0" in sc or "Expires=Thu" in sc)
    assert c.get("/api/auth/me").status_code == 401
    # the same value re-presented as a stolen cookie is dead server-side
    r2 = server.app.test_client().get(
        "/api/auth/me", headers={"Cookie": f"nodiq_session={token}"})
    assert r2.status_code == 401


# ----------------------------------------------------- negative credentials --

def test_expired_cookie_rejected(client, acct):
    user, _ = auth_svc.authenticate(acct["email"], acct["password"])
    stale = auth_svc.issue_token(user["id"], ttl_s=-10)
    r = server.app.test_client().get(
        "/api/auth/me", headers={"Cookie": f"nodiq_session={stale}"})
    assert r.status_code == 401


def test_forged_cookie_rejected():
    r = server.app.test_client().get(
        "/api/auth/me", headers={"Cookie": "nodiq_session=eyJ1aWQiOiAiVVNSLTEi.X"})
    assert r.status_code == 401
    r2 = server.app.test_client().get(
        "/api/auth/me", headers={"Cookie": "nodiq_session=garbage"})
    assert r2.status_code == 401


def test_reset_token_never_authenticates_as_cookie(client, acct):
    tok = auth_svc.generate_reset_token(acct["email"])
    r = server.app.test_client().get(
        "/api/auth/me", headers={"Cookie": f"nodiq_session={tok}"})
    assert r.status_code == 401


def test_revoked_token_rejected_via_cookie(client, acct):
    c = server.app.test_client()
    c.post("/api/auth/login", json={
        "email": acct["email"], "password": acct["password"]})
    token = _cookie_token(c.get("/api/auth/me")) if False else None
    # login again for a fresh token (logout above may have consumed one)
    r = c.post("/api/auth/login", json={
        "email": acct["email"], "password": acct["password"]})
    token = _cookie_token(r)
    auth_svc.revoke_token(token)
    assert c.get("/api/auth/me").status_code == 401


# ------------------------------------------------------------- Secure flag --

def test_secure_cookie_over_https_and_env_override(client, acct):
    c = server.app.test_client()
    # auto mode + https request -> Secure present
    r = c.post("/api/auth/login", json={
        "email": acct["email"], "password": acct["password"]},
        base_url="https://localhost")
    assert "Secure" in r.headers.get("Set-Cookie", "")
    # explicit override -> Secure even over http
    old = server.os.environ.get("COOKIE_SECURE")
    server.os.environ["COOKIE_SECURE"] = "true"
    try:
        r2 = c.post("/api/auth/login", json={
            "email": acct["email"], "password": acct["password"]})
        assert "Secure" in r2.headers.get("Set-Cookie", "")
    finally:
        if old is None:
            server.os.environ.pop("COOKIE_SECURE", None)
        else:
            server.os.environ["COOKIE_SECURE"] = old


# ------------------------------------------------------------- CSRF posture --

def test_state_changing_endpoints_reject_non_json_bodies(client):
    """Cross-site form posts cannot set application/json, and the JSON-only
    contract rejects urlencoded/text bodies — the server-side half of the
    SameSite=Lax CSRF defense."""
    c = server.app.test_client()
    r1 = c.post("/api/auth/login",
                data="email=a@b.c&password=x",
                content_type="application/x-www-form-urlencoded")
    assert r1.status_code == 400
    r2 = c.post("/api/auth/login",
                data=json.dumps({"email": "a@b.c", "password": "x"}),
                content_type="text/plain")
    assert r2.status_code == 400
    # authenticated state-changing route, form-encoded: must not pass
    r3 = c.post("/api/analyses",
                data="name=x",
                content_type="application/x-www-form-urlencoded")
    assert r3.status_code in (400, 401)


def test_no_get_route_mutates_state():
    """CSRF-audit invariant: every GET handler is read-only. Any store/auth
    mutation inside a GET route is a finding."""
    import inspect
    mutating = ("INSERT INTO", "UPDATE ", "DELETE FROM", "create_",
                "revoke_token", "end_session", "set_password",
                "consume_reset_token")
    for rule in server.app.url_map.iter_rules():
        if "GET" not in rule.methods or rule.endpoint.startswith("static"):
            continue
        fn = server.app.view_functions[rule.endpoint]
        src = inspect.getsource(fn)
        for m in mutating:
            assert m not in src, f"GET route {rule} appears to mutate: {m}"


# ------------------------------------------------ session switch rotates --

def test_session_create_rotates_cookie_not_json_token(client, acct):
    """POST /api/sessions (manual session switch) rotates the credential:
    the new session-bound token goes to the HttpOnly cookie, never the JSON
    body; the rotated cookie authenticates against the new session."""
    c = server.app.test_client()
    c.post("/api/auth/login", json={
        "email": acct["email"], "password": acct["password"]})
    r = c.post("/api/sessions", json={"label": "Heat-105 QC run"})
    assert r.status_code == 200
    body = r.get_json()
    assert "token" not in body and body.get("session"), body
    assert "nodiq_session=" in r.headers.get("Set-Cookie", "")
    # rotated cookie authenticates; new session label is visible
    assert c.get("/api/auth/me").status_code == 200
    lst = c.get("/api/sessions")
    assert any(s.get("label") == "Heat-105 QC run"
               for s in lst.get_json().get("sessions", []))


# ------------------------------------------------------ no leakage in logs --

def test_session_cookie_never_reaches_security_log(client, acct):
    c = server.app.test_client()
    r = c.post("/api/auth/login", json={
        "email": acct["email"], "password": acct["password"]})
    token = _cookie_token(r)
    assert token
    try:
        log_text = seclog._LOG_PATH.read_text(encoding="utf-8")
    except OSError:
        log_text = ""
    assert token not in log_text
    assert "nodiq_session=" not in log_text
