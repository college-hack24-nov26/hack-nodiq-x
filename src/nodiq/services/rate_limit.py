#!/usr/bin/env python3
"""
services/rate_limit.py — multi-worker-safe sliding-window rate limiter.

Replaces the earlier in-memory counter dict: Gunicorn runs N workers, so a
process-local limiter lets an attacker multiply every limit by the worker
count by simply load-balancing their attempts across workers.

Design
------
- Storage: a `rate_limit_hits` table in the existing server_data/nodiq.db
  (stdlib sqlite3, WAL). No new infrastructure dependency.
- Admission is atomic across processes: one `INSERT ... SELECT ... WHERE
  count < limit` statement executed inside BEGIN IMMEDIATE, so two workers
  can never both admit the (limit+1)-th hit. `cursor.rowcount` reports
  whether the row was inserted (allowed) or not (limited).
- Fail-closed: any storage error returns True (i.e. limited) and logs one
  server-side warning. A broken limiter must never silently disable
  brute-force protection.
- Bounded growth: each call prunes its own bucket's expired hits; a periodic
  global prune removes everything older than 2x the widest window.
- Bucket key format is caller-owned (e.g. f"{route}|{client_ip}"), so this
  module stays reusable for any route family.

Test hook: set the env var RATE_LIMIT_DB (or call set_db_path()) to point
the limiter at a scratch database. Default is the shared application DB so
all Gunicorn workers converge on the same counters.
"""
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

from nodiq.core.config import DATA_DIR as _DATA_DIR
DEFAULT_DB_PATH = _DATA_DIR / "nodiq.db"

_DB_PATH = Path(os.environ.get("RATE_LIMIT_DB", DEFAULT_DB_PATH))
_CONN: sqlite3.Connection | None = None
_LOCK = threading.Lock()

# Widen every window by 2x before a global prune is worth the round trip.
_MAX_WINDOW_S = 3600
_PRUNE_INTERVAL = 500          # global prune every N admission checks
_prune_counter = 0


def set_db_path(path) -> None:
    """Point the limiter at another SQLite file (tests). Closes the current
    connection; the next check reopens lazily."""
    global _DB_PATH, _CONN
    with _LOCK:
        _DB_PATH = Path(path)
        if _CONN is not None:
            try:
                _CONN.close()
            except sqlite3.Error:
                pass
            _CONN = None


def _connect() -> sqlite3.Connection:
    """Open (once) a dedicated connection. check_same_thread=False because
    Flask threaded mode + batch engine share the process; the module lock
    serializes access in-process, WAL + BEGIN IMMEDIATE serialize across
    processes."""
    global _CONN
    if _CONN is None:
        _DB_PATH.parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), timeout=5,
                               check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS rate_limit_hits ("
            " bucket TEXT NOT NULL,"
            " ts     REAL NOT NULL)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rate_limit_hits "
            "ON rate_limit_hits(bucket, ts)")
        conn.commit()
        _CONN = conn
    return _CONN


def is_limited(bucket: str, limit: int, window_s: int) -> bool:
    """True when `bucket` already has `limit` hits inside the sliding window.
    Otherwise records this hit atomically and returns False.

    Storage errors are fail-closed: the caller sees `True` (limited) so a
    broken datastore can never silently disable brute-force protection.
    """
    global _prune_counter
    if limit <= 0 or window_s <= 0:
        return False
    now = time.time()
    with _LOCK:
        try:
            conn = _connect()
            conn.execute("BEGIN IMMEDIATE")
            try:
                # expire this bucket's old hits
                conn.execute(
                    "DELETE FROM rate_limit_hits "
                    "WHERE bucket = ? AND ts <= ?",
                    (bucket, now - window_s))
                # atomic cross-process admission: insert only if the window
                # still has room; rowcount 0 means the limit is reached.
                cur = conn.execute(
                    "INSERT INTO rate_limit_hits (bucket, ts) "
                    "SELECT ?, ? WHERE ("
                    "  SELECT COUNT(*) FROM rate_limit_hits"
                    "  WHERE bucket = ? AND ts > ?) < ?",
                    (bucket, now, bucket, now - window_s, limit))
                conn.commit()
                allowed = cur.rowcount == 1
            except Exception:
                conn.rollback()
                raise
            _prune_counter += 1
            if _prune_counter >= _PRUNE_INTERVAL:
                _prune_counter = 0
                conn.execute("DELETE FROM rate_limit_hits WHERE ts <= ?",
                             (now - 2 * _MAX_WINDOW_S,))
                conn.commit()
            return not allowed
        except sqlite3.Error as exc:
            print(f"[rate-limit] storage unavailable, failing CLOSED "
                  f"({exc.__class__.__name__})", file=sys.stderr)
            return True


def reset_all() -> None:
    """Test helper: drop every recorded hit."""
    with _LOCK:
        try:
            _connect().execute("DELETE FROM rate_limit_hits")
            _CONN.commit()
        except sqlite3.Error:
            pass
