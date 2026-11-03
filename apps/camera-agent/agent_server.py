"""NODIQ-X Camera Agent — localhost HTTP API (Phase 2).

Standard-library-only HTTP layer over the existing Phase 1 capture stack:

    Browser (NODIQ-X React SPA)
      -> http://127.0.0.1:<port>/status | /preview | /capture
        -> camera.py (mvIMPACT Acquire)
          -> MATRIX VISION camera

Endpoints (all GET):
  /status    JSON camera info (queried live from the driver, never hardcoded)
  /preview   one fresh frame as JPEG (simple, no streaming — per Phase 2 spec)
  /capture   one fresh frame as PNG (lossless, for analysis)

CORS: strict allow-list from config.py (NODIQ_CAMERA_ALLOWED_ORIGINS), no
wildcard. OPTIONS preflights — including Chrome's Private Network Access
(Access-Control-Request-Private-Network) — are answered with the matching
headers and `Access-Control-Allow-Private-Network: true`.

Run:  python agent_server.py            (or: python -m nodiq_camera_agent ... —
this folder is standalone; no package context required)
"""
from __future__ import annotations

import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np

import camera
from config import (AGENT_DIR, CAMERA_AGENT_PORT,
                    CAMERA_AGENT_ALLOWED_ORIGINS, ALLOWED_ORIGINS_DESC,
                    DEVICE_IDLE_CLOSE_S, PREVIEW_MAX_SIDE)

# ---------------------------------------------------------------------------
# Device session: one DeviceManager + optionally-open Device for the server
# lifetime. All SDK calls are serialized by _LOCK because the driver objects
# are not thread-safe and ThreadingHTTPServer handles each request in its own
# thread.
# ---------------------------------------------------------------------------
_LOCK = threading.RLock()
_MANAGER = None            # acquire.DeviceManager (kept referenced forever)
_DEVICES: list[camera.DeviceInfo] | None = None
_SESSION_DEV = None        # cached open Device (Phase 3: fast preview frames)
_SESSION_INFO = None       # DeviceInfo of the cached device
_SESSION_TIMER = None      # closes the device after DEVICE_IDLE_CLOSE_S


def _close_session() -> None:
    """Drop the cached open device (best-effort) so other apps can claim it."""
    global _SESSION_DEV, _SESSION_INFO
    dev, _SESSION_DEV = _SESSION_DEV, None
    _SESSION_INFO = None
    if dev is not None:
        camera.close_device(dev)


def _arm_idle_close() -> None:
    """(Re)schedule the idle-close for the cached device."""
    global _SESSION_TIMER
    if _SESSION_TIMER is not None:
        _SESSION_TIMER.cancel()
    if DEVICE_IDLE_CLOSE_S > 0:
        _SESSION_TIMER = threading.Timer(DEVICE_IDLE_CLOSE_S, _close_session)
        _SESSION_TIMER.daemon = True
        _SESSION_TIMER.start()


def _manager():
    """(Re)build the DeviceManager. Rescanned lazily on each /status call so
    a camera plugged in after server start is found without a restart."""
    global _MANAGER, _DEVICES
    if _MANAGER is None:
        from mvIMPACT import acquire
        _MANAGER = acquire.DeviceManager()
        _DEVICES = None
    return _MANAGER


def _scan_devices() -> list[camera.DeviceInfo]:
    global _DEVICES
    _manager()
    _DEVICES = camera.enumerate_devices(_MANAGER)
    return _DEVICES


def _pick() -> tuple[int, camera.DeviceInfo]:
    """Best device index + info; raises camera.NoDeviceFound when absent."""
    devices = _scan_devices()
    index = camera.pick_device(_MANAGER, devices)
    return index, devices[index]


# ---------------------------------------------------------------------------
# Capture helpers (fresh frame on EVERY call — never a cached file)
# ---------------------------------------------------------------------------

def _png_bytes(frame: camera.Frame) -> bytes:
    ok, buf = cv2.imencode(".png", frame.array[:, :, ::-1]
                           if frame.array.ndim == 3 else frame.array)
    if not ok:
        raise camera.CaptureFailed("[ERROR] PNG encoding failed.")
    return buf.tobytes()


