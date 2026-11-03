#!/usr/bin/env python3
"""
services/db.py — SQLite persistence layer (Advancement 2).

Replaces the JSON-file "databases" (analyses.json, reports.json,
feedback.json, calibrations.json) with a single SQLite file at
server_data/nodiq.db. On first import any existing JSON files are imported
once and renamed to *.imported so nothing is lost.

Design notes
------------
- stdlib sqlite3 only: no new dependency, no server process.
- A module-level connection guarded by an RLock (Flask threaded mode + the
  batch engine share the process). WAL mode for better read/write overlap.
- Rows keep a JSON `data` column so payloads evolve without migrations;
  typed columns exist only for what we filter/sort by (user_id, timestamps).
- Every payload row may carry `user_id`: NULL means shared/legacy data, which
  stays visible to everyone exactly like before (back-compat).

Public API (used by server.py)
------------------------------
    init_db()                        -> create schema + migrate JSON
    list_analyses(user_id)           -> newest first
    insert_analysis(record, user_id)
    get_analysis_record(analysis_id, user_id)
    delete_analysis(analysis_id, user_id)
    list_reports(user_id) / insert_report(rec, uid) / get_report(id, uid)
    delete_report(report_id, user_id)
    list_feedback() / insert_feedback(rec)
    save_calibration(key, data) / load_calibration(key)
"""
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

# ------------------------------------------------------------ backend ----
# Persistence backend selection (explicit, never silent):
#   NODIQ_BACKEND=supabase  -> PostgreSQL (DATABASE_URL required, e.g. the
#                              Supabase pooler connection string). Production.
#   NODIQ_BACKEND=sqlite    -> local SQLite file. Development fallback.
# Unset: supabase when DATABASE_URL is present, otherwise sqlite with a
# startup notice — so local dev keeps working while production deployments
# that expect Supabase get it from DATABASE_URL alone.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
BACKEND = os.environ.get("NODIQ_BACKEND", "").strip().lower()
_AUTO_BACKEND = False
if not BACKEND:
    BACKEND = "supabase" if DATABASE_URL else "sqlite"
    _AUTO_BACKEND = True
if BACKEND not in ("supabase", "sqlite"):
    raise RuntimeError(
        f"NODIQ_BACKEND='{BACKEND}' is invalid — use 'supabase' or 'sqlite'")
if BACKEND == "supabase" and not DATABASE_URL:
    raise RuntimeError(
        "NODIQ_BACKEND=supabase requires DATABASE_URL (Supabase Postgres "
        "connection string). Set it in the environment — never in code.")
if _AUTO_BACKEND and BACKEND == "sqlite" and os.environ.get("RENDER"):
    # Production safety: a Render deployment that lost its persistence env
    # vars must never silently come up on the ephemeral dev fallback — every
    # account/analysis would be wiped on the next restart or redeploy with
    # no error anywhere. Refuse the boot so the missing configuration is
    # immediately visible. A DELIBERATE sqlite rollback stays possible via
    # an explicit NODIQ_BACKEND=sqlite (documented in DEPLOY_SUPABASE.md).
    raise RuntimeError(
        "Persistence is not configured on this Render service: "
        "NODIQ_BACKEND/DATABASE_URL are unset, so the ephemeral sqlite "
        "fallback would silently lose all data on restart/redeploy. Set "
        "NODIQ_BACKEND=supabase + DATABASE_URL (Supabase Postgres) and "
        "SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY (Storage) in the Render "
        "environment. (Deliberate sqlite rollback: set NODIQ_BACKEND=sqlite "
        "explicitly.)")
