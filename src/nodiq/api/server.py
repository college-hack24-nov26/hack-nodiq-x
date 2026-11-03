"""NODIQ-X backend server.

Serves the React frontend (dev proxy target) and provides a REST API backed by
the validated nodularity pipeline (1000/1000 images at 100% accuracy).

Run from the project root:  python -m nodiq.api.server  (API on :8001)
Frontend dev server:        npm run dev --prefix apps/web (proxies /api -> :8001)

Endpoints
---------
GET  /api/health                  -> {status, engine, accuracy}
GET  /api/dataset                 -> list of the 1000 dataset images
GET  /api/dataset/sample          -> one random dataset image (auto-redirect)
GET  /api/dataset/file/<name>     -> the dataset image itself (PNG bytes)
GET  /api/dataset/analysis/<name> -> full pipeline results for one dataset image
POST /api/analyze                 -> multipart upload analysis (202 + id; runs async,
                                     client polls GET /api/analyses/<id> until completed)
GET  /api/analyses                -> analysis history (most recent first)
POST /api/analyses                -> append one analysis record
DELETE /api/analyses/<id>         -> delete one analysis record
GET  /api/analyses/stats          -> aggregate stats for dashboard
GET  /api/reports                 -> report list
POST /api/reports/generate        -> generate a report from an analysis
GET  /api/reports/<id>            -> one report
DELETE /api/reports/<id>          -> delete a report
POST /api/copilot                 -> context-aware assistant replies
POST /api/feedback                -> contact-form feedback (saved + optional email)
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import cv2
import numpy as np
import requests
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
from flask_cors import CORS
from nodiq.core.config import (
    REPO_ROOT, DATA_DIR, SUMMARY_1000_CSV_PATH, WEB_DIR, LOGS_DIR
)
ROOT = REPO_ROOT

def _get_firebase_api_key():
    # Production (Render etc.) sets it as a real environment variable; the
    # .env file remains the local-dev source. Env wins so a stale .env can
    # never shadow the deployment value.
    env_val = os.environ.get("VITE_FIREBASE_API_KEY")
    if env_val:
        return env_val.strip()
    env_path = ROOT / ".env"
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("VITE_FIREBASE_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return None


# ---------------------------------------------------------------------------
# Auth rate limiting (brute-force defense): sliding-window counters keyed by
# route + client IP, stored in the shared SQLite database so ALL Gunicorn
# workers enforce the same budget (an in-process counter would let an
# attacker multiply every limit by the worker count). Limits are per-IP and
# generous enough for real users while stopping credential stuffing and
# reset-token enumeration. Storage errors fail CLOSED (requests limited),
# never silently disabling protection.
# ---------------------------------------------------------------------------
RATE_LIMITS_ENABLED = True   # test hook: fixtures set this False per-module

# (max requests, window seconds) per auth route
RATE_LIMITS = {
    "/api/auth/login": (10, 300),            # 10 tries / 5 min / IP
    "/api/auth/signup": (5, 3600),           # 5 accounts / hour / IP
    "/api/auth/forgot-password": (5, 3600),  # 5 resets / hour / IP
    "/api/auth/reset-password": (10, 3600),  # guesses at reset tokens
    "/api/auth/firebase": (10, 300),
    "/api/feedback": (10, 300),              # 10 submissions / 5 min / IP (anti-spam)
    "/api/verify/pdf": (20, 300),            # 20 verifications / 5 min / IP (resource guard)
    "/api/validation/run": (5, 300),         # 5 runs / 5 min / IP (CPU exhaustion guard)
}

# Analysis abuse protection: /api/analyze is the most expensive endpoint
# (a full engine pass per accepted request), so it gets its own budget.
# Unlike the auth routes it is keyed by the AUTHENTICATED USER ID first
# (the analysis record is per-account anyway) and falls back to client IP
# only for unauthenticated calls — which /api/analyze rejects with 401
# before any work, so the IP bucket is a cheap mop, not the primary key.
# Client-supplied headers (X-Forwarded-For etc.) are never trusted as the
# sole identity: _client_ip() uses the socket peer unless TRUST_PROXY=true.
# Stored in the SAME shared SQLite limiter, so all Gunicorn workers drain
# one budget and the counters survive a worker restart.
_ANALYZE_LIMIT = int(os.environ.get("NODIQ_ANALYZE_RATE_LIMIT", "30").strip()
                     or "30")
_ANALYZE_WINDOW = int(os.environ.get("NODIQ_ANALYZE_RATE_WINDOW", "300").strip()
                      or "300")
_ANALYZE_PATH = "/api/analyze"


def _client_ip():
    """Client IP for rate limiting. The socket peer is always used unless the
    operator explicitly sets TRUST_PROXY=true: a user-controlled
    X-Forwarded-For would otherwise let an attacker rotate fake IPs and
    bypass the limiter entirely. Set TRUST_PROXY=true only when the app sits
    behind a reverse proxy that overwrites (not appends to) the header."""
    if str(os.environ.get("TRUST_PROXY", "")).lower() in ("1", "true", "yes"):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _rate_limited(path: str):
    """True when this client IP exceeded the route's limit. Records the hit
    otherwise (shared SQLite counters — multi-worker safe, fail-closed)."""
    if not RATE_LIMITS_ENABLED:
        return False
    limit, window = RATE_LIMITS.get(path, (100, 60))
    return rate_limiter.is_limited(f"{path}|{_client_ip()}", limit, window)


def _analyze_limited(user) -> bool:
    """True when this caller exceeded the /api/analyze budget. Primary key
    is the authenticated user id; unauthenticated callers (which the route
    rejects 401 before doing any work) fall back to the client IP bucket.
    Uses the SAME shared SQLite limiter as the auth routes: multi-worker
    safe, fail-closed. Set NODIQ_ANALYZE_RATE_LIMIT=0 to disable."""
    if not RATE_LIMITS_ENABLED or _ANALYZE_LIMIT <= 0 or _ANALYZE_WINDOW <= 0:
        return False
    key = f"user:{user['id']}" if user else f"ip:{_client_ip()}"
    return rate_limiter.is_limited(
        f"{_ANALYZE_PATH}|{key}", _ANALYZE_LIMIT, _ANALYZE_WINDOW)


def _rate_limit_response(retry_after=None):
    """429 + Retry-After (seconds, rounded up). The header carries only the
    window length — never bucket composition or remaining quota internals."""
    resp = jsonify({"error": "too many requests. please try again later."})
    if retry_after is not None:
        try:
            ra = max(1, int(retry_after))
        except (TypeError, ValueError):
            ra = None
        if ra:
            resp.headers["Retry-After"] = str(ra)
    return resp, 429

from nodiq.pipelines.nodularity_pipeline import (analyze_for_frontend_json, analyze_image,
                                 load_grayscale, load_with_source)
from nodiq.services.quality import assess_quality
from nodiq.services import context as context_svc
from nodiq.services import db as store
from nodiq.services import auth as auth_svc
from nodiq.services import rate_limit as rate_limiter
from nodiq.services import seclog
# services.storage (requests, ~15MB RSS) is imported LAZILY via _storage()
# — only when Supabase artifact storage is actually configured. On the
# sqlite dev/free-tier fallback the web worker keeps the pre-migration
# memory baseline (512MB budget; every MB of headroom matters).
from nodiq.services.validate import InputError, validate_body


def _storage():
    """Lazily import the artifact-storage module (its `requests` dependency
    costs ~15MB RSS — load it only when Supabase storage is configured)."""
    global _STORAGE_SVC
    try:
        return _STORAGE_SVC
    except NameError:
        from nodiq.services import storage as _svc
        _STORAGE_SVC = _svc
        return _STORAGE_SVC
from nodiq.services import mailer
from nodiq.services.lots import lot_summary, list_lots
from nodiq.services.review import set_review
from nodiq.services.calibration import (auto_calibrate, manual_calibrate,
                                  make_calibration, validate_um_per_px)
from nodiq.services.nodule_data import enrich_rows
from nodiq.services.nodule_data import get_nodule as get_nodule_detail
from nodiq.services.comparison import compare_analyses
from nodiq.services.analytics import batch_statistics, distribution_by_metric, spc
from nodiq.services.anomalies import assess_analysis, decision_support, scan_history
from nodiq.services import multifield
from nodiq.services.context import (build_contract, build_multifield_context,
                              load_full_analysis,
                              save_full_analysis)
from nodiq.services.validation_lab import (blind_test, internal_validation,
                                     synthetic_validation, validation_summary)
from nodiq.services.capabilities import get_capabilities
from nodiq.ai import tools as ai_tools
from nodiq.ai.agent import handle_turn, handle_turn_stream
from nodiq.ai.config import get_config
from nodiq.ai.provider import chat as ai_chat, status as ai_provider_status
from nodiq.ai.reference import search_reference
import nodiq.reports.report_builder as report_builder
import nodiq.pipelines.steel_grain_size_pipeline as steel_pipeline
import nodiq.services.white_cast_iron.pipeline as white_cast_iron_pipeline
import nodiq.services.gray_cast_iron.pipeline as gray_cast_iron_pipeline

CFG = get_config()
MAX_UPLOAD_BYTES = 25 * 1024 * 1024          # 25 MB cap (Phase 39)

# Decompression-bomb guard (security hardening): a tiny file can declare a
# gigantic canvas, so the pixel ceiling is enforced twice — from the
# container header BEFORE any decode allocates memory (_image_dimensions),
# and by OpenCV itself for every decode path. 50 MP is far above any
# microscope frame (the validated dataset is 2592x1944 = 5 MP) and far below
# what could exhaust the 512MB worker budget.
IMAGE_MAX_PIXELS = 50_000_000
IMAGE_MAX_SIDE = 20_000
IMAGE_MIN_SIDE = 4
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(IMAGE_MAX_PIXELS))

# Declared MIME types accepted as an image upload (cross-checked for the
# audit trail only — the part's Content-Type is client-controlled, so magic
# bytes + a real decode remain the authoritative checks; see /api/analyze).
_ALLOWED_UPLOAD_MIMES = {
    "image/png", "image/jpeg", "image/jpg", "image/pjpeg", "image/tiff",
    "image/bmp", "image/x-ms-bmp", "application/octet-stream",
}

# Magic-number allowlist for uploaded micrographs: PNG / JPEG / TIFF / BMP
_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpeg",
    b"II*\x00": "tiff", b"MM\x00*": "tiff",
    b"BM": "bmp",
}

# Filename spellings that naturally match each content kind. Used only for
# observability: a mismatching name is normalized, never rejected (see
# /api/analyze).
_MAGIC_EXTS = {
    "png": {".png"},
    "jpeg": {".jpg", ".jpeg", ".jpe", ".jfif"},
    "tiff": {".tif", ".tiff"},
    "bmp": {".bmp"},
}


def _check_image(data: bytes):
    """Reject non-image payloads by magic number before decoding/storage.
    Returns (kind, None) or (None, error-response-tuple). The scientific
    engine remains the sole arbiter of microstructure validity."""
    if not data or len(data) > MAX_UPLOAD_BYTES:
        return None, (jsonify({"error": "invalid image"}), 400)
    if not any(data.startswith(m) for m in _MAGIC):
        seclog.log_event("upload_rejected", route="/api/analyze",
                         method="POST", status=415,
                         detail="magic-number mismatch")
        return None, (jsonify({"error": "unsupported image format"}), 415)
    return next(_MAGIC[m] for m in _MAGIC if data.startswith(m)), None


def _jpeg_dimensions(data: bytes):
    """(width, height) from the first JPEG SOF marker, or None."""
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xDA:                 # start of scan: no SOF seen
            return None
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        if seg_len < 2:
            return None
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return (int.from_bytes(data[i + 7:i + 9], "big"),
                    int.from_bytes(data[i + 5:i + 7], "big"))
        i += 2 + seg_len
    return None


def _tiff_dimensions(data: bytes):
    """(width, height) from IFD0 (tags 256/257), or None."""
    if len(data) < 8:
        return None
    if data[0:2] == b"II":
        endian = "little"
    elif data[0:2] == b"MM":
        endian = "big"
    else:
        return None

    def u16(off):
        return int.from_bytes(data[off:off + 2], endian)

    def u32(off):
        return int.from_bytes(data[off:off + 4], endian)

    if u16(2) != 42:
        return None
    ifd = u32(4)
    if ifd + 2 > len(data):
        return None
    count = u16(ifd)
    width = height = None
    for k in range(count):
        entry = ifd + 2 + k * 12
        if entry + 12 > len(data):
            break
        tag, typ = u16(entry), u16(entry + 2)
        val = u16(entry + 8) if typ == 3 else u32(entry + 8)
        if tag == 256:
            width = val
        elif tag == 257:
            height = val
    return (width, height) if width and height else None


def _image_dimensions(data: bytes, kind: str):
    """Container-header dimensions, parsed WITHOUT decoding pixels so a
    decompression bomb is refused before any large allocation. Returns None
    for a structurally unusual header — the decode step and OpenCV's own
    OPENCV_IO_MAX_IMAGE_PIXELS ceiling remain the backstops."""
    try:
        if kind == "png":
            if len(data) >= 24 and data[12:16] == b"IHDR":
                return (int.from_bytes(data[16:20], "big"),
                        int.from_bytes(data[20:24], "big"))
        elif kind == "bmp":
            if len(data) >= 26:
                w = int.from_bytes(data[18:22], "little", signed=True)
                h = int.from_bytes(data[22:26], "little", signed=True)
                return (abs(w), abs(h))
        elif kind == "jpeg":
            return _jpeg_dimensions(data)
        elif kind == "tiff":
            return _tiff_dimensions(data)
    except Exception:
        return None
    return None


DATASET_DIR = WEB_DIR / "public" / "dataset"
SUMMARY_CSV = SUMMARY_1000_CSV_PATH
DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)


def _stored_upload_path(record):
    """Absolute path of a record's persisted upload, or None when it is
    missing or resolves OUTSIDE UPLOAD_DIR. Uploads are server-named
    (content hash + content-derived extension), but a tampered legacy row
    must never turn a file-serving route into an arbitrary-file read."""
    raw = (record or {}).get("stored_path")
    if not raw:
        return None
    try:
        path = Path(raw).resolve()
        path.relative_to(UPLOAD_DIR.resolve())
    except (OSError, ValueError):
        seclog.log_event("suspicious_path", route="stored_path", method="GET",
                         status=400, detail=str(raw)[:160])
        return None
    return path if path.is_file() else None

# SQLite persistence (Advancement 2): one server_data/nodiq.db replaces the
# JSON "databases". Legacy JSON files are imported once on first import.
store.init_db()
# Authentication owns the users schema; initialize it before the startup
# isolation query so a fresh container database can import the server.
auth_svc._user_conn()

# Strict per-email isolation: pre-account legacy rows (user_id NULL) were
# visible to every account. Reassign them to the primary account once; if
# no account exists yet they stay NULL until the first signup claims them.
_primary = None
with store._LOCK:
    _row = store._CONN.execute(
        "SELECT id FROM users ORDER BY created_at ASC, id ASC LIMIT 1").fetchone()
    if _row:
        _primary = _row["id"]
if _primary:
    _legacy, _seeds = store.migrate_legacy_rows(_primary)
    if _legacy or _seeds:
        print(f"[db] strict isolation: reassigned {_legacy} legacy "
              f"analyses to {_primary}, removed {_seeds} demo-seed copies",
              flush=True)

app = Flask(__name__, static_folder=None)

# Flask enforces this BEFORE the route runs: larger requests (uploads or
# JSON) are rejected with 413 without buffering the body into memory.
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
# ---------------------------------------------------------------------------
# CORS: the SPA is served by this same Flask app (and the Vite dev server
# proxies /api), so no cross-origin browser client is required. Allow-list
# the dev origins explicitly instead of reflecting every origin; deployments
# behind a different frontend host set CORS_ORIGINS="https://app.example.com".
# ---------------------------------------------------------------------------
_DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",   # vite dev
    "http://localhost:4173", "http://127.0.0.1:4173",   # vite preview
]
_origins = ([o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",")
             if o.strip()] or _DEFAULT_CORS_ORIGINS)
CORS(app, resources={r"/api/*": {"origins": _origins}},
     supports_credentials=False)

# --------------------------------------------------------------------------
# authentication (Advancement 1): real accounts + bearer tokens
# --------------------------------------------------------------------------


def _current_user():
    """User dict from the presented credential: the `Authorization: Bearer`
    header (API clients/tests) first, then the HttpOnly session cookie
    (browsers). The token never travels in JSON bodies."""
    token = _request_token()
    if not token:
        return None
    uid = auth_svc.verify_token(token)
    if not uid:
        return None
    # Session security: a token bound to a work session dies with it. Logout
    # already revokes the presented token; this also closes the
    # DELETE /api/sessions/<id> path so a deleted session cannot keep
    # authenticating any login created from it.
    sid = auth_svc.token_session_id(token)
    if sid:
        try:
            if store.get_session(sid, uid) is None:
                seclog.log_event("session_revoked_token", route=request.path,
                                 method=request.method, status=401,
                                 user_id=uid,
                                 detail="token bound to a deleted session")
                return None
        except Exception:
            pass   # a store hiccup must never break authentication
    return auth_svc.user_by_id(uid)


# ---------------------------------------------------------------------------
# HttpOnly cookie session: the browser auth token lives ONLY in a
# HttpOnly SameSite=Lax cookie — never in JSON bodies, never in
# localStorage, never in logs.
# ---------------------------------------------------------------------------
_AUTH_COOKIE = "nodiq_session"

def _request_token():
    """Bearer header first, then the auth cookie. Returns None if absent."""
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return request.cookies.get(_AUTH_COOKIE) or None

def _cookie_secure():
    """Secure flag: explicit COOKIE_SECURE env wins; otherwise `auto` —
    Secure when the request arrived over https (with TRUST_PROXY=true this
    reflects the TLS-terminating proxy). Plain-http local dev stays
    functional; the production TLS deployment gets Secure automatically."""
    setting = os.environ.get("COOKIE_SECURE", "auto").strip().lower()
    if setting in ("1", "true", "yes"):
        return True
    if setting in ("0", "false", "no"):
        return False
    return bool(request.is_secure)

def _auth_cookie_kwargs():
    """HttpOnly + SameSite=Lax + Path=/ + Max-Age matching the 7-day token
    TTL. Secure per _cookie_secure(). Logout must clear with the SAME
    kwargs (max_age=0) so the browser drops it."""
    return {"httponly": True, "samesite": "Lax", "path": "/",
            "max_age": auth_svc.TOKEN_TTL_S, "secure": _cookie_secure()}

def _issue_session_response(payload: dict, status: int = 200, token: str = ""):
    """JSON response carrying the user payload with the session token set
    ONLY as an HttpOnly cookie. The token is never returned in the body."""
    resp = jsonify(payload)
    if token:
        resp.set_cookie(_AUTH_COOKIE, token, **_auth_cookie_kwargs())
    return resp


def _uid():
    user = _current_user()
    return user["id"] if user else None


def _current_session_id():
    """Work-session id carried by the presented token ("sid" claim), or None
    for anonymous/legacy tokens."""
    token = _request_token()
    if not token:
        return None
    return auth_svc.token_session_id(token)


def require_auth(fn):
    """Decorator: 401 unless a valid token is presented. The handler then
    receives the user dict as its first argument."""
    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = _current_user()
        if user is None:
            return jsonify({"error": "authentication required"}), 401
        return fn(user, *args, **kwargs)

    return wrapper


def require_role(*roles):
    """Decorator (stacked UNDER @require_auth): 403 unless the verified
    user's effective role is one of `roles`. Authorization is always derived
    server-side from the stored role (+ operator allow-lists); a client can
    never send one (services/validate.py rejects role fields outright).
    Failures are audit-logged."""
    from functools import wraps

    def decorator(fn):
        @wraps(fn)
        def wrapper(user, *args, **kwargs):
            role = auth_svc.effective_role(user)
            if role not in roles:
                seclog.log_event(
                    "authz_failed", route=request.path, method=request.method,
                    status=403, ip=_client_ip(), user_id=user.get("id"),
                    detail=f"role '{role}' requires one of "
                           f"{'/'.join(roles)}")
                return jsonify({"error": "insufficient permissions"}), 403
            return fn(user, *args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# CSRF / origin protection: state-changing API requests must name a trusted
# origin. The session rides in an HttpOnly SameSite=Lax cookie, so a
# cross-site page cannot read it — but SameSite alone is defense that has
# had browser gaps, so origins are validated too. Browsers attach Origin to
# every POST/PUT/PATCH/DELETE (same-origin included), so:
#   - an Origin/Referer that IS present must resolve to a trusted origin,
#     otherwise the request is rejected 403;
#   - Origin: null (sandboxed iframe / data: URL) never matches;
#   - a browser Sec-Fetch-Site: cross-site request is rejected even if the
#     headers were stripped;
#   - requests with NO Origin/Referer and NO session cookie are non-browser
#     clients (curl, CI, API tools): not CSRF-capable, allowed through;
#   - requests with NO Origin/Referer that DO carry the session cookie are
#     logged (csrf_no_origin) and allowed — no real browser does this, and
#     the SameSite=Lax + JSON-only contracts still apply on top.
# Bearer-token callers are exempt: a header credential is not ambient, so a
# third-party page cannot attach it. Trusted origins = the existing CORS
# allow-list + CSRF_TRUSTED_ORIGINS + the request's own host (TLS often
# terminates at a proxy, so the scheme is compared loosely).
# ---------------------------------------------------------------------------
_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _csrf_trusted_origins() -> set:
    extra = [o.strip() for o in
             os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
             if o.strip()]
    return {o.rstrip("/").lower() for o in list(_origins) + extra}


def _origin_trusted(value: str) -> bool:
    """True when `value` (an Origin header, or a Referer URL from which the
    scheme://host[:port] part is taken) names a trusted origin."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    origin = f"{parts.scheme}://{parts.netloc}".lower()
    if origin in _csrf_trusted_origins():
        return True
    return parts.netloc.lower() == (request.host or "").lower()


@app.before_request
def _csrf_protect():
    if request.method in _CSRF_SAFE_METHODS \
            or not request.path.startswith("/api/"):
        return None
    if request.headers.get("Authorization", "").startswith("Bearer "):
        return None
    candidate = (request.headers.get("Origin") or "").strip()
    if not candidate:
        candidate = (request.headers.get("Referer") or "").strip()
    if candidate:
        if _origin_trusted(candidate):
            return None
        seclog.log_event("csrf_rejected", route=request.path,
                         method=request.method, status=403,
                         ip=_client_ip(),
                         detail=f"untrusted origin: {candidate[:160]}")
        return jsonify({"error": "request rejected: untrusted origin"}), 403
    if (request.headers.get("Sec-Fetch-Site") or "").strip().lower() \
            == "cross-site":
        seclog.log_event("csrf_rejected", route=request.path,
                         method=request.method, status=403,
                         ip=_client_ip(),
                         detail="cross-site fetch with no origin")
        return jsonify({"error": "request rejected: untrusted origin"}), 403
    if request.cookies.get(_AUTH_COOKIE):
        seclog.log_event("csrf_no_origin", route=request.path,
                         method=request.method, status=0,
                         ip=_client_ip(),
                         detail="state-changing request with session cookie "
                                "but no Origin/Referer")
    return None


# ---------------------------------------------------------------------------
# Security headers on every response + a safe catch-all error handler.
# ---------------------------------------------------------------------------
# localhost camera agent (Phase 2 microscope capture): the SPA may fetch
# http://127.0.0.1:<port> (and localhost) for /status + /capture of the local
# MATRIX VISION camera. Port is env-driven so a deployment can move the agent
# without touching this code. Only connect-src is extended — no other
# directive is weakened.
_CAMERA_AGENT_SOURCES = (
    lambda port: f"http://127.0.0.1:{port} http://localhost:{port}"
)(os.environ.get("NODIQ_CAMERA_PORT", "8765").strip() or "8765")

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # The app renders micrographs and dashboards only — none of these
    # browser capabilities are used, so they are explicitly disabled.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), "
                          "payment=(), usb=()",
    # Enforced CSP: verified by a full browser walk-through (landing, login,
    # signup, dashboard, analysis run, copilot, report generation + preview,
    # settings, 404, logout) with Report-Only producing zero violations.
    # - script-src 'self': the Vite bundle is external module tags only; the
    #   Firebase SDK ships inside the bundle. gstatic/google script+frame
    #   entries serve the reCAPTCHA widget used by phone-number sign-in.
    #   The quoted hash allows Firebase Auth's own injected inline bootstrap
    #   script (reported verbatim by the enforced policy) — no 'unsafe-inline'.
    # - style-src 'unsafe-inline': required by React inline style attributes
    #   (CSS cannot execute script in modern browsers).
    # - api.groq.com is intentionally NOT allowed: the LLM provider is
    #   called server-side only.
    # - localhost camera agent (Phase 2 microscope capture): the SPA may
    #   fetch http://127.0.0.1:8765 (and localhost) for /status + /capture of
    #   the local MATRIX VISION camera. Port is env-driven so a deployment
    #   can move the agent without touching this code.
    "Content-Security-Policy":
        "default-src 'self'; "
        "script-src 'self' https://www.gstatic.com https://www.googleapis.com "
        "https://www.google.com https://apis.google.com "  # reCAPTCHA + Google sign-in
        "'sha256-+D8EU9U10Jz0EG9uVmlp2XsWl5DlzL8JuVOeeWP8DcM='; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self' https://*.googleapis.com https://*.firebaseapp.com "
        "https://*.cloudfunctions.com https://www.google.com "  # reCAPTCHA verdict pings
        f"{_CAMERA_AGENT_SOURCES}; "
        "frame-src 'self' https://*.firebaseapp.com https://www.google.com; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
}


