# NODIQ-X Camera Agent — Phase 1

Local Windows CLI that talks to the **MATRIX VISION mvBlueFOX-ML/IGC205C**
microscope camera through the installed **Balluff Impact Acquire** SDK and
saves one micrograph as `test_capture.png`.

Phase 1 scope ONLY: `Python → mvIMPACT Acquire → camera → test_capture.png`.
No web API, no NODIQ-X website integration (Phase 2).

This directory is fully isolated from the NODIQ-X analysis code — nothing
outside `nodiq-camera-agent/` was modified.

## 1. Prerequisites (verified on this machine)

| Component | Value found |
|---|---|
| Impact Acquire SDK | 3.7.2.4495, installed with root at `D:\` (`MVIMPACT_ACQUIRE_DIR=D:\`) |
| Camera driver | `mvBlueFOX.dll` 3.7.2 (System32), PnP device "MATRIX VISION mvBlueFOX(kernel driver version 2)" — Status OK |
| Official Python API | **`from mvIMPACT import acquire`** (not `import mvIMPACT`) |
| Python | 3.11.8 (`C:\Users\Atharv\AppData\Local\Programs\Python\Python311`) |

## 2. Installing the Python binding (one-time, done already)

There is **no PyPI wheel** — Balluff ships the binding as SWIG source that
must be compiled with a matching MSVC. This machine has VS Build Tools
(`D:\VSBuildTools`, MSVC 14.44), so the official build works without admin:

```bat
cd /d "D:\LanguageBindings\Python"
set MVIMPACT_ACQUIRE_DIR=D:\
python -m build --no-isolation
pip install --user dist\ImpactAcquire-3.7.2.4495-cp311-cp311-win_amd64.whl
```

The wheel installs the `mvIMPACT` package into the user site-packages
(`...\Roaming\Python\Python311\site-packages\mvIMPACT`, incl. the native
`lib_mvIMPACT_acquire.cp311-win_amd64.pyd`).

## 3. Usage

```bat
cd nodiq-camera-agent

python camera_agent.py --list     :: enumerate devices only
python camera_agent.py            :: enumerate + capture + validate + save
python camera_agent.py --out D:\temp\shot.png
```

Exit codes: `0` OK · `2` capture saved but validation WARN ·
`3` SDK/binding missing · `4` no camera detected · `5` open failed (e.g.
busy in ImpactControlCenter) · `6` acquisition failed/timeout.

## 4. Important operational notes

- **Close ImpactControlCenter / wxPropView first.** The mvBlueFOX is
  single-client: while another application owns the device, opening it from
  the agent fails with a clear `DeviceOpenFailed` message instead of a
  traceback.
- The capture is free-run with **firmware exposure/gain** (no manual
  overrides) — the agent never guesses illumination parameters.
- `test_capture.png` is written losslessly; 16-bit sensor data stays 16-bit.
- Validation (Phase 1D) checks geometry, black/white frames, flat fields and
  reports mean/min/max intensity before any NODIQ-X analysis is involved.

## 5. Files

| File | Purpose |
|---|---|
| `camera.py` | SDK layer: enumeration, safe open, single-frame capture → numpy |
| `camera_agent.py` | CLI: list / capture / validate / save + typed error handling |
| `config.py` | Device matching strings, timeout, validation thresholds |
| `requirements.txt` | numpy + opencv only; binding comes from the local SDK build |