if BACKEND == "supabase" and os.environ.get("RENDER") \
        and not (SUPABASE_URL and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
    # With the supabase database backend, artifacts (original/annotated/mask
    # images) would silently stay ephemeral without Storage: analyses would
    # still "complete" but their images would vanish on the next redeploy.
    # Same policy as above — fail visibly instead of losing user data.
    raise RuntimeError(
        "NODIQ_BACKEND=supabase on Render requires SUPABASE_URL and "
        "SUPABASE_SERVICE_ROLE_KEY (private Storage bucket) so analysis "
        "artifacts persist. Set them in the Render environment.")

from nodiq.core.config import DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
# NODIQ_DB_PATH: full explicit override (analysis_child.py receives it from
# the parent so the isolated child writes to the very same database file,
# including tests that point DB_PATH somewhere custom).
DB_PATH = Path(os.environ.get("NODIQ_DB_PATH") or (DATA_DIR / "nodiq.db"))

# pgcompat is imported ONLY when the supabase backend is selected: its
# psycopg2 import costs several MB of RSS which the sqlite dev/child path
# must not pay (512MB free-tier budget — the analysis child inherits this
# module and every MB matters).
if BACKEND == "supabase":
    from nodiq.services import pgcompat  # noqa: E402  (after env validation)
else:
    pgcompat = None

# Under supabase, a non-default DB_PATH selects an isolated PG schema with
# the same name — giving tests the per-fixture "fresh database" semantics of
# the sqlite backend's tmp DB files. Production (default DB_PATH) uses the
# plain public schema.
_PG_POOL = pgcompat.PGPool(DATABASE_URL) if BACKEND == "supabase" else None


def _pg_schema():
    if BACKEND != "supabase" or DB_PATH == (DATA_DIR / "nodiq.db"):
        return None
    # stable per-path hash: every fixture tmp dir gets its OWN schema even
    # when the file name is the ubiquitous "test.db"
    import hashlib
    return "t" + hashlib.sha1(str(DB_PATH).encode()).hexdigest()[:14]

_LOCK = threading.RLock()
_CONN = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id         TEXT PRIMARY KEY,
    user_id    TEXT,
    session_id TEXT,
    created_at TEXT,
    data       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_user ON analyses(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_analyses_session ON analyses(session_id);

CREATE TABLE IF NOT EXISTS reports (
    id         TEXT PRIMARY KEY,
    user_id    TEXT,
    created_at TEXT,
    data       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id, created_at);

CREATE TABLE IF NOT EXISTS feedback (
    id         TEXT PRIMARY KEY,
    created_at TEXT,
    data       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calibrations (
    key  TEXT PRIMARY KEY,
    data TEXT NOT NULL
);

-- Login-scoped work sessions: one session per login, analyses are tagged
-- with their session so users can browse what each login produced.
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    label      TEXT,
    started_at TEXT NOT NULL,
    ended_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, started_at);
"""


def _connect():
    if BACKEND == "supabase":
        return _PG_POOL.get(_pg_schema())
    # timeout: seconds a write waits for a competing lock before raising
    # "database is locked". Multi-worker deployments (gunicorn -w N) share
    # one SQLite file; 30s comfortably covers init + migration bursts.
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    """Create schema (and import any legacy JSON databases on SQLite)."""
    global _CONN
    # Multi-worker boot: every gunicorn worker imports server.py and runs
    # this at the same instant. All steps are idempotent (IF NOT EXISTS /
    # check-then-ALTER), so simply retrying the full init resolves races.
    last_exc = None
    for attempt in range(5):
        try:
            with _LOCK:
                if _CONN is not None:
                    try:
                        _CONN.execute("SELECT 1")
                    except Exception:
                        try:
                            _CONN.close()
                        except Exception:
                            pass
                        _CONN = None
                if _CONN is None:
                    _CONN = _connect()
                if BACKEND == "supabase":
                    _init_pg()
                else:
                    _init_sqlite()
            return
        except Exception as exc:
            retriable = ("locked" in str(exc).lower()
                         or "busy" in str(exc).lower()
                         or (BACKEND == "supabase" and pgcompat is not None and isinstance(
                             exc, pgcompat.psycopg2.OperationalError)))
            if _CONN is not None:
                try:
                    _CONN.rollback()
                except Exception:
                    pass
                try:
                    _CONN.close()
                except Exception:
                    pass
                _CONN = None
            if BACKEND == "supabase" and _PG_POOL is not None:
                _PG_POOL.reset()   # dead sockets: reconnect on next attempt
            if not retriable:
                raise
            last_exc = exc
            time.sleep(0.5 + attempt)   # backoff: 0.5s .. 4.5s
    if last_exc is not None:
        raise last_exc


# PostgreSQL schema mirrors the SQLite one; 'seq' replaces rowid as the
# insertion-order proxy (ORDER BY seq DESC), and full analysis payloads —
# previously JSON files on disk — get a dedicated table so they survive
# redeploys with everything else.
_PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id         TEXT PRIMARY KEY,
    user_id    TEXT,
    session_id TEXT,
    created_at TEXT,
    seq        BIGSERIAL,
    data       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_user ON analyses(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_analyses_session ON analyses(session_id);
CREATE TABLE IF NOT EXISTS reports (
    id         TEXT PRIMARY KEY,
    user_id    TEXT,
    created_at TEXT,
    seq        BIGSERIAL,
    data       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id, created_at);
CREATE TABLE IF NOT EXISTS feedback (
    id         TEXT PRIMARY KEY,
    created_at TEXT,
    seq        BIGSERIAL,
    data       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calibrations (
    key  TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    label      TEXT,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    seq        BIGSERIAL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, started_at);
CREATE TABLE IF NOT EXISTS full_payloads (
    id         TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    stored_at  TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    name          TEXT,
    phone         TEXT,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revoked_tokens (
    token_hash TEXT PRIMARY KEY,
    expires_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS resets (
    token_hash TEXT PRIMARY KEY,
    uid        TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    used       INTEGER DEFAULT 0
);
"""


def _init_pg():
    """PostgreSQL init: schema + ensure columns that SQLite adds lazily."""
    _CONN.executescript(_PG_SCHEMA)
    _CONN.commit()


def _init_sqlite():
    """SQLite init (original path): schema + lazy columns + JSON import."""
    _CONN.executescript(_SCHEMA)
    _ensure_column("analyses", "session_id", "TEXT")
    _CONN.execute(
        "CREATE INDEX IF NOT EXISTS idx_analyses_session "
        "ON analyses(session_id)")
    _CONN.commit()
    _migrate_json("analyses.json", "analyses", _import_analysis_row)
    _migrate_json("reports.json", "reports", _import_report_row)
    _migrate_json("feedback.json", "feedback", _import_simple_row)
    _migrate_json("calibrations.json", "calibrations",
                  _import_calibration_row)


# ----------------------------------------------------------- migration ----
def _ensure_column(table, column, decl):
    """Add a typed column to an existing table if it is missing (older DBs
    were created before the column existed). No-op on fresh databases that
    already include it in their CREATE TABLE."""
    try:
        cols = {r["name"] for r in
                _CONN.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return
    if column not in cols:
        try:
            _CONN.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            _CONN.commit()
            print(f"[db] added column {column} to {table}")
        except sqlite3.OperationalError as exc:
            # Multi-worker boot race: another gunicorn worker added the
            # column between our PRAGMA check and the ALTER. That IS the
            # desired end state — tolerate it, fail on anything else.
            err_msg = str(exc).lower()
            if "duplicate column" not in err_msg and "already exists" not in err_msg:
                try:
                    _CONN.rollback()
                except Exception:
                    pass
                raise
            print(f"[db] column {column} already added by another worker")


def _migrate_json(filename, table, row_fn):
    path = DATA_DIR / filename
    if not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[db] could not parse {filename}: {exc} (left in place)")
        return

    rows = []
    if isinstance(payload, list):
        rows = [row_fn(item) for item in payload]
    elif isinstance(payload, dict):          # calibrations shape
        rows = [row_fn(k, v) for k, v in payload.items()]

    with _LOCK:
        cur = _CONN.cursor()
        imported = 0
        for row in rows:
            if row is None:
                continue
            try:
                if table == "calibrations":
                    cur.execute(
                        "INSERT OR IGNORE INTO calibrations (key, data) VALUES (?, ?)",
                        row)
                elif table == "feedback":
                    cur.execute(
                        "INSERT OR IGNORE INTO feedback (id, created_at, data) VALUES (?, ?, ?)",
                        row)
                else:
                    cur.execute(
                        f"INSERT OR IGNORE INTO {table} (id, user_id, created_at,"
                        " data) VALUES (?, ?, ?, ?)",
                        row)
                imported += 1
            except sqlite3.Error:
                pass
        _CONN.commit()
    path.rename(path.with_suffix(path.suffix + ".imported"))
    print(f"[db] migrated {imported} row(s) from {filename} -> {table}")


def _import_analysis_row(item):
    if not isinstance(item, dict) or not item.get("id"):
        return None
    return (item["id"], item.get("user_id"),
            item.get("created_at"), json.dumps(item))


def _import_report_row(item):
    if not isinstance(item, dict) or not item.get("id"):
        return None
    return (item["id"], item.get("user_id"),
            item.get("created_at"), json.dumps(item))


def _import_simple_row(item):
    if not isinstance(item, dict) or not item.get("id"):
        return None
    return (item["id"], item.get("created_at"), json.dumps(item))


def _import_calibration_row(key, value):
    return (str(key), json.dumps(value))


# ------------------------------------------------------------- helpers ----
def _visible(user_id):
    """WHERE fragment: STRICT per-account isolation — an account sees only
    rows created under its own login. No shared/legacy rows. Anonymous
    callers (no token) match nothing, so public endpoints answer a clean
    404 instead of a binding-count sqlite error."""
    init_db()                                 # lazy: safe for direct test use
    return "user_id = ?" if user_id is not None else "1 = 0"


def _params(user_id):
    return [] if user_id is None else [user_id]


# ------------------------------------------------------------- analyses ----
def list_analyses(user_id=None, session_id=None):
    sql = (f"SELECT data, session_id FROM analyses WHERE {_visible(user_id)} ")
    params = _params(user_id)
    if session_id is not None:
        sql += "AND session_id = ? "
        params = [*params, session_id]
    sql += "ORDER BY created_at DESC, rowid DESC"
    with _LOCK:
        rows = _CONN.execute(sql, params).fetchall()
    # session_id column is authoritative (JSON payload may be stale)
    return [{**json.loads(r["data"]), "session_id": r["session_id"]}
            for r in rows]


def insert_analysis(record, user_id=None):
    init_db()
    with _LOCK:
        _CONN.execute(
            "INSERT OR REPLACE INTO analyses (id, user_id, session_id,"
            " created_at, data) VALUES (?, ?, ?, ?, ?)",
            (record["id"], user_id, record.get("session_id"),
             record.get("created_at"), json.dumps(record)))
        _CONN.commit()


def analysis_owner(analysis_id):
    """Owning user_id of an analysis row, or None when the id is unknown.
    Lets write routes refuse client-supplied ids that already belong to a
    different account (INSERT OR REPLACE would otherwise hijack the row)."""
    init_db()
    with _LOCK:
        row = _CONN.execute(
            "SELECT user_id FROM analyses WHERE id = ?",
            (analysis_id,)).fetchone()
    return row[0] if row else None


def get_analysis_record(analysis_id, user_id=None):
    with _LOCK:
        row = _CONN.execute(
            f"SELECT data, session_id FROM analyses "
            f"WHERE id = ? AND {_visible(user_id)}",
            [analysis_id, *_params(user_id)]).fetchone()
    if not row:
        return None
    # session_id column is authoritative (JSON payload may be stale)
    return {**json.loads(row["data"]), "session_id": row["session_id"]}


def delete_analysis(analysis_id, user_id=None):
    with _LOCK:
        cur = _CONN.execute(
            f"DELETE FROM analyses WHERE id = ? AND {_visible(user_id)}",
            [analysis_id, *_params(user_id)])
        _CONN.commit()
    return cur.rowcount > 0


# -------------------------------------------------------------- reports ----
def list_reports(user_id=None):
    with _LOCK:
        rows = _CONN.execute(
            f"SELECT data FROM reports WHERE {_visible(user_id)} "
            "ORDER BY created_at DESC, rowid DESC",
            _params(user_id)).fetchall()
    return [json.loads(r["data"]) for r in rows]


def insert_report(record, user_id=None):
    init_db()
    with _LOCK:
        _CONN.execute(
            "INSERT OR REPLACE INTO reports (id, user_id, created_at, data)"
            " VALUES (?, ?, ?, ?)",
            (record["id"], user_id, record.get("created_at"),
             json.dumps(record)))
        _CONN.commit()


def get_report(report_id, user_id=None):
    with _LOCK:
        row = _CONN.execute(
            f"SELECT data FROM reports WHERE id = ? AND {_visible(user_id)}",
            [report_id, *_params(user_id)]).fetchone()
    return json.loads(row["data"]) if row else None


def get_report_public(report_id):
    """Retrieve report for public cryptographic verification (no user auth filter)."""
    if not report_id:
        return None
    init_db()
    with _LOCK:
        row = _CONN.execute(
            "SELECT data FROM reports WHERE id = ?", [report_id]).fetchone()
    return json.loads(row["data"]) if row else None


def get_report_by_hash(verification_hash):
    """Public lookup for third-party auditor verification by SHA-256 fingerprint."""
    if not verification_hash:
        return None
    init_db()
    target_hash = str(verification_hash).lower().strip()
    with _LOCK:
        rows = _CONN.execute(
            "SELECT data FROM reports ORDER BY created_at DESC").fetchall()
    for r in rows:
        try:
            d = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
            vh = (
                d.get("verification_hash")
                or (d.get("verification") or {}).get("sha256_fingerprint")
                or (d.get("full_report") or {}).get("verification", {}).get("sha256_fingerprint")
            )
            if vh and str(vh).lower().strip() == target_hash:
                return d
        except Exception:
            continue
    return None


def delete_report(report_id, user_id=None):
    with _LOCK:
        cur = _CONN.execute(
            f"DELETE FROM reports WHERE id = ? AND {_visible(user_id)}",
            [report_id, *_params(user_id)])
        _CONN.commit()
    return cur.rowcount > 0


# ------------------------------------------------------------- feedback ----
def list_feedback():
    with _LOCK:
        rows = _CONN.execute(
            "SELECT data FROM feedback ORDER BY created_at DESC, rowid DESC"
        ).fetchall()
    return [json.loads(r["data"]) for r in rows]


def insert_feedback(record):
    init_db()
    with _LOCK:
        _CONN.execute(
            "INSERT OR REPLACE INTO feedback (id, created_at, data)"
            " VALUES (?, ?, ?)",
            (record["id"], record.get("created_at"), json.dumps(record)))
        _CONN.commit()


# ------------------------------------------------- legacy data migration ----
def migrate_legacy_rows(default_user_id):
    """One-time cleanup for strict isolation: legacy rows created before
    accounts existed (user_id NULL) and demo-seed copies are reassigned to
    default_user_id so no data is lost and no account sees another's data.
    Returns (legacy_reassigned, seed_copies_deleted)."""
    init_db()
    with _LOCK:
        cur = _CONN.execute(
            "UPDATE analyses SET user_id = ? WHERE user_id IS NULL",
            (default_user_id,))
        legacy = cur.rowcount
        cur = _CONN.execute(
            "DELETE FROM analyses WHERE data LIKE '%\"seed\": true%'")
        seeds = cur.rowcount
        _CONN.commit()
    return (legacy, seeds)


# ------------------------------------------------------------- sessions ----
def create_session(user_id, label=None):
    """Open a new work session for user_id. One session is created per login
    (and via POST /api/sessions); analyses run while its token is active are
    tagged with its id. Returns the session dict."""
    init_db()
    sid = "SES-" + secrets.token_hex(4).upper()
    started = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _LOCK:
        _CONN.execute(
            "INSERT INTO sessions (id, user_id, label, started_at, ended_at)"
            " VALUES (?, ?, ?, ?, NULL)",
            (sid, user_id, label, started))
        _CONN.commit()
    return {"id": sid, "user_id": user_id, "label": label,
            "started_at": started, "ended_at": None}


def get_session(session_id, user_id):
    with _LOCK:
        row = _CONN.execute(
            "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id)).fetchone()
    return dict(row) if row else None


def end_session(session_id, user_id):
    """Mark a session ended (logout). Returns True if it was open."""
    with _LOCK:
        cur = _CONN.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ? AND user_id = ?"
            " AND ended_at IS NULL",
            (time.strftime("%Y-%m-%dT%H:%M:%S"), session_id, user_id))
        _CONN.commit()
    return cur.rowcount > 0


def delete_session(session_id, user_id):
    """Delete a session and detach its analyses (they stay in history,
    untagged, so nothing is lost)."""
    with _LOCK:
        _CONN.execute(
            "UPDATE analyses SET session_id = NULL "
            "WHERE session_id = ? AND user_id = ?", (session_id, user_id))
        cur = _CONN.execute(
            "DELETE FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id))
        _CONN.commit()
    return cur.rowcount > 0


def delete_all_user_sessions(user_id):
    """Delete all active sessions for a user (e.g. on password reset or account recovery).
    All tokens bound to any deleted session are immediately invalidated."""
    init_db()
    with _LOCK:
        _CONN.execute(
            "UPDATE analyses SET session_id = NULL WHERE user_id = ?",
            (user_id,))
        cur = _CONN.execute(
            "DELETE FROM sessions WHERE user_id = ?", (user_id,))
        _CONN.commit()
    return cur.rowcount


def list_sessions(user_id):
    """All of the user's sessions, newest first, with analysis counts and
    mean ISO nodularity (computed in Python — no json1 dependency)."""
    init_db()
    with _LOCK:
        rows = _CONN.execute(
            "SELECT * FROM sessions WHERE user_id = ? "
            "ORDER BY started_at DESC, rowid DESC", (user_id,)).fetchall()
        # dict(zip(...)) not dict(rows): rows are Row-like (index 0/1 access
        # must map to session_id / count on BOTH sqlite3.Row and pgcompat.PGRow)
        counts = {_r[0]: _r[1] for _r in _CONN.execute(
            "SELECT session_id, COUNT(*) FROM analyses "
            "WHERE user_id = ? AND session_id IS NOT NULL "
            "GROUP BY session_id", (user_id,)).fetchall()}
    out = []
    for r in rows:
        d = dict(r)
        d["analysis_count"] = int(counts.get(d["id"], 0))
        if d["analysis_count"]:
            vals = [a["iso_nodularity_pct"] for a in
                    session_analyses(d["id"], user_id)
                    if isinstance(a.get("iso_nodularity_pct"),
                                  (int, float))]
            d["avg_iso_pct"] = round(sum(vals) / len(vals), 1) if vals \
                else None
        else:
            d["avg_iso_pct"] = None
        out.append(d)
    return out


def session_analyses(session_id, user_id):
    """Analyses produced within a session (owner-scoped)."""
    return list_analyses(user_id, session_id=session_id)


# ---------------------------------------------------------- calibrations ----
def save_calibration(key, data):
    with _LOCK:
        _CONN.execute(
            "INSERT OR REPLACE INTO calibrations (key, data) VALUES (?, ?)",
            (key, json.dumps(data)))
        _CONN.commit()


def load_calibration(key):
    with _LOCK:
        row = _CONN.execute(
            "SELECT data FROM calibrations WHERE key = ?", (key,)).fetchone()
    return json.loads(row["data"]) if row else None
