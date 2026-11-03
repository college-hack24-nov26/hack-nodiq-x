# NODIQ-X — REVISED PHASE 2 + PHASE 3 REPORT
## Camera-Only Validation at Home (microscope deferred)

Date: 2026-10-01 · Branch: `supabase-migration` · Camera: mvBlueFOX-ML/IGC205C (S/N 29605128)

---

## A. Scope & objective

Validate the MATRIX VISION mvBlueFOX-ML/IGC205C integration into NODIQ-X **as an extra
image input source**, camera-only, at home — **without** the physical microscope. All
microscope-specific validation (illumination, focus, positioning workflow, real-specimen
image quality) is **explicitly DEFERRED** by user decision.

Invariant enforced throughout: microscope capture flows
`microscopeAgent.captureImage() → Blob → File → runOnFile() → startAnalysis() →
api.analyzeUpload() → POST /api/analyze → existing engine`. No second analysis pipeline.

## B. Architecture (unchanged, verified)

- Camera agent: `nodiq-camera-agent/agent_server.py`, stdlib `http.server`, 127.0.0.1:8765.
- Endpoints: `/status` (live driver query), `/preview` (JPEG ≤1024px, q88), `/capture` (PNG).
- SDK layer: `camera.py` (mvIMPACT Acquire 3.7.2.4495), RGBx888Packed 4-byte stride handled.
- Device session cache (Phase 3): device stays open 15 s between requests
  (`NODIQ_CAMERA_IDLE_CLOSE_S`), idle timer closes it so other apps can claim the camera.
- Frontend: `nodiq-x/src/services/microscopeAgent.js` + `nodiq-x/src/pages/Analysis.jsx`.
- Engine: nodularity_pipeline.py + analyze_with_recovery.py — **only funnel wiring touched,
  never the pipeline itself**, in Phases 2–3.

## C. Test matrix — results

| # | Test | Result |
|---|------|--------|
| 1 | `/status` live values (model, S/N, 2592×1944) | PASS |
| 2 | `/capture` freshness (two distinct ~3 MB frames, lens cap dark) | PASS |
| 3 | `/preview` downscaled 1024×768 JPEG (~14 KB) | PASS |
| 4 | CORS allow-list (no wildcard; foreign origin gets no ACAO) | PASS |
| 5 | Chrome Private Network Access preflight | PASS |
| 6 | CSP `connect-src` includes 127.0.0.1:8765 + localhost:8765 (server.py only change) | PASS |
| 7 | Browser: panel opens, ● Connected, model/S/N/resolution | PASS |
| 8 | Browser: live preview frames in panel, "PREVIEW: LIVE (1 s refresh)" | PASS |
| 9 | Browser: CAPTURE → File → runOnFile staging (`microscope_*.png`) | PASS |
| 10 | Browser: dark-frame hint "Image appears too dark. Check microscope illumination." — shown in panel AND persisted near staged image after panel unmounts | PASS |
| 11 | Camera disconnect: `/status` → `connected:false`, `/preview` → clean 503 JSON, UI shows ○ Camera disconnected + RETRY, no crash (observed during a real USB-bus drop) | PASS |
| 12 | Camera busy (another app holds device): agent `/capture`,`/preview` → 409 `camera_busy`; `/status` → `connected:true, resolution:null`; browser CAPTURE → friendly "being used by another application" + RETRY; preview loop keeps retrying through the busy window and **self-recovers** (preview 200s resume, next CAPTURE succeeds) — no crash, no stale lock | PASS |
| 13 | Agent offline: typed message "Cannot reach the camera agent at http://127.0.0.1:8765. Start it with: python agent_server.py" + RETRY, no crash | PASS |
| 14 | Retry/recovery after agent restart: panel reopen → ● Connected + live preview | PASS |
| 15 | Upload-path regression (same session): staging + analysis unchanged | PASS |
| 16 | Parity — see section D | PASS (with documented engine-version finding) |
| 17 | Engine test suite: **293 passed, 0 failed** (Part A restoration) + today's re-run of the 56 engine-pinning tests (annotation regressions, accuracy bench, invalid-microstructure, size filter, audit, regression gate) → **56 passed** | PASS |
| 18 | `oxlint`: 0 errors | PASS |
| 19 | `npm run build`: OK | PASS |
| 20 | Dark-frame gate E2E: fresh dark capture POSTed to `/api/analyze` → engine rejects gracefully "Not a valid microstructure image…" (HTTP 202 → failed record, no crash, no hang) | PASS |

## D. Parity — PROVEN, with one important clarification