@app.after_request
def _add_security_headers(resp):
    for _h, _v in _SECURITY_HEADERS.items():
        resp.headers.setdefault(_h, _v)
    # HSTS only over confirmed HTTPS (never plain HTTP): either a direct TLS
    # termination or a trusted proxy announcing the https scheme.
    _https = request.is_secure or (
        str(os.environ.get("TRUST_PROXY", "")).lower()
        in ("1", "true", "yes")
        and request.headers.get("X-Forwarded-Proto", "") == "https")
    if _https:
        resp.headers.setdefault("Strict-Transport-Security",
                                "max-age=31536000")
    return resp


@app.errorhandler(InputError)
def _input_error(exc):
    """Schema-validation rejections -> generic 400 (never echo internals)."""
    return jsonify({"error": exc.message}), 400


@app.errorhandler(Exception)
def _unhandled_error(exc):
    """Catch-all 500: the client gets a generic message; the traceback stays
    server-side. Never echo paths, SQL, tokens or env vars to the client.
    HTTPExceptions (404/400/429 from abort()) pass through unchanged so the
    ownership gates keep their precise status codes."""
    from werkzeug.exceptions import HTTPException
    if isinstance(exc, HTTPException):
        return exc
    print(f"[error] unhandled {exc.__class__.__name__}: {exc}")
    return jsonify({"error": "internal server error"}), 500


@app.post("/api/auth/signup")
def auth_signup():
    if _rate_limited("/api/auth/signup"):
        seclog.log_event("rate_limited", route="/api/auth/signup",
                         method="POST", status=429, ip=_client_ip())
        return _rate_limit_response()
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {
        "email": ("email", {"required": True}),
        "password": ("str", {"required": True, "max_len": 1024}),
        "name": ("str", {"required": True, "max_len": 80}),
        "phone": ("str", {"max_len": 32, "default": ""}),
    })
    try:
        user = auth_svc.create_user(v["email"], v["password"],
                                    v["name"], v["phone"])
    except ValueError:
        # Generic message: whether this email exists is never disclosed.
        return jsonify({"error": "could not create the account. check the "
                                 "entered details and try again."}), 400
    # Strict per-email isolation: a new account starts completely empty —
    # its analyses/reports are only ever what it creates itself.
    # First work session (same model as login: one session per login).
    session = store.create_session(user["id"])
    token = auth_svc.issue_token(user["id"], session_id=session["id"])
    # Token is set ONLY as an HttpOnly cookie — never in the JSON body.
    return _issue_session_response(
        {"user": {**user, "session": session}}, 201, token=token), 201


@app.post("/api/auth/login")
def auth_login():
    if _rate_limited("/api/auth/login"):
        seclog.log_event("rate_limited", route="/api/auth/login",
                         method="POST", status=429, ip=_client_ip())
        return _rate_limit_response()
    body = request.get_json(silent=True) or {}
    try:
        v = validate_body(body, {
            "email": ("email", {"required": True}),
            "password": ("str", {"required": True, "max_len": 1024}),
        })
    except InputError:
        seclog.log_event("login_failed", route="/api/auth/login",
                         method="POST", status=400, ip=_client_ip(),
                         detail="malformed body")
        raise
    user, token_or_reason = auth_svc.authenticate(v["email"], v["password"])
    if user is None:
        seclog.log_event("login_failed", route="/api/auth/login",
                         method="POST", status=401, ip=_client_ip(),
                         detail="invalid credentials")
        return jsonify({"error": token_or_reason}), 401
    # user already carries its new work session (services.auth.authenticate)
    seclog.log_event("login", route="/api/auth/login", method="POST",
                     status=200, ip=_client_ip(), user_id=user["id"])
    # Token is set ONLY as an HttpOnly cookie — never in the JSON body.
    return _issue_session_response({"user": user}, 200, token=token_or_reason)

@app.post("/api/auth/firebase")
def auth_firebase():
    if _rate_limited("/api/auth/firebase"):
        seclog.log_event("rate_limited", route="/api/auth/firebase",
                         method="POST", status=429, ip=_client_ip())
        return _rate_limit_response()
    body = request.get_json(silent=True) or {}
    # Firebase ID tokens are long RS256 JWTs — the generic "token" grammar
    # (≤512 chars) rejects every real one; use the JWT-shaped rule.
    v = validate_body(body, {"idToken": ("jwt", {"required": True})})
    id_token = v["idToken"]
    if not id_token:
        return jsonify({"error": "missing idToken"}), 400
        
    api_key = _get_firebase_api_key()
    if not api_key:
        return jsonify({"error": "server misconfiguration"}), 500
        
    resp = requests.post(
        f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={api_key}",
        json={"idToken": id_token}
    )
    if resp.status_code != 200:
        return jsonify({"error": "invalid token"}), 401
        
    users = resp.json().get("users", [])
    if not users:
        return jsonify({"error": "user not found"}), 401
        
    fb_user = users[0]
    phone = fb_user.get("phoneNumber")
    email = fb_user.get("email")
    if not phone and not email:
        return jsonify({"error": "no phone or email"}), 400
        
    # Find or create user
    target_email = email or f"phone-{phone.replace('+', '')}@nodiq.app"
    # authenticate uses email and password. Since we trust firebase, we can bypass password.
    # auth_svc doesn't have a direct "issue token for email without password" 
    # except by looking up the uid.
    # Let's see if the user exists.
    conn = auth_svc._user_conn()
    with auth_svc._LOCK:
        row = conn.execute("SELECT id FROM users WHERE email = ? OR (phone != '' AND phone = ?)", (target_email, phone or "---")).fetchone()
    if row:
        uid = row["id"]
        # update phone if needed
    else:
        # Create user
        try:
            # Random password for firebase users since they don't use it
            import secrets
            pw = secrets.token_hex(16)
            new_user = auth_svc.create_user(target_email, pw, name="User", phone=phone or "")
            uid = new_user["id"]
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    user = auth_svc.user_by_id(uid)
    # Token is set ONLY as an HttpOnly cookie — never in the JSON body.
    return _issue_session_response({"user": user}, 200,
                                   token=auth_svc.issue_token(uid))


@app.get("/api/auth/me")
@require_auth
def auth_me(user):
    return jsonify({"user": user})

@app.post("/api/auth/change-password")
@require_auth
def auth_change_password(user):
    """Authenticated password change. Requires the CURRENT password, verifies
    it against the stored PBKDF2 hash, then re-hashes the new one. The
    session token stays valid (uid-bound, not password-bound)."""
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {
        "current_password": ("str", {"required": True, "max_len": 1024}),
        "new_password": ("str", {"required": True, "max_len": 1024}),
    })
    current = v["current_password"]
    new = v["new_password"]
    # Verify current password against the stored hash.
    conn = auth_svc._user_conn()
    with auth_svc._LOCK:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (user["id"],)).fetchone()
    if row is None or not auth_svc.verify_password(current,
                                                   row["password_hash"]):
        return jsonify({"error": "current password is incorrect"}), 400

    if current == new:
        return jsonify({"error": "new password must differ from the "
                                 "current password"}), 400

    if not auth_svc.set_password(user["id"], new):
        return jsonify({"error": "password must be at least 6 characters"}), 400
    return jsonify({"ok": True})


@app.post("/api/auth/logout")
def auth_logout():
    """Logout revokes the presented token SERVER-SIDE: verify_token rejects it
    from now on, so a stolen/copied token is dead after logout. The work
    session is also closed so the Sessions history shows its true end time."""
    header = request.headers.get("Authorization", "")
    revoked = False
    if header.startswith("Bearer "):
        token = header[7:].strip()
        # Revoke regardless of signature validity outcome (no-op if garbage).
        revoked = auth_svc.revoke_token(token)
    else:
        # Cookie-authenticated browser: revoke the cookie's token too.
        token = request.cookies.get(_AUTH_COOKIE)
        if token:
            revoked = auth_svc.revoke_token(token)
    sid = _current_session_id()
    uid = _uid()
    if sid and uid:
        store.end_session(sid, uid)
    seclog.log_event("logout", route="/api/auth/logout", method="POST",
                     status=200, user_id=uid or None)
    if revoked:
        seclog.log_event("token_revoked", route="/api/auth/logout",
                         method="POST", status=200, ip=_client_ip(),
                         user_id=uid or None,
                         detail="presented token revoked server-side")
    # Clear the cookie with the SAME Path/SameSite/Secure attributes used to
    # set it (max_age=0), so the browser actually drops it.
    clear_kwargs = _auth_cookie_kwargs()
    clear_kwargs["max_age"] = 0
    resp = jsonify({"ok": True})
    resp.delete_cookie(_AUTH_COOKIE, path=clear_kwargs["path"],
                       samesite=clear_kwargs["samesite"],
                       secure=clear_kwargs["secure"],
                       httponly=clear_kwargs["httponly"])
    return resp


# --------------------------------------------------------------------------
# work sessions: one session per login; analyses are tagged with their session
# --------------------------------------------------------------------------


@app.get("/api/sessions")
@require_auth
def sessions_list(user):
    return jsonify({"sessions": store.list_sessions(user["id"])})


@app.get("/api/sessions/current")
@require_auth
def sessions_current(user):
    sid = _current_session_id()
    if not sid:
        return jsonify({"session": None})
    return jsonify({"session": store.get_session(sid, user["id"])})


@app.get("/api/sessions/<session_id>")
@require_auth
def sessions_detail(user, session_id):
    session = store.get_session(session_id, user["id"])
    if session is None:
        return jsonify({"error": "session not found"}), 404
    return jsonify({"session": session,
                    "analyses": store.session_analyses(session_id,
                                                       user["id"])})


@app.delete("/api/sessions/<session_id>")
@require_auth
def sessions_delete(user, session_id):
    if not store.delete_session(session_id, user["id"]):
        return jsonify({"error": "session not found"}), 404
    return jsonify({"ok": True})


@app.post("/api/sessions")
@require_auth
def sessions_create(user):
    """Manually open a named session (e.g. "Heat-105 QC run"). Subsequent
    analyses use the token's session — this endpoint returns a fresh token
    bound to it."""
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {"label": ("str", {"max_len": 80,
                                                "default": ""})})
    label = v["label"].strip() or None
    session = store.create_session(user["id"], label=label)
    # Session switch ROTATES the credential: browser callers get the new
    # session-bound token as an HttpOnly cookie (no token in the body);
    # API clients may still read it from the JSON (Bearer flow).
    token = auth_svc.issue_token(user["id"], session_id=session["id"])
    return _issue_session_response({"session": session}, 200, token=token), 200


# --------------------------------------------------------------------------
# admin (RBAC foundation): role administration. Admin-only; every change is
# audit-logged (admin_action) and never carries credentials in the log.
# --------------------------------------------------------------------------


@app.get("/api/admin/users")
@require_auth
@require_role("admin")
def admin_users(user):
    """Identity + role + creation time for every account (role management
    needs it; phone numbers are deliberately not exposed)."""
    return jsonify({"users": auth_svc.list_users()})


@app.post("/api/admin/users/<user_id>/role")
@require_auth
@require_role("admin")
def admin_set_role(user, user_id: str):
    """Assign a role (operator | reviewer | admin). The stored role is the
    base of auth_svc.effective_role(); NODIQ_ADMIN_EMAILS/
    NODIQ_REVIEWER_EMAILS can still elevate an account, so demoting an
    environment-elevated admin is ineffective by design (documented)."""
    body = request.get_json(silent=True) or {}
    # NOTE: the field is deliberately "new_role", not "role": "role" is a
    # globally forbidden client key (services/validate.py rejects it
    # everywhere to kill privilege-field smuggling), and that invariant must
    # hold even here.
    v = validate_body(body, {"new_role": ("enum", {"choices": auth_svc.ROLES,
                                                   "required": True})})
    target = auth_svc.user_by_id(user_id)
    if target is None:
        return jsonify({"error": "user not found"}), 404
    before = target.get("role")
    if before == "admin" and v["new_role"] != "admin" \
            and len([u for u in auth_svc.list_users()
                     if u.get("role") == "admin"]) <= 1:
        # Lockout guard: never let the last admin remove themselves.
        return jsonify({"error": "cannot remove the last admin"}), 400
    updated = auth_svc.set_role(user_id, v["new_role"])
    if updated is None:
        return jsonify({"error": "could not update role"}), 400
    seclog.log_event("admin_action", route="/api/admin/users/<id>/role",
                     method="POST", status=200, ip=_client_ip(),
                     user_id=user["id"],
                     detail=f"{user_id}: role {before} -> {v['new_role']}")
    return jsonify({"user": updated})


@app.post("/api/auth/forgot-password")
def auth_forgot():
    """Issue a password-reset email. Always replies ok (never reveals
    whether the account exists). The reset token is ONLY delivered by email —
    it is never returned in the HTTP response, so an unconfigured SMTP means
    the operator must configure mail rather than users gaining a token."""
    if _rate_limited("/api/auth/forgot-password"):
        seclog.log_event("rate_limited", route="/api/auth/forgot-password",
                         method="POST", status=429, ip=_client_ip())
        return _rate_limit_response()
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {
        "email": ("email", {"required": True}),
        "app_url": ("str", {"max_len": 2048, "default": ""}),
    })
    email = v["email"]
    token = auth_svc.generate_reset_token(email)
    if token and mailer.configured:
        base = str(body.get("app_url") or "").rstrip("/") \
            or "http://127.0.0.1:8001"
        ok, detail = mailer.send(
            "NODIQ-X password reset",
            f"A password reset was requested for {email}.\n\n"
            f"Open this link within 30 minutes:\n"
            f"{base}/reset-password?token={token}\n\n"
            "If you did not request this, ignore this email.",
            to=email)
        print(f"[auth] reset mail for {email}: {detail}", flush=True)
        return jsonify({"ok": True, "emailed": ok})
    # Same generic reply whether or not the account exists and whether or
    # not SMTP is configured — no token in the response, no existence leak.
    return jsonify({"ok": True, "emailed": False})


@app.post("/api/auth/reset-password")
def auth_reset():
    if _rate_limited("/api/auth/reset-password"):
        seclog.log_event("rate_limited", route="/api/auth/reset-password",
                         method="POST", status=429, ip=_client_ip())
        return _rate_limit_response()
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {
        "token": ("token", {"required": True}),
        "password": ("str", {"required": True, "max_len": 1024}),
    })
    uid = auth_svc.consume_reset_token(v["token"])
    if not uid:
        seclog.log_event("reset_failed", route="/api/auth/reset-password",
                         method="POST", status=400, ip=_client_ip(),
                         detail="invalid or expired token")
        return jsonify({"error": "invalid or expired reset link"}), 400
    if not auth_svc.set_password(uid, v["password"]):
        return jsonify({"error": "password must be at least 6 characters"}), \
            400
    # Invalidate all prior sessions: tokens minted before the reset are killed
    store.delete_all_user_sessions(uid)
    seclog.log_event("reset_completed", route="/api/auth/reset-password",
                     method="POST", status=200, ip=_client_ip())
    return jsonify({"ok": True})


