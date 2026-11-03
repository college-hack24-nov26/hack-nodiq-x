#!/usr/bin/env python3
"""
services/review.py — review sign-off workflow (Advancement).

Attaches an electronic review record to a stored analysis:
    {status: approved|rejected|changes_requested,
     comment, reviewed_by, reviewed_at, history: [...]}

Signed-off state rides on the analysis record itself (single source of
truth), so reports can print it and the history list can badge it.

Audit trail: every status change appends an immutable entry to
review["history"] (previous status -> new status, reviewer, timestamp,
comment). Entries are never edited or removed — only appended — so the
Review Center can show the full validation history of a sample.
"""
import time

import nodiq.services.db as store

VALID = ("approved", "rejected", "changes_requested")


def set_review(analysis_id, status, comment="", reviewed_by="", user_id=None):
    """Attach/clear a review decision. status=None clears the review.

    Returns True when the analysis record exists (and was updated).
    """
    rec = store.get_analysis_record(analysis_id, user_id)
    if not rec:
        return False

    if status is None:
        previous = rec.get("review") or {}
        rec["review"] = None
        history = rec.get("review_history") or []
        history.append({
            "action": "cleared",
            "previous_status": previous.get("status"),
            "new_status": None,
            "comment": str(comment or "")[:2000],
            "reviewed_by": str(reviewed_by or "")[:120],
            "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        rec["review_history"] = history
    else:
        status = str(status).strip().lower()
        if status not in VALID:
            return False
        previous = rec.get("review") or {}
        rec["review"] = {
            "status": status,
            "comment": str(comment or "")[:2000],
            "reviewed_by": str(reviewed_by or "")[:120],
            "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        history = rec.get("review_history") or []
        history.append({
            "action": "set",
            "previous_status": previous.get("status"),
            "new_status": status,
            "comment": rec["review"]["comment"],
            "reviewed_by": rec["review"]["reviewed_by"],
            "reviewed_at": rec["review"]["reviewed_at"],
        })
        rec["review_history"] = history

    store.insert_analysis(rec, user_id)
    return True
