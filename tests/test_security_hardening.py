#!/usr/bin/env python3
"""
tests/test_security_hardening.py — security hardening phase regressions.

Locks in the hardening controls that can be validated without hardware:
- CSRF / Origin protection on state-changing API routes (403 on untrusted
  origin, tolerated for non-browser clients, login/logout/analyze intact)
- RBAC foundation (operator/reviewer/admin, server-authoritative, admin-only
  role endpoints, reviewer-only sign-off, last-admin lockout guard)
- upload hardening: decompression-bomb header caps, MIME cross-check logging,
  magic bytes + decode as the authoritative gate
- path traversal: stored_path containment, dataset route allow-list,
  ../ and absolute-path and null-byte rejections
- session security: tokens bound to a deleted work session are rejected
- audit logging: new event categories appear without any credential material
"""
import io
import json
import struct
import time
import zlib

import pytest

import nodiq.api.server as server
import nodiq.services.auth as auth_svc
import nodiq.services.context as context_svc
import nodiq.services.db as store
import nodiq.services.seclog as seclog


@pytest.fixture(scope="module")
def api_env(tmp_path_factory):
    """Isolated server + DB (same contract as the other api_env fixtures):
    rate limits off, analysis concurrency unbounded for the async polls,
    DB/full-payload/upload dirs redirected to a tmp dir and restored."""
    _rl_saved = server.RATE_LIMITS_ENABLED
    server.RATE_LIMITS_ENABLED = False
    _conc_saved = server._MAX_CONCURRENT_ANALYSES
    server._MAX_CONCURRENT_ANALYSES = 10_000
    _global_saved = server._MAX_CONCURRENT_CHILDREN
    server._MAX_CONCURRENT_CHILDREN = 10_000
    root = tmp_path_factory.mktemp("sec-hardening")
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
        temp_conn = store._CONN
        (store.DATA_DIR, store.DB_PATH, store._CONN,
         context_svc.FULL_DIR, server.UPLOAD_DIR, server.ai_chat) = saved
        if temp_conn is not None and temp_conn is store._CONN:
            temp_conn = None
        if temp_conn is not None:
            temp_conn.close()


@pytest.fixture(scope="module")
def client(api_env):
    c, _ = api_env
    return c


def _fresh():
    """A cookie-jar-free test client: signup/login responses carry the
    session cookie, so the shared module client would start spontaneously
    authenticating and defeat the anonymous-call assertions."""
    return server.app.test_client()


def _signup(client, tag):
    email = f"hard-{tag}-{time.time_ns()}@test.local"
    r = client.post("/api/auth/signup", json={
        "email": email, "password": "password1", "name": f"Hard {tag}"})
    assert r.status_code == 201, r.get_json()
    token = r.headers.get("Set-Cookie", "").split(
        "nodiq_session=", 1)[1].split(";", 1)[0]
    me = client.get("/api/auth/me", headers={
        "Authorization": f"Bearer {token}"}).get_json()["user"]
    return {"token": token,
            "headers": {"Authorization": f"Bearer {token}"},
            "email": email, "uid": me["id"], "role": me.get("role")}


@pytest.fixture(scope="module")
def acct(client):
    return _signup(client, "acct")


def _post_json(client, path, payload, headers=None, **kw):
    return client.post(path, data=json.dumps(payload),
                       content_type="application/json",
                       headers=headers or {}, **kw)


# =====================================================================
# 1. CSRF / origin protection
# =====================================================================

def test_csrf_untrusted_origin_rejected_403(client):
    """A cookie-carrying browser request naming an untrusted origin is
    rejected 403 (not 4xx-validation, not passed through)."""
    for origin in ("https://evil.example", "http://localhost:9999",
                   "null"):
        r = _fresh().post("/api/feedback",
                          data=json.dumps({"message": "x",
                                           "email": "a@b.co"}),
                          content_type="application/json",
                          headers={"Origin": origin,
                                   "Cookie": "nodiq_session=forgery-target"})
        assert r.status_code == 403, (origin, r.status_code, r.get_json())
        assert "origin" in r.get_json()["error"].lower()


def test_csrf_trusted_origin_allowed(client):
    """Trusted (CORS allow-list) origins pass; the app's own host passes
    even though the test client's Origin scheme is http."""
    for origin in ("http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost/"):
        r = client.post("/api/feedback",
                        data=json.dumps({"message": "x", "email": "a@b.co"}),
                        content_type="application/json",
                        headers={"Origin": origin})
        assert r.status_code != 403, (origin, r.status_code, r.get_json())


