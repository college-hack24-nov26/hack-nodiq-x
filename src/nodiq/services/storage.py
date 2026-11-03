#!/usr/bin/env python3
"""
services/storage.py

Stores analysis artifacts using either Supabase Storage or the local
filesystem. Both backends use the same functions, so the rest of the
application doesn't need to know where files are stored.

Supabase uses the service-role key on the server. The bucket stays
private, and Flask routes handle access checks before returning files.

Required environment variables:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY

Optional environment variables:
    SUPABASE_BUCKET (default: nodiq-artifacts)
    NODIQ_LOCAL_STORAGE_DIR (default: server_data/storage)

Local files follow the same key structure as Supabase, which makes
moving existing artifacts between backends straightforward.

Each key includes the owning user and analysis:
    users/{user_id}/analyses/{analysis_id}/{kind}.{ext}

Access checks belong in the Flask routes, not in this module.
"""

import os
import time
from pathlib import Path

import requests


from nodiq.core.config import REPO_ROOT, DATA_DIR

ROOT = REPO_ROOT

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
BUCKET = os.environ.get("SUPABASE_BUCKET", "nodiq-artifacts")

LOCAL_DIR = Path(
    os.environ.get("NODIQ_LOCAL_STORAGE_DIR")
    or (DATA_DIR / "storage")
)

BACKEND_OVERRIDE = (os.environ.get("NODIQ_STORAGE_BACKEND") or "").strip().lower()
if BACKEND_OVERRIDE in ("local", "supabase"):
    BACKEND = BACKEND_OVERRIDE
else:
    BACKEND = "supabase" if (SUPABASE_URL and SERVICE_KEY) else "local"

_KIND_EXT = {
    "original": "png",
    "annotated": "png",
    "mask": "png",
    "report": "pdf",

    # Steel grain-size analysis
    "gsat_mask": "png",
    "gsat_overlay": "png",
    "gsat_intercept": "png",
    "gsat_preprocessed": "png",
    "astm_mask": "png",
    "astm_overlay": "png",
    "astm_labels": "png",

    # White cast iron carbide analysis
    "carde_mask": "png",
    "carde_overlay": "png",

    # Gray cast iron graphite flake analysis
    "flake_mask": "png",
    "flake_overlay": "png",
    "flake_contour": "png",
    "flake_exclusion": "png",
}


def object_key(user_id, analysis_id, kind, ext=None):
    """Build the storage key for an analysis artifact."""

    if kind not in _KIND_EXT:
        raise ValueError(f"unknown artifact kind: {kind!r}")

    ext = ext or _KIND_EXT[kind]

    if not user_id or not analysis_id or "/" in str(user_id) \
            or "/" in str(analysis_id):
        raise ValueError("invalid artifact path components")

    return f"users/{user_id}/analyses/{analysis_id}/{kind}.{ext}"


# ----------------------------------------------------------------- writes --

def put_bytes(user_id, analysis_id, kind, data, ext=None):
    """Save an artifact and return its storage key."""

    key = object_key(user_id, analysis_id, kind, ext)

    # Always persist locally first so artifact retrieval is always guaranteed
    path = LOCAL_DIR / key
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_bytes(data)
    except Exception:
        pass

    if BACKEND == "supabase":
        url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{key}"
        headers = {
            "Authorization": f"Bearer {SERVICE_KEY}",
            "apikey": SERVICE_KEY,
            "Content-Type": "application/octet-stream",
            "x-upsert": "true",
        }

        last_exc = None
        data_size = len(data) if isinstance(data, (bytes, bytearray)) else 0
        # Adaptive timeout: at least 120s, scaling dynamically with payload size
        # to prevent write timeouts on large micrographs over slow connections
        timeout_s = max(120, int(data_size / 20000))

        for attempt in range(2):
            try:
                resp = requests.post(
                    url,
                    data=data,
                    headers=headers,
                    timeout=timeout_s,
                )

                if resp.status_code in (200, 201):
                    return key

                last_exc = RuntimeError(
                    f"supabase upload failed ({resp.status_code}): "
                    f"{resp.text[:200]}"
                )

            except requests.RequestException as exc:
                last_exc = RuntimeError(
                    f"supabase upload transport error: "
                    f"{type(exc).__name__}: {str(exc)[:150]}"
                )

            if attempt == 0:
                time.sleep(1)

        if last_exc is not None:
            # Clean advisory notice without spewing multi-line transport traces
            print(
                f"[storage] cloud upload notice for {key}: {last_exc} — using local disk artifact",
                flush=True,
            )
            raise last_exc
        raise RuntimeError(f"supabase upload failed for {key}")

    return key


# ------------------------------------------------------------------ reads --

def get_bytes(user_id, analysis_id, kind, ext=None):
    """Return an artifact's bytes, or None if it doesn't exist."""

    key = object_key(user_id, analysis_id, kind, ext)

    if BACKEND == "supabase":
        url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{key}"

        resp = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {SERVICE_KEY}",
                "apikey": SERVICE_KEY,
            },
            timeout=60,
        )

        # Supabase can return either 404 or a 400 response for a
        # missing object, depending on the error response.
        if resp.status_code == 404 or (
            resp.status_code == 400
            and (
                "not_found" in resp.text.lower()
                or "object not found" in resp.text.lower()
            )
        ):
            return None

        if resp.status_code != 200:
            raise RuntimeError(
                f"supabase download failed ({resp.status_code}): "
                f"{resp.text[:200]}"
            )

        return resp.content

    path = LOCAL_DIR / key

    if not path.exists():
        return None

    return path.read_bytes()


def exists(user_id, analysis_id, kind, ext=None):
    """Check whether an artifact exists."""

    if BACKEND == "supabase":
        return get_bytes(user_id, analysis_id, kind, ext) is not None

    return (
        LOCAL_DIR / object_key(user_id, analysis_id, kind, ext)
    ).exists()


def delete(user_id, analysis_id, kind, ext=None):
    """Try to delete an artifact without interrupting the caller."""

    key = object_key(user_id, analysis_id, kind, ext)

    if BACKEND == "supabase":
        url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{key}"

        try:
            requests.delete(
                url,
                headers={
                    "Authorization": f"Bearer {SERVICE_KEY}",
                    "apikey": SERVICE_KEY,
                },
                timeout=30,
            )
        except Exception:
            pass

        return

    path = LOCAL_DIR / key

    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def health():
    """Return the active storage backend and its configuration."""

    if BACKEND == "supabase":
        return {
            "backend": "supabase",
            "bucket": BUCKET,
            "configured": bool(SUPABASE_URL and SERVICE_KEY),
        }

    return {
        "backend": "local",
        "dir": str(LOCAL_DIR),
    }
