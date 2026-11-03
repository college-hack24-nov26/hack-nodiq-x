#!/usr/bin/env python3

"""
services/mailer.py — tiny SMTP wrapper (Advancement: SPC email alerts).

Reads SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / FEEDBACK_TO_EMAIL from
the environment (ai.config already loaded the project .env). Sends plain-text
mail and NEVER raises: callers decide how to surface (ok, detail).
"""

import os
import smtplib
import sys
from email.message import EmailMessage


def _load_project_env() -> None:
    """Seed os.environ from the project .env for local dev (`python server.py`).

    ai.config only injects .env values lazily (via get_config), which runs
    AFTER this module's import-time reads — so a dev server would otherwise
    keep SMTP disabled despite a correct .env.

    In Docker this is a no-op: compose's env_file pre-sets the variables,
    and os.environ always wins (values here are never overwritten).
    Best-effort by design.

    Skipped under pytest: tests must run with a clean environment. A real
    .env (e.g. live Supabase credentials) leaking into the test process via
    a transitive `import server` would silently flip module-level backend
    flags (services.storage.BACKEND etc.) and break test isolation.
    """
    if "pytest" in sys.modules:
        return

    try:
        from nodiq.ai.config import _read_env_file

        for key, value in _read_env_file().items():
            os.environ.setdefault(key, value)
    except Exception:
        pass


_load_project_env()

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
TO_EMAIL = os.environ.get("FEEDBACK_TO_EMAIL", "")

configured = bool(
    SMTP_HOST
    and SMTP_USER
    and SMTP_PASS
    and TO_EMAIL
)

def send(subject, body, reply_to=None, to=None):
    """Best-effort send. Returns (ok, detail).

    `to` overrides the default recipient (TO_EMAIL); used by the
    password-reset flow to mail the requesting user directly.
    """
    if not configured:
        return False, "smtp not configured (set SMTP_* in .env)"

    # Header injection defense: remove CR/LF characters from headers
    subject_clean = " ".join(str(subject or "").splitlines()).strip()
    recipient = "".join(str(to or TO_EMAIL or "").splitlines()).strip()

    if not recipient:
        return False, "no recipient address"

    try:
        msg = EmailMessage()
        msg["Subject"] = subject_clean
        msg["From"] = SMTP_USER
        msg["To"] = recipient

        if reply_to:
            msg["Reply-To"] = "".join(str(reply_to).splitlines()).strip()

        msg.set_content(body)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)

        return True, "emailed"

    except Exception as exc:
        return False, f"email failed: {exc}"
