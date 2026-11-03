#!/usr/bin/env python3
"""
ai/memory.py — Copilot conversation memory (Phases 16, 29).

Per-session storage in server_data/copilot_sessions/<session_id>.json:
messages, tool calls and the referenced-analysis id so "compare it with B"
resolves from context. Sessions are lightweight and expire; only technical
content is kept — no credentials, no personal data beyond the chat text.
"""
import json
import threading
import time
from pathlib import Path

from nodiq.services.context import DATA_DIR

SESSIONS_DIR = DATA_DIR / "copilot_sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

_LOCK = threading.Lock()
MAX_MESSAGES = 60          # keep last 60 messages per session
SESSION_TTL = 12 * 3600    # 12h


def _safe_name(text):
    return "".join(c for c in str(text) if c.isalnum() or c in "-_")


def _path(session_id, owner_id=None):
    """Session file path. When an owner is given the file is namespaced to
    that account (owner--session.json), so user A can never read or append
    to user B's conversation by guessing a session id."""
    safe = _safe_name(session_id) or "default"
    if owner_id:
        return SESSIONS_DIR / f"{_safe_name(owner_id)}--{safe}.json"
    return SESSIONS_DIR / f"{safe}.json"


def load_session(session_id, owner_id=None):
    p = _path(session_id, owner_id)
    if not p.exists():
        return {"session_id": session_id, "messages": [],
                "tool_calls": [], "referenced_analysis_id": None,
                "created_at": time.time()}
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        s = {"session_id": session_id, "messages": [], "tool_calls": [],
             "referenced_analysis_id": None, "created_at": time.time()}
    # defense in depth: a file found outside the owner namespace (legacy
    # layout or a colliding id) is treated as empty for this caller
    if owner_id and s.get("owner_id") != str(owner_id):
        return {"session_id": session_id, "owner_id": str(owner_id),
                "messages": [], "tool_calls": [],
                "referenced_analysis_id": None,
                "created_at": time.time()}
    return s


def save_session(session):
    session["updated_at"] = time.time()
    cutoff = time.time() - SESSION_TTL
    session["messages"] = session["messages"][-MAX_MESSAGES:]
    with _LOCK:
        _path(session["session_id"],
              session.get("owner_id")).write_text(
            json.dumps(session), encoding="utf-8")
    # opportunistic cleanup of stale sessions
    try:
        for f in SESSIONS_DIR.glob("*.json"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
    except Exception:
        pass


def append_message(session, role, content, meta=None):
    session["messages"].append({
        "role": role,
        "content": content,
        "ts": time.time(),
        **({"meta": meta} if meta else {}),
    })


def recent_messages(session, limit=12):
    """Last N messages formatted for the LLM (role/content only)."""
    return [{"role": m["role"], "content": m.get("content", "")}
            for m in session["messages"][-limit:]]


def set_referenced_analysis(session, analysis_id):
    """Track the analysis the conversation is 'about' (Phase 16)."""
    if analysis_id:
        session["referenced_analysis_id"] = analysis_id


def referenced_analysis_id(session):
    return session.get("referenced_analysis_id")


def resolve_reference(session, text):
    """Resolve 'this/that/the sample/the previous one' to the tracked id."""
    if not text:
        return referenced_analysis_id(session)
    low = text.lower()
    if any(w in low for w in ("this sample", "this analysis", "current",
                              "it", "this one")):
        return referenced_analysis_id(session)
    return referenced_analysis_id(session)
