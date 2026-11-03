#!/usr/bin/env python3
"""
tests/test_change_password.py — authenticated password change (Profile →
Account & Security → Change Password).

Covers the service-level contract of services.auth.set_password plus the
HTTP endpoint POST /api/auth/change-password: 401 unauthenticated, wrong
current password rejected, minimum length enforced, new-must-differ,
success re-hash verified by re-login, and token survives the change.
"""
import json

import pytest

import nodiq.services.auth as auth_svc
import nodiq.services.db as store

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

    user = auth_svc.create_user("pw@test.local", "password1", "PW User")
    _, token = auth_svc.authenticate("pw@test.local", "password1")

    client = server.app.test_client()
    return client, token, user


def _change(client, token, current, new):
    return client.post(
        "/api/auth/change-password",
        data=json.dumps({"current_password": current, "new_password": new}),
        content_type="application/json",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_requires_authentication(env):
    client, _, _ = env
    resp = client.post(
        "/api/auth/change-password",
        data=json.dumps({"current_password": "x", "new_password": "yyyyyy"}),
        content_type="application/json",
    )
    assert resp.status_code == 401


def test_wrong_current_password_rejected(env):
    client, token, _ = env
    resp = _change(client, token, "wrongpass", "newpass99")
    assert resp.status_code == 400
    assert "incorrect" in resp.get_json()["error"]


def test_new_password_minimum_length(env):
    client, token, _ = env
    resp = _change(client, token, "password1", "abc")
    assert resp.status_code == 400


def test_new_password_must_differ(env):
    client, token, _ = env
    resp = _change(client, token, "password1", "password1")
    assert resp.status_code == 400


def test_change_succeeds_and_relogin_works(env):
    client, token, user = env
    resp = _change(client, token, "password1", "newpass99")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    # old password no longer authenticates
    ok_old, _ = auth_svc.authenticate("pw@test.local", "password1")
    assert ok_old is None
    # new password does
    ok_new, tok_new = auth_svc.authenticate("pw@test.local", "newpass99")
    assert ok_new["id"] == user["id"]


def test_token_survives_password_change(env):
    """Tokens are uid-bound, not password-bound: an open session stays valid."""
    client, token, _ = env
    assert _change(client, token, "password1", "newpass99").status_code == 200
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
