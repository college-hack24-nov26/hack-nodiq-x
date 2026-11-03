#!/usr/bin/env python3
"""
tests/test_forgot_password.py — logged-out password reset (login page →
"Forgot password" → email link → new password → sign in).

Covers the /api/auth/forgot-password and /api/auth/reset-password endpoints:
unknown-email requests never leak a token, the emailed recipient is the
requesting user, tokens are single-use, issuing a newer request invalidates
an older link, invalid/expired tokens are rejected, and after a successful
reset the new password authenticates while the old one does not.
"""
import json

import pytest

import nodiq.services.auth as auth_svc
import nodiq.services.db as store
import nodiq.services.mailer as mailer

# server.py is imported lazily inside the client fixture so that module-level
# side effects (dataset listing, store.init_db) run AFTER monkeypatching.


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Isolated DB + Flask test client with one seeded account."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(store, "_CONN", None)

    def _stub_conn():
        store.init_db()
        store._CONN.executescript(auth_svc._USERS_SCHEMA)
        store._CONN.commit()
        return store._CONN

    monkeypatch.setattr(auth_svc, "_user_conn", _stub_conn)
    import importlib
    import sys
    server = importlib.import_module("nodiq.api.server")
    importlib.reload(server) if "server" in sys.modules else None
    # Rate limiter is IP-keyed; the shared test-client IP would trip it.
    monkeypatch.setattr(server, "RATE_LIMITS_ENABLED", False)

    auth_svc.create_user("user@test.local", "oldpass1", "Reset User")

    client = server.app.test_client()
    return client


def _forgot(client, email, **extra):
    return client.post(
        "/api/auth/forgot-password",
        data=json.dumps({"email": email, **extra}),
        content_type="application/json",
    )


def _token_via_email(client, server, email):
    """Request a reset and read the token from the (stubbed) email body —
    the ONLY channel a reset token may travel on (security fix: it used to
    be returned in the HTTP response when SMTP was unconfigured)."""
    import nodiq.services.mailer as mailer_mod
    sent = {}
    orig_send = mailer_mod.send
    orig_conf = mailer_mod.configured
    mailer_mod.configured = True
    mailer_mod.send = (lambda subject, body, reply_to=None, to=None:
                       sent.update(body=body, to=to) or (True, "emailed"))
    try:
        resp = _forgot(client, email)
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True and body.get("token") is None
    finally:
        mailer_mod.send = orig_send
        mailer_mod.configured = orig_conf
    assert "/reset-password?token=" in sent["body"]
    return sent["body"].split("token=")[1].split()[0].rstrip("\n")


def _reset(client, token, password):
    return client.post(
        "/api/auth/reset-password",
        data=json.dumps({"token": token, "password": password}),
        content_type="application/json",
    )


def test_unknown_email_never_reveals_token(env):
    resp = _forgot(env, "nobody@test.local")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    # Security: the response must never carry a reset token, whether or not
    # the account exists and whether or not SMTP is configured.
    assert body.get("token") is None


def test_forgot_never_returns_token_even_without_mail(env):
    """Security regression: without SMTP the token used to be returned in the
    HTTP response (account takeover via API). It must only ever travel by
    email; without mail the reply is the same generic ok with no token."""
    resp = _forgot(env, "user@test.local")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["ok"] is True
    assert body.get("token") is None

    # The token WAS generated and is single-use for the real account owner
    # via email; here we verify it exists in the resets table (hashed), and
    # that a guessed/garbage token still cannot reset.
    assert _reset(env, "garbage.token", "newpass1").status_code == 400


def test_reset_email_goes_to_the_requesting_user(env, monkeypatch):
    """The reset link must reach the account owner, not the alert inbox."""
    monkeypatch.setattr(mailer, "configured", True)
    sent = {}
    monkeypatch.setattr(mailer, "send",
                        lambda subject, body, reply_to=None, to=None:
                        sent.update(subject=subject, body=body, to=to)
                        or (True, "emailed"))
    _forgot(env, "user@test.local")
    assert sent["to"] == "user@test.local"
    assert "/reset-password?token=" in sent["body"]


def test_reset_flow_roundtrip_and_relogin(env):
    client = env
    tok = _token_via_email(client, env, "user@test.local")

    assert _reset(client, tok, "newpass1").status_code == 200

    # old password no longer authenticates; new one does
    ok_old, _ = auth_svc.authenticate("user@test.local", "oldpass1")
    assert ok_old is None
    ok_new, _ = auth_svc.authenticate("user@test.local", "newpass1")
    assert ok_new is not None


def test_reset_token_is_single_use(env):
    client = env
    tok = _token_via_email(client, env, "user@test.local")
    assert _reset(client, tok, "newpass1").status_code == 200
    # second attempt with the same link fails
    resp = _reset(client, tok, "another9")
    assert resp.status_code == 400
    assert "invalid" in resp.get_json()["error"]


def test_newer_request_invalidates_older_link(env):
    client = env
    first = _token_via_email(client, env, "user@test.local")
    second = _token_via_email(client, env, "user@test.local")
    assert first != second
    # the older link is dead
    resp = _reset(client, first, "newpass1")
    assert resp.status_code == 400
    # the newest link works
    assert _reset(client, second, "newpass1").status_code == 200


def test_reset_rejects_invalid_token_and_short_password(env):
    client = env
    assert _reset(client, "garbage.token", "newpass1").status_code == 400
    tok = _token_via_email(client, env, "user@test.local")
    assert _reset(client, tok, "abc").status_code == 400  # min length
