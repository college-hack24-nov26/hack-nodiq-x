#!/usr/bin/env python3
"""
tests/test_sessions.py — login-scoped work sessions.

Covers: session creation per login, token sid binding, analysis tagging,
session isolation between users, listing with aggregates, end-on-logout,
and delete (analyses survive, untagged).
"""
import json
import time

import pytest

import nodiq.services.auth as auth_svc
import nodiq.services.db as store


@pytest.fixture()
def two_users(tmp_path, monkeypatch):
    """Two isolated accounts in a throwaway database."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(store, "_CONN", None)
    def _stub_conn():
        store.init_db()
        store._CONN.executescript(auth_svc._USERS_SCHEMA)
        store._CONN.commit()
        return store._CONN

    monkeypatch.setattr(auth_svc, "_user_conn", _stub_conn)
    u1 = auth_svc.create_user("s1@test.local", "password1", "User One")
    u2 = auth_svc.create_user("s2@test.local", "password2", "User Two")
    return u1, u2


def test_login_creates_new_session_each_time(two_users):
    u1, _ = two_users
    user, tok1 = auth_svc.authenticate("s1@test.local", "password1")
    assert user["session"]["id"].startswith("SES-")
    _, tok2 = auth_svc.authenticate("s1@test.local", "password1")
    # every login starts a NEW session
    assert auth_svc.token_session_id(tok1) != auth_svc.token_session_id(tok2)


def test_analyses_are_tagged_with_session(two_users):
    u1, _ = two_users
    _, token = auth_svc.authenticate("s1@test.local", "password1")
    sid = auth_svc.token_session_id(token)

    rec = {"id": "ANL-SESS1", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "iso_nodularity_pct": 91.0, "session_id": sid}
    store.insert_analysis(rec, u1["id"])

    in_session = store.session_analyses(sid, u1["id"])
    assert [a["id"] for a in in_session] == ["ANL-SESS1"]

    listing = store.list_sessions(u1["id"])
    assert len(listing) == 1
    assert listing[0]["analysis_count"] == 1
    assert listing[0]["avg_iso_pct"] == 91.0


def test_sessions_are_isolated_per_user(two_users):
    u1, u2 = two_users
    _, tok1 = auth_svc.authenticate("s1@test.local", "password1")
    _, tok2 = auth_svc.authenticate("s2@test.local", "password2")
    sid1, sid2 = (auth_svc.token_session_id(t) for t in (tok1, tok2))
    assert sid1 != sid2

    store.insert_analysis({"id": "ANL-U1", "created_at": "t",
                           "iso_nodularity_pct": 80, "session_id": sid1},
                          u1["id"])
    # u1's session: visible to u1 only
    assert store.session_analyses(sid1, u1["id"])
    assert store.session_analyses(sid1, u2["id"]) == []
    # u2 cannot fetch u1's session
    assert store.get_session(sid1, u2["id"]) is None
    assert store.get_session(sid1, u1["id"])["id"] == sid1


def test_logout_ends_session(two_users):
    u1, _ = two_users
    _, token = auth_svc.authenticate("s1@test.local", "password1")
    sid = auth_svc.token_session_id(token)
    assert store.get_session(sid, u1["id"])["ended_at"] is None
    assert store.end_session(sid, u1["id"]) is True
    assert store.get_session(sid, u1["id"])["ended_at"] is not None
    # second logout is a no-op
    assert store.end_session(sid, u1["id"]) is False


def test_manual_session_with_label_and_custom_token(two_users):
    u1, _ = two_users
    s = store.create_session(u1["id"], label="Heat-105 QC run")
    assert s["label"] == "Heat-105 QC run"
    tok = auth_svc.issue_token(u1["id"], session_id=s["id"])
    assert auth_svc.token_session_id(tok) == s["id"]


def test_delete_session_keeps_analyses(two_users):
    u1, _ = two_users
    s = store.create_session(u1["id"])
    store.insert_analysis({"id": "ANL-KEEP", "created_at": "t",
                           "session_id": s["id"]}, u1["id"])
    assert store.delete_session(s["id"], u1["id"]) is True
    assert store.get_session(s["id"], u1["id"]) is None
    # analysis survives, untagged
    got = store.get_analysis_record("ANL-KEEP", u1["id"])
    assert got["id"] == "ANL-KEEP" and got.get("session_id") is None


def test_legacy_analyses_untagged_still_listed(two_users):
    u1, _ = two_users
    store.insert_analysis({"id": "ANL-OLD", "created_at": "t"}, u1["id"])
    assert store.list_analyses(u1["id"])[0]["id"] == "ANL-OLD"
    # and they don't appear in any session bucket
    _, token = auth_svc.authenticate("s1@test.local", "password1")
    sid = auth_svc.token_session_id(token)
    assert store.session_analyses(sid, u1["id"]) == []