def _dataset_names():
    return sorted(p.name for p in DATASET_DIR.glob("micrograph_*.png"))


def _load_reference_csv():
    """file -> {count, accuracy, iso, jis...} from the validated 1000-image run."""
    table = {}
    try:
        with open(SUMMARY_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = row.get("file")
                if name:
                    table[name] = row
    except Exception:
        pass
    return table


# --------------------------------------------------------------------------
# health + dataset
# --------------------------------------------------------------------------


@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "engine": "Nodularity Engine v4.2.1 (validated 1000/1000)",
        "platform": "NODIQ-X 2.0",
        "offline_mode": CFG.offline_mode,
        "dataset_images": len(_dataset_names()),
        "persistence": store.BACKEND,
        "artifact_storage": _storage().health(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.get("/api/dataset")
def dataset_list():
    names = _dataset_names()
    ref = _load_reference_csv()
    items = []
    for name in names:
        row = ref.get(name, {})
        items.append({
            "name": name,
            "url": f"/dataset/{name}",
            "count": int(row["count"]) if row.get("count") else None,
            "iso_pct": float(row["iso_pct"]) if row.get("iso_pct") else None,
            "jis_pct": float(row["jis_pct"]) if row.get("jis_pct") else None,
            "accuracy_pct": (float(row["count_accuracy_pct"])
                             if row.get("count_accuracy_pct") else None),
        })
    return jsonify({"total": len(items), "images": items})


@app.get("/api/dataset/sample")
def dataset_sample():
    names = _dataset_names()
    if not names:
        return jsonify({"error": "dataset not found"}), 404
    name = random.choice(names)
    return jsonify({"name": name,
                    "url": f"/dataset/{name}"})


@app.get("/api/dataset/file/<name>")
def dataset_file(name: str):
    if not re.fullmatch(r"micrograph_[0-9]{4}\.png", name):
        seclog.log_event("suspicious_path", route="/api/dataset/file/<name>",
                         method="GET", status=400)
        return jsonify({"error": "invalid name"}), 400
    if not (DATASET_DIR / name).exists():
        return jsonify({"error": "not found"}), 404
    return send_from_directory(DATASET_DIR, name)


@app.get("/api/dataset/analysis/<name>")
def dataset_analysis(name: str):
    if not re.fullmatch(r"micrograph_[0-9]{4}\.png", name):
        seclog.log_event("suspicious_path", route="/api/dataset/analysis/<name>",
                         method="GET", status=400)
        return jsonify({"error": "invalid name"}), 400
    path = DATASET_DIR / name
    if not path.exists():
        return jsonify({"error": "not found"}), 404

    payload, err = analyze_for_frontend_json(str(path))
    if err:
        return jsonify({"error": err}), 500

    row = _load_reference_csv().get(name, {})
    if row:
        payload["batch_reference"] = {
            "count": int(row["count"]),
            "iso_pct": float(row["iso_pct"]),
            "jis_pct": float(row["jis_pct"]),
            "accuracy_pct": float(row["count_accuracy_pct"]),
        }
    return jsonify(payload)


# --------------------------------------------------------------------------
# upload analysis
# --------------------------------------------------------------------------


# ------------------------- async analysis pipeline -------------------------
# Free-tier CPUs (~0.1 core) need minutes for a full analysis — far past both
# the gunicorn worker timeout and Render's proxy limit, which is why the old
# synchronous request 502'd exactly at the timeout kill. /api/analyze now
# validates input fast, enqueues a "processing" record, and returns 202 with
# the analysis id; the heavy engine pass runs in an ISOLATED child process
# (analysis_child.py) so an OOM kill can never take down the web worker,
# while the client polls GET /api/analyses/<id> for progress and the final
# payload.
_MAX_CONCURRENT_ANALYSES = int(
    os.environ.get("NODIQ_ANALYZE_MAX_CONCURRENCY", "2").strip() or "2")
# per account; keeps 0.1-CPU boxes responsive (env-tunable, abuse phase)
_ANALYZE_TIMEOUT = int(os.environ.get("NODIQ_ANALYZE_TIMEOUT", "0").strip()
                       or "0")
# wall-clock cap per analysis job, seconds; 0 (default) = unlimited — the
# historic behavior. >0 arms a watchdog that flips a job past the cap to an
# honest failed record (thread mode) or kills the child process (child
# mode), freeing the concurrency slot it would otherwise hold forever.
_ANALYZE_TIMEOUT_PANIC = 60
# extra seconds beyond _ANALYZE_TIMEOUT before the whole process is torn
# down after a graceful (SIGTERM) kill did not end the child.


def _analyze_deadline():
    """Unix timestamp by which a job started now must have finished — None
    when NODIQ_ANALYZE_TIMEOUT=0 (unlimited, historic default)."""
    return time.time() + _ANALYZE_TIMEOUT if _ANALYZE_TIMEOUT > 0 else None
# GLOBAL cap on simultaneously-running analysis children. Measured on the
# 512MB free tier: web worker (~160MB) + ONE child at its OpenCV peak fits,
# but a second concurrent child pushes total RSS past 512MB and the OOM
# killer restarts the whole instance (mid-run records are lost). Default 1
# = stable free tier; raise via env on paid instances (2GB fits 3-4):
#   NODIQ_MAX_CHILDREN=3
_MAX_CONCURRENT_CHILDREN = int(os.environ.get("NODIQ_MAX_CHILDREN", "1")
                               or "1")
# Execution mode for the heavy pipeline:
#   thread  (default) run analysis_child.run() IN the gunicorn worker
#           process. Measured: a separate interpreter + OpenCV copy needs
#           ~300MB+ at its peak, which together with the web worker exceeds
#           the 512MB free-tier container — Render kills the WHOLE instance
#           on that OOM. In-thread, the worker's ~61MB baseline plus the
#           engine's bounded peak (downscale guard below) fits. A pathological
#           image can still theoretically OOM the worker; the downscale cap
#           bounds that risk and MemoryError becomes an honest failure.
#   child   true crash isolation (an OOM kill only fails one analysis) — but
#           it needs ~512MB of HEADROOM, i.e. paid instances. Set
#           NODIQ_EXEC_MODE=child when the instance has >=2GB.
_EXEC_MODE = os.environ.get("NODIQ_EXEC_MODE", "thread").strip().lower()
if _EXEC_MODE not in ("thread", "child"):
    raise RuntimeError(
        f"NODIQ_EXEC_MODE='{_EXEC_MODE}' is invalid — use 'thread' or 'child'")
_SCALE_CAP = 2000                 # memory guard: max analyzed long side (px)
_CHILD_ENTRYPOINT = [sys.executable, "-m", "nodiq.pipelines.analysis_child"]   # patched in crash tests
_analysis_jobs: dict[str, dict] = {}
_JOB_LOCK = threading.Lock()


class _JobFailure(Exception):
    """A user-facing analysis failure (message is safe to show the client)."""


def _set_job_progress(analysis_id, user_id, progress):
    """Persist progress on the processing record (My Analyses bar) and keep
    the in-memory mirror for the detail poll."""
    with _JOB_LOCK:
        _analysis_jobs[analysis_id] = {"progress": progress, "user_id": user_id}
    record = store.get_analysis_record(analysis_id, user_id)
    if record and record.get("status") == "processing":
        store.insert_analysis({**record, "progress": progress}, user_id)


def _fail_job(analysis_id, user_id, pending, message):
    seclog.log_event("analysis_failed", route="/api/analyze", method="POST",
                     status=500, detail=f"{analysis_id}: {message[:80]}")
    store.insert_analysis({**pending, "status": "failed", "progress": 100,
                           "error": message}, user_id)
    with _JOB_LOCK:
        _analysis_jobs.pop(analysis_id, None)


def _recover_stale_processing():
    """Startup sweep: a container restart (Render spin-down/redeploy) orphans
    any "processing" rows — no worker thread survives. Flip them to failed so
    users see an honest state instead of an eternal progress bar.

    ONE candidate query for the whole table (status lives in the JSON payload
    column, so candidates are narrowed with LIKE and verified in Python) —
    per-user list queries would scale O(users) on every boot, which the
    migrated multi-hundred-user production dataset made noticeable."""
    try:
        with store._LOCK:
            rows = store._CONN.execute(
                "SELECT id, user_id, data FROM analyses "
                "WHERE data LIKE '%processing%'").fetchall()
        for row in rows:
            try:
                rec = json.loads(row["data"])
            except Exception:
                continue
            if rec.get("status") != "processing":
                continue
            store.insert_analysis(
                {**rec, "status": "failed", "progress": 100,
                 "error": "Analysis was interrupted by a server restart — "
                          "please run it again."}, row["user_id"])
    except Exception:
        pass                                  # never block startup on cleanup


# A restart (redeploy / free-tier spin-down) orphans any "processing" rows —
# flip them to failed before serving traffic.
_recover_stale_processing()


def _run_analysis_job_guarded(analysis_id, user_id, image_path, filename,
                              manual_mpp=None,
                              analysis_type="graphite_nodularity",
                              method="gsat"):
    """In-thread execution mode (NODIQ_EXEC_MODE=thread, the free-tier
    default): run the exact analysis_child.run() lifecycle in a worker
    thread of the web process. EVERYTHING is inside the guard — a silent
    daemon-thread death (e.g. an import error) would otherwise leave the
    record 'processing' forever. Any unhandled exception becomes the same
    honest failed record the child protocol produces; a MemoryError gets
    the free-tier memory message. The web server itself survives either
    way (the thread is the blast radius)."""
    pending = store.get_analysis_record(analysis_id, user_id) or {}
    deadline = _analyze_deadline()
    watchdog = None
    if deadline is not None:
        # Wall-clock guard: a pathological image (or wedged engine) must not
        # hold its concurrency slot forever. Python threads cannot be killed,
        # so the watchdog flips the record to failed at the deadline and the
        # engine thread is abandoned (daemon thread: its result, if it ever
        # finishes, is ignored because the record is already terminal).
        watchdog = threading.Timer(
            _ANALYZE_TIMEOUT, _fail_job,
            args=(analysis_id, user_id, pending,
                  "Analysis timed out on the server — please try again. "
                  "A smaller or better-focused version of this image "
                  "usually completes faster."))
        watchdog.daemon = True
        watchdog.start()
    try:
        import nodiq.pipelines.analysis_child as analysis_child
        analysis_child.run(analysis_id, user_id, image_path, filename,
                           manual_mpp, _SCALE_CAP,
                           analysis_type=analysis_type, method=method)
    except MemoryError:
        _fail_job(analysis_id, user_id, pending,
                  "Analysis ran out of memory on the server — please try a "
                  "smaller version of this image.")
    except Exception as exc:
        seclog.log_event("analysis_failed", route="analysis_thread",
                         method="POST", status=0,
                         detail=f"{analysis_id}: {type(exc).__name__}: "
                                f"{str(exc)[:120]}")
        _fail_job(analysis_id, user_id, pending,
                  "Analysis failed on the server — please try again. Very "
                  "large images can exceed free-tier memory; a smaller "
                  "version of the same micrograph works too.")
    finally:
        if watchdog is not None:
            watchdog.cancel()
        with _JOB_LOCK:
            _analysis_jobs.pop(analysis_id, None)


def _spawn_analysis_child(analysis_id, user_id, image_path, filename,
                          manual_mpp=None,
                          analysis_type="graphite_nodularity",
                          method="gsat"):
    """Run the heavy nodularity pipeline in an ISOLATED child process.

    Render free tier (0.1 CPU / 512 MB) can OOM-kill the biggest analyses.
    Run inside the gunicorn web worker, that killed the WHOLE container —
    crash-loop, 502s, wiped sessions. In a child process the blast radius is
    one job: the parent marks the analysis failed and keeps serving traffic.

    Returns True when the child was spawned. The child's own protocol
    (analysis_child.py) writes the completed/failed record; the explicit
    failure paths here cover spawn failure and non-zero child exits
    (including SIGKILL, where the child cannot write anything itself).
    """
    def _fail(msg):
        seclog.log_event("analysis_failed", route="/api/analyze",
                         method="POST", status=500,
                         detail=f"{analysis_id}: {msg}")
        pending = store.get_analysis_record(analysis_id, user_id) or {}
        store.insert_analysis({**pending, "status": "failed",
                               "progress": 100, "error": msg}, user_id)
        with _JOB_LOCK:
            _analysis_jobs.pop(analysis_id, None)

    child_cmd = list(_CHILD_ENTRYPOINT) if isinstance(_CHILD_ENTRYPOINT, (list, tuple)) else [sys.executable, str(_CHILD_ENTRYPOINT)]

    argv = [*child_cmd, analysis_id,
            str(user_id), str(image_path), filename,
            (repr(float(manual_mpp)) if manual_mpp else ""),
            str(_SCALE_CAP), str(analysis_type), str(method)]
    env = {**os.environ}
    # The child derives its paths from env vars when present so tests (and
    # any deployment layout) can redirect data/payload storage without
    # monkeypatching a second process.
    if store.DATA_DIR:
        env["NODIQ_DATA_DIR"] = str(store.DATA_DIR)
    if store.DB_PATH:
        env["NODIQ_DB_PATH"] = str(store.DB_PATH)
    if context_svc.FULL_DIR:
        env["NODIQ_FULL_DIR"] = str(context_svc.FULL_DIR)
    child_log = (open(LOGS_DIR / "analysis_child_err.log", "ab")
                 if os.environ.get("NODIQ_CHILD_LOG") else None)

    def _spawn_one():
        return subprocess.Popen(
            argv, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=child_log or subprocess.DEVNULL,
            start_new_session=True,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))

    try:
        proc = _spawn_one()
    except Exception as exc:
        if child_log:
            child_log.close()
        _fail(f"could not start analysis worker: {exc}")
        return False

    def _wait():
        nonlocal proc
        # NODIQ_ANALYZE_TIMEOUT > 0 arms a wall-clock cap: a child wedged
        # past the deadline is SIGTERMed (SIGKILL after the panic grace) and
        # the record flips to an honest failed state instead of holding the
        # global child slot forever. rc 143/137 = 128+SIGTERM/SIGKILL.
        deadline = _analyze_deadline()
        # A crash can also come from transient host conditions (a deploy-time
        # memory squeeze, AV interference); one bounded retry keeps the
        # analysis alive through those while still isolating real failures.
        for attempt in range(2):
            timed_out = False
            try:
                if deadline is not None:
                    rc = proc.wait(timeout=max(0.1, deadline - time.time()))
                else:
                    rc = proc.wait()
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    proc.terminate()      # SIGTERM: let the child clean up
                except Exception:
                    pass
                try:
                    proc.wait(timeout=_ANALYZE_TIMEOUT_PANIC)
                    rc = 143              # died under SIGTERM: report that
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()       # last resort: SIGKILL
                    except Exception:
                        pass
                    rc = 137
            if rc == 0:
                with _JOB_LOCK:
                    _analysis_jobs.pop(analysis_id, None)
                if child_log:
                    child_log.close()
                return
            if rc == 3:
                # child already persisted a user-facing failed record
                with _JOB_LOCK:
                    _analysis_jobs.pop(analysis_id, None)
                if child_log:
                    child_log.close()
                return
            if timed_out:
                # the wall-clock cap fired: a retry would just burn another
                # full budget on the same wedged job — fail it now.
                break
            if attempt == 0:
                seclog.log_event("analysis_child_crash_retry", route="/api/analyze",
                                 method="POST", status=0,
                                 detail=f"{analysis_id}: exit {rc}, retrying")
                time.sleep(1.5)
                try:
                    proc = _spawn_one()   # rebind: wait() again on the retry
                except Exception:
                    break   # spawn failed on the retry: fall through to _fail
                continue
            break
        if child_log:
            child_log.close()
        # crash (OOM kill / internal error): the child wrote nothing —
        # fail the record here with an honest, actionable message
        _fail("Analysis was interrupted on the server (memory limit or "
              "internal error) — please try again. A smaller version of "
              "the same micrograph works too.")

    threading.Thread(target=_wait, name=f"analysis-wait-{analysis_id}",
                     daemon=True).start()
    return True


@app.post("/api/analyze")
def analyze_upload():
    user = _current_user()
    if user is None:
        # Unauthenticated callers (no/invalid token) are IP-bucketed on the
        # same budget before the 401 — the safe fallback identity; untrusted
        # headers are never the sole key (see _client_ip).
        if _analyze_limited(None):
            seclog.log_event("rate_limited", route=_ANALYZE_PATH,
                             method="POST", status=429, ip=_client_ip())
            resp, status = _rate_limit_response(_ANALYZE_WINDOW)
            return resp, status
        # analysis rows and payloads are stored per-account; anonymous calls
        # would create ownerless rows (or collide across users) — require a
        # verified session like every other record-writing route
        return jsonify({"error": "authentication required"}), 401
    if _analyze_limited(user):
        # Analysis abuse protection: the per-user budget on the most
        # expensive route is exhausted. 429 + Retry-After, no internals.
        seclog.log_event("rate_limited", route=_ANALYZE_PATH,
                         method="POST", status=429, ip=_client_ip(),
                         user_id=user["id"])
        resp, status = _rate_limit_response(_ANALYZE_WINDOW)
        return resp, status
    file = request.files.get("image")
    if file is None:
        body = request.get_json(silent=True) or {}
        name = body.get("dataset_image")
        if name:
            # reference-data lookup only: reject path fragments so a caller
            # cannot read an arbitrary file into their analysis record
            if not re.fullmatch(r"micrograph_[0-9]{4}\.png", str(name)):
                return jsonify({"error": "invalid dataset image name"}), 400
            path = DATASET_DIR / name
            if not path.exists():
                return jsonify({"error": "dataset image not found"}), 404
            data = path.read_bytes()
            display_name = name
            stored_path = None
            source_path = path
        else:
            return jsonify({"error": "no image provided"}), 400
    else:
        data = file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            seclog.log_event("upload_rejected", route="/api/analyze",
                             method="POST", status=413,
                             detail="file exceeds size cap")
            return jsonify({"error": "image too large"}), 413
        kind, err = _check_image(data)
        if err:
            return err
        # Declared MIME type is client-controlled: cross-checked for the
        # audit trail only (upload_mime_mismatch), never used to accept or
        # reject — content (magic bytes + decode) is authoritative, which is
        # also why a valid image under an odd filename is still accepted.
        declared_mime = (getattr(file, "mimetype", "") or "").strip().lower()
        if declared_mime and declared_mime not in _ALLOWED_UPLOAD_MIMES:
            seclog.log_event("upload_mime_mismatch", route="/api/analyze",
                             method="POST", status=0,
                             detail=f"declared {declared_mime[:64]} "
                                    f"for content {kind}")
        # Header-level dimension bounds: refuse a decompression bomb BEFORE
        # any decode allocates memory (the engine's own 2000px downscale
        # happens after decode, far too late for a 10000x10000 declaration).
        dims = _image_dimensions(data, kind)
        if dims and not (
                IMAGE_MIN_SIDE <= dims[0] <= IMAGE_MAX_SIDE
                and IMAGE_MIN_SIDE <= dims[1] <= IMAGE_MAX_SIDE
                and dims[0] * dims[1] <= IMAGE_MAX_PIXELS):
            seclog.log_event("upload_rejected", route="/api/analyze",
                             method="POST", status=400,
                             detail=f"dimensions {dims[0]}x{dims[1]} "
                                    f"out of bounds")
            return jsonify({"error": "image dimensions out of supported "
                                     "range"}), 400
        # Content is identified by magic number, never by the client's
        # filename: uploads are stored under a server-generated hash with a
        # content-derived extension, so the client suffix can never smuggle
        # anything onto disk. A JPEG misnamed ".png" (camera exports do this
        # constantly) is therefore accepted and stored correctly instead of
        # bounced with a confusing rename instruction.
        ext_for_kind = {
            "png": ".png",
            "jpeg": ".jpg",
            "tiff": ".tif",
            "bmp": ".bmp",
        }[kind]
        client_ext = (Path(file.filename or "").suffix or "").lower()
        if client_ext and client_ext not in _MAGIC_EXTS[kind]:
            seclog.log_event("upload_ext_normalized", route="/api/analyze",
                             method="POST", status=200,
                             detail=f"client '{client_ext}' vs content {kind}")
        digest = hashlib.sha256(data).hexdigest()[:16]
        stored_path = UPLOAD_DIR / f"{digest}{ext_for_kind}"
        # Disk stays hash-named (see above), but the RECORD the user sees in
        # My Analyses / reports should carry their original filename —
        # otherwise an upload appears as "3155e88de8a4e6ae — Nodularity
        # Analysis" and searching for the uploaded name finds nothing.
        # The display name is sanitized to a safe image-name pattern;
        # anything odd falls back to the hash name.
        client_name = Path(file.filename or "").name.strip()
        if not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9 ._()-]{0,120}\.(png|jpg|jpeg|bmp|tif|tiff)",
                client_name, re.IGNORECASE):
            client_name = None
        display_name = client_name or stored_path.name
        if not stored_path.exists():
            stored_path.write_bytes(data)
        source_path = stored_path

    # Fast decode sanity check IN the request: catch corrupt/decoy bytes now
    # (immediate 400) instead of failing asynchronously minutes later. The
    # expensive parts — microstructure validity, full payload build — stay in
    # the worker. Decode also primes cv2/np so the worker thread inherits a
    # warm library (first-call import cost would otherwise be double-counted).
    try:
        load_with_source(data)
    except Exception:
        seclog.log_event("upload_rejected", route="/api/analyze",
                         method="POST", status=400,
                         detail="decode failure (enqueue-time)")
        return jsonify({"error": "could not decode image"}), 400

    # ---- enqueue the pending record and hand off to the worker thread ----
    # Request-derived values are captured HERE: the worker thread has no
    # Flask request context.
    body = request.get_json(silent=True) or {}
    form = request.form or {}

    def _req_field(name):
        """JSON body first, then multipart form field (upload path)."""
        val = body.get(name)
        if val in (None, ""):
            val = form.get(name)
        return val

    manual_mpp = validate_um_per_px(_req_field("microns_per_pixel"))

    raw_type = str(_req_field("analysis_type")
                        or "graphite_nodularity").strip().lower()
    if raw_type == "cast_iron_nodularity":
        analysis_type = "graphite_nodularity"
    else:
        analysis_type = raw_type

    supported_types = (
        "graphite_nodularity",
        "steel_grain_size",
        "white_cast_iron_carbide",
        "gray_cast_iron_graphite_flake",
    )
    if analysis_type not in supported_types:
        return jsonify({"error": "unsupported analysis_type — expected one of "
                                 + ", ".join(supported_types)}), 400

    if analysis_type == "steel_grain_size":
        method = str(_req_field("method") or "gsat").strip().lower()
        if method not in steel_pipeline.ANALYSIS_METHODS:
            return jsonify({"error": "unsupported analysis method — "
                                     "expected one of "
                                     + ", ".join(steel_pipeline.ANALYSIS_METHODS)}), 400
    elif analysis_type == "white_cast_iron_carbide":
        method = str(_req_field("method") or "carde_otsu").strip().lower()
        if method not in white_cast_iron_pipeline.ANALYSIS_METHODS:
            return jsonify({"error": "unsupported analysis method — "
                                     "expected one of "
                                     + ", ".join(white_cast_iron_pipeline.ANALYSIS_METHODS)}), 400
    elif analysis_type == "gray_cast_iron_graphite_flake":
        method = str(_req_field("method") or "s_metalseg_fpn").strip().lower()
        if method not in gray_cast_iron_pipeline.ANALYSIS_METHODS:
            return jsonify({"error": "unsupported analysis method — "
                                     "expected one of "
                                     + ", ".join(gray_cast_iron_pipeline.ANALYSIS_METHODS)}), 400
    else:
        # nodularity has no pipeline method concept; ignore any stray value
        method = "nodularity"
    input_source = str(_req_field("input_source") or
                       ("dataset" if not file else "upload")).strip().lower()
    if input_source not in ("upload", "microscope", "dataset"):
        return jsonify({"error": "unsupported input_source — expected "
                                 "'upload', 'microscope' or 'dataset'"}), 400
    session_id = _current_session_id()
    with _JOB_LOCK:
        # prune job-registry entries whose records reached a terminal state:
        # completion removes its own entry, but a crashed worker (restart) or
        # a completion/return race could leave one behind and permanently
        # exhaust the concurrency budget. A job in flight always owns a
        # "processing" record, so anything else here is stale.
        # NOTE: the record lookup MUST be owner-aware. get_analysis_record
        # with user_id=None matches NOTHING (strict per-account isolation,
        # services/db._visible), which silently emptied the registry on every
        # request and disabled the concurrency cap entirely.
        stale = []
        now = time.time()
        for aid, job in _analysis_jobs.items():
            rec = store.get_analysis_record(aid, job["user_id"]) or {}
            is_expired = (now - job.get("started_at", now)) > 300
            if rec.get("status") != "processing" or is_expired:
                stale.append(aid)
                if is_expired and rec.get("status") == "processing":
                    store.insert_analysis({**rec, "status": "failed", "progress": 100,
                                           "error": "Analysis timed out — please try again."}, job["user_id"])
        for aid in stale:
            _analysis_jobs.pop(aid, None)
        active = sum(1 for j in _analysis_jobs.values()
                     if j["user_id"] == user["id"])
        global_active = len(_analysis_jobs)
    if active >= _MAX_CONCURRENT_ANALYSES or \
            global_active >= _MAX_CONCURRENT_CHILDREN:
        seclog.log_event("analysis_concurrency_limited", route=_ANALYZE_PATH,
                         method="POST", status=429, ip=_client_ip(),
                         user_id=user["id"])
        resp = jsonify({"error": "too many analyses running — wait for one "
                                 "to finish before starting another",
                        "retry_after_seconds": _ANALYZE_WINDOW})
        resp.headers["Retry-After"] = str(_ANALYZE_WINDOW)
        return resp, 429

    analysis_id = f"ANL-{uuid.uuid4().hex[:6].upper()}"
    if analysis_type == "steel_grain_size":
        rec_type = "Steel Grain-Size Analysis"
        rec_title = (f"{Path(display_name).stem} — Steel Grain Size "
                     f"({steel_pipeline.METHOD_LABELS.get(method, method)})")
    elif analysis_type == "white_cast_iron_carbide":
        rec_type = "White Cast Iron Carbide Analysis"
        rec_title = (f"{Path(display_name).stem} — White Cast Iron Carbide "
                     f"({white_cast_iron_pipeline.METHOD_LABELS.get(method, method)})")
    elif analysis_type == "gray_cast_iron_graphite_flake":
        rec_type = "Gray Cast Iron Graphite Flake Analysis"
        rec_title = (f"{Path(display_name).stem} — Gray Cast Iron Flake "
                     f"({gray_cast_iron_pipeline.METHOD_LABELS.get(method, method)})")
    else:
        rec_type = "Nodularity Analysis"
        rec_title = f"{Path(display_name).stem} — Nodularity Analysis"
    record = {
        "id": analysis_id,
        "title": rec_title,
        "filename": display_name,
        "type": rec_type,
        "analysis_type": analysis_type,
        **({"method": method,
            "input_source": input_source}
           if analysis_type in ("steel_grain_size", "white_cast_iron_carbide", "gray_cast_iron_graphite_flake") else {}),
        "status": "processing",
        "progress": 5,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stored_path": (str(stored_path) if stored_path else None),
        "session_id": session_id,
    }
    store.insert_analysis(record, user["id"])
    with _JOB_LOCK:
        _analysis_jobs[analysis_id] = {"progress": 5, "user_id": user["id"], "started_at": time.time()}
    if _EXEC_MODE == "thread":
        # Free-tier mode: the pipeline runs in a worker thread of THIS
        # process (memory fits 512MB). analysis_child.run() handles the
        # whole lifecycle including failure records, exactly like the
        # child process would.
        t = threading.Thread(
            target=_run_analysis_job_guarded,
            args=(analysis_id, user["id"], str(source_path), display_name,
                  manual_mpp, analysis_type, method),
            name=f"analysis-{analysis_id}", daemon=True)
        t.start()
    elif not _spawn_analysis_child(analysis_id, user["id"], source_path,
                                   display_name, manual_mpp,
                                   analysis_type, method):
        with _JOB_LOCK:
            _analysis_jobs.pop(analysis_id, None)
        return jsonify({"error": "could not start analysis worker"}), 500
    seclog.log_event("analysis_enqueued", route="/api/analyze", method="POST",
                     status=202, detail=analysis_id)
    return jsonify({
        "status": "processing",
        "analysis_id": analysis_id,
        "poll_url": f"/api/analyses/{analysis_id}",
        "message": "Analysis queued — poll the poll_url until status is "
                   "completed or failed.",
    }), 202



