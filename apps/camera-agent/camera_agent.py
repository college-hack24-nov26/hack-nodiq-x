"""NODIQ-X Camera Agent — Phase 1 command-line tool.

    python camera_agent.py            # enumerate + capture + validate + save
    python camera_agent.py --list     # enumerate devices only
    python camera_agent.py --out X.png

Phase 1 scope ONLY (no web API, no NODIQ-X website integration):
    Python -> mvIMPACT Acquire -> MATRIX VISION camera -> capture -> PNG
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from config import (BLACK_MEAN_MAX, DARK_MEAN_MAX, DEFAULT_CAPTURE_PATH,
                    EXPECTED_MANUFACTURER, EXPECTED_MODEL_SUBSTRINGS,
                    UNIFORM_STD_MAX, WHITE_MEAN_MIN)
from camera import (CaptureFailed, DeviceOpenFailed, Frame, NoDeviceFound,
                    SdkUnavailable, capture_frame, enumerate_devices,
                    open_device, pick_device, require_sdk)


def _fmt(value: float | None, suffix: str) -> str:
    return "n/a" if value is None else f"{value:g}{suffix}"


def list_devices() -> int:
    """Enumerate and print every device; exit code 0 when at least one."""
    require_sdk()
    dev_mgr = _new_device_manager()
    devices = enumerate_devices(dev_mgr)
    if not devices:
        print("[ERROR] MATRIX VISION camera not detected.")
        print("        The driver loaded fine, but no device is connected.")
        return 1
    for i, d in enumerate(devices):
        print(f"[{i}] {d.model() or '(unknown model)'}")
        print(f"    manufacturer : {d.manufacturer or '(n/a)'}")
        print(f"    device id    : {d.device_id}")
        print(f"    serial       : {d.serial or '(n/a)'}")
        print(f"    interface    : {d.interface or '(n/a)'}")
        print(f"    in use by    : {d.in_use or '(free)'}")
    match = _matching_summary(devices)
    if match:
        print(f"\nExpected camera match: {match}")
    else:
        print("\n[WARN] None of the detected devices matches the expected "
              f"{EXPECTED_MANUFACTURER} mvBlueFOX-ML/IGC205C.")
    return 0


def _new_device_manager():
    # Keep the DeviceManager alive for as long as we work with devices: when
    # the last reference dies, the SDK closes everything automatically.
    from mvIMPACT import acquire
    return acquire.DeviceManager()


def _matching_summary(devices) -> str | None:
    for d in devices:
        haystack = " ".join((d.family, d.product, d.family_full,
                             d.manufacturer)).lower()
        if "mvbluefox" in haystack:
            model = d.model()
            flag = "" if "igc205c" in haystack else \
                " (variant differs from IGC205C)"
            return f"{d.manufacturer or EXPECTED_MANUFACTURER} {model}{flag}"
    return None


def validate_frame(frame: Frame) -> tuple[bool, dict]:
    """Phase 1D checks on the captured array (pre-save, full precision)."""
    a = np.asarray(frame.array)
    if a.dtype == np.uint16:
        norm = a.astype(np.float64) / 257.0       # comparable to 8-bit scale
    else:
        norm = a.astype(np.float64)
    stats = {
        "mean": float(norm.mean()),
        "min": float(norm.min()),
        "max": float(norm.max()),
        "std": float(norm.std()),
    }
    reasons = []
    if stats["mean"] <= BLACK_MEAN_MAX:
        reasons.append("image is completely black")
    elif stats["mean"] <= DARK_MEAN_MAX:
        reasons.append(
            "frame is nearly black — no usable micrograph signal; "
            "remove the lens cap / switch on the microscope illumination")
    if stats["mean"] >= WHITE_MEAN_MIN:
        reasons.append("image is completely white (lens cap on?)")
    if stats["std"] <= UNIFORM_STD_MAX:
        reasons.append("flat field — no texture visible")
    return (not reasons), {"reasons": reasons, **stats}


def save_capture(frame: Frame, path: Path) -> None:
    """Save the raw acquisition losslessly; 16-bit data stays 16-bit PNG."""
    import cv2
    a = frame.array
    if a.ndim == 3:
        ok = cv2.imwrite(str(path), a[:, :, ::-1])   # numpy BGR -> file BGR
    else:
        ok = cv2.imwrite(str(path), a)
    if not ok:
        raise CaptureFailed(f"[ERROR] Could not write {path}.")


def capture(out_path: Path) -> int:
    """Full pipeline: enumerate -> open -> capture -> validate -> save."""
    t0 = time.time()
    require_sdk()
    dev_mgr = _new_device_manager()
    devices = enumerate_devices(dev_mgr)

    index = pick_device(dev_mgr, devices)             # raises NoDeviceFound
    info = devices[index]
    print(f"Camera detected ✓")
    print(f"Manufacturer: {info.manufacturer or EXPECTED_MANUFACTURER}")
    print(f"Model: {info.model()}")
    print(f"Device ID: {info.device_id}"
          + (f"  (serial {info.serial})" if info.serial else ""))
    print(f"Interface: {info.interface or '(n/a)'}")

    p_dev = open_device(dev_mgr, index, info)         # raises DeviceOpenFailed
    print("Status: Connected — device opened")
    print("Acquiring one frame (free-run, firmware exposure/gain)…")

    frame = capture_frame(p_dev)                      # raises CaptureFailed
    ok, stats = validate_frame(frame)
    save_capture(frame, out_path)

    print()
    print("Capture successful ✓")
    print()
    print("File:")
    print(str(out_path))
    print()
    print("Resolution:")
    print(f"{frame.width} × {frame.height}")
    print()
    print(f"Pixel format: {frame.pixel_format or '(unspecified)'}"
          f" — {frame.channels} channel(s) @ {frame.bit_depth} bit")
    print(f"Exposure: {_fmt(frame.exposure_us, ' µs')}   "
          f"Gain: {_fmt(frame.gain_db, ' dB')}")
    print()
    print("Mean intensity: {:.2f}".format(stats["mean"]))
    print("Min: {:.0f}".format(stats["min"]))
    print("Max: {:.0f}".format(stats["max"]))
    print()
    if ok:
        print("Image validation:")
        print("PASS")
    else:
        print("Image validation:")
        print("WARN — " + "; ".join(stats["reasons"]))
        print("(frame saved anyway for inspection)")
    print(f"\nElapsed: {time.time() - t0:.2f} s")
    return 0 if ok else 2


def main() -> int:
    # Windows consoles default to cp1252; the report uses ✓/×/µ glyphs.
    # Reconfigure (never crash on encoding), then run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(
        description="NODIQ-X camera agent — Phase 1 CLI (mvIMPACT Acquire)")
    parser.add_argument("--list", action="store_true",
                        help="enumerate devices only")
    parser.add_argument("--out", type=Path, default=DEFAULT_CAPTURE_PATH,
                        help="output PNG path (default: test_capture.png)")
    args = parser.parse_args()

    try:
        if args.list:
            return list_devices()
        return capture(args.out)
    except SdkUnavailable as exc:
        print(f"[ERROR] {exc}")
        return 3
    except NoDeviceFound as exc:
        print(str(exc).splitlines()[0])
        return 4
    except DeviceOpenFailed as exc:
        print(str(exc).splitlines()[0])
        return 5
    except CaptureFailed as exc:
        print(str(exc).splitlines()[0])
        return 6
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