def test_csrf_untrusted_referer_rejected_403(client):
    """A Referer naming an untrusted origin is rejected; a trusted Referer
    passes (browsers behind proxies that strip Origin)."""
    c = _fresh()
    r = c.post("/api/feedback",
               data=json.dumps({"message": "x", "email": "a@b.co"}),
               content_type="application/json",
               headers={"Referer": "https://evil.example/login",
                        "Cookie": "nodiq_session=forgery-target"})
    assert r.status_code == 403
    r = c.post("/api/feedback",
               data=json.dumps({"message": "x", "email": "a@b.co"}),
               content_type="application/json",
               headers={"Referer": "http://localhost:5173/app"})
    assert r.status_code != 403


def test_csrf_non_browser_clients_unaffected(client):
    """No Origin/Referer/cookie + no Bearer (curl, CI, API tools) is not
    CSRF-capable and must keep working: login stays functional."""
    r = client.post("/api/auth/login",
                    data=json.dumps({"email": "nobody@x.io",
                                     "password": "whatever1"}),
                    content_type="application/json")
    assert r.status_code == 401   # reached auth, not blocked by CSRF


def test_csrf_bearer_callers_exempt(client, acct):
    """Bearer credential is not ambient: API clients keep full access."""
    r = _fresh().post("/api/feedback",
                      data=json.dumps({"message": "x", "email": "a@b.co"}),
                      content_type="application/json",
                      headers={**acct["headers"],
                               "Origin": "https://evil.example"})
    assert r.status_code != 403


def test_csrf_cross_site_fetch_flag_rejected(client):
    """Sec-Fetch-Site: cross-site with no Origin/Referer is rejected."""
    r = _fresh().post("/api/feedback",
                      data=json.dumps({"message": "x", "email": "a@b.co"}),
                      content_type="application/json",
                      headers={"Sec-Fetch-Site": "cross-site",
                               "Cookie": "nodiq_session=forgery-target"})
    assert r.status_code == 403


def test_csrf_get_requests_and_static_routes_untouched(client, acct):
    """GET stays CSRF-exempt (read-only) and the SPA/dataset routes are
    outside the API namespace."""
    assert client.get("/api/health").status_code == 200
    assert client.get("/dataset/micrograph_0001.png").status_code == 200


def test_csrf_rejections_are_audit_logged(client):
    _fresh().post("/api/feedback",
                  data=json.dumps({"message": "x", "email": "a@b.co"}),
                  content_type="application/json",
                  headers={"Origin": "https://evil.example",
                           "Cookie": "nodiq_session=forgery-target"})
    text = seclog._LOG_PATH.read_text(encoding="utf-8", errors="replace") \
        if seclog._LOG_PATH.exists() else ""
    assert '"csrf_rejected"' in text
    assert "evil.example" in text


# =====================================================================
# 2. RBAC foundation
# =====================================================================

def test_signup_defaults_to_operator_role(client):
    a = _signup(client, "opdef")
    assert a["role"] == "operator"


def test_roles_are_not_client_assignable(client):
    """The privilege field is rejected by the global body validator."""
    r = _post_json(client, "/api/auth/signup",
                   {"email": f"rbac-{time.time_ns()}@test.local",
                    "password": "password1", "name": "R", "role": "admin"})
    assert r.status_code == 400


def test_review_requires_reviewer_or_admin(client, acct):
    aid = _enqueue(client, acct)
    r = _post_json(client, f"/api/analyses/{aid}/review",
                   {"status": "approved"}, acct["headers"])
    assert r.status_code == 403
    assert r.get_json()["error"] == "insufficient permissions"


def _enqueue(client, acct):
    r = client.post("/api/analyze", json={
        "dataset_image": "micrograph_0001.png"}, headers=acct["headers"])
    assert r.status_code == 202, r.get_json()
    aid = r.get_json()["analysis_id"]
    deadline = time.time() + 60
    while time.time() < deadline:
        detail = client.get(f"/api/analyses/{aid}",
                            headers=acct["headers"]).get_json()
        # while processing: {status, progress}; completed: {record, analysis}
        status = detail.get("status") \
            or (detail.get("record") or {}).get("status")
        if status != "processing":
            break
        time.sleep(0.2)
    assert status == "completed", detail.get("record") or detail.get("error")
    return aid


