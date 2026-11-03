"""NODIQ-X Camera Agent — mvIMPACT Acquire (Balluff) camera layer.

Official API (verified against the SDK installed on this machine, Impact
Acquire 3.7.2.4495):

    from mvIMPACT import acquire

Follows the SDK's documented single-image acquisition pattern:
DeviceManager -> pDev.open() -> FunctionInterface.imageRequestSingle()
-> imageRequestWaitFor() -> check request.isOK -> copy pixels -> unlock.
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass, field

import numpy as np

try:
    from mvIMPACT import acquire
except ImportError as exc:  # binding missing/not built for this Python
    acquire = None
    _ACQUIRE_IMPORT_ERROR = exc
else:
    _ACQUIRE_IMPORT_ERROR = None

from config import ACQUISITION_TIMEOUT_MS, PREFERRED_DEVICE_SUBSTRINGS


class CameraError(Exception):
    """Base class for all camera-agent failures (message is user-facing)."""


class SdkUnavailable(CameraError):
    """mvIMPACT Acquire Python binding could not be imported."""


class NoDeviceFound(CameraError):
    """SDK works, but no camera is connected/visible to the driver."""


class DeviceOpenFailed(CameraError):
    """A device was found but could not be opened."""


class CaptureFailed(CameraError):
    """Device open succeeded but no valid frame could be acquired."""


@dataclass
class DeviceInfo:
    """Everything Identity/DeviceManager exposes for one connected device."""

    family: str
    product: str
    family_full: str          # deviceModelName, e.g. "mvBlueFOX-ML/IGC205C"
    manufacturer: str
    serial: str
    device_id: str
    interface: str
    in_use: bool = False      # True when another process owns the device

    def model(self) -> str:
        # deviceModelName is the natural full form (e.g. "mvBlueFOX-ML/IGC205C");
        # product usually equals it and family is just "mvBlueFOX".
        return self.family_full or self.product or self.family

    def as_dict(self) -> dict:
        return {
            "model": self.model(),
            "manufacturer": self.manufacturer or None,
            "device_id": self.device_id,
            "serial": self.serial or None,
            "interface": self.interface or None,
            "in_use_by": self.in_use or None,
        }


@dataclass
class Frame:
    """One acquired image plus the metadata read from the request buffer."""

    array: np.ndarray                     # (h, w) u8/u16 or (h, w, 3) u8
    width: int
    height: int
    channels: int
    bit_depth: int
    pixel_format: str
    # Settings actually in effect after the driver applied our defaults
    exposure_us: float | None = field(default=None)
    gain_db: float | None = field(default=None)


def require_sdk() -> None:
    """Raise SdkUnavailable with actionable guidance if the binding is missing."""
    if acquire is not None:
        return
    raise SdkUnavailable(
        "The mvIMPACT Acquire Python binding is not importable "
        f"(underlying error: {_ACQUIRE_IMPORT_ERROR}). Build and install it "
        "from the SDK installation:  cd /d LanguageBindings\\Python && "
        "python -m build --no-isolation && pip install --user dist\\ImpactAcquire-*.whl"
    )


def _safe(obj, attr: str, default: str = "") -> str:
    """Read a (possibly Property) attribute defensively — never let one bad
    field kill device enumeration. Driver properties need .read(); some
    (like `manufacturer` on a closed mvBlueFOX) raise until the device is
    opened, which is fine here."""
    try:
        value = getattr(obj, attr)
        if callable(value):
            value = value()               # e.g. getIsInUse()
        if hasattr(value, "read"):
            value = value.read()
        if value is None:
            return default
        return value if isinstance(value, str) else str(value)
    except Exception:
        return default


def _read_bool(obj, attr: str) -> bool:
    """Boolean driver state (e.g. Device.isInUse) read defensively."""
    try:
        value = getattr(obj, attr)
        if callable(value):
            value = value()
        if hasattr(value, "read"):
            value = value.read()
        return bool(value)
    except Exception:
        return False


def enumerate_devices(dev_mgr: "acquire.DeviceManager") -> list[DeviceInfo]:
    """List every device the installed driver can see (hardware queried,
    nothing hardcoded)."""
    count = dev_mgr.deviceCount()
    devices: list[DeviceInfo] = []
    for i in range(count):
        try:
            p_dev = dev_mgr.getDevice(i)
            devices.append(DeviceInfo(
                family=_safe(p_dev, "family"),
                product=_safe(p_dev, "product"),
                family_full=_safe(p_dev, "deviceModelName"),
                manufacturer=_safe(p_dev, "manufacturer"),
                serial=_safe(p_dev, "serial"),
                device_id=_safe(p_dev, "deviceID", default=str(i)),
                interface=_safe(p_dev, "interface"),
                in_use=_read_bool(p_dev, "isInUse"),
            ))
        except Exception as exc:
            # Keep enumerating the remaining devices regardless.
            devices.append(DeviceInfo(
                family=f"<unreadable device {i}: {exc}>", product="",
                family_full="", manufacturer="", serial="", device_id=str(i),
                interface="", in_use=False))
    return devices


def pick_device(dev_mgr: "acquire.DeviceManager",
                devices: list[DeviceInfo]) -> int:
    """Index of the best matching device (preferred substrings), raising
    NoDeviceFound when there is nothing usable."""
    if not devices:
        raise NoDeviceFound(
            "[ERROR] MATRIX VISION camera not detected. Connect the camera "
            "and check its driver status in Device Manager, then retry.")
    for i, info in enumerate(devices):
        haystack = " ".join((info.family, info.product, info.family_full,
                             info.manufacturer))
        if any(s.lower() in haystack.lower()
               for s in PREFERRED_DEVICE_SUBSTRINGS):
            return i
    # Devices exist but none matches the expected family — surface them.
    found = "; ".join(d.model() or f"device {d.device_id}" for d in devices)
    raise NoDeviceFound(
        f"[ERROR] MATRIX VISION camera not detected. Other devices are "
        f"visible to the driver: {found}")


def open_device(dev_mgr: "acquire.DeviceManager", index: int,
                info: DeviceInfo) -> "acquire.Device":
    """Open the device, translating 'in use by another application'."""
    p_dev = dev_mgr.getDevice(index)
    if info.in_use:
        raise DeviceOpenFailed(
            f"[ERROR] Camera is currently being used by another application. "
            "Close it there (e.g. ImpactControlCenter / wxPropView) and "
            "retry.")
    try:
        result = p_dev.open()
    except acquire.ImpactAcquireException as exc:
        raise DeviceOpenFailed(
            f"[ERROR] Could not open camera ({info.model()}): "
            f"{acquire.ImpactAcquireException.getErrorCodeAsString(exc.errorCode)}"
        ) from exc
    # The binding returns None on success (verified against 3.7.2.4495); a
    # numeric non-zero result is the documented error path.
    if result is not None and result != acquire.DMR_NO_ERROR:
        raise DeviceOpenFailed(
            f"[ERROR] Could not open camera ({info.model()}): "
            f"{acquire.ImpactAcquireException.getErrorCodeAsString(result)}")
    return p_dev


def close_device(p_dev) -> None:
    """Best-effort close so other applications can claim the camera right
    after us (mvBlueFOX is single-client)."""
    try:
        p_dev.close()
    except Exception:
        pass


def _apply_safe_defaults(settings: "acquire.CameraSettingsBlueFOX") -> None:
    """Conservative acquisition defaults; every write is best-effort because
    property availability varies between device families (verified on this
    mvBlueFOX: there is no `acquisitionMode`, and free-run is the firmware
    default anyway). We deliberately set NO exposure/gain overrides: the
    firmware defaults give a correctly exposed frame; validation — not the
    agent — judges the result."""
    # Free-run (no hardware trigger) when the constant exists for this family.
    tm_continuous = getattr(acquire, "tmContinuous", None)
    if tm_continuous is not None:
        try:
            settings.triggerMode.write(tm_continuous)
        except Exception:
            pass


def capture_frame(p_dev: "acquire.Device",
                  timeout_ms: int = ACQUISITION_TIMEOUT_MS) -> Frame:
    """Acquire exactly one frame and return it as a numpy array.

    The caller keeps NO reference to the request after this returns (pixels
    are copied), so the buffer is unlocked and the driver stays healthy.
    """
    fi = acquire.FunctionInterface(p_dev)
    settings = acquire.CameraSettingsBlueFOX(p_dev)
    _apply_safe_defaults(settings)
    statistics = acquire.Statistics(p_dev)

    if fi.imageRequestSingle() != acquire.DMR_NO_ERROR:
        raise CaptureFailed(
            "[ERROR] The driver rejected the acquisition request.")

    request_nr = fi.imageRequestWaitFor(timeout_ms)
    if not fi.isRequestNrValid(request_nr):
        try:
            code_str = acquire.ImpactAcquireException.getErrorCodeAsString(
                request_nr)
        except Exception:
            code_str = f"code {request_nr}"
        fi.imageRequestReset(0, 0)
        raise CaptureFailed(
            f"[ERROR] Acquisition timeout — no frame arrived within "
            f"{timeout_ms} ms ({code_str}). Is the camera shutter/lens cap "
            "ok and is another application streaming?")

    request = fi.getRequest(request_nr)
    try:
        if not request.isOK:
            raise CaptureFailed(
                "[ERROR] The captured frame is invalid "
                f"({request.requestResult.readS()}).")
        frame = _request_to_frame(request)
    finally:
        fi.imageRequestUnlock(request_nr)

    # Carry out the actual exposure/gain values the driver used (verified
    # property names on CameraSettingsBlueFOX: expose_us, gain_dB).
    try:
        frame.exposure_us = float(settings.expose_us.read())
    except Exception:
        pass
    try:
        frame.gain_db = float(settings.gain_dB.read())
    except Exception:
        pass
    del statistics
    return frame


def _request_to_frame(request: "acquire.Request") -> Frame:
    """Copy pixels out of a locked request into a numpy array.

    mvBlueFOX-ML/IGC205C is a monochrome sensor, so the common case is a
    single-channel 8-bit or 12/16-bit frame; RGB is supported for safety.
    """
    w = int(request.imageWidth.read())
    h = int(request.imageHeight.read())
    channels = int(request.imageChannelCount.read())
    bit_depth = int(request.imageChannelBitDepth.read())
    pixel_format = request.imagePixelFormat.readS()

    if w <= 0 or h <= 0 or channels <= 0:
        raise CaptureFailed(
            f"[ERROR] Acquired frame has invalid geometry "
            f"({w}x{h}, {channels} channels).")

    size = int(request.imageSize.read())
    buffer = (ctypes.c_char * size).from_address(int(request.imageData.read()))
    raw = bytes(buffer)

    # Bytes per pixel from the actual buffer size — formats like
    # RGBx888Packed store 4 bytes per pixel while imageChannelCount says 3
    # (verified on this device: 2592*1944*4 = 20155392). Trust the buffer.
    bytes_per_px = max(1, size // (w * h))
    if channels >= 3:
        packed = np.frombuffer(raw, dtype=np.uint8,
                               count=h * w * bytes_per_px).reshape(h, w,
                                                                   bytes_per_px)
        array = packed[:, :, :3]           # BGR byte order from the driver
    elif bit_depth > 8:
        array = np.frombuffer(raw, dtype=np.uint16, count=h * w)\
                  .reshape(h, w)
    else:
        array = np.frombuffer(raw, dtype=np.uint8, count=h * w).reshape(h, w)
    return Frame(array=array, width=w, height=h, channels=channels,
                 bit_depth=bit_depth, pixel_format=pixel_format)
