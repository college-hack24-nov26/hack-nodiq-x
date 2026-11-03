"""NODIQ-X Camera Agent — configuration.

Phase 2 adds the localhost HTTP API; everything is configurable via
environment variables with sensible defaults (nothing hardcoded at call
sites).
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Device matching
# ---------------------------------------------------------------------------
# The microscope camera in this lab setup. Matching is done against the
# strings the SDK actually reports (never hardcoded as a successful result —
# the values below are only used to FIND the device and to warn when the
# detected model differs).
EXPECTED_MANUFACTURER = "MATRIX VISION"
EXPECTED_MODEL_SUBSTRINGS = ("mvBlueFOX", "IGC205C")

# Prefer a device whose reported name/family contains any of these. If none
# matches but other devices exist, the agent reports them and fails cleanly
# rather than silently using the wrong camera.
PREFERRED_DEVICE_SUBSTRINGS = ("mvBlueFOX", "MATRIX", "Balluff")

# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------
# Single-frame wait timeout. mvBlueFOX sensors are slow at full resolution;
# 10 s is generous but bounded (never wait forever in an unattended run).
ACQUISITION_TIMEOUT_MS = 10_000

# Phase 3 live preview: the browser polls /preview repeatedly. Re-opening
# the device for every frame costs seconds (the open is the slow part), so
# the agent keeps the device OPEN between requests and closes it after this
# idle period — other applications can claim the camera again after it.
# Set 0 to disable caching (open/close per request, Phase 2 behavior).
DEVICE_IDLE_CLOSE_S = float(os.environ.get("NODIQ_CAMERA_IDLE_CLOSE_S", "15") or 0) or 15.0

# /preview downscale target (long side, px). A full 2592x1944 JPEG per poll
# is wasteful for a positioning preview; 1024 is crisp on any panel.
PREVIEW_MAX_SIDE = int(os.environ.get("NODIQ_CAMERA_PREVIEW_MAX", "1024") or 1024)

# ---------------------------------------------------------------------------
# HTTP API (Phase 2)
# ---------------------------------------------------------------------------
# Dedicated port — verified free; 8001 (Flask) / 5173 / 4173 (Vite) reserved.
DEFAULT_CAMERA_AGENT_PORT = 8765


def _port() -> int:
    raw = (os.environ.get("NODIQ_CAMERA_PORT") or "").strip()
    try:
        return int(raw) if raw else DEFAULT_CAMERA_AGENT_PORT
    except ValueError:
        return DEFAULT_CAMERA_AGENT_PORT


CAMERA_AGENT_PORT = _port()

# Browser origins allowed to call the agent. Never a wildcard HOST: the agent
# can trigger hardware access, so only exact loopback origins are allowed —
# localhost / 127.0.0.1 only, never a non-loopback address, never a scheme or
# host wildcard. Extendable via NODIQ_CAMERA_ALLOWED_ORIGINS (comma-separated).
#
# Ports cover Vite's real behaviour: `vite` auto-increments when 5173 is
# already taken (5174, 5175, …) and `vite preview` uses 4173+. Pinning only
# 5173 made the camera panel fail CORS the moment the port drifted — the SPA
# origin was correct, the allow-list was stale.
_DEV_PORT_RANGE = range(5173, 5185)        # vite dev (auto-increments)
_PREVIEW_PORT_RANGE = range(4173, 4185)     # vite preview
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1")

_DEFAULT_ORIGINS = [
    f"http://{host}:{port}"
    for host in _LOOPBACK_HOSTS
    for port in (*_PREVIEW_PORT_RANGE, *_DEV_PORT_RANGE)
]


def _origins() -> list[str]:
    raw = (os.environ.get("NODIQ_CAMERA_ALLOWED_ORIGINS") or "").strip()
    if not raw:
        return list(_DEFAULT_ORIGINS)
    return [o.strip() for o in raw.split(",") if o.strip()]


CAMERA_AGENT_ALLOWED_ORIGINS = _origins()

# Compact startup-log description: the default list is 48 entries, too long
# for one log line (an explicit NODIQ_CAMERA_ALLOWED_ORIGINS is printed in
# full because that list is short and worth showing verbatim).
ALLOWED_ORIGINS_DESC = (
    ", ".join(CAMERA_AGENT_ALLOWED_ORIGINS)
    if os.environ.get("NODIQ_CAMERA_ALLOWED_ORIGINS")
    else "loopback only: localhost|127.0.0.1 on ports 5173-5184 (vite dev) "
         "+ 4173-4184 (preview)"
)

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
AGENT_DIR = Path(__file__).resolve().parent
DEFAULT_CAPTURE_PATH = AGENT_DIR / "test_capture.png"

# ---------------------------------------------------------------------------
# Validation thresholds (8-bit-equivalent scale; 16-bit data is normalised)
# ---------------------------------------------------------------------------
BLACK_MEAN_MAX = 1.0        # mean <= this (0-255 scale) => "completely black"
DARK_MEAN_MAX = 20.0        # mean <= this => effectively dark: no usable
                            # micrograph signal (lens cap / illumination off?)
WHITE_MEAN_MIN = 254.0      # mean >= this (0-255 scale) => "completely white"
UNIFORM_STD_MAX = 0.5       # std  <= this => flat field (sensor cap on?)