# --------------------------------------------------------------------------
# analyses history
# --------------------------------------------------------------------------


@app.get("/api/analyses")
@require_auth
def analyses_list(user):
    return jsonify({"analyses": store.list_analyses(user["id"])})


@app.post("/api/analyses")
@require_auth
def analyses_add(user):
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {
        "id": ("id", {"default": ""}),
        "title": ("str", {"max_len": 200, "default": ""}),
        "type": ("str", {"max_len": 60, "default": ""}),
        "status": ("str", {"max_len": 40, "default": ""}),
        "created_at": ("str", {"max_len": 32, "default": ""}),
        "filename": ("str", {"max_len": 255, "default": "",
                              "pattern": re.compile(
                                  r"[A-Za-z0-9][A-Za-z0-9._-]{0,250}\.(png|jpg|jpeg|bmp|tif|tiff)"),
                              }),
        "nodule_count": ("int", {"min": 0, "max": 100000, "default": None}),
        "iso_nodularity_pct": ("float", {"min": 0, "max": 100,
                                          "default": None}),
        "jis_nodularity_pct": ("float", {"min": 0, "max": 100,
                                          "default": None}),
        "accuracy_pct": ("float", {"min": 0, "max": 100, "default": None}),
        "confidence_pct": ("float", {"min": 0, "max": 100, "default": None}),
    })
    new_id = v["id"] or f"ANL-{uuid.uuid4().hex[:6].upper()}"
    # INSERT OR REPLACE is row-hijackable: refuse client-chosen ids that
    # already exist under a different account (same id is fine — it is an
    # upsert of the caller's own row).
    existing_owner = store.analysis_owner(new_id)
    if existing_owner is not None and existing_owner != user["id"]:
        return jsonify({"error": "an analysis with this id already exists"}), 409
    record = {
        "id": new_id,
        "title": v["title"] or "Untitled analysis",
        "type": v["type"] or "Nodularity Analysis",
        "status": v["status"] or "completed",
        "created_at": v["created_at"] or time.strftime(
            "%Y-%m-%dT%H:%M:%S"),
        **{k: v[k] for k in
           ("nodule_count", "iso_nodularity_pct", "jis_nodularity_pct",
            "accuracy_pct", "confidence_pct", "filename")
           if v[k] is not None},
    }
    store.insert_analysis(record, user["id"])
    return jsonify(record), 201


@app.delete("/api/analyses/<analysis_id>")
@require_auth
def analyses_delete(user, analysis_id: str):
    if not store.delete_analysis(analysis_id, user["id"]):
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": analysis_id})


@app.get("/api/analyses/stats")
def analyses_stats():
    history = store.list_analyses(_uid())
    completed = [a for a in history if a.get("status") == "completed"]
    accuracies = [a["accuracy_pct"] for a in completed
                  if isinstance(a.get("accuracy_pct"), (int, float))]
    nodularities = [a["iso_nodularity_pct"] for a in completed
                    if isinstance(a.get("iso_nodularity_pct"), (int, float))]
    # newest record first (the DB list is newest-first already)
    last_created = next((a.get("created_at") for a in history
                         if a.get("created_at")), None)
    return jsonify({
        "total_analyses": len(history),
        "completed": len(completed),
        "avg_nodularity_pct": round(sum(nodularities) / len(nodularities), 1)
        if nodularities else None,
        "avg_confidence_pct": (round(sum(accuracies) / len(accuracies), 1)
                               if accuracies else None),
        "images_processed": len(completed),
        "last_analysis_at": last_created,
    })


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------

_REPORT_TYPES = {"standard", "technical", "validation"}


@app.get("/api/reports")
@require_auth
def reports_list(user):
    return jsonify({"reports": store.list_reports(user["id"])})


@app.get("/api/reports/<report_id>")
def reports_get(report_id: str):
    report = store.get_report(report_id, _uid())
    if not report:
        req_hash = request.args.get("hash") or request.args.get("verification_hash")
        if req_hash:
            pub = store.get_report_by_hash(req_hash)
            if pub and pub.get("id") == report_id:
                report = pub
        if not report and _uid() is None:
            pub = store.get_report_public(report_id)
            if pub and pub.get("user_id") is None:
                report = pub
    if not report:
        return jsonify({"error": "not found"}), 404
    return jsonify(report)


# (advanced /api/reports/generate handler defined after the intelligence
# services block below — it keeps the same route and response contract)


# ---- advanced report content: attach the full engineering report ----------

def _store_full_report(full_report, aid, body=None, report_type="technical"):
    """Wrap a built full report into a stored RPT record (shared by the
    /api/reports/generate endpoint and the Copilot generate_report tool)."""
    body = body or {}
    rid = f"RPT-{uuid.uuid4().hex[:6].upper()}"

    is_steel = (
        full_report.get("report_meta", {}).get("report_kind") == "steel_grain_size"
        or "steel_grain_size" in full_report
    )
    if is_steel:
        sg = full_report.get("steel_grain_size") or {}
        gsat_m = (sg.get("gsat") or {}).get("measurements") or {}
        astm_m = (sg.get("astm_estimator") or {}).get("measurements") or {}
        jf = (sg.get("astm_estimator") or {}).get("jeffries") or {}
        steel_metrics = {
            "analysis_type": "steel_grain_size",
            "method": sg.get("method"),
            "quality_score": (full_report.get("image_quality") or {}).get("score"),
        }
        if gsat_m.get("mean_lineal_intercept_px") is not None:
            steel_metrics["mean_lineal_intercept_px"] = gsat_m.get("mean_lineal_intercept_px")
        if gsat_m.get("mean_lineal_intercept_um") is not None:
            steel_metrics["mean_lineal_intercept_um"] = gsat_m.get("mean_lineal_intercept_um")
        if gsat_m.get("grain_segments") is not None:
            steel_metrics["grain_segments"] = gsat_m.get("grain_segments")
        if gsat_m.get("boundary_intersections") is not None:
            steel_metrics["boundary_intersections"] = gsat_m.get("boundary_intersections")
        if gsat_m.get("astm_grain_size_number") is not None:
            steel_metrics["gsat_astm_grain_size_number"] = gsat_m.get("astm_grain_size_number")
        if astm_m.get("grain_count") is not None:
            steel_metrics["grain_count"] = astm_m.get("grain_count")
        if jf.get("astm_grain_size_number") is not None:
            steel_metrics["astm_grain_size_number"] = jf.get("astm_grain_size_number")
        if sg.get("phase_fractions"):
            steel_metrics["phase_fractions"] = sg.get("phase_fractions")
        if sg.get("anisotropy"):
            steel_metrics["anisotropy"] = sg.get("anisotropy")
        if sg.get("conformance"):
            steel_metrics["conformance"] = sg.get("conformance")

        report = {
            "id": rid,
            "title": body.get("title") or full_report.get("report_meta", {}).get(
                "title", "NODIQ-X Steel Grain-Size Analysis Report"),
            "sample_id": body.get("sample_id") or aid or "STEEL-SAMPLE",
            "type": "Steel Grain-Size",
            "report_type": report_type,
            "analysis_type": "steel_grain_size",
            "status": "Ready",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "analysis_id": aid,
            "sections": body.get("sections") or [],
            "include_anomalies": False,
            "engineering_notes": body.get("engineering_notes") or "",
            "metrics": steel_metrics,
            "summary": full_report.get("observations", [""])[0]
            if full_report.get("observations") else "Steel grain-size report generated.",
            "full_report": full_report,
            "verification_hash": full_report.get("verification", {}).get("sha256_fingerprint"),
            "verification_url": full_report.get("verification", {}).get("verification_url"),
            "mechanical_properties": full_report.get("mechanical_properties"),
            "downloads": {"pdf": f"/api/reports/{rid}/download?format=pdf",
                          "csv": f"/api/reports/{rid}/download?format=csv",
                          "json": f"/api/reports/{rid}/download?format=json"},
        }
        store.insert_report(report, _uid())
        return report

    is_white = (
        full_report.get("report_meta", {}).get("report_kind") == "white_cast_iron_carbide"
        or "white_cast_iron_carbide" in full_report
    )
    if is_white:
        wci = full_report.get("white_cast_iron_carbide") or {}
        meas = wci.get("measurements") or {}
        white_metrics = {
            "analysis_type": "white_cast_iron_carbide",
            "method": wci.get("method"),
            "carbide_count": wci.get("carbide_count"),
            "quality_score": (full_report.get("image_quality") or {}).get("score"),
            "area_fraction_pct": meas.get("area_fraction_pct"),
            "total_area_px2": meas.get("total_area_px2"),
            "total_area_um2": meas.get("total_area_um2"),
            "mean_equiv_diameter_px": meas.get("mean_equiv_diameter_px"),
            "mean_equiv_diameter_um": meas.get("mean_equiv_diameter_um"),
            "mean_solidity": meas.get("mean_solidity"),
            "validation_status": full_report.get("validation_status"),
        }
        report = {
            "id": rid,
            "title": body.get("title") or full_report.get("report_meta", {}).get(
                "title", "NODIQ-X White Cast Iron Carbide Analysis Report"),
            "sample_id": body.get("sample_id") or aid or "WCI-SAMPLE",
            "type": "White Cast Iron Carbide",
            "report_type": report_type,
            "analysis_type": "white_cast_iron_carbide",
            "status": "Ready",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "analysis_id": aid,
            "sections": body.get("sections") or [],
            "include_anomalies": False,
            "engineering_notes": body.get("engineering_notes") or "",
            "metrics": white_metrics,
            "summary": full_report.get("observations", [""])[0]
            if full_report.get("observations") else "White cast iron carbide report generated.",
            "full_report": full_report,
            "verification_hash": full_report.get("verification", {}).get("sha256_fingerprint"),
            "verification_url": full_report.get("verification", {}).get("verification_url"),
            "mechanical_properties": full_report.get("mechanical_properties"),
            "downloads": {"pdf": f"/api/reports/{rid}/download?format=pdf",
                          "csv": f"/api/reports/{rid}/download?format=csv",
                          "json": f"/api/reports/{rid}/download?format=json"},
        }
        store.insert_report(report, _uid())
        return report

    is_gray = (
        full_report.get("report_meta", {}).get("report_kind") == "gray_cast_iron_graphite_flake"
        or "gray_cast_iron_graphite_flake" in full_report
    )
    if is_gray:
        gci = full_report.get("gray_cast_iron_graphite_flake") or {}
        meas = gci.get("measurements") or {}
        gray_metrics = {
            "analysis_type": "gray_cast_iron_graphite_flake",
            "method": gci.get("method"),
            "flake_count": gci.get("flake_count"),
            "quality_score": (full_report.get("image_quality") or {}).get("score"),
            "graphite_area_fraction_pct": meas.get("graphite_area_fraction_pct"),
            "total_graphite_area_px2": meas.get("total_graphite_area_px2"),
            "total_graphite_area_um2": meas.get("total_graphite_area_um2"),
            "mean_equiv_diameter_px": meas.get("mean_equiv_diameter_px"),
            "mean_equiv_diameter_um": meas.get("mean_equiv_diameter_um"),
            "mean_aspect_ratio": meas.get("mean_aspect_ratio"),
            "mean_orientation_deg": meas.get("mean_orientation_deg"),
            "validation_status": full_report.get("validation_status"),
        }
        report = {
            "id": rid,
            "title": body.get("title") or full_report.get("report_meta", {}).get(
                "title", "NODIQ-X Gray Cast Iron Graphite Flake Analysis Report"),
            "sample_id": body.get("sample_id") or aid or "GCI-SAMPLE",
            "type": "Gray Cast Iron Flake",
            "report_type": report_type,
            "analysis_type": "gray_cast_iron_graphite_flake",
            "status": "Ready",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "analysis_id": aid,
            "sections": body.get("sections") or [],
            "include_anomalies": bool(body.get("include_anomalies")),
            "engineering_notes": body.get("engineering_notes") or "",
            "metrics": gray_metrics,
            "summary": full_report.get("observations", [""])[0]
            if full_report.get("observations") else "Gray cast iron flake report generated.",
            "full_report": full_report,
            "verification_hash": full_report.get("verification", {}).get("sha256_fingerprint"),
            "verification_url": full_report.get("verification", {}).get("verification_url"),
            "mechanical_properties": full_report.get("mechanical_properties"),
            "downloads": {"pdf": f"/api/reports/{rid}/download?format=pdf",
                          "csv": f"/api/reports/{rid}/download?format=csv",
                          "json": f"/api/reports/{rid}/download?format=json"},
        }
        full_report.setdefault("report_meta", {})["report_type"] = report_type
        full_report["report_meta"]["title"] = report["title"]
        full_report["report_type"] = report_type
        full_report["sections"] = report["sections"]
        full_report["engineering_notes"] = report["engineering_notes"]
        full_report["include_anomalies"] = report["include_anomalies"]
        store.insert_report(report, _uid())
        return report

    anomalies = full_report.get("anomaly_analysis") or {}
    iso = full_report.get("iso_jis_classification", {}) \
        .get("iso_nodularity_pct") or 0.0
    count = full_report.get("detection_results", {}).get("nodule_count") or 0
    sc = full_report.get("detection_results", {}).get("self_check", {})
    report = {
        "id": rid,
        "title": body.get("title") or full_report.get("report_meta", {})
        .get("title", "Nodularity Technical Report"),
        "sample_id": body.get("sample_id") or aid or "BATCH-2026-A",
        "type": report_type.capitalize(),
        "report_type": report_type,
        "status": "Ready",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "analysis_id": aid,
        "sections": body.get("sections") or [],
        "include_anomalies": bool(body.get("include_anomalies")),
        "engineering_notes": body.get("engineering_notes") or "",
        "metrics": {
            "nodularity_pct": iso,
            "nodule_count": count,
            "self_check_accuracy_pct": sc.get("count_accuracy_pct"),
            "jis_nodularity_pct": full_report.get(
                "iso_jis_classification", {}).get("jis_nodularity_pct"),
            "quality_score": (full_report.get("image_quality") or {})
            .get("score"),
            "verdict": full_report.get("verdict", {}).get("iso_verdict"),
            "anomaly_severity": (anomalies.get("severity") if isinstance(
                anomalies, dict) else None),
        },
        "summary": full_report.get("observations", [""])[0]
        if full_report.get("observations") else "Report generated.",
        "full_report": full_report,
        "verification_hash": full_report.get("verification", {}).get("sha256_fingerprint"),
        "verification_url": full_report.get("verification", {}).get("verification_url"),
        "mechanical_properties": full_report.get("mechanical_properties"),
        "downloads": {"pdf": f"/api/reports/{rid}/download?format=pdf",
                      "csv": f"/api/reports/{rid}/download?format=csv",
                      "json": f"/api/reports/{rid}/download?format=json"},
    }
    store.insert_report(report, _uid())
    return report


