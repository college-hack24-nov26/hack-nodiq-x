#!/usr/bin/env python3
"""
services/validate.py — server-side input schema validation toolkit.

Every meaningful JSON body is validated through validate_body():
- explicit types, bounds and length caps per field
- UNKNOWN FIELDS ARE REJECTED (mass-assignment and privilege-field
  smuggling like {"role": "admin"} / {"user_id": "..."} fail with 400)
- identity fields (user_id / owner_id / role / permissions / isAdmin) are
  never accepted from clients anywhere; the verified session is the only
  source of identity.

Field kinds: str, email, id, session_id, token, int, float, bool, enum,
list. All return coerced, bounded values; anything malformed raises
InputError -> 400 by the app-level handler.
"""
import re


class InputError(Exception):
    """Raised for any rejected request body; the app handler turns it into
    a 400 with a generic message."""

    def __init__(self, message="invalid request"):
        super().__init__(message)
        self.message = message


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ID_RE = re.compile(r"^[A-Z]{3}-[A-Z0-9]{1,24}$")
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.-]{8,512}$")
# Firebase ID tokens are JWTs: three base64url segments (~1000-1200 chars for
# RS256 tokens). The generic _TOKEN_RE cap of 512 rejects every real token,
# so the /api/auth/firebase exchange must use this JWT-shaped grammar
# instead (same alphabet, JWT structure, realistic length bound).
_JWT_RE = re.compile(r"^[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}$")

# Fields a client may never supply, regardless of schema (identity and
# privilege are derived from the verified token, never the request).
FORBIDDEN_KEYS = {
    "user_id", "userid", "owner_id", "ownerid", "role", "roles", "admin",
    "isadmin", "is_admin", "permissions", "account_id", "organization_id",
    "org_id", "price", "authenticated", "verified",
}


def _reject_unknown(body: dict, schema: dict, ctx: str) -> None:
    for key in body:
        if key.lower() in FORBIDDEN_KEYS:
            raise InputError("invalid request")
        if key not in schema:
            raise InputError(f"unknown field: {key}")


def _scalar_ok(v, max_str=4000):
    """Bounded scalar for dict values (context/history items)."""
    if v is None or isinstance(v, bool):
        return True
    if isinstance(v, (int, float)):
        return abs(v) < 2**31
    return isinstance(v, str) and len(v) <= max_str


def validate_body(body: dict, schema: dict, ctx: str = "") -> dict:
    """Validate `body` against `schema` and return the cleaned dict.

    schema maps field name -> (kind, **opts). Unknown fields and forbidden
    identity/privilege fields raise InputError. body must be a dict (callers
    pass `request.get_json(silent=True) or {}`).
    """
    if not isinstance(body, dict):
        raise InputError("invalid request body")
    _reject_unknown(body, schema, ctx)
    clean = {}
    for key, (kind, opts) in schema.items():
        clean[key] = _validate_one(body.get(key), kind, opts, key)
    return clean


def _validate_one(value, kind, o, key):
    required = o.get("required", False)
    if value is None or (isinstance(value, str) and not value.strip()
                         and not o.get("allow_empty", False)):
        if required:
            raise InputError(f"{key} is required")
        return o.get("default")
    if kind == "str":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            raise InputError(f"invalid {key}")
        max_len = o.get("max_len", 256)
        if len(value) > max_len:
            if o.get("truncate", False):
                value = value[:max_len]
            else:
                raise InputError(f"invalid {key}")
        if o.get("pattern") and not o["pattern"].fullmatch(value):
            raise InputError(f"invalid {key}")
        return value
    if kind == "email":
        if not isinstance(value, str) or not _EMAIL_RE.fullmatch(value) \
                or len(value) > 254:
            raise InputError(f"invalid {key}")
        return value.strip().lower()
    if kind == "id":
        if not isinstance(value, str) or not _ID_RE.fullmatch(value):
            raise InputError(f"invalid {key}")
        return value
    if kind == "session_id":
        if not isinstance(value, str) or not _SESSION_RE.fullmatch(value):
            raise InputError(f"invalid {key}")
        return value
    if kind == "token":
        if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
            raise InputError(f"invalid {key}")
        return value
    if kind == "jwt":
        if not isinstance(value, str) or not _JWT_RE.fullmatch(value):
            raise InputError(f"invalid {key}")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise InputError(f"invalid {key}")
        if not (o.get("min", -(2**31)) <= value <= o.get("max", 2**31 - 1)):
            raise InputError(f"invalid {key}")
        return value
    if kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InputError(f"invalid {key}")
        value = float(value)
        if value != value or value in (float("inf"), float("-inf")):
            raise InputError(f"invalid {key}")
        if not (o.get("min", -(2**31)) <= value <= o.get("max", 2**31 - 1)):
            raise InputError(f"invalid {key}")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise InputError(f"invalid {key}")
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in o["choices"]:
            raise InputError(f"invalid {key}")
        return value
    if kind == "dict":
        if not isinstance(value, dict):
            raise InputError(f"invalid {key}")
        if len(value) > o.get("max_keys", 24):
            raise InputError(f"invalid {key}")
        for k, v in value.items():
            if not isinstance(k, str) or len(k) > 64:
                raise InputError(f"invalid {key}")
            if not _scalar_ok(v):
                raise InputError(f"invalid {key}")
        return value
    if kind == "list":
        if not isinstance(value, list):
            raise InputError(f"invalid {key}")
        max_items = o.get("max_items", 50)
        item_max_len = o.get("item_max_len", 256)
        if len(value) > max_items:
            raise InputError(f"invalid {key}")
        out = []
        for item in value:
            if o.get("item_kind") == "obj":
                if not isinstance(item, dict) or len(item) > 12:
                    raise InputError(f"invalid {key}")
                if any(not isinstance(k, str) or len(k) > 64
                       or not _scalar_ok(v, item_max_len)
                       for k, v in item.items()):
                    raise InputError(f"invalid {key}")
                out.append(item)
                continue
            if not isinstance(item, str) or len(item) > item_max_len:
                raise InputError(f"invalid {key}")
            out.append(item)
        return out
    raise InputError(f"invalid {key}")