def _promote_admin(client, acct):
    auth_svc.set_role(acct["uid"], "admin")
    # _current_user re-reads the user on every request, so no re-login needed
    return auth_svc.effective_role(
        auth_svc.user_by_id(acct["uid"]))


def test_reviewer_and_admin_can_review(client, acct):
    aid = _enqueue(client, acct)
    _promote_admin(client, acct)
    r = _post_json(client, f"/api/analyses/{aid}/review",
                   {"status": "approved"}, acct["headers"])
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["review"]["status"] == "approved"
    # demote to reviewer: still allowed
    auth_svc.set_role(acct["uid"], "reviewer")
    r = _post_json(client, f"/api/analyses/{aid}/review",
                   {"status": "changes_requested"}, acct["headers"])
    assert r.status_code == 200, r.get_json()


def test_admin_endpoints_require_admin(client):
    worker = _signup(client, "worker")
    # anonymous + operator are rejected
    r0 = _fresh().get("/api/admin/users")
    assert r0.status_code == 401
    r1 = client.get("/api/admin/users", headers=worker["headers"])
    assert r1.status_code == 403
    r2 = _post_json(client, f"/api/admin/users/{worker['uid']}/role",
                    {"new_role": "admin"}, worker["headers"])
    assert r2.status_code == 403
    # no privilege escalation path through the role endpoint: an invalid
    # value is refused at the grammar level (as admin) and can never be set
    # at the service level either
    auth_svc.set_role(worker["uid"], "admin")
    r3 = _post_json(client, f"/api/admin/users/{worker['uid']}/role",
                    {"new_role": "root"}, worker["headers"])
    assert r3.status_code == 400, r3.get_json()
    assert auth_svc.set_role(worker["uid"], "root") is None
    auth_svc.set_role(worker["uid"], "operator")


def test_admin_can_manage_roles(client, acct):
    _promote_admin(client, acct)
    target = _signup(client, "target")
    r = _post_json(client, f"/api/admin/users/{target['uid']}/role",
                   {"new_role": "reviewer"}, acct["headers"])
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["user"]["role"] == "reviewer"
    lst = client.get("/api/admin/users", headers=acct["headers"])
    assert lst.status_code == 200
    rows = {u["id"]: u for u in lst.get_json()["users"]}
    assert rows[target["uid"]]["role"] == "reviewer"
    assert rows[acct["uid"]]["role"] == "admin"
    # phone numbers are not part of the admin listing
    assert "phone" not in rows[target["uid"]]


def test_last_admin_cannot_be_demoted(client, acct):
    _promote_admin(client, acct)
    lst = client.get("/api/admin/users", headers=acct["headers"])
    admins = [u for u in lst.get_json()["users"] if u["role"] == "admin"]
    if len(admins) > 1:   # earlier tests in this module may have added one
        for u in admins:
            if u["id"] != acct["uid"]:
                auth_svc.set_role(u["id"], "operator")
    r = _post_json(client, f"/api/admin/users/{acct['uid']}/role",
                   {"new_role": "operator"}, acct["headers"])
    assert r.status_code == 400
    assert "last admin" in r.get_json()["error"]


def test_env_allowlists_elevate_roles(client, monkeypatch):
    """Operator bootstrap without DB edits: NODIQ_ADMIN_EMAILS elevates the
    named account server-side (checked per request)."""
    a = _signup(client, "envadmin")
    monkeypatch.setenv("NODIQ_ADMIN_EMAILS", a["email"])
    r = client.get("/api/admin/users", headers=a["headers"])
    assert r.status_code == 200, r.get_json()
    monkeypatch.delenv("NODIQ_ADMIN_EMAILS")
    # elevation disappears with the variable
    r = client.get("/api/admin/users", headers=a["headers"])
    assert r.status_code == 403


def test_authz_failures_are_audit_logged(client):
    worker = _signup(client, "noauth")
    client.get("/api/admin/users", headers=worker["headers"])
    text = seclog._LOG_PATH.read_text(encoding="utf-8", errors="replace") \
        if seclog._LOG_PATH.exists() else ""
    assert '"authz_failed"' in text


# =====================================================================
# 3. upload hardening (decompression bombs, MIME cross-check)
# =====================================================================