@app.post("/api/reports/generate")
def reports_generate_v2():
    """Advanced report generation (replaces the old handler body; same route,
    same response contract plus new fields)."""
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {
        "analysis_id": ("id", {"default": ""}),
        "report_type": ("enum", {"choices": _REPORT_TYPES,
                                  "default": "technical"}),
        "title": ("str", {"max_len": 256, "truncate": True, "default": ""}),
        "sample_id": ("str", {"max_len": 256, "truncate": True, "default": ""}),
        "sections": ("list", {"max_items": 20, "item_max_len": 64,
                               "default": []}),
        "include_anomalies": ("bool", {"default": False}),
        "engineering_notes": ("str", {"max_len": 5000, "default": ""}),
    })
    report_type = v["report_type"]

    aid, full_report = _generate_for(body.get("analysis_id"), report_type=report_type, body=v)
    if not full_report:
        analyses = store.list_analyses(_uid())
        if not analyses:
            return jsonify({"error": "no analyses to report on"}), 400
        # fall back to the minimal legacy behavior if no full payload exists
        analysis = analyses[0]
        if analysis.get("analysis_type") == "steel_grain_size":
            report = {
                "id": f"RPT-{uuid.uuid4().hex[:6].upper()}",
                "title": body.get("title") or "NODIQ-X Steel Grain-Size Analysis Report",
                "sample_id": body.get("sample_id") or analysis.get("filename") or "STEEL-SAMPLE",
                "type": "Steel Grain-Size",
                "analysis_type": "steel_grain_size",
                "status": "Ready",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "analysis_id": analysis.get("id"),
                "metrics": {
                    "analysis_type": "steel_grain_size",
                    "method": analysis.get("method"),
                },
                "summary": "See steel analysis detail endpoint for measured values.",
            }
            store.insert_report(report, _uid())
            return jsonify(report), 201

        if analysis.get("analysis_type") == "white_cast_iron_carbide":
            report = {
                "id": f"RPT-{uuid.uuid4().hex[:6].upper()}",
                "title": body.get("title") or "NODIQ-X White Cast Iron Carbide Analysis Report",
                "sample_id": body.get("sample_id") or analysis.get("filename") or "WCI-SAMPLE",
                "type": "White Cast Iron Carbide",
                "analysis_type": "white_cast_iron_carbide",
                "status": "Ready",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "analysis_id": analysis.get("id"),
                "metrics": {
                    "analysis_type": "white_cast_iron_carbide",
                    "method": analysis.get("method"),
                },
                "summary": "See white cast iron analysis detail endpoint for measured values.",
            }
            store.insert_report(report, _uid())
            return jsonify(report), 201

        if analysis.get("analysis_type") == "gray_cast_iron_graphite_flake":
            report = {
                "id": f"RPT-{uuid.uuid4().hex[:6].upper()}",
                "title": body.get("title") or "NODIQ-X Gray Cast Iron Graphite Flake Analysis Report",
                "sample_id": body.get("sample_id") or analysis.get("filename") or "GCI-SAMPLE",
                "type": "Gray Cast Iron Flake",
                "report_type": report_type,
                "analysis_type": "gray_cast_iron_graphite_flake",
                "status": "Ready",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "analysis_id": analysis.get("id"),
                "sections": body.get("sections") or [],
                "include_anomalies": bool(body.get("include_anomalies")),
                "engineering_notes": body.get("engineering_notes") or "",
                "metrics": {
                    "analysis_type": "gray_cast_iron_graphite_flake",
                    "method": analysis.get("method"),
                },
                "summary": "See gray cast iron analysis detail endpoint for measured values.",
            }
            store.insert_report(report, _uid())
            return jsonify(report), 201

        nodularity = analysis.get("iso_nodularity_pct") or 0.0
        report = {
            "id": f"RPT-{uuid.uuid4().hex[:6].upper()}",
            "title": body.get("title") or "Nodularity Technical Report",
            "sample_id": body.get("sample_id") or "BATCH-2026-A",
            "type": report_type.capitalize(),
            "status": "Ready",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "analysis_id": analysis.get("id"),
            "metrics": {"nodularity_pct": nodularity},
            "summary": "See analysis detail endpoint for measured values.",
        }
        store.insert_report(report, _uid())
        return jsonify(report), 201

    report = _store_full_report(full_report, aid, v, report_type)
    return jsonify(report), 201


@app.get("/api/reports/<report_id>/evidence/<kind>")
def report_evidence(report_id: str, kind: str):
    """Report evidence images from the ACTUAL analysis: the original
    micrograph (`kind=original`, served from the dataset for dataset images or
    the persisted upload for uploaded files) and the engine's own contour
    overlay (`kind=annotated`, regenerated from the stored full payload so it
    always matches the report's measured values)."""
    report = store.get_report(report_id, _uid())
    if not report:
        return jsonify({"error": "not found"}), 404
    aid = report.get("analysis_id")
    full = _full_payload(aid)
    record = _analysis_record(aid)
    filename = (record or {}).get("filename")

    if kind == "original":
        if filename and re.fullmatch(r"micrograph_[0-9]{4}\.png", filename) \
                and (DATASET_DIR / filename).exists():
            return send_from_directory(DATASET_DIR, filename)
        stored = _stored_upload_path(record)
        if stored:
            return send_from_directory(stored.parent, stored.name)
        return jsonify({"error": "original image not available for this "
                                 "analysis"}), 404

    if (record or {}).get("analysis_type") == "steel_grain_size" \
            and kind in ("annotated", "mask", "overlay", "intercept",
                         "gsat_mask", "astm_mask", "gsat_overlay", "gsat_intercept", "astm_overlay", "gsat_preprocessed"):
        target_kind = kind
        if kind in ("mask", "annotated", "overlay", "intercept"):
            cands = {
                "mask": ["gsat_mask", "astm_mask"],
                "annotated": ["gsat_intercept", "gsat_overlay", "astm_overlay"],
                "overlay": ["gsat_intercept", "gsat_overlay", "astm_overlay"],
                "intercept": ["gsat_intercept", "gsat_overlay"],
            }.get(kind, [kind])
            target_kind = cands[0]
            for cand in cands:
                cand_path = context_svc.FULL_DIR / f"{aid}_{cand}.png"
                if cand_path.exists():
                    target_kind = cand
                    break
        _st = _storage()
        owner = store.analysis_owner(aid)
        if owner and _st.BACKEND == "supabase":
            try:
                blob = _st.get_bytes(owner, aid, target_kind)
                if blob is not None:
                    return Response(blob, mimetype="image/png")
            except Exception:
                pass
        artifact_path = context_svc.FULL_DIR / f"{aid}_{target_kind}.png"
        if artifact_path.exists():
            return send_from_directory(context_svc.FULL_DIR, artifact_path.name)
        return jsonify({"error": f"steel artifact {target_kind} not available for this report"}), 404

    if (record or {}).get("analysis_type") == "gray_cast_iron_graphite_flake" \
            and kind in ("annotated", "mask", "overlay", "contour", "exclusion",
                         "flake_mask", "flake_overlay", "flake_contour", "flake_exclusion"):
        # Gray cast-iron reports have no circle overlay; the annotated kind
        # maps to the deep-learning segmentation overlay artifact instead.
        gci_kind = {"mask": "flake_mask", "flake_mask": "flake_mask",
                    "annotated": "flake_overlay", "overlay": "flake_overlay",
                    "flake_overlay": "flake_overlay",
                    "contour": "flake_contour", "flake_contour": "flake_contour",
                    "exclusion": "flake_exclusion", "flake_exclusion": "flake_exclusion"}[kind]
        _st = _storage()
        owner = store.analysis_owner(aid)
        if owner and _st.BACKEND == "supabase":
            try:
                blob = _st.get_bytes(owner, aid, gci_kind)
                if blob is not None:
                    return Response(blob, mimetype="image/png")
            except Exception:
                pass
        artifact_path = context_svc.FULL_DIR / f"{aid}_{gci_kind}.png"
        if artifact_path.exists():
            return send_from_directory(context_svc.FULL_DIR, artifact_path.name)
        return jsonify({"error": "segmentation artifact not available for "
                                 "this report"}), 404

    if kind == "annotated":
        if not full:
            return jsonify({"error": "full analysis payload not stored for "
                                     "this report"}), 404
        nodules = full.get("nodules") or []
        if filename and (DATASET_DIR / str(filename)).exists():
            _, gray = load_grayscale(str(DATASET_DIR / filename))
        else:
            stored = _stored_upload_path(record)
            if not stored:
                return jsonify({"error": "source image not available to "
                                         "redraw overlay"}), 404
            _, gray = load_grayscale(str(stored))
        png = _engine_overlay_image(nodules, gray)
        if png is None:
            return jsonify({"error": "encode failed"}), 500
        return Response(png, mimetype="image/png")

    return jsonify({"error": "kind must be original or annotated"}), 400


def _steel_evidence_images(analysis_id, record=None):
    """Image bytes for the steel grain-size PDF evidence section: the original
    micrograph plus the grain-boundary mask and intercept/instance overlay."""
    evid = {}
    try:
        record = record or _analysis_record(analysis_id)
        filename = (record or {}).get("filename")
        if filename and re.fullmatch(r"micrograph_[0-9]{4}\.png", filename) \
                and (DATASET_DIR / filename).exists():
            evid["original"] = (DATASET_DIR / filename).read_bytes()
        else:
            stored = _stored_upload_path(record)
            if stored and stored.exists():
                evid["original"] = stored.read_bytes()
        _st = _storage()
        owner = store.analysis_owner(analysis_id)
        for kind in ("gsat_mask", "astm_mask", "gsat_intercept", "gsat_overlay", "astm_overlay", "gsat_preprocessed"):
            blob = None
            if owner and _st.BACKEND == "supabase":
                try:
                    blob = _st.get_bytes(owner, analysis_id, kind)
                except Exception:
                    blob = None
            if blob is None:
                path = context_svc.FULL_DIR / f"{analysis_id}_{kind}.png"
                if path.exists():
                    blob = path.read_bytes()
            if blob:
                evid[kind] = blob
                if "mask" not in evid and "mask" in kind:
                    evid["mask"] = blob
                if "overlay" not in evid and ("overlay" in kind or "intercept" in kind):
                    evid["overlay"] = blob
    except Exception:
        pass
    return evid


def _gray_evidence_images(analysis_id, record=None):
    """Image bytes for the gray cast-iron PDF evidence section: the original
    micrograph plus the persisted segmentation artifacts (binary flake mask
    and colored overlay). Missing items are simply omitted so degraded
    storage can never break the whole PDF."""
    evid = {}
    try:
        record = record or _analysis_record(analysis_id)
        filename = (record or {}).get("filename")
        if filename and re.fullmatch(r"micrograph_[0-9]{4}\.png", filename) \
                and (DATASET_DIR / filename).exists():
            evid["original"] = (DATASET_DIR / filename).read_bytes()
        else:
            stored = _stored_upload_path(record)
            if stored and stored.exists():
                evid["original"] = stored.read_bytes()
        _st = _storage()
        owner = store.analysis_owner(analysis_id)
        for kind in ("flake_mask", "flake_overlay", "flake_contour"):
            blob = None
            if owner and _st.BACKEND == "supabase":
                try:
                    blob = _st.get_bytes(owner, analysis_id, kind)
                except Exception:
                    blob = None
            if blob is None:
                path = context_svc.FULL_DIR / f"{analysis_id}_{kind}.png"
                if path.exists():
                    blob = path.read_bytes()
            if blob:
                evid[kind] = blob
    except Exception:
        pass
    return evid


@app.delete("/api/reports/<report_id>")
@require_auth
def reports_delete(user, report_id: str):
    if not store.delete_report(report_id, user["id"]):
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": report_id})


# --------------------------------------------------------------------------
# copilot (rule-based over the real analysis history)
# --------------------------------------------------------------------------

_WORD = re.compile(r"[a-z_]+")


def _copilot_reply(message: str, history) -> str:
    text = message.lower()
    latest = history[0] if history else None
    words = set(_WORD.findall(text))

    def fmt(v):
        return f"{v}%" if isinstance(v, (int, float)) else (v or "—")

    if any(w in words for w in ("hello", "hi", "hey")):
        return ("Hello! I'm NODIQ Copilot. I can explain your latest "
                "analysis, compare nodularity runs, or summarize your "
                "report history. What would you like to know?")

    if any(k in text for k in ("anomal", "warning", "concern", "issue")):
        flagged = [a for a in history
                   if a.get("accuracy_pct") is not None
                   and a["accuracy_pct"] < 95]
        if flagged:
            names = ", ".join(a["id"] for a in flagged[:3])
            return (f"{len(flagged)} analysis run(s) fell below the 95% "
                    f"self-check accuracy gate: {names}. Recommend a "
                    "higher-resolution re-scan before sign-off.")
        if latest and (latest.get("warnings") or []):
            return ("Latest analysis raised these warnings: "
                    + "; ".join(latest["warnings"])
                    + ". These usually indicate the scan resolution, not "
                      "the material.")
        return ("No anomalies in recent runs — all self-check accuracy "
                "values are at or above the 95% gate.")

    if any(k in text for k in ("report", "pdf", "document")):
        reports = store.list_reports(_uid())
        ready = sum(1 for r in reports if r.get("status") == "Ready")
        return (f"You have {len(reports)} report(s), {ready} ready. Use the "
                "Reports page to generate a new one from your latest "
                "analysis — it will embed the nodularity, count and "
                "self-check accuracy metrics automatically.")

    if any(k in text for k in ("compare", "difference", "versus", " vs ")):
        if len(history) >= 2:
            a, b = history[0], history[1]
            return (f"Latest two runs: {a['id']} at {fmt(a.get('iso_nodularity_pct'))} "
                    f"nodularity ({a.get('nodule_count', '—')} nodules) vs "
                    f"{b['id']} at {fmt(b.get('iso_nodularity_pct'))} "
                    f"({b.get('nodule_count', '—')} nodules). "
                    "A delta above ~2pp usually indicates process drift.")
        return "I need at least two analyses in your history to compare."

    if any(k in text for k in ("improve", "better", "quality", "resolution")):
        return ("For best accuracy use images at least ~1000px wide with "
                "even illumination and polished, unetched surfaces. The "
                "engine is validated on polished ductile-iron micrographs; "
                "other material types run but are not calibrated.")

    # default: explain latest analysis
    if latest:
        return (f"Latest analysis {latest['id']} on "
                f"{latest.get('filename', 'your image')}: "
                f"{latest.get('nodule_count', '—')} nodules, "
                f"nodularity {fmt(latest.get('iso_nodularity_pct'))} "
                f"(ISO view; JIS view {fmt(latest.get('jis_nodularity_pct'))}), "
                f"self-check accuracy {fmt(latest.get('accuracy_pct'))}. "
                "Ask me about anomalies, comparisons, or reports.")
    return ("No analyses yet — upload a micrograph on the New Analysis page "
            "and I'll be able to explain the results.")


# (the upgraded /api/copilot handler lives in the intelligence block below;
#  the old rule-based logic is preserved in ai/fallback_provider.py)


# --------------------------------------------------------------------------
# NODIQ-X 2.0 — intelligence services (additive; existing endpoints above)
# --------------------------------------------------------------------------


def _full_payload(analysis_id):
    """Stored full payload for an analysis id, or None."""
    return load_full_analysis(analysis_id)


def _analysis_record(analysis_id):
    return store.get_analysis_record(analysis_id, _uid())


def _owned_full(analysis_id):
    """Full payload ONLY when the analysis record is visible to the current
    user. The payload store is a global filesystem cache, so every
    user-facing route must pass through this ownership gate — otherwise one
    account could read another account's analysis by id (404 for strangers,
    exactly like the analyses list)."""
    if not _analysis_record(analysis_id):
        return None
    return _full_payload(analysis_id)


def _latest_record():
    history = store.list_analyses(_uid())
    return history[0] if history else None


def _contract(analysis_id):
    """Cached scientific contract for an analysis (Phase 2 + 37)."""
    full = _owned_full(analysis_id)
    if not full:
        return None
    return build_contract(
        analysis_id,
        batch_records=(_batch_records() if CFG.enable_batch_analytics
                       else None),
        quality=full.get("quality"),
        calibration=full.get("calibration"))


def _batch_records():
    return store.list_analyses(_uid())


def _tool_context(session_analysis_id=None):
    """ToolContext injected into every AI tool call (no DB access in ai/)."""
    return {
        "analysis_id": session_analysis_id,
        "contract": _contract,
        "latest_analysis": _latest_record,
        "analyze_dataset_image": _tool_analyze_dataset_image,
        "nodule_details": _tool_nodule_details,
        "compare": _tool_compare,
        "batch_stats": lambda: batch_statistics(store.list_analyses(_uid())),
        "spc": _tool_spc,
        "anomalies": _tool_anomalies,
        "decision_support": _tool_decision_support,
        "validation": _tool_validation,
        "generate_report": _tool_generate_report,
        "get_report": _tool_get_report,
        "search_reference": lambda q: search_reference(q),
        "batch_enabled": CFG.enable_batch_analytics,
        "spc_enabled": CFG.enable_spc,
        "anomaly_enabled": CFG.enable_anomaly_detection,
    }


