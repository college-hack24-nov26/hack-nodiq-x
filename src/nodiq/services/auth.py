#!/usr/bin/env python3
"""
services/auth.py — real backend authentication (Advancement 1).

Password hashing with bcrypt (cost 12). Legacy PBKDF2-HMAC-SHA256 hashes
(200k iterations, per-user salt) from the previous scheme still verify and
are transparently upgraded to bcrypt on the next successful login.

Session tokens are HMAC-signed stateless strings `payload.signature` with a
per-install secret (server_data/secret.key, auto-generated). Logout revokes
the presented token server-side via a revocation table; revoked tokens are
rejected by verify_token until their natural expiry passes.

Token payload: {"uid": user_id, "exp": unix_seconds, "sid": session_id?}
Reset tokens additionally carry "k": "reset" and are NEVER accepted as
login bearer tokens (and vice versa).

Storage: users table inside the shared SQLite DB (services/db).
"""
import hashlib
import hmac
import base64
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

import bcrypt

import nodiq.services.db as db
from nodiq.services.pgcompat import psycopg2 as _pg  # UniqueViolation on PG

from nodiq.core.config import DATA_DIR
SECRET_PATH = DATA_DIR / "secret.key"
TOKEN_TTL_S = 60 * 60 * 24 * 7          # 7 days
PBKDF2_ITERS = 200_000
BCRYPT_ROUNDS = 12

# Precomputed dummy hash so unknown-email logins burn the same bcrypt cost
# as wrong-password logins (login timing must not reveal account existence).
_DUMMY_HASH = bcrypt.hashpw(b"!dummy-password-for-timing!",
                            bcrypt.gensalt(rounds=BCRYPT_ROUNDS))

_LOCK = threading.Lock()
_SECRET = None


# ------------------------------------------------------------- secret ----
def _secret() -> bytes:
    global _SECRET
    with _LOCK:
        if _SECRET is None:
            if SECRET_PATH.exists():
                _SECRET = SECRET_PATH.read_bytes().strip()
            else:
                _SECRET = secrets.token_hex(32).encode()
                SECRET_PATH.write_bytes(_SECRET)
                try:
                    SECRET_PATH.chmod(0o600)
                except OSError:
                    pass
        return _SECRET


