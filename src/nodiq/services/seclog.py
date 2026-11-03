#!/usr/bin/env python3
"""
services/seclog.py — structured security event logging.

Records auth/authorization/validation/rate-limit events server-side with
useful metadata and NEVER any credential material: no passwords, tokens,
JWTs, API keys, Authorization headers, or request bodies.

Events are JSON lines in server_data/security.log (gitignored via the
server_data rule). IP addresses are recorded because brute-force defense
depends on them; the file sits next to the user database and inherits the
same access controls.
"""
import json
import threading
import time
from pathlib import Path

from nodiq.core.config import DATA_DIR

_LOG_PATH = DATA_DIR / "security.log"
_log_lock = threading.Lock()

FIELDS = ("event", "route", "method", "status", "ip", "user_id",
          "request_id", "detail")


def log_event(event: str, *, route: str = "", method: str = "",
              status: object = "", ip: str = "", user_id: str = "",
              request_id: str = "", detail: str = "") -> None:
    """Append one structured event. Never raises: logging must not break
    request handling. Values are truncated to keep lines bounded and are
    stripped of control characters."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "event": str(event)[:64],
        "route": str(route)[:128],
        "method": str(method)[:8],
        "status": str(status)[:8],
        "ip": str(ip)[:64],
        "user_id": str(user_id)[:64],
        "request_id": str(request_id)[:64],
        "detail": _clean(detail)[:200],
    }
    try:
        line = json.dumps(entry, separators=(",", ":"))
    except (TypeError, ValueError):
        return
    try:
        with _log_lock:
            _LOG_PATH.parent.mkdir(exist_ok=True)
            with open(_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError:
        pass


def _clean(text: str) -> str:
    return "".join(c if 32 <= ord(c) < 127 or c in "\t" else "?"
                   for c in str(text))