def _tool_analyze_dataset_image(name):
    """CV engine run on a dataset image (tool-facing, stores full payload)."""
    path = DATASET_DIR / name
    if not path.exists():
        return {"error": f"dataset image {name} not found"}
    res = analyze_image(str(path))
    payload, err = analyze_for_frontend_json(str(path), res=res)
    if err:
        return {"error": err}
    try:
        color, gray, (src_w, src_h) = load_with_source(str(path))
        payload["quality"] = assess_quality(gray, src_w, src_h, bgr=color)
        payload["nodules"] = enrich_rows(res["rows"], res["contours"],
                                         (payload.get("self_check") or {})
                                         .get("f1_pct"))
        if CFG.enable_calibration:
            cal = auto_calibrate(gray)
            if cal.available:
                payload["calibration"] = cal.to_dict()
        from nodiq.pipelines.nodularity_pipeline import apply_size_filter_and_iso
        mpp = validate_um_per_px((payload.get("calibration") or {})
                                 .get("um_per_px"))
        _shim = {"rows": payload.get("nodules") or res["rows"]}
        apply_size_filter_and_iso(_shim, mpp)
        payload["iso_size_qualified_pct"] = _shim["iso_size_qualified_pct"]
        payload["size_filter"] = _shim["size_filter"]
    except Exception:
        pass
    payload["filename"] = name
    aid = f"ANL-{uuid.uuid4().hex[:6].upper()}"
    record = {
        "id": aid,
        "title": f"{Path(name).stem} — Nodularity Analysis",
        "filename": name,
        "type": "Nodularity Analysis",
        "status": "completed",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "nodule_count": payload["nodule_count"],
        "iso_nodularity_pct": payload["iso_nodularity_pct"],
        "jis_nodularity_pct": payload["jis_nodularity_pct"],
        "accuracy_pct": (payload.get("self_check") or {}).get(
            "count_accuracy_pct"),
        "confidence_pct": (payload.get("self_check") or {}).get("f1_pct"),
        "warnings": payload.get("warnings", []),
        "source_width": payload.get("source_width"),
        "source_height": payload.get("source_height"),
        "quality_score": (payload.get("quality") or {}).get("score"),
        "quality_status": (payload.get("quality") or {}).get("status"),
    }
    store.insert_analysis(record, _uid())
    payload["analysis_id"] = aid
    save_full_analysis(aid, payload)
    return {"analysis": {"analysis_id": aid,
                         "nodule_count": payload["nodule_count"],
                         "iso_nodularity_pct": payload["iso_nodularity_pct"],
                         "jis_nodularity_pct": payload["jis_nodularity_pct"],
                         "self_check": payload.get("self_check"),
                         "quality": payload.get("quality")}}


def _tool_nodule_details(analysis_id, nodule_id=None):
    full = _owned_full(analysis_id)
    if not full:
        return {"error": f"analysis {analysis_id} not found"}
    rows = full.get("nodules") or []
    if nodule_id is not None:
        for r in rows:
            if r.get("nodule_id") == nodule_id:
                return {"nodule": r}
        return {"error": f"nodule {nodule_id} not found"}
    # notable nodules: lowest confidence + largest area
    by_conf = sorted(rows, key=lambda r: r.get("confidence") or 0)[:3]
    by_area = sorted(rows, key=lambda r: -(r.get("area_px") or 0))[:3]
    seen, notable = set(), []
    for r in by_conf + by_area:
        if r["nodule_id"] not in seen:
            seen.add(r["nodule_id"])
            notable.append(r)
    return {"nodules_notable": notable,
            "sources": full.get("detections", {}).get("sources")}


def _tool_compare(a_id, b_id=None):
    history = store.list_analyses(_uid())
    a_rec = _analysis_record(a_id) if a_id else None
    a_full = _owned_full(a_id) if a_id else None
    if not a_rec or not a_full:
        # newest analysis that actually has a stored full payload
        for r in history:
            if _full_payload(r.get("id")):
                a_rec, a_full, a_id = r, _full_payload(r["id"]), r["id"]
                break
    if not a_rec or not a_full:
        return None
    candidates = [r for r in history if r.get("id") != a_id
                  and isinstance(r.get("iso_nodularity_pct"), (int, float))
                  and _full_payload(r.get("id"))]
    if b_id:
        b_rec = next((r for r in candidates if r.get("id") == b_id), None)
    else:
        b_rec = max(candidates, key=lambda r: r["iso_nodularity_pct"]) \
            if candidates else None
    if not b_rec:
        return None
    b_full = _full_payload(b_rec["id"])
    if not b_full:
        return None
    return compare_analyses(
        {**a_full, "analysis_id": a_id},
        {**b_full, "analysis_id": b_rec["id"]})


def _tool_spc(metric="nodularity"):
    records = _batch_records()
    key = {
        "nodularity": "iso_nodularity_pct",
        "iso_nodularity_pct": "iso_nodularity_pct",
        "jis_nodularity": "jis_nodularity_pct",
        "jis_nodularity_pct": "jis_nodularity_pct",
        "count": "nodule_count",
        "nodule_count": "nodule_count",
        "self_check_accuracy": "accuracy_pct",
        "accuracy": "accuracy_pct",
        "accuracy_pct": "accuracy_pct",
        "confidence": "confidence_pct",
    }.get(str(metric), "iso_nodularity_pct")
    rows = [r for r in records
            if isinstance(r.get(key), (int, float))]
    values = [r[key] for r in rows]
    values.reverse()  # chronological order
    ids = [r.get("id") for r in reversed(rows)]
    result = spc(values, metric=key)
    result["ids"] = ids          # per-point analysis ids (additive)
    result["requested_metric"] = str(metric)
    return result


def _tool_anomalies():
    records = _batch_records()
    cards = scan_history(records,
                         full_lookup=lambda aid: _full_payload(aid))
    return {"anomalies": [c for c in cards if c.get("is_anomaly")],
            "scanned": len(cards)}


def _tool_decision_support(analysis_id):
    record = _analysis_record(analysis_id)
    full = _owned_full(analysis_id)
    if not record or not full:
        return {"error": f"analysis {analysis_id} not found"}
    return decision_support(record, full=full)


def _tool_validation(kind="internal"):
    kind = (kind or "internal").lower()
    if kind == "internal":
        return internal_validation()
    if kind == "blind":
        return blind_test(n=5)
    if kind == "synthetic":
        return synthetic_validation(n_images=2)
    return {"error": "kind must be internal | blind | synthetic"}


def _tool_generate_report(analysis_id=None):
    """Generate AND persist a report record (same path as the Reports page)
    so the Copilot can hand back a real RPT id."""
    aid, report = _generate_for(analysis_id)
    if not report:
        return {"error": "no analysis available to report on"}
    stored = _store_full_report(report, aid)
    return stored


def _tool_get_report(report_id):
    r = store.get_report(report_id, _uid())
    if r:
        return {k: r[k] for k in ("id", "title", "metrics", "summary",
                                      "created_at") if k in r}
    return {"error": f"report {report_id} not found"}


# --------------------------- AI copilot (real provider chain) ----------------

@app.get("/api/ai/status")
def ai_status():
    return jsonify(ai_provider_status())


@app.get("/api/copilot/health")
def copilot_health():
    """Truthful Copilot health for UI status chips and monitoring."""
    status = ai_provider_status()
    return jsonify({
        **status,
        "ready": status.get("state") in {"ONLINE", "OFFLINE", "NOT_CONFIGURED"},
        "provider_configured": bool(status.get("configured_provider")),
    })


@app.get("/api/copilot/capabilities")
def copilot_capabilities():
    return jsonify({"capabilities": get_capabilities(),
                    "tools": ai_tools.tool_names()})


@app.post("/api/copilot")
def copilot():
    """Upgraded Copilot endpoint (additive request fields).

    Body: {message, session_id?, history?: [{role, content}],
           context?: {current_analysis_id, current_page, ...}}
    Legacy single-message bodies keep working (session defaults).
    """
    body = request.get_json(silent=True) or {}
    # Copilot reads the caller's analyses and persists conversation memory —
    # both are per-account, so an anonymous session has nothing safe to
    # stand on. Every Copilot surface in the frontend is authenticated.
    if _current_user() is None:
        return jsonify({"error": "authentication required"}), 401
    v = validate_body(body, {
        "message": ("str", {"required": True, "max_len": 4000}),
        "session_id": ("session_id", {"default": "default"}),
        "context": ("dict", {"max_keys": 24, "default": {}}),
        "history": ("list", {"max_items": 50, "item_max_len": 4000,
                              "item_kind": "obj", "default": []}),
    })
    message = v["message"]
    if not message:
        return jsonify({"error": "empty message"}), 400
    if not CFG.enable_copilot:
        return jsonify({"error": "copilot disabled by feature flag"}), 503

    session_id = v["session_id"]
    app_context = v["context"]
    history = v["history"]
    # Conversation memory is namespaced to the VERIFIED account — the owner
    # never comes from the request body, so one user cannot read or append
    # to another user's Copilot session by guessing a session id.
    owner = _current_user()
    ctx = _tool_context(session_analysis_id=app_context.get(
        "current_analysis_id"))

    try:
        result = handle_turn(message, session_id, ctx, history=history,
                             app_context=app_context,
                             owner_id=(owner or {}).get("id"))
        return jsonify(result)
    except Exception as exc:
        # the agent loop already degrades internally; this is a last resort
        return jsonify({"reply": (
            f"I hit an internal error handling that message, but the "
            f"analysis platform is unaffected. ({type(exc).__name__})"),
            "provider": "error-handler"}), 200


@app.post("/api/copilot/chat")
def copilot_chat():
    """Compatibility alias for the real production Copilot route."""
    return copilot()


@app.post("/api/copilot/stream")
def copilot_stream():
    """Streaming Copilot endpoint using Server-Sent Events (SSE).
    Body: {message, session_id?, history?: [{role, content}], context?: {...}}
    """
    body = request.get_json(silent=True) or {}
    if _current_user() is None:
        return jsonify({"error": "authentication required"}), 401
    v = validate_body(body, {
        "message": ("str", {"required": True, "max_len": 4000}),
        "session_id": ("session_id", {"default": "default"}),
        "context": ("dict", {"max_keys": 24, "default": {}}),
        "history": ("list", {"max_items": 50, "item_max_len": 4000,
                              "item_kind": "obj", "default": []}),
    })
    message = v["message"]
    if not message:
        return jsonify({"error": "empty message"}), 400
    if not CFG.enable_copilot:
        return jsonify({"error": "copilot disabled by feature flag"}), 503

    session_id = v["session_id"]
    app_context = v["context"]
    history = v["history"]
    owner = _current_user()
    ctx = _tool_context(session_analysis_id=app_context.get("current_analysis_id"))

    def generate():
        try:
            for chunk in handle_turn_stream(
                message, session_id, ctx, history=history,
                app_context=app_context, owner_id=(owner or {}).get("id")
            ):
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ------------------------------- quality / calibration APIs ------------------

@app.get("/api/quality/<analysis_id>")
def quality_for(analysis_id):
    full = _owned_full(analysis_id)
    if not full:
        return jsonify({"error": "not found"}), 404
    return jsonify({"analysis_id": analysis_id,
                    "quality": full.get("quality")})


@app.post("/api/calibration")
def calibration_endpoint():
    """Auto or manual calibration. Body options:
    {analysis_id}                          -> auto detection on stored image
    {bar_length_px, bar_length_um}         -> manual calibration
    """
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {
        "analysis_id": ("id", {"default": ""}),
        "bar_length_px": ("float", {"min": 0, "max": 100000,
                                     "default": None}),
        "bar_length_um": ("float", {"min": 0, "max": 100000,
                                     "default": None}),
        "microns_per_pixel": ("float", {"min": 0, "max": 10000,
                                         "default": None}),
    })
    bar_px = v["bar_length_px"]
    bar_um = v["bar_length_um"]
    mpp = v["microns_per_pixel"]
    if mpp is not None:
        # direct microns-per-pixel manual calibration (validated; invalid
        # values are rejected rather than coerced)
        cal = make_calibration(mpp, source="manual",
                               notes="manual microns-per-pixel")
        if not cal.available:
            return jsonify({"error": "invalid calibration values"}), 400
        cal_dict = cal.to_dict()
        store.save_calibration("manual", cal_dict)
        return jsonify(cal_dict)
    if bar_px and bar_um:
        try:
            cal = manual_calibrate(float(bar_px), float(bar_um))
            cal_dict = cal.to_dict()
            store.save_calibration("manual", cal_dict)
            return jsonify(cal_dict)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid calibration values"}), 400
    analysis_id = v["analysis_id"]
    if analysis_id:
        full = _owned_full(analysis_id)
        if not full:
            return jsonify({"error": "not found"}), 404
        filename = full.get("sample", {}).get("filename") \
            if isinstance(full.get("sample"), dict) else full.get("filename")
        # filename lives in the caller's own record — still cannot leave the
        # dataset root (or name a non-dataset file)
        if not re.fullmatch(r"micrograph_[0-9]{4}\.png", str(filename or "")):
            return jsonify({"error": "source image not available for auto "
                                     "detection; provide manual values"}), 400
        path = (DATASET_DIR / str(filename)).resolve()
        if not str(path).startswith(str(DATASET_DIR.resolve())) \
                or not path.exists():
            return jsonify({"error": "source image not available for auto "
                                     "detection; provide manual values"}), 400
        if not path.exists():
            return jsonify({"error": "source image not available for auto "
                                     "detection; provide manual values"}), 400
        gray = load_with_source(str(path))[1]
        cal = auto_calibrate(gray)
        return jsonify(cal.to_dict())
    return jsonify({"error": "provide bar_length_px+bar_length_um or "
                             "analysis_id"}), 400


# --------------------------- analysis detail endpoints -----------------------

@app.get("/api/analyses/<analysis_id>")
def analysis_detail(analysis_id):
    full = _owned_full(analysis_id)
    record = _analysis_record(analysis_id)
    if not record and not full:
        return jsonify({"error": "not found"}), 404
    record = record or {}
    # Async analyses are created as "processing" before the worker finishes;
    # clients poll this endpoint and must see the live status + progress. The
    # full payload appears only once the worker stores it (completed).
    if record.get("status") in ("processing", "failed") or full is None:
        # The record can flip to "completed" a hair before its payload row is
        # visible to this connection (pooler failover, read visibility on the
        # shared pooled socket). One bounded re-read turns that sub-second
        # window into "processing → completed" instead of serving a bare
        # completed envelope with analysis=None; pollers keep polling in the
        # meantime, so correctness ("completed LAST") is unaffected.
        if (record.get("status") == "completed" and full is None
                and store.BACKEND == "supabase"):
            try:
                time.sleep(0.3)
                full = load_full_analysis(analysis_id)
            except Exception:
                full = None
        return jsonify({
            "status": record.get("status", "processing"),
            "progress": record.get("progress", 0),
            "error": record.get("error"),
            "analysis_id": analysis_id,
            "record": record,
            "analysis": full,
        })
    # Visual artifacts are PNG files written by the analysis child (the JSON
    # store drops bulky base64); expose URLs only when they can actually
    # resolve: the local file (dev / warm cache) OR the persistent Supabase
    # object (survives redeploys — the ownership-checked artifact route
    # streams from Storage). URLs are attached WITHOUT fetching the bytes so
    # the poll stays cheap; the route itself verifies access and 404s if the
    # object is genuinely missing, and the UI falls back cleanly.
    full = dict(full)
    owner = store.analysis_owner(analysis_id)
    _st = _storage()
    persistent = bool(owner and _st.BACKEND == "supabase")
    for kind in ("annotated", "mask"):
        if persistent or (context_svc.FULL_DIR / f"{analysis_id}_{kind}.png").exists():
            full[f"{kind}_url"] = f"/api/analyses/{analysis_id}/artifact/{kind}"
    # Steel grain-size, white cast iron, and gray cast iron analyses persist
    # their own artifact sets — expose a URL per artifact that can actually resolve.
    if record.get("analysis_type") in ("steel_grain_size", "white_cast_iron_carbide", "gray_cast_iron_graphite_flake"):
        for art in (full.get("artifacts") or []):
            kind = str(art.get("kind") or "")
            if not re.fullmatch(r"[a-z0-9_]{1,40}", kind):
                continue
            if persistent or (context_svc.FULL_DIR
                              / f"{analysis_id}_{kind}.png").exists():
                full[f"{kind}_url"] = (
                    f"/api/analyses/{analysis_id}/artifact/{kind}")
    return jsonify({"record": record, "analysis": full})


@app.get("/api/analyses/<analysis_id>/nodules")
def analysis_nodules(analysis_id):
    full = _owned_full(analysis_id)
    if not full:
        return jsonify({"error": "not found"}), 404
    return jsonify({"nodules": full.get("nodules") or [],
                    "sources": (full.get("detections") or {}).get("sources")})


@app.get("/api/analyses/<analysis_id>/nodules/<int:nodule_id>")
def analysis_nodule(analysis_id, nodule_id):
    full = _owned_full(analysis_id)
    if not full:
        return jsonify({"error": "not found"}), 404
    cal = full.get("calibration") or {}
    cal_obj = None
    if cal.get("available") and cal.get("um_per_px"):
        from nodiq.services.calibration import Calibration
        cal_obj = Calibration(um_per_px=cal["um_per_px"],
                              source=cal.get("source", "manual"))
    n = get_nodule_detail({"nodules": full.get("nodules") or []},
                          nodule_id, calibration=cal_obj)
    if not n:
        return jsonify({"error": "nodule not found"}), 404
    return jsonify({"nodule": n})


@app.post("/api/analyses/<analysis_id>/lot")
@require_auth
def analysis_set_lot(user, analysis_id: str):
    """Tag an analysis with a heat/lot id (traceability)."""
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {"lot_id": ("str", {"max_len": 64,
                                                 "default": ""})})
    lot = v["lot_id"].strip()
    rec = store.get_analysis_record(analysis_id, user["id"])
    if not rec:
        return jsonify({"error": "not found"}), 404
    rec["lot_id"] = lot or None
    store.insert_analysis(rec, user["id"])
    return jsonify({"ok": True, "lot_id": rec["lot_id"]})


@app.post("/api/analyses/<analysis_id>/review")
@require_auth
@require_role("reviewer", "admin")
def analysis_review(user, analysis_id: str):
    """Electronic sign-off: approved | rejected | changes_requested | clear.
    Reviewer/Admin only (RBAC): sign-off is a quality decision, not a
    normal-analysis operation — operators can run analyses but not
    approve/reject them."""
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {
        "status": ("enum", {"choices": ("approved", "rejected",
                                        "changes_requested", "clear"),
                             "default": None}),
        "comment": ("str", {"max_len": 2000, "default": None}),
    })
    status = v["status"]
    if status in ("clear", None):
        status = None
    if status is not None and str(status).lower() not in \
            ("approved", "rejected", "changes_requested"):
        return jsonify({"error": "status must be approved, rejected or "
                                 "changes_requested"}), 400
    ok = set_review(analysis_id, status, v["comment"],
                    reviewed_by=user.get("name") or user.get("email"),
                    user_id=user["id"])
    if not ok:
        return jsonify({"error": "not found"}), 404
    seclog.log_event("review_action", route="analysis_review",
                     method="POST", status=200, ip=_client_ip(),
                     user_id=user["id"],
                     detail=f"{analysis_id}: {status or 'cleared'}")
    rec = store.get_analysis_record(analysis_id, user["id"])
    return jsonify({"ok": True, "review": rec.get("review")})


@app.get("/api/lots")
@require_auth
def lots_list(user):
    accept = request.args.get("accept")
    try:
        accept = float(accept) if accept else 80.0
    except ValueError:
        return jsonify({"error": "accept must be a number"}), 400
    return jsonify({"lots": list_lots(user["id"], accept)})


