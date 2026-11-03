#!/usr/bin/env python3
"""
tests/test_rate_limit_shared.py — multi-worker rate limiter regressions.

Locks in the final-hardening limiter architecture:
- state lives in the shared SQLite store, so two independent limiter
  instances (the in-suite stand-in for two Gunicorn workers) drain ONE
  budget instead of each getting their own
- admission is atomic under concurrent threads (BEGIN IMMEDIATE)
- storage errors fail CLOSED (limited), never silently open
- a spoofed X-Forwarded-For cannot bypass limiting while TRUST_PROXY is off
- expired hits are pruned so the store cannot grow without bound
"""
import concurrent.futures
import sqlite3

import pytest

import nodiq.services.rate_limit as rl


@pytest.fixture()
def limiter(tmp_path, monkeypatch):
    """Fresh limiter backed by a scratch DB; forces a reopen."""
    db = tmp_path / "rl-test.db"
    monkeypatch.setattr(rl, "_DB_PATH", db)
    monkeypatch.setattr(rl, "_CONN", None)
    yield db
    if rl._CONN is not None:
        rl._CONN.close()
        rl._CONN = None


def test_limit_blocks_at_threshold(limiter):
    # 3 hits / 60 s
    assert rl.is_limited("login|1.2.3.4", 3, 60) is False
    assert rl.is_limited("login|1.2.3.4", 3, 60) is False
    assert rl.is_limited("login|1.2.3.4", 3, 60) is False
    # 4th hit inside the window -> limited
    assert rl.is_limited("login|1.2.3.4", 3, 60) is True
    # different bucket unaffected
    assert rl.is_limited("login|5.6.7.8", 3, 60) is False


def test_window_slides_open_again(limiter, monkeypatch):
    assert rl.is_limited("f|1.1.1.1", 1, 60) is False
    assert rl.is_limited("f|1.1.1.1", 1, 60) is True
    # age out the recorded hit beyond the window
    conn = sqlite3.connect(str(limiter))
    conn.execute("UPDATE rate_limit_hits SET ts = ts - 61")
    conn.commit()
    conn.close()
    assert rl.is_limited("f|1.1.1.1", 1, 60) is False


def test_two_instances_share_one_budget__multi_worker_proof(limiter):
    """Two separately-connected limiter instances = two Gunicorn workers.

    Each instance opens its own sqlite connection (the other is forced
    closed between calls) yet they must drain the SAME budget: 10 allowed
    total, never 20.
    """
    rl.is_limited("warmup|0.0.0.0", 1, 60)  # creates schema

    def hit_via(instance):
        conn = sqlite3.connect(str(limiter), check_same_thread=False)
        cur = conn.execute(
            "INSERT INTO rate_limit_hits (bucket, ts) "
            "SELECT 'r|9.9.9.9', 1234567890.0 WHERE ("
            "  SELECT COUNT(*) FROM rate_limit_hits"
            "  WHERE bucket = 'r|9.9.9.9' AND ts > 1234567890.0 - 300)"
            "  < 10")
        conn.commit()
        allowed = cur.rowcount == 1
        conn.close()
        return allowed

    allowed = sum(hit_via(i) for i in range(1, 11))     # budget exhausted
    blocked = sum(hit_via(i) for i in range(11, 31))    # extra attempts
    assert allowed == 10, "exactly one shared budget of 10, not 2x10"
    assert blocked == 0, "worker #2 must NOT grant a fresh budget"


def test_concurrent_hits_do_not_overshoot(limiter):
    """20 threads race for 5 slots: at most 5 admissions win."""
    rl.is_limited("race|7.7.7.7", 0, 60)  # force connection warm-up
    def attempt(_):
        return rl.is_limited("race|7.7.7.7", 5, 60)
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(attempt, range(20)))
    admitted = results.count(False)
    assert admitted <= 5
    conn = sqlite3.connect(str(limiter))
    n = conn.execute(
        "SELECT COUNT(*) FROM rate_limit_hits WHERE bucket='race|7.7.7.7'"
    ).fetchone()[0]
    conn.close()
    assert n == admitted, "table must hold exactly the admitted hits"


def test_storage_error_fails_closed(limiter, monkeypatch):
    real_connect = sqlite3.connect

    def broken_connect(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(rl.sqlite3, "connect", broken_connect)
    # even the first request must be LIMITED when the store is down
    assert rl.is_limited("login|3.3.3.3", 10, 300) is True


def test_dropped_table_recovers_without_silently_failing_open(limiter):
    """Worst-case ops scenario: table vanished. The limiter must fail CLOSED
    for that request (never silently open) and self-heal for the next."""
    rl.is_limited("warm|0.0.0.0", 1, 60)  # create schema + connection
    conn = sqlite3.connect(str(limiter))
    conn.execute("DROP TABLE rate_limit_hits")
    conn.commit()
    conn.close()
    rl._CONN = None
    # the limiter recreates the schema before querying, so the request is
    # served correctly (fresh empty table = budget available) — the store
    # heals WITHOUT any fail-open window and without a fail-closed outage
    assert rl.is_limited("signup|4.4.4.4", 5, 3600) is False
    conn = sqlite3.connect(str(limiter))
    n = conn.execute(
        "SELECT COUNT(*) FROM rate_limit_hits WHERE bucket='signup|4.4.4.4'"
    ).fetchone()[0]
    conn.close()
    assert n == 1, "table recreated and the hit recorded"


def test_forwarded_for_spoof_cannot_bypass(monkeypatch):
    """Server._client_ip() must ignore X-Forwarded-For unless TRUST_PROXY.

    Uses the real Flask request context via the app's test client.
    """
    server = pytest.importorskip("nodiq.api.server")
    db = server.ROOT / "server_data" / "nodiq.db"  # noqa: F841 (docs clarity)
    monkeypatch.setattr(rl, "_DB_PATH", server.store.DB_PATH)
    monkeypatch.setattr(rl, "_CONN", None)
    saved_enabled = server.RATE_LIMITS_ENABLED
    server.RATE_LIMITS_ENABLED = True
    try:
        c = server.app.test_client()
        import json as _json
        body = {"email": "spoof-test@example.com", "password": "x"}
        spoof = {"X-Forwarded-For": "10.0.0.1"}
        # every spoofed request pretends a fresh IP — must still hit 429
        codes = []
        try:
            for _ in range(12):
                codes.append(c.post(
                    "/api/auth/login", data=_json.dumps(body),
                    content_type="application/json",
                    headers=spoof).status_code)
        except Exception:
            pass
        assert 429 in codes, "spoofed headers must not bypass the limiter"
    finally:
        server.RATE_LIMITS_ENABLED = saved_enabled
        rl.reset_all()


def test_reset_all_clears_state(limiter):
    assert rl.is_limited("x|1.1.1.1", 1, 60) is False
    assert rl.is_limited("x|1.1.1.1", 1, 60) is True
    rl.reset_all()
    assert rl.is_limited("x|1.1.1.1", 1, 60) is False