**Byte-for-byte parity (funnel equivalence) is PROVEN** — 2026-09-30 16:23/16:34, same server
process, same engine, same exact PNG bytes:

| Path | count | ISO | JIS | accuracy | confidence |
|------|-------|-----|-----|----------|------------|
| Microscope capture (cb30dc355d723be5.png) | 21 | 15.56 | 60.0 | 95 | 100 |
| Same bytes via normal upload | 21 | 15.56 | 60.0 | 95 | 100 |

DB cross-check (ANL-D23A37 vs ANL-FC3DE1) confirms identical metrics for both paths.

**Engine-version finding (root-caused today, not a funnel defect):** re-running the stored
bytes today returned count 12 / ISO 15.49 / JIS 55.83 / acc 100 (ANL-4039A5, twice-confirmed
deterministic). Root cause: `server.py` runs the engine **in-process** (`NODIQ_EXEC_MODE`
default `thread`), so the engine loads into the server's memory at boot. Yesterday's
"post-fix parity rerun" (21, at 18:48) ran in a server process booted **before** the 18:07
Part A engine fix — it silently used the pre-fix in-memory engine. Evidence:
- Fresh processes on current disk code: 12, 12, 12 (deterministic; thread caps irrelevant).
- No engine source/package changes since Sep 30 18:48.
- All 56 engine-pinning tests pass on current disk code (the 293-test suite always spawns
  fresh interpreters, so it validated the disk engine all along).
- The 21→12 delta is exactly the restored 800px minimum-area floor (Part A) excluding 9
  sub-floor particles from the count path: self_check reference_count 20→12, doubles 1→0,
  ISO nearly unchanged (15.56→15.49).
**Conclusion: same funnel + same bytes + same engine = identical numbers, both directions
(proven). Cross-boot engine-version deltas are expected and are not parity failures.**

## E. Part A (engine) recap

Pre-existing uncommitted engine edits caused 2 locked-bench failures. Root cause:
SMALL_AREA_FLOOR_RATIO=150px@1920 (vs validated AREA_FLOOR_RATIO=800px). User chose
"Restore 800px floor": all 5 count-path sites in nodularity_pipeline.py use
min_nodule_area again; recover_and_merge min_recover_area back to AREA_FLOOR_RATIO;
SPLIT_TOUCHING_PAIRS=False gate (reversible); recovery darkness-ceiling relaxation
RETAINED. hi5 pin re-pinned to measured 49 / 42.86 (count matches commit; ISO −0.02 due to
retained thin-bar blanking). Suite: 293/293.

## F–G. Phase 3 features delivered

Live preview (1 s polling loop, start/stop, unmount cleanup, auto-retry through busy/
offline windows) · Capture UX (status, model, S/N, resolution, live preview, CAPTURE IMAGE
with CAPTURING… + duplicate-click guard, RETRY everywhere) · Quality hints (canvas 128px,
hint-only: too dark/too saturated; backend stays authoritative) · Busy/offline/disconnect/
timeout/malformed/network error handling — all graceful, no Analysis-page crashes.

## H. Security

CORS allow-list (no wildcard), PNA preflight answered, CSP connect-src scoped to the agent
on loopback, agent binds 127.0.0.1 only, no LAN exposure. Preserved throughout.

## I. Known limitations (camera-only scope)

1. Stale busy-error text can remain visible in the panel until the next status/preview
   action refreshes it (cosmetic; the loop itself recovers automatically).
2. Dark frames (lens cap / no microscope light) are correctly hinted and correctly rejected
   by the engine — real-specimen image quality is untested until the microscope phase.
3. Preview is 1 Hz polling JPEG by design (reliability over fanciness, per spec).

## J. Explicitly DEFERRED (not validated at home)

- Illumination/exposure behavior on real specimens (no exposure/gain controls built — per scope).
- Focus/positioning workflow ergonomics at the eyepiece.
- Calibration/mpp wiring, mm-scale measurements.
- Any microscope-mounted mechanical workflow.
- Live parity on a specimen image (deferred with the microscope).

## K. How to run

See `.freebuff/run.md` (3 processes table). Microscope flow requires the camera agent AND
the camera free (close ImpactControlCenter / wxPropView).

## L. Verdict

**PHASE 2 + PHASE 3 CAMERA-ONLY COMPLETE — STOP**

All camera-only validation targets pass. No Phase 4 work started. Engine untouched by
Phases 2–3 beyond the user-approved Part A restoration (800px floor), which is fully
regression-tested (293/293 + 56/56 pinning re-run).