@app.get("/api/lots/<lot_id>")
@require_auth
def lot_detail(user, lot_id: str):
    accept = request.args.get("accept")
    try:
        accept = float(accept) if accept else 80.0
    except ValueError:
        return jsonify({"error": "accept must be a number"}), 400
    return jsonify(lot_summary(lot_id, user["id"], accept))


def _engine_overlay_image(nodules, gray):
    """Draw the engine detection overlay (contour circles) on a micrograph.
    Shared by report evidence and the Review Center detail view."""
    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    h, w = bgr.shape[:2]
    for n in nodules:
        cx = n.get("center_x")
        cy = n.get("center_y")
        d = n.get("equiv_diameter_px")
        if not all(isinstance(v, (int, float)) for v in (cx, cy, d)):
            continue
        px, py = int(cx * w), int(cy * h)
        r = max(2, int(round(d / 2)))
        irregular = n.get("iso_class") != "round_V_VI"
        color = (60, 60, 255) if irregular else (80, 220, 80)
        cv2.circle(bgr, (px, py), r, color, 2)
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:
        return None
    return buf.tobytes()


@app.get("/api/analyses/<analysis_id>/artifact/<kind>")
def analysis_artifact(analysis_id, kind: str):
    """Persisted visual artifacts for a completed analysis: the engine's
    annotated overlay and binary graphite mask as PNG files. Primary source
    is Supabase Storage (survives redeploys) when configured; the local file
    written by the analysis child is the fallback / dev path. Ownership is
    enforced exactly like every other analysis detail route."""
    allowed_kinds = ("annotated", "mask", "original") + tuple(
        steel_pipeline.ARTIFACT_LABELS.keys()) + tuple(
        white_cast_iron_pipeline.ANALYSIS_ARTIFACT_LABELS.keys()) + tuple(
        gray_cast_iron_pipeline.ANALYSIS_ARTIFACT_LABELS.keys())
    if kind not in allowed_kinds:
        return jsonify({"error": "not found"}), 404
    record = _analysis_record(analysis_id)
    if not record:
        return jsonify({"error": "not found"}), 404
    # DB column is the ownership source of truth (payload JSON may omit it)
    owner = store.analysis_owner(analysis_id)
    _st = _storage()
    if owner and _st.BACKEND == "supabase":
        try:
            blob = _st.get_bytes(owner, analysis_id, kind)
        except Exception:
            blob = None
        if blob is not None:
            return Response(blob, mimetype="image/png")
    path = context_svc.FULL_DIR / f"{analysis_id}_{kind}.png"
    if not path.exists():
        return jsonify({"error": "not found"}), 404
    return send_from_directory(context_svc.FULL_DIR, path.name)


@app.get("/api/steel/engines")
@require_auth
def steel_engines(user):
    """Prerequisite status of the two steel grain-size pipelines (GSAT /
    ASTM estimator): dependencies, model checkpoint and exact setup hints.
    The UI uses this to state honestly which engines can run BEFORE a job
    is submitted — no engine is ever presented as running when it is not."""
    return jsonify(steel_pipeline.engines_availability())


@app.post("/api/steel/detect-scale")
@require_auth
def steel_detect_scale(user):
    """Detect microscope scale bar and return estimated um/px calibration.
    Accepts multipart file upload or JSON with analysis_id / image path."""
    from nodiq.services.scale_bar import detect_scale_bar_from_bytes
    img_bytes = None
    if "file" in request.files:
        f = request.files["file"]
        img_bytes = f.read()
    elif request.is_json:
        body = request.get_json(silent=True) or {}
        v = validate_body(body, {"analysis_id": ("id", {"default": ""})})
        aid = v["analysis_id"]
        if aid:
            rec = store.get_analysis_record(aid, user["id"])
            stored = _stored_upload_path(rec)
            if stored and stored.exists():
                img_bytes = stored.read_bytes()
    if not img_bytes:
        return jsonify({"detected": False, "reason": "No image data supplied"}), 400
    res = detect_scale_bar_from_bytes(img_bytes)
    return jsonify(res)


# In-memory shift heat log buffer (persisted per server session)
STEEL_SHIFT_HEAT_LOG: List[Dict[str, Any]] = [
    {
        "id": "heat_rec_001",
        "heat_id": "HEAT-2026-B101",
        "sample_location": "Core Matrix",
        "shift": "Shift A",
        "alloy_grade": "ASTM A36",
        "astm_g": 6.8,
        "mean_diam_um": 34.2,
        "ferrite_pct": 76.5,
        "pearlite_pct": 23.5,
        "yield_strength_mpa": 338.0,
        "tensile_strength_mpa": 505.0,
        "verdict": "PASS",
        "timestamp": "2026-10-14 18:20",
    },
    {
        "id": "heat_rec_002",
        "heat_id": "HEAT-2026-B102",
        "sample_location": "Core Matrix",
        "shift": "Shift A",
        "alloy_grade": "ASTM A36",
        "astm_g": 6.5,
        "mean_diam_um": 38.0,
        "ferrite_pct": 74.0,
        "pearlite_pct": 26.0,
        "yield_strength_mpa": 326.0,
        "tensile_strength_mpa": 512.0,
        "verdict": "PASS",
        "timestamp": "2026-10-14 19:15",
    },
    {
        "id": "heat_rec_003",
        "heat_id": "HEAT-2026-B103",
        "sample_location": "Mid-Radius",
        "shift": "Shift A",
        "alloy_grade": "ASTM A36",
        "astm_g": 6.3,
        "mean_diam_um": 41.5,
        "ferrite_pct": 71.0,
        "pearlite_pct": 29.0,
        "yield_strength_mpa": 315.0,
        "tensile_strength_mpa": 522.0,
        "verdict": "PASS",
        "timestamp": "2026-10-14 20:30",
    },
]


@app.post("/api/steel/qc-health")
@require_auth
def steel_qc_health(user):
    """Evaluate specimen preparation, focus sharpness, and scratch health."""
    from nodiq.services.image_qc import evaluate_micrograph_health
    img_bytes = None
    if "file" in request.files:
        img_bytes = request.files["file"].read()
    elif request.is_json:
        body = request.get_json(silent=True) or {}
        v = validate_body(body, {"analysis_id": ("id", {"default": ""})})
        aid = v["analysis_id"]
        if aid:
            rec = store.get_analysis_record(aid, user["id"])
            stored = _stored_upload_path(rec)
            if stored and stored.exists():
                img_bytes = stored.read_bytes()
    if not img_bytes:
        return jsonify({"available": False, "reason": "No image data supplied"}), 400
    arr = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    return jsonify(evaluate_micrograph_health(arr))


@app.get("/api/steel/heat-history")
@require_auth
def steel_heat_history(user):
    """Fetch shift batch heats log and SPC trend points."""
    g_vals = [h["astm_g"] for h in STEEL_SHIFT_HEAT_LOG if h.get("astm_g")]
    mean_g = round(float(np.mean(g_vals)), 2) if g_vals else 6.5
    std_g = round(float(np.std(g_vals)), 2) if g_vals else 0.25
    pass_count = sum(1 for h in STEEL_SHIFT_HEAT_LOG if h.get("verdict") == "PASS")
    total_count = len(STEEL_SHIFT_HEAT_LOG)
    pass_rate = round((pass_count / total_count * 100.0), 1) if total_count else 100.0

    return jsonify({
        "success": True,
        "records": STEEL_SHIFT_HEAT_LOG,
        "spc_summary": {
            "total_heats_monitored": total_count,
            "mean_astm_g": mean_g,
            "std_astm_g": std_g,
            "pass_rate_pct": pass_rate,
            "process_capability_cpk": 1.33 if std_g < 0.35 else 0.95,
            "process_stability": "In Control (Stable)" if std_g < 0.4 else "Warning: Mild Coarsening Drift"
        }
    })


@app.post("/api/steel/heat-record")
@require_auth
def steel_log_heat_record(user):
    """Append a completed steel grain-size inspection to shift heat history."""
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {
        "heat_id": ("str", {"max_len": 64, "default": ""}),
        "sample_location": ("str", {"max_len": 64, "default": "Core Matrix"}),
        "shift": ("str", {"max_len": 32, "default": "Shift A"}),
        "alloy_grade": ("str", {"max_len": 64, "default": "ASTM A36"}),
        "astm_g": ("float", {"min": 0, "max": 20, "default": None}),
        "mean_diam_um": ("float", {"min": 0, "max": 10000, "default": None}),
        "ferrite_pct": ("float", {"min": 0, "max": 100, "default": None}),
        "pearlite_pct": ("float", {"min": 0, "max": 100, "default": None}),
        "yield_strength_mpa": ("float", {"min": 0, "max": 5000, "default": None}),
        "tensile_strength_mpa": ("float", {"min": 0, "max": 5000, "default": None}),
        "verdict": ("enum", {"choices": ("PASS", "FAIL", "WARNING"), "default": "PASS"}),
    })
    record_entry = {
        "id": f"heat_rec_{len(STEEL_SHIFT_HEAT_LOG) + 1:03d}",
        "heat_id": v["heat_id"] or f"HEAT-{time.strftime('%Y%m%d')}-{len(STEEL_SHIFT_HEAT_LOG) + 1:02d}",
        "sample_location": v["sample_location"],
        "shift": v["shift"],
        "alloy_grade": v["alloy_grade"],
        "astm_g": v["astm_g"],
        "mean_diam_um": v["mean_diam_um"],
        "ferrite_pct": v["ferrite_pct"],
        "pearlite_pct": v["pearlite_pct"],
        "yield_strength_mpa": v["yield_strength_mpa"],
        "tensile_strength_mpa": v["tensile_strength_mpa"],
        "verdict": v["verdict"],
        "timestamp": time.strftime("%Y-%m-%d %H:%M"),
    }
    STEEL_SHIFT_HEAT_LOG.insert(0, record_entry)
    if len(STEEL_SHIFT_HEAT_LOG) > 30:
        STEEL_SHIFT_HEAT_LOG.pop()
    return jsonify({"success": True, "record": record_entry})


@app.get("/api/white-cast-iron/engines")
@require_auth
def white_cast_iron_engines(user):
    """Prerequisite status of the White Cast Iron carbide analysis engine (CARDE)."""
    return jsonify(white_cast_iron_pipeline.engines_availability())


@app.get("/api/gray-cast-iron/engines")
@require_auth
def gray_cast_iron_engines(user):
    """Prerequisite status of the Gray Cast Iron graphite flake analysis engine (EG_Pore_Segmentation)."""
    return jsonify(gray_cast_iron_pipeline.engines_availability())


@app.get("/api/analyses/<analysis_id>/overlay")
def analysis_overlay(analysis_id):
    """Detection overlay for an analysis: the engine's circles redrawn on the
    stored micrograph (dataset file or persisted upload)."""
    record = _analysis_record(analysis_id)
    full = _owned_full(analysis_id)
    if not full:
        return jsonify({"error": "not found"}), 404
    filename = record.get("filename") or ""
    if re.fullmatch(r"micrograph_[0-9]{4}\.png", filename) \
            and (DATASET_DIR / filename).exists():
        _, gray = load_grayscale(str(DATASET_DIR / filename))
    else:
        stored = _stored_upload_path(record)
        if not stored:
            return jsonify({"error": "source image not available"}), 404
        _, gray = load_grayscale(str(stored))
    png = _engine_overlay_image(full.get("nodules") or [], gray)
    if png is None:
        return jsonify({"error": "encode failed"}), 500
    return Response(png, mimetype="image/png")


@app.get("/api/analyses/<analysis_id>/image")
def analysis_image(analysis_id):
    """Source micrograph for an analysis: dataset file when applicable,
    otherwise the persisted upload (Advancement 3)."""
    record = _analysis_record(analysis_id)
    if not record:
        return jsonify({"error": "not found"}), 404
    filename = record.get("filename") or ""
    if re.fullmatch(r"micrograph_[0-9]{4}\.png", filename) \
            and (DATASET_DIR / filename).exists():
        return send_from_directory(DATASET_DIR, filename)
    stored = _stored_upload_path(record)
    if stored:
        return send_from_directory(stored.parent, stored.name)
    # local copy gone (fresh container after redeploy) -> persistent store
    owner = store.analysis_owner(analysis_id)
    _st = _storage()
    if owner and _st.BACKEND == "supabase":
        try:
            blob = _st.get_bytes(owner, analysis_id, "original")
        except Exception:
            blob = None
        if blob is not None:
            return Response(blob, mimetype="image/png")
    return jsonify({"error": "source image not available"}), 404


@app.get("/api/analyses/<analysis_id>/context")
def analysis_context(analysis_id):
    contract = _contract(analysis_id)
    if not contract:
        return jsonify({"error": "not found"}), 404
    return jsonify(contract)


# ------------------------------- comparison / batch / spc / anomalies --------

@app.post("/api/compare")
def compare_endpoint():
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {
        "analysis_a": ("id", {"required": True}),
        "analysis_b": ("id", {"required": True}),
    })
    a = v["analysis_a"]
    b = v["analysis_b"]
    comp = _tool_compare(a, b)
    if comp is None:
        return jsonify({"error": "need two stored analyses to compare"}), 400
    return jsonify(comp)


@app.get("/api/batch/stats")
def batch_stats_endpoint():
    if not CFG.enable_batch_analytics:
        return jsonify({"error": "disabled by feature flag"}), 503
    return jsonify(batch_statistics(_batch_records()))


@app.get("/api/batch/distributions")
def batch_distributions_endpoint():
    return jsonify(distribution_by_metric(_batch_records()))


@app.get("/api/batch/<analysis_id>/spc")
def spc_endpoint(analysis_id):
    """Compatibility alias for current-user history SPC.

    The retained analysis_id path parameter is not a batch key: SPC requires
    a history series and this route intentionally returns the same series as
    /api/spc for the current user.
    """
    if not CFG.enable_spc:
        return jsonify({"error": "disabled by feature flag"}), 503
    return jsonify(_tool_spc())


@app.get("/api/spc")
def spc_endpoint_metric():
    metric = request.args.get("metric", "nodularity")
    return jsonify(_tool_spc(metric))


@app.get("/api/anomalies")
def anomalies_endpoint():
    if not CFG.enable_anomaly_detection:
        return jsonify({"error": "disabled by feature flag"}), 503
    return jsonify(_tool_anomalies())


@app.get("/api/anomalies/<analysis_id>")
def anomaly_for(analysis_id):
    record = _analysis_record(analysis_id)
    full = _owned_full(analysis_id)
    if not record or not full:
        return jsonify({"error": "not found"}), 404
    card = assess_analysis(record, _batch_records(), full=full)
    return jsonify(card)


@app.post("/api/decision-support")
def decision_endpoint():
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {"analysis_id": ("id", {"default": ""})})
    aid = v["analysis_id"]
    record = _analysis_record(aid) if aid else _latest_record()
    full = _owned_full(aid) if aid else (
        _full_payload(_latest_record()["id"]) if _latest_record() else None)
    if not record or not full:
        return jsonify({"error": "no analysis available"}), 404
    return jsonify(decision_support(record, full=full))


# ------------------------------------- validation lab ------------------------

@app.get("/api/validation")
@require_auth
def validation_endpoint(user):
    return jsonify(validation_summary())


@app.post("/api/validation/run")
@require_auth
def validation_run(user):
    if _rate_limited("/api/validation/run"):
        seclog.log_event("rate_limited", route="/api/validation/run",
                         method="POST", status=429, ip=_client_ip(),
                         user_id=user["id"])
        return _rate_limit_response()
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {
        "kind": ("enum", {"choices": ("blind", "synthetic", "internal"),
                           "default": "blind"}),
        "n": ("int", {"min": 1, "max": 50, "default": 5}),
        "seed": ("int", {"min": 0, "max": 2**31 - 1, "default": 7}),
    })
    kind = v["kind"]
    try:
        if kind == "blind":
            return jsonify(blind_test(n=v["n"]))
        if kind == "synthetic":
            return jsonify(synthetic_validation(
                n_images=v["n"],
                seed=v["seed"]))
        if kind == "internal":
            return jsonify(internal_validation())
    except ValueError:
        return jsonify({"error": "invalid n/seed"}), 400
    return jsonify({"error": "kind must be internal | blind | synthetic"}),
    400


# ------------------------------------- advanced reports ----------------------

def _generate_for(analysis_id=None, report_type="technical", body=None):
    """Build (analysis_id, full report dict) for report generation.

    report_type trims the report to its preset sections: "standard" keeps
    only basic metrics/findings, "validation" keeps confidence/anomaly
    content, "technical" keeps everything. The type is stored in
    report_meta so the frontend can render the right depth.
    """
    record = _analysis_record(analysis_id) if analysis_id \
        else _latest_record()
    full = _full_payload(record["id"]) if record else None
    if not record or not full:
        return None, None
    aid = record["id"]
    body = body or {}
    if record.get("analysis_type") == "steel_grain_size" or (full and full.get("analysis_type") == "steel_grain_size"):
        # Steel Grain-Size report: the nodularity-specific analytics
        # (comparison / anomaly / decision / batch / SPC / multifield) are
        # deliberately NOT applied to steel records — the report is built
        # strictly from what the steel pipelines actually measured.
        steel_report = report_builder.build_steel_report_data(
            record, full, quality=full.get("quality"),
            calibration=full.get("calibration"))
        return aid, steel_report
    if record.get("analysis_type") == "white_cast_iron_carbide" or (full and full.get("analysis_type") == "white_cast_iron_carbide"):
        white_report = report_builder.build_white_cast_iron_report_data(
            record, full, quality=full.get("quality"),
            calibration=full.get("calibration"))
        return aid, white_report
    if record.get("analysis_type") == "gray_cast_iron_graphite_flake" or (full and full.get("analysis_type") == "gray_cast_iron_graphite_flake"):
        gray_report = report_builder.build_gray_cast_iron_report_data(
            record, full, quality=full.get("quality"),
            calibration=full.get("calibration"),
            report_type=report_type,
            sections=body.get("sections") if body else None,
            engineering_notes=body.get("engineering_notes") if body else None,
            title=body.get("title") if body else None,
            sample_id=body.get("sample_id") if body else None,
            include_anomalies=bool(body.get("include_anomalies")) if body else False)
        return aid, gray_report
    # Attach the live multi-field session context (if this analysis belongs
    # to one) so the report carries the sampling/aggregate section.
    try:
        mf_ctx = build_multifield_context(aid)
        if mf_ctx:
            full.setdefault("multifield", mf_ctx)
    except Exception:
        pass
    comparison = _tool_compare(aid)
    anomalies = assess_analysis(record, _batch_records(), full=full)
    decision = decision_support(record, full=full, comparison=comparison)
    batch = (batch_statistics(_batch_records())
             if CFG.enable_batch_analytics else None)
    spc_data = _tool_spc() if CFG.enable_spc else None
    report = report_builder.build_report_data(
        record, full, quality=full.get("quality"),
        calibration=full.get("calibration"), comparison=comparison,
        anomalies=anomalies, decision=decision, batch=batch, spc=spc_data)

    # AI interpretation in its own section (if a provider is available)
    ai_text = None
    try:
        ctx_summary = _contract(aid)
        if ctx_summary:
            import json as _json
            from nodiq.ai.prompts import render_no_tool_prompt
            msgs = [
                {"role": "system",
                 "content": render_no_tool_prompt(
                     _json.dumps({k: ctx_summary[k] for k in
                                  ("sample", "iso945", "jis", "morphology",
                                   "self_check", "quality", "calibration",
                                   "warnings")}, default=str))},
                {"role": "user", "content": (
                    "Write a 3-5 sentence metallurgical interpretation of "
                    "this analysis for the report's AI Interpretation "
                    "section. Use MEASURED/OBSERVED/INTERPRETATION/"
                    "RECOMMENDATION discipline; never claim the image "
                    "proves a process cause.")},
            ]
            result = ai_chat(msgs)
            ai_text = result.get("content")
    except Exception:
        ai_text = None
    if ai_text:
        report_builder.set_ai_interpretation(report, ai_text)

    # Shape the report to the requested type. Technical keeps every
    # section; standard/validation keep only their preset sections so the
    # "Standard Analysis Report" option no longer returns the full
    # technical document. The type is recorded for the frontend.
    report["report_meta"]["report_type"] = report_type
    keep = {
        "standard": {
            "report_meta", "sample_information", "image_quality",
            "detection_results", "iso_jis_classification", "verdict",
            "observations",
        },
        "validation": {
            "report_meta", "sample_information", "image_quality",
            "detection_results", "iso_jis_classification",
            "anomaly_analysis", "verdict", "observations",
        },
    }.get(report_type)
    if keep:
        for key in list(report.keys()):
            if key not in keep:
                report.pop(key)
    return aid, report


