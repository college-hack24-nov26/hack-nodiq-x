"""Camera-agent CORS — loopback dev-origin allow-list.

Regression for the "Cannot reach the camera agent" panel failure: Vite
auto-increments its dev port when 5173 is already taken (5174, 5175, …), so
an allow-list pinned to 5173 alone blocked the SPA the moment the port
drifted — the SPA origin was perfectly correct, the list was stale.

Locked in:
  * every loopback origin inside the configured dev/preview window is echoed
    back as Access-Control-Allow-Origin (including drifted ports);
  * everything else — foreign host, port-spoofed host, out-of-window port,
    non-loopback IP, "null" — gets NO Access-Control-Allow-Origin: never a
    wildcard host.

No camera hardware required: `/` is answered by the handler alone.
"""
from __future__ import annotations

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
import config  # noqa: E402


@pytest.fixture()
def agent_url():
    """Fresh agent HTTP server on an ephemeral loopback port."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), agent_server.AgentHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _acao(url: str, origin: str) -> str | None:
    """GET `url` carrying `Origin`; returns the echoed ACAO header or None."""
    req = urllib.request.Request(url, headers={"Origin": origin})
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == 200
        return resp.headers.get("Access-Control-Allow-Origin")


def test_dev_port_window_is_allowed(agent_url):
    """Vite drifts off 5173 (5174, 5175, …) — those origins must still work."""
    for origin in ("http://localhost:5173", "http://localhost:5174",
                   "http://localhost:5184", "http://127.0.0.1:5174",
                   "http://127.0.0.1:5184", "http://localhost:4173"):
        assert _acao(f"{agent_url}/", origin) == origin, origin


def test_foreign_origins_get_no_acao(agent_url):
    """Never a wildcard: foreign / spoofed / out-of-window origins are
    served but not CORS-readable, so the browser keeps the panel blocked."""
    for origin in ("https://evil.example", "http://evil.example:5174",
                   "http://localhost:9999", "http://localhost:5185",
                   "http://10.0.0.5:5174", "null"):
        assert _acao(f"{agent_url}/", origin) is None, origin


def test_allow_list_is_exact_loopback_origins_only():
    """The default list stays explicit: no `*`, no non-loopback host."""
    origins = config.CAMERA_AGENT_ALLOWED_ORIGINS
    assert origins
    assert not any("*" in o for o in origins)
    for o in origins:
        assert o.startswith("http://"), o
        host = o.split("://", 1)[1].rsplit(":", 1)[0]
        assert host in ("localhost", "127.0.0.1"), o