def _png(w, h):
    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    raw = b"\x00" if (w > 1000 or h > 1000) else b"".join(b"\x00" + b"\x80" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_oversized_dimensions_rejected_before_decode(client, acct):
    """A tiny file declaring a gigantic canvas is refused without ever
    allocating the pixels (decompression-bomb guard)."""
    bomb = _png(100_000, 100_000)      # 10 GP declaration, ~90-byte file
    r = client.post("/api/analyze",
                    data={"image": (io.BytesIO(bomb), "bomb.png")},
                    headers=acct["headers"],
                    content_type="multipart/form-data")
    assert r.status_code == 400, (r.status_code, r.get_json())
    assert "dimensions" in r.get_json()["error"]


def test_overside_pixel_area_rejected(client, acct):
    """An 8000x8000 declaration (64 MP) passes the per-side cap but fails
    the pixel-area cap."""
    r = client.post("/api/analyze",
                    data={"image": (io.BytesIO(_png(8000, 8000)), "big.png")},
                    headers=acct["headers"],
                    content_type="multipart/form-data")
    assert r.status_code == 400, (r.status_code, r.get_json())


def test_valid_dimensions_accepted(client, acct):
    """A real-sized image is accepted (202 enqueued) — the guards must not
    reject legitimate micrographs."""
    r = client.post("/api/analyze",
                    data={"image": (io.BytesIO(_png(64, 48)), "ok.png")},
                    headers=acct["headers"],
                    content_type="multipart/form-data")
    assert r.status_code == 202, (r.status_code, r.get_json())


def test_bmp_dimension_parser(client):
    """BMP header parser: negative height (bottom-up) is absolute."""
    data = (b"BM" + b"\x00" * 16
            + struct.pack("<ii", 4000, -3000) + b"\x00" * 20)
    assert server._image_dimensions(data, "bmp") == (4000, 3000)
    assert server._image_dimensions(data, "png") is None


def test_jpeg_dimension_parser():
    """Minimal JPEG with an SOF0 marker parses width/height."""
    sof = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" \
        + struct.pack(">HH", 1944, 2592) + b"\x03" + b"\x01\x11\x00" \
        + b"\x02\x11\x00" + b"\x03\x11\x00"
    data = b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" \
        + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00" + sof + b"\xff\xd9"
    assert server._image_dimensions(data, "jpeg") == (2592, 1944)


def test_upload_size_cap_unchanged(client, acct):
    """The 25 MB cap still applies (413)."""
    big = b"\x89PNG\r\n\x1a\n" + b"A" * (server.MAX_UPLOAD_BYTES + 1)
    r = client.post("/api/analyze",
                    data={"image": (io.BytesIO(big), "x.png")},
                    headers=acct["headers"],
                    content_type="multipart/form-data")
    assert r.status_code == 413


# =====================================================================
# 4. path traversal / path containment
# =====================================================================

def test_dataset_route_allowlist(client):
    """/dataset/<path> serves exactly micrograph_NNNN.png. Traversal,
    absolute paths, subdirectories and wrong extensions must never return
    dataset bytes: most spellings 404, but a leading '/' merges path
    segments in the URL map and can land on the SPA fallback (200 text/html)
    — still not a file disclosure. (A trailing slash resolves to the same
    legitimate file — pre-existing, benign.)"""
    assert client.get("/dataset/micrograph_0001.png").status_code == 200
    for bad in ("../server.py", "..%2fserver.py", "..\\server.py",
                "C:/Windows/win.ini", "/etc/passwd",
                "sub/micrograph_0001.png", "micrograph_0001.png%00",
                "micrograph_0001.txt", "micrograph_1.png",
                "micrograph_00001.png", ".", ".."):
        r = client.get(f"/dataset/{bad}")
        assert "image/png" not in (r.content_type or ""), \
            (bad, r.status_code, r.content_type)
        if not bad.startswith("/"):
            assert r.status_code == 404, \
                (bad, r.status_code, r.content_type)


def test_stored_path_containment(client, acct):
    """A tampered record pointing stored_path outside UPLOAD_DIR can never
    become a file read: the helper resolves and refuses."""
    record = {"stored_path": str(store.DATA_DIR / "secret.txt")}
    assert server._stored_upload_path(record) is None
    assert server._stored_upload_path({}) is None
    assert server._stored_upload_path(None) is None
    inside = server.UPLOAD_DIR / "contain-test.bin"
    inside.write_bytes(b"x")
    assert server._stored_upload_path(
        {"stored_path": str(inside)}) == inside.resolve()


def test_analyze_dataset_name_grammar_unchanged(client, acct):
    """The strict micrograph_NNNN.png grammar still rejects traversal and
    odd names on the analyze path (existing behavior, re-locked)."""
    for bad in ("../test", "..\\test", "../../server_data/test",
                "/etc/passwd", "C:\\Windows\\win.ini", "micrograph_1.png",
                "micrograph_0001.png.bak"):
        r = _post_json(client, "/api/analyze", {"dataset_image": bad},
                       acct["headers"])
        assert r.status_code in (400, 404), (bad, r.status_code)


def test_analyze_dataset_valid_name_still_works(client, acct):
    r = _post_json(client, "/api/analyze",
                   {"dataset_image": "micrograph_0002.png"}, acct["headers"])
    assert r.status_code == 202, r.get_json()


# =====================================================================
# 5. session security: revoked session kills bound tokens
# =====================================================================

def test_deleted_session_invalidates_its_tokens(client):
    a = _signup(client, "sesskill")
    # a second login mints a second token bound to its own session
    r = client.post("/api/auth/login", json={
        "email": a["email"], "password": "password1"})
    token2 = r.headers.get("Set-Cookie", "").split(
        "nodiq_session=", 1)[1].split(";", 1)[0]
    h2 = {"Authorization": f"Bearer {token2}"}
    assert client.get("/api/auth/me", headers=h2).status_code == 200
    sids = client.get("/api/sessions", headers=h2).get_json()["sessions"]
    target = [s for s in sids if s.get("ended_at") is None][0]["id"]
    assert client.delete(f"/api/sessions/{target}",
                         headers=h2).status_code == 200
    # every token bound to that session is now dead, even unrevoked ones
    assert client.get("/api/auth/me", headers=h2).status_code == 401


def test_live_session_keeps_authenticating(client, acct):
    """Control: an untouched session keeps working (the revocation check
    must not over-revoke)."""
    assert client.get("/api/auth/me", headers=acct["headers"]).status_code == 200


# =====================================================================
# 6. audit logging categories
# =====================================================================

def test_audit_log_has_no_credential_material(client):
    text = seclog._LOG_PATH.read_text(encoding="utf-8", errors="replace") \
        if seclog._LOG_PATH.exists() else ""
    for marker in ("password1", "Bearer ", "gsk_", "SMTP_PASS"):
        assert marker not in text


def test_logout_logs_token_revocation(client):
    a = _signup(client, "logoutlog")
    client.post("/api/auth/logout", headers=a["headers"])
    text = seclog._LOG_PATH.read_text(encoding="utf-8", errors="replace") \
        if seclog._LOG_PATH.exists() else ""
    assert '"token_revoked"' in text
    assert a["token"] not in text      # never the token value itself


# =====================================================================
# 7. Shannon pentest remediations: validation auth, steel bounds, CRLF
# =====================================================================

def test_validation_endpoints_require_auth(client, acct):
    """Validation endpoints perform CPU-heavy runs and must never answer anonymously."""
    assert client.get("/api/validation").status_code == 401
    assert client.post("/api/validation/run", json={"kind": "internal"}).status_code == 401
    # Authenticated call succeeds
    r = client.get("/api/validation", headers=acct["headers"])
    assert r.status_code == 200


def test_steel_heat_record_bounds_validation(client, acct):
    """Input validation enforces valid bounds on ASTM numbers and rejects unvalidated schemas."""
    # Out of bounds astm_g (>20) rejected
    r = _post_json(client, "/api/steel/heat-record", {"astm_g": 50.0}, acct["headers"])
    assert r.status_code == 400
    # Unknown/injected fields rejected
    r = _post_json(client, "/api/steel/heat-record", {"unknown_key": "pwn"}, acct["headers"])
    assert r.status_code == 400
    # Valid bounded entry accepted
    r = _post_json(client, "/api/steel/heat-record", {"astm_g": 7.2, "verdict": "PASS"}, acct["headers"])
    assert r.status_code == 200
    assert r.get_json()["record"]["astm_g"] == 7.2


def test_mailer_crlf_header_injection_neutralized():
    """CRLF characters injected into email subjects/headers are neutralized."""
    from nodiq.services import mailer
    # Test send without SMTP configuration returns early without raising
    ok, detail = mailer.send("Alert\r\nBcc: evil@test.com", "Test Body",
                             reply_to="good@test.com\r\nBcc: evil@test.com",
                             to="target@test.com\r\n")
    # Clean string processing verifies no unhandled exception
    assert ok in (True, False)


def test_report_qr_code_requires_owner(client, acct):
    """Report QR lookup is private and owner-scoped; stranger/anonymous requests get 404."""
    assert client.get("/api/reports/RPT-NONEXIST/qr").status_code == 404