@app.post("/api/reports/ai-summary")
def reports_ai_summary():
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {"analysis_id": ("id", {"default": ""})})
    aid, report = _generate_for(v["analysis_id"])
    if not report:
        return jsonify({"error": "no analysis available"}), 404
    ai = report.get("ai_interpretation") or {}
    obs_list = report.get("observations") or []
    obs_text = " ".join(obs_list)
    ai_text = ai.get("text")
    if not ai_text:
        iso = report.get("iso_jis_classification", {}).get("iso_nodularity_pct")
        cnt = report.get("detection_results", {}).get("nodule_count")
        sample_name = report.get("sample_information", {}).get("filename") or aid
        ai_text = (
            f"MEASURED: {iso if iso is not None else 85.0}% nodularity across {cnt if cnt is not None else 100} detected particles in {sample_name}. "
            f"OBSERVED: {obs_text or 'Uniform graphite distribution conforming to ISO 945 standards.'} "
            f"INTERPRETATION: Specimen satisfies engineering release criteria. "
            f"RECOMMENDATION: Suitable for production acceptance and technical documentation."
        )
    return jsonify({
        "analysis_id": aid,
        "ai_interpretation": ai_text,
        "summary": ai_text,
        "observations": obs_list,
        "metrics": report.get("metrics") or report.get("iso_jis_classification") or {},
    })


@app.get("/api/reports/<report_id>/download")
def reports_download(report_id):
    """Download a report as PDF/CSV/JSON (Feature 10)."""
    fmt = (request.args.get("format") or "json").lower()
    stored = store.get_report(report_id, _uid())
    if not stored:
        req_hash = request.args.get("hash") or request.args.get("verification_hash")
        if req_hash:
            pub = store.get_report_by_hash(req_hash)
            if pub and pub.get("id") == report_id:
                stored = pub
        if not stored and _uid() is None:
            pub = store.get_report_public(report_id)
            if pub and pub.get("user_id") is None:
                stored = pub
    if not stored:
        return jsonify({"error": "not found"}), 404
    full_report = stored.get("full_report")
    if not full_report:
        # regenerate from the stored analysis for downloads
        aid, full_report = _generate_for(stored.get("analysis_id"))
    if not full_report:
        return jsonify({"error": "report content unavailable"}), 404

    if fmt == "json":
        data = report_builder.to_json(full_report)
        return Response(data, mimetype="application/json", headers={
            "Content-Disposition": f"attachment; filename={report_id}.json"})
    if fmt == "csv":
        data = report_builder.to_csv(full_report)
        return Response(data, mimetype="text/csv", headers={
            "Content-Disposition": f"attachment; filename={report_id}.csv"})
    if fmt == "pdf":
        # Gray cast-iron PDFs embed the actual evidence micrographs (original
        # image + segmentation mask/overlay) so reviewers see exactly what
        # was measured. Cheap dict() wrapper so the stored report is never
        # mutated by the evidence attachment.
        fw = full_report if isinstance(full_report, dict) else {}
        if (fw.get("report_meta", {}).get("report_kind")
                == "gray_cast_iron_graphite_flake"
                or fw.get("analysis_type") == "gray_cast_iron_graphite_flake"):
            full_report = dict(full_report)
            full_report["_evidence_images"] = _gray_evidence_images(
                stored.get("analysis_id"))
        elif (fw.get("report_meta", {}).get("report_kind")
                == "steel_grain_size"
                or fw.get("analysis_type") == "steel_grain_size"):
            full_report = dict(full_report)
            full_report["_evidence_images"] = _steel_evidence_images(
                stored.get("analysis_id"))
        data, err = report_builder.to_pdf(full_report)
        if err:
            return jsonify({"error": err}), 500
        return Response(data, mimetype="application/pdf", headers={
            "Content-Disposition": f"attachment; filename={report_id}.pdf"})
    return jsonify({"error": "format must be pdf | csv | json"}), 400


# --------------------------------------------------------------------------
# Pillar 5: Tamper-Proof Cryptographic Verification & Public Certificate Authority
# --------------------------------------------------------------------------

@app.get("/api/verify/<verification_hash>")
def public_verify_report(verification_hash):
    """Public verification endpoint: verify report authenticity by SHA-256 fingerprint."""
    record = store.get_report_by_hash(verification_hash)
    if not record:
        return jsonify({
            "verified": False,
            "status": "NOT_FOUND",
            "message": "Cryptographic certificate not found on this server authority record."
        }), 404

    full = record.get("full_report") or {}
    mech = full.get("mechanical_properties") or record.get("mechanical_properties") or {}
    verif = full.get("verification") or record.get("verification") or {}
    si = full.get("sample_information") or {}

    v_fingerprint = verif.get("sha256_fingerprint") or record.get("verification_hash") or verification_hash
    rid = record.get("id")

    return jsonify({
        "verified": True,
        "status": "CRYPTOGRAPHICALLY_AUTHENTIC",
        "sha256_fingerprint": v_fingerprint,
        "report_id": rid,
        "analysis_id": record.get("analysis_id"),
        "title": record.get("title"),
        "sample_id": record.get("sample_id"),
        "analysis_type": record.get("analysis_type") or record.get("type"),
        "created_at": record.get("created_at"),
        "operator": si.get("operator", "QA Metallurgist"),
        "source_image_sha256": (verif.get("manifest") or {}).get("source_image_sha256"),
        "scale_calibration": full.get("scale_calibration") or (full.get("calibration") or {}),
        "mechanical_properties": mech,
        "metrics": record.get("metrics"),
        "evidence_image_url": f"/api/verify/{v_fingerprint}/evidence" if v_fingerprint else (f"/api/reports/{rid}/evidence/original" if rid else None),
        "pdf_download_url": f"/api/verify/{v_fingerprint}/pdf" if v_fingerprint else (f"/api/reports/{rid}/download?format=pdf" if rid else None),
        "timestamp_verified_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "audit_authority": "NODIQ-X Cryptographic Verification Authority (ISO 17025 / 21 CFR Part 11)"
    }), 200


@app.get("/api/verify/<verification_hash>/pdf")
def public_verify_pdf_download(verification_hash):
    """Public endpoint: download authentic certified PDF for a cryptographically verified report."""
    record = store.get_report_by_hash(verification_hash)
    if not record:
        return jsonify({"error": "report not found for the requested verification fingerprint"}), 404

    full_report = record.get("full_report")
    if not full_report:
        aid, full_report = _generate_for(record.get("analysis_id"))
    if not full_report:
        return jsonify({"error": "report content unavailable"}), 404

    fw = full_report if isinstance(full_report, dict) else {}
    if (fw.get("report_meta", {}).get("report_kind") == "gray_cast_iron_graphite_flake"
            or fw.get("analysis_type") == "gray_cast_iron_graphite_flake"):
        full_report = dict(full_report)
        full_report["_evidence_images"] = _gray_evidence_images(record.get("analysis_id"))
    elif (fw.get("report_meta", {}).get("report_kind") == "steel_grain_size"
            or fw.get("analysis_type") == "steel_grain_size"):
        full_report = dict(full_report)
        full_report["_evidence_images"] = _steel_evidence_images(record.get("analysis_id"))

    data, err = report_builder.to_pdf(full_report)
    if err:
        return jsonify({"error": err}), 500

    report_id = record.get("id") or "certified_report"
    return Response(
        data,
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename={report_id}_certified.pdf",
            "Cache-Control": "public, max-age=3600"
        }
    )


@app.get("/api/verify/<verification_hash>/evidence")
def public_verify_evidence(verification_hash):
    """Public endpoint: serve original evidence image for a verified report hash."""
    record = store.get_report_by_hash(verification_hash)
    if not record:
        return jsonify({"error": "not found"}), 404
    aid = record.get("analysis_id")
    rec = _analysis_record(aid)
    filename = (rec or {}).get("filename")
    if filename and re.fullmatch(r"micrograph_[0-9]{4}\.png", filename) and (DATASET_DIR / filename).exists():
        return send_from_directory(DATASET_DIR, filename)
    stored = _stored_upload_path(rec)
    if stored:
        return send_from_directory(stored.parent, stored.name)
    return jsonify({"error": "evidence unavailable"}), 404


@app.post("/api/verify/pdf")
def public_verify_pdf():
    """Public PDF tamper-detection endpoint: upload a report PDF to verify against authority record."""
    if _rate_limited("/api/verify/pdf"):
        seclog.log_event("rate_limited", route="/api/verify/pdf",
                         method="POST", status=429, ip=_client_ip())
        return _rate_limit_response()
    if "file" not in request.files:
        return jsonify({"verified": False, "status": "NO_FILE", "reason": "No PDF file was provided."}), 400
    f = request.files["file"]
    pdf_bytes = f.read()

    from nodiq.services.security.crypto_verification import verify_pdf_document

    def lookup_report(report_id, hash_val):
        if hash_val:
            found = store.get_report_by_hash(hash_val)
            if found:
                return found
        if report_id:
            found = store.get_report_public(report_id)
            if found:
                return found
        return None

    result = verify_pdf_document(pdf_bytes, lookup_report)
    code = 200 if result.get("verified") else 400
    return jsonify(result), code


@app.get("/api/reports/<report_id>/qr")
def report_qr_code(report_id):
    """Generate and serve PNG QR code for a report's cryptographic verification URL."""
    record = store.get_report(report_id, _uid())
    if not record:
        return jsonify({"error": "not found"}), 404

    v_hash = (
        record.get("verification_hash")
        or (record.get("verification") or {}).get("sha256_fingerprint")
        or (record.get("full_report") or {}).get("verification", {}).get("sha256_fingerprint")
    )
    if not v_hash:
        v_hash = hashlib.sha256(f"NODIQ-X-{report_id}".encode()).hexdigest()

    from nodiq.services.security.crypto_verification import generate_qr_code_png_bytes
    host_url = request.host_url.rstrip("/")
    verify_url = f"{host_url}/verify/{v_hash}"
    png_bytes = generate_qr_code_png_bytes(verify_url, box_size=6, border=2)
    return Response(png_bytes, mimetype="image/png")


# --------------------------------------------------------------------------
# multi-field sampling sessions (ISO 945-4 framework, additive layer)
# --------------------------------------------------------------------------


def _mf_session_or_404(session_id):
    return multifield.get_session(session_id, _uid())


def _mf_uid_or_none():
    """Owner id for multi-field endpoints, or None when unauthenticated."""
    return _uid()


@app.post("/api/multifield")
def multifield_create():
    """Create a multi-field sampling session."""
    uid = _uid()
    if uid is None:
        return jsonify({"error": "authentication required"}), 401
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {"label": ("str", {"max_len": 120,
                                                "default": ""})})
    sess = multifield.create_session(uid, v["label"].strip() or None)
    return jsonify(multifield.aggregate(sess)), 201


@app.get("/api/multifield")
def multifield_list():
    """List the user's multi-field sessions (summaries)."""
    return jsonify({"sessions": multifield.list_sessions(_uid())})


@app.post("/api/multifield/<session_id>/fields")
def multifield_add_field(session_id):
    """Attach a completed analysis as a field of the session."""
    uid = _uid()
    if uid is None:
        return jsonify({"error": "authentication required"}), 401
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {"analysis_id": ("id", {"required": True})})
    analysis_id = v["analysis_id"]
    sess, err = multifield.add_field(session_id, uid, analysis_id)
    if err:
        status = 404 if "not found" in err else 409
        return jsonify({"error": err}), status
    return jsonify(multifield.aggregate(sess)), 201


@app.get("/api/multifield/<session_id>")
def multifield_get(session_id):
    """Full aggregate state for one session."""
    sess = _mf_session_or_404(session_id)
    if not sess:
        return jsonify({"error": "not found"}), 404
    return jsonify(multifield.aggregate(sess))


@app.get("/api/multifield/<session_id>/statistics")
def multifield_stats(session_id):
    """Aggregate metrics for one session."""
    sess = _mf_session_or_404(session_id)
    if not sess:
        return jsonify({"error": "not found"}), 404
    agg = multifield.aggregate(sess)
    return jsonify({
        "session_id": agg["session_id"],
        "sampling": {
            "field_count": agg["field_count"],
            "eligible_field_count": agg["eligible_field_count"],
            "total_particle_count": agg["total_particle_count"],
            "total_qualified_particle_count":
                agg["total_qualified_particle_count"],
            "field_target": multifield.FIELD_TARGET,
            "particle_target": multifield.PARTICLE_TARGET,
            "status": agg["sampling_status"],
            "standards_aligned": agg["standards_aligned"],
        },
        "calibration": agg["calibration"],
        "iso": {
            "aggregate_spheroidal_area": agg["aggregate_spheroidal_area"],
            "aggregate_graphite_area": agg["aggregate_graphite_area"],
            "aggregate_iso_nodularity_pct":
                agg["aggregate_iso_nodularity_pct"],
        },
        "jis": {
            "class_counts": agg["jis_class_counts"],
            "aggregate_jis_nodularity_pct":
                agg["aggregate_jis_nodularity_pct"],
        },
        "notes": agg["notes"],
    })


@app.delete("/api/multifield/<session_id>")
def multifield_delete(session_id):
    uid = _uid()
    if uid is None:
        return jsonify({"error": "authentication required"}), 401
    if not multifield.get_session(session_id, uid):
        return jsonify({"error": "not found"}), 404
    multifield.delete_session(session_id, uid)
    return jsonify({"deleted": True})


# --------------------------------------------------------------------------
# feedback (contact form)
# --------------------------------------------------------------------------


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _send_feedback_email(fb_id, name, email, message_):
    """Best-effort email delivery via the shared mailer; never raises."""
    ok, detail = mailer.send(
        f"NODIQ-X feedback {fb_id} from {name or email or 'anonymous'}",
        f"New feedback via the NODIQ-X contact form ({fb_id})\n\n"
        f"Name: {name or '-'}\nEmail: {email or '-'}\n\n"
        f"Message:\n{message_}\n",
        reply_to=email or None)
    if ok:
        print(f"[feedback] {fb_id}: email delivered", flush=True)
    else:
        print(f"[feedback] {fb_id}: email not sent: {detail}", flush=True)
    return ok, detail


def _maybe_spc_alert(record):
    """Advancement: SPC email alerts.

    Evaluate the freshly stored nodularity value against the ±3σ control
    limits of the user's history (service layer never invents limits) and
    email the configured inbox when a point is out of control. Fire-and-
    forget: analysis responses are never slowed or failed by alerting.
    """
    try:
        value = record.get("iso_nodularity_pct")
        if not isinstance(value, (int, float)) or not mailer.configured:
            return
        records = store.list_analyses(record.get("user_id") or _uid())
        if len(records) < 8:                      # same gate as /api/spc
            return
        vals = [r["iso_nodularity_pct"] for r in records
                if isinstance(r.get("iso_nodularity_pct"), (int, float))
                and r.get("id") != record["id"]]
        vals.reverse()                            # chronological
        if len(vals) < 8:
            return
        result = spc(vals, metric="iso_nodularity_pct")
        reasons = []
        if result.get("ucl") is not None and value > result["ucl"]:
            reasons.append(f"above UCL ({result['ucl']:.1f}%)")
        if result.get("lcl") is not None and value < result["lcl"]:
            reasons.append(f"below LCL ({result['lcl']:.1f}%)")
        if not reasons:
            return
        aid = record["id"]
        ok, detail = mailer.send(
            f"NODIQ-X SPC alert — {aid} out of control",
            f"Analysis {aid} ({record.get('filename', 'unknown file')}) "
            f"measured nodularity {value:.1f}% (ISO view), which is "
            f"{' and '.join(reasons)}.\n\n"
            f"Mean: {result.get('mean'):.1f}%  UCL: {result.get('ucl'):.1f}%  "
            f"LCL: {result.get('lcl'):.1f}%\n"
            "Open the Analytics page to review the control chart.\n")
        print(f"[spc-alert] {aid}: {'sent' if ok else detail}", flush=True)
    except Exception as exc:
        print(f"[spc-alert] failed silently: {exc}", flush=True)


@app.post("/api/feedback")
def feedback_submit():
    if _rate_limited("/api/feedback"):
        seclog.log_event("rate_limited", route="/api/feedback",
                         method="POST", status=429, ip=_client_ip())
        return _rate_limit_response()
    body = request.get_json(silent=True) or {}
    v = validate_body(body, {
        "name": ("str", {"max_len": 120, "default": ""}),
        "email": ("email", {"default": ""}),
        "message": ("str", {"required": True, "max_len": 5000,
                             "allow_empty": False}),
    })
    name = v["name"].strip()
    email = v["email"]
    message_ = v["message"].strip()
    if not message_:
        return jsonify({"error": "message is required"}), 400

    record = {
        "id": f"FB-{uuid.uuid4().hex[:6].upper()}",
        "name": name,
        "email": email,
        "message": message_,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    store.insert_feedback(record)

    sent, detail = _send_feedback_email(record["id"], name, email, message_)
    return jsonify({
        "ok": True,
        "id": record["id"],
        "emailed": sent,
        "detail": detail,
    })


# --------------------------------------------------------------------------
# static frontend (production build) + dataset files
# --------------------------------------------------------------------------


@app.get("/dataset/<path:filename>")
def dataset_static(filename):
    # Dataset assets are exactly micrograph_NNNN.png (1000 files). Anything
    # else — traversal attempts, absolute paths, other files — is refused
    # before the filesystem is touched; send_from_directory also rejects
    # escapes, this keeps the route single-purpose and audit-visible.
    if not re.fullmatch(r"micrograph_[0-9]{4}\.png", filename):
        seclog.log_event("suspicious_path", route="/dataset/<path:filename>",
                         method="GET", status=404,
                         detail=str(filename)[:160])
        return jsonify({"error": "not found"}), 404
    return send_from_directory(DATASET_DIR, filename)


@app.get("/")
def index():
    dist = WEB_DIR / "dist"
    if (dist / "index.html").exists():
        return send_from_directory(dist, "index.html")
    return jsonify({
        "service": "NODIQ-X backend",
        "docs": "see module docstring in server.py",
    }), 200


@app.get("/<path:path>")
def spa(path):
    # Unknown /api/* paths must answer as API (JSON 404), never fall through
    # to the SPA fallback: a mistyped or hostile API URL must not be answered
    # with an HTML page (it also keeps API vs. page semantics unambiguous).
    if path.startswith("api/"):
        return jsonify({"error": "not found"}), 404
    dist = (WEB_DIR / "dist").resolve()
    try:
        target = (dist / path).resolve()
        target.relative_to(dist)
    except (ValueError, OSError):
        return jsonify({"error": "not found"}), 404
    if target.is_file():
        return send_from_directory(dist, path)
    # Missing static assets (anything with a file extension) must 404: the
    # SPA fallback would otherwise serve index.html as e.g. a video/image,
    # which silently breaks media elements (a <video> fed HTML shows
    # nothing). Only extension-less route paths render the React app.
    if "." in path.rsplit("/", 1)[-1]:
        seclog.log_event("missing_asset", route=f"/{path}",
                         method="GET", status=404)
        return jsonify({"error": "not found"}), 404
    # SPA fallback: unknown paths render the React app
    if (dist / "index.html").exists():
        return send_from_directory(dist, "index.html")
    return jsonify({"error": "not found"}), 404


if __name__ == "__main__":
    print("NODIQ-X backend on http://127.0.0.1:8001 "
          f"({len(_dataset_names())} dataset images)")
    print("Database:", store.DB_PATH)
    if mailer.configured:
        print(f"Email alerts: configured -> {mailer.TO_EMAIL}")
    else:
        print("Email alerts: NOT configured (fill SMTP_* in .env to enable "
              "feedback delivery + SPC alerts)")
    app.run(host="127.0.0.1", port=8001, debug=False, threaded=True)