def _jpeg_bytes(frame: camera.Frame, quality: int = 92,
                max_side: int | None = None) -> bytes:
    src = frame.array[:, :, ::-1] if frame.array.ndim == 3 else frame.array
    if max_side:
        h, w = src.shape[:2]
        long_side = max(h, w)
        if long_side > max_side:
            scale = max_side / float(long_side)
            src = cv2.resize(src, (int(round(w * scale)),
                                   int(round(h * scale))),
                             interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", src, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise camera.CaptureFailed("[ERROR] JPEG encoding failed.")
    return buf.tobytes()


def _device_gone(info: camera.DeviceInfo) -> bool:
    """True when the device no longer enumerates in a FRESH DeviceManager.

    Phase 4 finding: the long-lived DeviceManager keeps a stale entry after a
    physical USB unplug (open then fails with a busy-looking error). A freshly
    constructed manager reflects reality immediately (verified with a hardware
    probe on 2026-10-01: count=0 while unplugged, count=1 after replug), so a
    fresh check — run ONLY on open-failure paths — separates:

        camera disconnected (fresh manager does not list the serial)
        != camera busy      (device present, isInUse / open refused)
        != agent offline    (no HTTP answer at all)

    Conservative by design: any error during the check returns False and the
    pre-existing busy behaviour is preserved.
    """
    from mvIMPACT import acquire
    with _LOCK:
        try:
            update = getattr(_MANAGER, "updateDeviceList", None)
            if callable(update):
                try:
                    update()                      # refresh the cached manager too
                except Exception:
                    pass
            fresh = acquire.DeviceManager()       # authoritative hardware view
            count = fresh.deviceCount()
            for i in range(count):
                try:
                    dev = fresh.getDevice(i)
                    serial = camera._safe(dev, "serial")
                    if serial and info.serial and serial == info.serial:
                        return False              # still present → not gone
                    if not serial or not info.serial:
                        if camera._safe(dev, "deviceModelName") == info.family_full:
                            return False
                except Exception:
                    continue
            return True                           # enumerated nowhere → gone
        except Exception:
            return False


def _fresh_frame(timeout_ms: int | None = None) -> camera.Frame:
    """Acquire one fresh frame using the cached open device when possible.

    The device stays open between requests for DEVICE_IDLE_CLOSE_S seconds
    (Phase 3 live preview would otherwise re-pay the multi-second open on
    every poll); afterwards the idle timer closes it so other applications
    can claim the camera. If opening fails because the device vanished or
    is held elsewhere, the cache is dropped and the error propagates — the
    next request rescans and retries.
    """
    global _SESSION_DEV, _SESSION_INFO
    with _LOCK:
        index, info = _pick()
        if _SESSION_DEV is not None:
            if _SESSION_INFO is not None and \
                    _SESSION_INFO.device_id != info.device_id:
                _close_session()          # different device — restart cache
            else:
                _arm_idle_close()
                try:
                    return camera.capture_frame(_SESSION_DEV,
                                                timeout_ms or _timeout())
                except camera.CameraError:
                    _close_session()      # stale handle: retry below, fresh
        try:
            _SESSION_DEV = camera.open_device(_MANAGER, index, info)
        except camera.DeviceOpenFailed as exc:
            _SESSION_DEV = None
            # Phase 5: distinguish a physically disconnected camera from one
            # held by another application (stale enumeration made an unplug
            # look like 'busy'). Fresh-manager check runs on failure only.
            if _device_gone(info):
                raise camera.NoDeviceFound(
                    "[ERROR] Camera disconnected. Reconnect the USB cable and retry."
                ) from exc
            raise
        _SESSION_INFO = info
        _arm_idle_close()
        return camera.capture_frame(_SESSION_DEV, timeout_ms or _timeout())


def _timeout() -> int:
    from config import ACQUISITION_TIMEOUT_MS
    return ACQUISITION_TIMEOUT_MS


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class AgentHandler(BaseHTTPRequestHandler):
    server_version = "NODIQ-CameraAgent/2.0"
    protocol_version = "HTTP/1.1"

    # ----------------------------- CORS / PNA -----------------------------
    def _origin(self) -> str | None:
        origin = self.headers.get("Origin")
        if origin and origin in CAMERA_AGENT_ALLOWED_ORIGINS:
            return origin
        return None

    def _cors_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        origin = self._origin()
        if origin:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Vary"] = "Origin"
            headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        # Chrome Private Network Access preflight (spec: the target of a
        # private-network request must answer the negotiation explicitly).
        if (self.command == "OPTIONS"
                and self.headers.get("Access-Control-Request-Private-Network")
                == "true"):
            headers["Access-Control-Allow-Private-Network"] = "true"
            headers["Access-Control-Allow-Headers"] = (
                self.headers.get("Access-Control-Request-Headers") or "*")
        return headers

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        headers = self._cors_headers()
        headers.update({
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",      # never cache camera frames/status
        })
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"),
                   "application/json; charset=utf-8")

    # ----------------------------- routes -----------------------------
    def do_OPTIONS(self) -> None:  # noqa: N802 (http.server naming)
        # Preflight always succeeds structurally; real enforcement happens
        # because the actual GETs only carry ACAO for allowed origins.
        self._send(204, b"", "text/plain")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        try:
            if path == "/status":
                self._route_status()
            elif path == "/capture":
                self._route_capture(png=True)
            elif path == "/preview":
                self._route_capture(png=False)
            elif path == "/":
                self._json(200, {
                    "service": "NODIQ-X camera agent",
                    "endpoints": ["/status", "/preview", "/capture"],
                    "camera_port": CAMERA_AGENT_PORT,
                })
            else:
                self._json(404, {"error": "not_found",
                                 "message": f"unknown path {path}"})
        except camera.NoDeviceFound as exc:
            self._json(503, {"error": "camera_not_found",
                             "message": _first_line(exc)})
        except camera.DeviceOpenFailed as exc:
            self._json(409, {"error": "camera_busy",
                             "message": _first_line(exc)})
        except camera.CaptureFailed as exc:
            self._json(504, {"error": "capture_failed",
                             "message": _code_msg(exc, "timeout")})
        except camera.SdkUnavailable as exc:
            self._json(503, {"error": "sdk_unavailable",
                             "message": _first_line(exc)})
        except Exception as exc:                 # noqa: BLE001 — last resort
            self._json(500, {"error": "internal_error",
                             "message": f"{type(exc).__name__}: {exc}"})

    # ----------------------------- /status -----------------------------
    def _route_status(self) -> None:
        try:
            index, info = _pick()
        except camera.NoDeviceFound:
            self._json(200, {"connected": False})
            return
        resolution = _current_resolution(_MANAGER, index, info)
        if resolution is None and _device_gone(info):
            # Phase 5: an unplug used to linger as connected:true with a stale
            # entry; a fresh manager that no longer lists the device means the
            # camera is physically gone → report the honest disconnected state.
            self._json(200, {"connected": False})
            return
        self._json(200, {
            "connected": True,
            "device_id": _as_int_or_str(info.device_id),
            "model": info.model(),
            "manufacturer": info.manufacturer or None,
            "serial": info.serial or None,
            "resolution": resolution,
        })

    # ----------------------------- /capture & /preview ----------------
    def _route_capture(self, png: bool) -> None:
        frame = _fresh_frame()
        if png:
            body = _png_bytes(frame)
        else:
            # Live-preview poll: downscaled JPEG keeps each request light on
            # both the camera bus and the browser (positioning only).
            body = _jpeg_bytes(frame, quality=88, max_side=PREVIEW_MAX_SIDE)
        self._send(200, body, "image/png" if png else "image/jpeg")

    def log_message(self, fmt: str, *args) -> None:  # quieter default logs
        if os.environ.get("NODIQ_CAMERA_VERBOSE"):
            super().log_message(fmt, *args)


