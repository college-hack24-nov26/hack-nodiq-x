#!/usr/bin/env python3
"""
tests/test_storage_backends.py — artifact storage layer regression tests.

Covers services/storage.py in both modes:
  local      real filesystem roundtrip (default in tests)
  supabase   mocked HTTP transport: correct URL/headers/verb, 404->None,
             non-2xx -> RuntimeError (so the analysis child can honestly
             fail an analysis instead of claiming success), key validation.

The ownership checks live in the Flask routes (test_ownership_isolation);
this module tests the byte-moving layer those routes call.
"""
import sys
from pathlib import Path

import pytest


import nodiq.services.storage as storage


@pytest.fixture()
def local_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "LOCAL_DIR", tmp_path / "storage")
    monkeypatch.setattr(storage, "BACKEND", "local")
    return tmp_path / "storage"


# --------------------------------------------------------------- key rules --
def test_object_key_layout():
    assert storage.object_key("USR-1", "ANL-1", "annotated") == \
        "users/USR-1/analyses/ANL-1/annotated.png"
    assert storage.object_key("USR-1", "ANL-1", "report") == \
        "users/USR-1/analyses/ANL-1/report.pdf"


def test_object_key_rejects_traversal():
    with pytest.raises(ValueError):
        storage.object_key("../etc", "ANL-1", "mask")
    with pytest.raises(ValueError):
        storage.object_key("USR-1", "a/b", "mask")
    with pytest.raises(ValueError):
        storage.object_key("USR-1", "ANL-1", "arbitrary")


# ------------------------------------------------------------- local mode --
def test_local_roundtrip(local_dir):
    key = storage.put_bytes("USR-1", "ANL-9", "annotated", b"\x89PNG-bytes")
    assert key.endswith("annotated.png")
    assert (local_dir / key).read_bytes() == b"\x89PNG-bytes"
    assert storage.get_bytes("USR-1", "ANL-9", "annotated") == \
        b"\x89PNG-bytes"
    assert storage.get_bytes("USR-1", "ANL-404", "annotated") is None
    storage.delete("USR-1", "ANL-9", "annotated")
    assert storage.get_bytes("USR-1", "ANL-9", "annotated") is None


# ---------------------------------------------------------- supabase mode --
class _FakeResp:
    def __init__(self, status, body=b""):
        self.status_code = status
        self.text = str(body)
        self.content = body


@pytest.fixture()
def supa_mode(monkeypatch):
    """Storage module in supabase mode with a recorded fake transport."""
    monkeypatch.setattr(storage, "SUPABASE_URL", "https://supa.test")
    monkeypatch.setattr(storage, "SERVICE_KEY", "svc-key")
    monkeypatch.setattr(storage, "BUCKET", "nodiq-artifacts")
    monkeypatch.setattr(storage, "BACKEND", "supabase")
    calls = []

    def fake(method, status_map):
        def _request(url, **kw):
            calls.append({"method": method, "url": url, **kw})
            return status_map(url)
        return _request

    return calls, fake


def test_supabase_put_and_get(supa_mode, monkeypatch):
    calls, fake = supa_mode

    def route(url):
        if url.endswith("mask.png"):
            return _FakeResp(200, b"\x89PNG-mask")
        return _FakeResp(404, "not found")

    monkeypatch.setattr(storage.requests, "post",
                        fake("POST", lambda url: _FakeResp(200)))
    monkeypatch.setattr(storage.requests, "get", fake("GET", route))

    key = storage.put_bytes("USR-7", "ANL-7", "mask", b"\x89PNG-mask")
    assert key == "users/USR-7/analyses/ANL-7/mask.png"
    post = calls[0]
    assert post["url"] == \
        "https://supa.test/storage/v1/object/nodiq-artifacts/" + key
    assert post["headers"]["Authorization"] == "Bearer svc-key"
    assert post["headers"]["apikey"] == "svc-key"
    assert post["data"] == b"\x89PNG-mask"          # raw bytes, not JSON

    # stored object reads back; missing object -> None (route 404s cleanly)
    assert storage.get_bytes("USR-7", "ANL-7", "mask") == b"\x89PNG-mask"
    assert storage.get_bytes("USR-7", "ANL-7", "annotated") is None


def test_supabase_put_failure_raises(supa_mode, monkeypatch):
    """Upload errors must propagate: the analysis child turns them into an
    honest analysis failure instead of 'completed' with missing files."""
    calls, fake = supa_mode
    monkeypatch.setattr(
        storage.requests, "post",
        fake("POST", lambda url: _FakeResp(503, "bucket unavailable")))
    with pytest.raises(RuntimeError, match="503"):
        storage.put_bytes("USR-7", "ANL-7", "mask", b"x")


def test_supabase_get_server_error_raises(supa_mode, monkeypatch):
    calls, fake = supa_mode
    monkeypatch.setattr(
        storage.requests, "get",
        fake("GET", lambda url: _FakeResp(500, "boom")))
    with pytest.raises(RuntimeError, match="500"):
        storage.get_bytes("USR-7", "ANL-7", "mask")
