"""Phase 5 — camera-agent state mapping tests.

Locks in the user-facing distinction the Phase 4 report documented:

    camera disconnected  -> 503 camera_not_found  ("Camera disconnected…")
    camera busy          -> 409 camera_busy       ("being used by another…")
    camera connected     -> 200 connected:true (resolution or null)

The distinction lives in agent_server.py: on open-failure paths a FRESH
DeviceManager is consulted (``_device_gone``) — a stale enumeration after a
physical unplug must not be reported as "busy". These tests stub the SDK
layer so no camera hardware is required.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "apps" / "camera-agent"
sys.path.insert(0, str(AGENT_DIR))

import agent_server  # noqa: E402
import camera  # noqa: E402


def _fake_info():
    return camera.DeviceInfo(
        family="mvBlueFOX",
        product="mvBlueFOX-ML/IGC205C",
        family_full="mvBlueFOX-ML/IGC205C",
        manufacturer="MATRIX VISION",
        serial="29605128",
        device_id="0",
        interface="USB",
    )


@pytest.fixture(autouse=True)
def _reset_session(monkeypatch):
    """Never leak the cached device handle or a real SDK call between tests."""
    monkeypatch.setattr(agent_server, "_SESSION_DEV", None, raising=False)
    monkeypatch.setattr(agent_server, "_SESSION_INFO", None, raising=False)
    yield


@pytest.fixture()
def agent_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), agent_server.AgentHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(url: str):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _stub_open_failure(monkeypatch):
    monkeypatch.setattr(agent_server, "_pick",
                        lambda: (0, _fake_info()))

    def _raise(*_a, **_k):
        raise camera.DeviceOpenFailed(
            "[ERROR] Could not open camera (mvBlueFOX-ML/IGC205C): busy")

    monkeypatch.setattr(agent_server.camera, "open_device", _raise)


def test_capture_busy_when_device_present(monkeypatch, agent_url):
    """Open failure + device still enumerates -> 409 camera_busy (unchanged)."""
    _stub_open_failure(monkeypatch)
    monkeypatch.setattr(agent_server, "_device_gone", lambda info: False)

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{agent_url}/capture")
    assert excinfo.value.code == 409
    payload = json.loads(excinfo.value.read().decode("utf-8"))
    assert payload["error"] == "camera_busy"


def test_capture_disconnected_when_device_gone(monkeypatch, agent_url):
    """Open failure + fresh manager no longer lists the serial -> 503."""
    _stub_open_failure(monkeypatch)
    monkeypatch.setattr(agent_server, "_device_gone", lambda info: True)

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(f"{agent_url}/capture")
    assert excinfo.value.code == 503
    payload = json.loads(excinfo.value.read().decode("utf-8"))
    assert payload["error"] == "camera_not_found"
    assert "disconnected" in payload["message"].lower()


def test_status_disconnected_when_device_gone(monkeypatch, agent_url):
    """Stale enumeration + gone device -> honest connected:false."""
    monkeypatch.setattr(agent_server, "_pick", lambda: (0, _fake_info()))
    monkeypatch.setattr(agent_server, "_current_resolution",
                        lambda *a, **k: None)
    monkeypatch.setattr(agent_server, "_device_gone", lambda info: True)

    status, payload = _get(f"{agent_url}/status")
    assert status == 200
    assert payload == {"connected": False}


def test_status_busy_keeps_connected_true(monkeypatch, agent_url):
    """Device present but unresolvable (busy) -> connected:true, res null."""
    monkeypatch.setattr(agent_server, "_pick", lambda: (0, _fake_info()))
    monkeypatch.setattr(agent_server, "_current_resolution",
                        lambda *a, **k: None)
    monkeypatch.setattr(agent_server, "_device_gone", lambda info: False)

    status, payload = _get(f"{agent_url}/status")
    assert status == 200
    assert payload["connected"] is True
    assert payload["resolution"] is None
    assert payload["serial"] == "29605128"


def test_status_connected_with_resolution(monkeypatch, agent_url):
    """Happy path: resolution read live; no gone-check needed."""
    called = {"gone": 0}
    monkeypatch.setattr(agent_server, "_pick", lambda: (0, _fake_info()))
    monkeypatch.setattr(agent_server, "_current_resolution",
                        lambda *a, **k: {"width": 2592, "height": 1944})

    def _gone(info):
        called["gone"] += 1
        return False

    monkeypatch.setattr(agent_server, "_device_gone", _gone)

    status, payload = _get(f"{agent_url}/status")
    assert status == 200
    assert payload["connected"] is True
    assert payload["resolution"] == {"width": 2592, "height": 1944}
    assert called["gone"] == 0          # fast path must not rescan hardware