def _as_int_or_str(value: str):
    try:
        return int(value)
        # device IDs are numeric in this driver
    except (TypeError, ValueError):
        return value


def _first_line(exc: Exception) -> str:
    return str(exc).splitlines()[0]


def _code_msg(exc: Exception, fallback: str) -> str:
    text = _first_line(exc)
    return text or fallback


def _current_resolution(dev_mgr, index: int,
                        info: camera.DeviceInfo) -> dict | None:
    """Live AOI resolution: open the device briefly and read the actual
    sensor settings — never a hardcoded or cached number. When the camera is
    busy in another application, resolution is reported as null while
    `connected` stays true (from the enumeration)."""
    from mvIMPACT import acquire
    with _LOCK:
        try:
            p_dev = camera.open_device(dev_mgr, index, info)
        except camera.DeviceOpenFailed:
            return None
        try:
            settings = acquire.CameraSettingsBlueFOX(p_dev)
            width = int(settings.aoiWidth.read())
            height = int(settings.aoiHeight.read())
            return {"width": width, "height": height} \
                if width > 0 and height > 0 else None
        except Exception:
            return None
        finally:
            camera.close_device(p_dev)


def serve() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", CAMERA_AGENT_PORT), AgentHandler)
    print(f"[camera-agent] listening on http://127.0.0.1:{CAMERA_AGENT_PORT} "
          f"(allowed origins: {ALLOWED_ORIGINS_DESC})",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