# ------------------------------------------------------------- users ----
_USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    name          TEXT,
    phone         TEXT,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'operator'
);
"""

# ---------------------------------------------------------------- roles ----
# Minimal RBAC foundation. Roles are server-authoritative: a client can never
# send one (services/validate.py rejects role fields outright), and the
# effective role is derived from the stored row plus the operator's
# environment allow-lists. Existing accounts keep working unchanged as
# "operator"; the environment lists are the bootstrap path to the first
# reviewer/admin without editing the database.
ROLES = ("operator", "reviewer", "admin")
ROLE_RANK = {"operator": 0, "reviewer": 1, "admin": 2}

_ROLE_COLUMN = None   # None = not probed yet, True/False = column presence


def _ensure_role_column(conn) -> bool:
    """Additive, non-destructive migration for databases created before
    RBAC: ALTER TABLE users ADD COLUMN role ... Existing rows keep every
    value they have and default to 'operator'. PRAGMA table_info is
    translated to information_schema by services/pgcompat on the Supabase
    backend. Returns True when the column is (now) available."""
    global _ROLE_COLUMN
    try:
        cols = {row["name"] for row in
                conn.execute("PRAGMA table_info(users)").fetchall()}
    except Exception:
        _ROLE_COLUMN = False
        return False
    if "role" in cols:
        _ROLE_COLUMN = True
        return True
    try:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL "
                     "DEFAULT 'operator'")
        conn.commit()
        _ROLE_COLUMN = True
        return True
    except Exception:
        _ROLE_COLUMN = False
        return False


def _role_available(conn) -> bool:
    """Whether SELECTs may reference users.role. Probed once per process;
    every connection path goes through _user_conn(), which runs the
    additive migration first."""
    if _ROLE_COLUMN is None:
        return _ensure_role_column(conn)
    return _ROLE_COLUMN


def _env_role_map() -> dict:
    """Bootstrap role assignments from the environment, read per call so an
    operator can promote the first admin without editing the database:
    NODIQ_ADMIN_EMAILS / NODIQ_REVIEWER_EMAILS (comma-separated emails).
    Admin wins over reviewer for the same address."""
    mapping = {}
    for var, role in (("NODIQ_REVIEWER_EMAILS", "reviewer"),
                      ("NODIQ_ADMIN_EMAILS", "admin")):
        for email in (os.environ.get(var) or "").split(","):
            email = email.strip().lower()
            if email:
                mapping[email] = role
    return mapping


def effective_role(user) -> str:
    """Server-side role for a user dict: stored role, elevated by the
    environment allow-lists (they can only raise privilege, never lower
    it), defaulting to 'operator' for legacy rows."""
    user = user or {}
    role = str(user.get("role") or "operator").strip().lower()
    if role not in ROLES:
        role = "operator"
    env_role = _env_role_map().get(str(user.get("email") or "").lower())
    if env_role and ROLE_RANK[env_role] > ROLE_RANK[role]:
        role = env_role
    return role


def set_role(uid: str, role: str):
    """Set a user's stored role. Returns the updated public user dict, or
    None when the role is invalid or the user does not exist."""
    role = str(role or "").strip().lower()
    if role not in ROLES:
        return None
    conn = _user_conn()
    if not _role_available(conn):
        return None
    with _LOCK:
        cur = conn.execute("UPDATE users SET role = ? WHERE id = ?",
                           (role, uid))
        conn.commit()
    if cur.rowcount <= 0:
        return None
    return user_by_id(uid)


def list_users():
    """Admin-only listing: identity + role + creation time. Phone numbers
    are deliberately omitted (not needed for role administration)."""
    conn = _user_conn()
    role_col = "role" if _role_available(conn) else "'operator' AS role"
    with _LOCK:
        rows = conn.execute(
            f"SELECT id, email, name, {role_col}, created_at FROM users "
            "ORDER BY created_at ASC, id ASC").fetchall()
    out = []
    for row in rows:
        user = dict(row)
        user["role"] = effective_role(user)
        out.append(user)
    return out


def _user_conn():
    """The users table lives in the same SQLite file as everything else."""
    db.init_db()
    conn = db._CONN
    with _LOCK:
        conn.executescript(_USERS_SCHEMA)
        _ensure_role_column(conn)
        conn.commit()
    return conn


# ---------------------------------------------------------- passwords ----
def hash_password(password: str) -> str:
    """bcrypt, cost 12. Returns the standard $2b$ modular crypt string."""
    return bcrypt.hashpw(str(password or "").encode(),
                         bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, stored: str) -> bool:
    """Verify against bcrypt ($2b$) or a legacy pbkdf2$ hash. Use
    needs_rehash() to decide whether to transparently upgrade."""
    stored = str(stored or "")
    try:
        if stored.startswith("$2"):
            return bcrypt.checkpw(str(password or "").encode(),
                                  stored.encode())
        if stored.startswith("pbkdf2$"):
            algo, iters, salt_hex, dk_hex = stored.split("$")
            dk = hashlib.pbkdf2_hmac("sha256", str(password or "").encode(),
                                     bytes.fromhex(salt_hex), int(iters))
            return hmac.compare_digest(dk.hex(), dk_hex)
        return False
    except Exception:
        return False


def needs_rehash(stored: str) -> bool:
    """True when `stored` uses the legacy scheme (upgrade after a
    successful verify)."""
    return not str(stored or "").startswith("$2")


# ------------------------------------------------------------- tokens ----
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


# ------------------------------------------------------- revocations -----
# Logout must invalidate the presented token server-side. Revoked tokens are
# stored by hash until their natural expiry; verify_token rejects them.
_REVOKED_SCHEMA = """
CREATE TABLE IF NOT EXISTS revoked_tokens (
    token_hash TEXT PRIMARY KEY,
    expires_at REAL NOT NULL
);
"""


def revoke_token(token: str) -> bool:
    """Revoke a bearer token so it can no longer authenticate. Idempotent."""
    if not token:
        return False
    try:
        payload, sig = token.split(".", 1)
        expect = hmac.new(_secret(), payload.encode(),
                          hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return False
        exp = float(json.loads(_unb64(payload)).get("exp", 0))
    except Exception:
        return False
    conn = _user_conn()
    tok_hash = hashlib.sha256(token.encode()).hexdigest()
    with _LOCK:
        conn.executescript(_REVOKED_SCHEMA)
        # Opportunistic sweep: revoked rows past expiry can never be
        # presented again, so drop them to keep the table small.
        conn.execute("DELETE FROM revoked_tokens WHERE expires_at < ?",
                     (time.time(),))
        conn.execute(
            "INSERT OR IGNORE INTO revoked_tokens (token_hash, expires_at)"
            " VALUES (?, ?)", (tok_hash, exp))
        conn.commit()
    return True


def _token_revoked(token: str) -> bool:
    try:
        conn = _user_conn()
        row = conn.execute(
            "SELECT 1 FROM revoked_tokens WHERE token_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return row is not None
    except Exception:
        return False


def issue_token(user_id: str, ttl_s: int = TOKEN_TTL_S,
                session_id: str | None = None,
                kind: str = "auth") -> str:
    """Mint an HMAC-signed token. `kind` separates token families: login
    bearer tokens ("auth") can never be presented as reset tokens and
    vice-versa (verified in verify_token). The random "n" (nonce) claim
    guarantees every issued token is unique — two tokens minted for the
    same user in the same second must not collide (e.g. reset tokens are
    stored by token hash, so a collision would overwrite a live token)."""
    payload_dict = {"uid": user_id, "exp": int(time.time()) + ttl_s,
                    "k": kind, "n": secrets.token_hex(8)}
    if session_id:
        payload_dict["sid"] = session_id
    payload = _b64(json.dumps(payload_dict).encode())
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def token_session_id(token: str):
    """Extract the session id ("sid" claim) from a token, or None."""
    try:
        payload, sig = token.split(".", 1)
        expect = hmac.new(_secret(), payload.encode(),
                          hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return None
        return json.loads(_unb64(payload)).get("sid")
    except Exception:
        return None


def verify_token(token: str, kind: str = "auth"):
    """Return user_id or None. Checks (in order): HMAC signature,
    expiry, token family (`k` claim must equal `kind`), and server-side
    revocation. Signature comparison is constant-time."""
    try:
        payload, sig = token.split(".", 1)
        expect = hmac.new(_secret(), payload.encode(),
                          hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expect):
            return None
        data = json.loads(_unb64(payload))
        if data.get("exp", 0) < time.time():
            return None
        # Token-family enforcement: legacy tokens carry no "k" and are
        # treated as "auth". A reset token is never a login token.
        if data.get("k", "auth") != kind:
            return None
        if _token_revoked(token):
            return None
        return data.get("uid")
    except Exception:
        return None


# ----------------------------------------------------------- accounts ----
def create_user(email, password, name="", phone=""):
    """Returns the public user dict. Raises ValueError on duplicates."""
    email = str(email or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("a valid email is required")
    if len(str(password or "")) < 6:
        raise ValueError("password must be at least 6 characters")
    conn = _user_conn()
    uid = "USR-" + secrets.token_hex(4).upper()
    try:
        with _LOCK:
            conn.execute(
                "INSERT INTO users (id, email, name, phone, password_hash,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, email, str(name or "").strip()[:120],
                 str(phone or "").strip()[:40], hash_password(password),
                 time.strftime("%Y-%m-%dT%H:%M:%S")))
            conn.commit()
    except (sqlite3.IntegrityError, _pg.errors.UniqueViolation):
        raise ValueError("an account with this email already exists")
    return {"id": uid, "email": email, "name": name, "phone": phone,
            "role": effective_role({"email": email})}


def authenticate(email, password):
    """Returns (user_dict, token) or (None, reason_str).

    Every login opens a NEW work session; the token carries its id ("sid").
    Analyses run with that token are tagged with the session, and the
    Sessions page lists every past login with what it produced.

    Unknown emails burn the same bcrypt cost as wrong passwords so login
    timing does not reveal whether an account exists. Legacy pbkdf2 hashes
    are upgraded to bcrypt after a successful verification."""
    email = str(email or "").strip().lower()
    conn = _user_conn()
    role_col = "role" if _role_available(conn) else "'operator' AS role"
    with _LOCK:
        row = conn.execute(
            f"SELECT id, email, name, phone, password_hash, {role_col} "
            "FROM users WHERE email = ?", (email,)).fetchone()
    if row is None:
        # Equalize timing with the wrong-password path (bcrypt cost 12).
        bcrypt.checkpw(b"!timing-equalizer!", _DUMMY_HASH)
        return None, "invalid email or password"
    if not verify_password(password or "", row["password_hash"]):
        return None, "invalid email or password"
    # Transparent legacy-hash upgrade (pbkdf2 -> bcrypt).
    if needs_rehash(row["password_hash"]):
        with _LOCK:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(password or ""), row["id"]))
            conn.commit()
    user = {"id": row["id"], "email": row["email"], "name": row["name"],
            "phone": row["phone"],
            "role": effective_role({"email": row["email"],
                                    "role": _row_role(row)})}
    session = db.create_session(row["id"])
    token = issue_token(row["id"], session_id=session["id"])
    user["session"] = session
    return user, token


def _row_role(row) -> str:
    """Stored role from a users row, tolerating databases whose additive
    role migration could not run (SELECTs then omit the column)."""
    try:
        return str(row["role"] or "operator")
    except (IndexError, KeyError):
        return "operator"


def user_by_id(uid):
    conn = _user_conn()
    role_col = "role" if _role_available(conn) else "'operator' AS role"
    with _LOCK:
        row = conn.execute(
            f"SELECT id, email, name, phone, {role_col} FROM users "
            "WHERE id = ?", (uid,)).fetchone()
    if not row:
        return None
    user = dict(row)
    user["role"] = effective_role(user)
    return user


# ------------------------------------------------- password reset tokens ----
# Single-use, 30-minute HMAC tokens bound to the user id, stored hashed in a
# dedicated table. Issuing a new reset for an account deletes any earlier
# token rows for that account, so only the most recent link works.
_RESET_SCHEMA = """
CREATE TABLE IF NOT EXISTS resets (
    token_hash TEXT PRIMARY KEY,
    uid        TEXT NOT NULL,
    expires_at REAL NOT NULL,
    used       INTEGER DEFAULT 0
);
"""


def generate_reset_token(email, ttl_s=60 * 30):
    """Return a reset token for the account, or None for unknown emails.
    (Never reveal whether an email exists — callers decide what to say.)"""
    email = str(email or "").strip().lower()
    conn = _user_conn()
    with _LOCK:
        conn.executescript(_RESET_SCHEMA)
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE email = ?",
                           (email,)).fetchone()
    if row is None:
        return None
    token = issue_token(row["id"], ttl_s=ttl_s, kind="reset")
    with _LOCK:
        # A newer reset request invalidates all earlier tokens for the
        # account; expired rows are dropped opportunistically.
        conn.execute("DELETE FROM resets WHERE uid = ? OR expires_at < ?",
                     (row["id"], time.time()))
        conn.execute(
            "INSERT INTO resets (token_hash, uid, expires_at, used)"
            " VALUES (?, ?, ?, 0)",
            (hashlib.sha256(token.encode()).hexdigest(), row["id"],
             time.time() + ttl_s))
        conn.commit()
    return token


def consume_reset_token(token):
    """Mark a valid reset token used; return uid or None."""
    if not token:
        return None
    # kind="reset": a login bearer token can never be consumed as a reset
    # token (verify_token enforces the family claim).
    uid = verify_token(token, kind="reset")
    if uid is None:
        return None
    try:
        data = json.loads(_unb64(token.split(".", 1)[0]))
    except Exception:
        return None
    if data.get("k") != "reset":
        return None
    conn = _user_conn()
    tok_hash = hashlib.sha256(token.encode()).hexdigest()
    with _LOCK:
        conn.executescript(_RESET_SCHEMA)
        row = conn.execute(
            "SELECT uid, expires_at, used FROM resets WHERE token_hash = ?",
            (tok_hash,)).fetchone()
        if row is None or row["used"] or row["expires_at"] < time.time() \
                or row["uid"] != uid:
            return None
        conn.execute("UPDATE resets SET used = 1 WHERE token_hash = ?",
                     (tok_hash,))
        conn.commit()
    return uid


def set_password(uid, new_password):
    """Set a new password for uid. Returns True on success."""
    if len(str(new_password or "")) < 6:
        return False
    conn = _user_conn()
    with _LOCK:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), uid))
        conn.commit()
    return cur.rowcount > 0
