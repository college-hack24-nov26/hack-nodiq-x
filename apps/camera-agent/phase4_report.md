# Phase 4 — Real Microscope Validation

Date: 2026-10-01
Branch: `supabase-migration`
Camera: MATRIX VISION mvBlueFOX-ML/IGC205C
Serial: 29605128
Microscope: physical metallurgical microscope at bench (model not recorded — not exposed in software)
Objective: not recorded (physical controls only, per scope)
Specimen: real metallographic specimen placed by user (type not recorded)

Baseline honored: Phase 2+3 frozen. No engine changes. No camera-architecture changes.
All captures flowed `captureImage() → Blob → File → runOnFile() → startAnalysis() →
api.analyzeUpload() → POST /api/analyze → existing engine`.

---

## 1. Physical setup — PASS

- Camera mounted on the microscope by the user; illumination working; real specimen placed;
  focus achieved through the microscope optics (user-confirmed).
- Camera visible to agent from the start of the session; while ImpactControlCenter held the
  camera during setup, the agent correctly reported `connected:true, resolution:null` and
  `/capture`+`/preview` returned **409 camera_busy** (verified by probe at 11:01).
- After the user closed ImpactControlCenter, the agent acquired the device (preview 200 at
  11:07:37) with no restart needed.
- Live preview displayed the real microscope field (screenshot evidence at 11:10).

## 2. Live preview — PASS

- Panel: ● Connected · mvBlueFOX-ML/IGC205C · S/N 29605128 · 2592 × 1944 · PREVIEW: LIVE (1 s refresh).
- Freshness: two `/preview` fetches 2 s apart → distinct MD5s (fresh acquisition each poll),
  identical brightness for the static field (expected).
- Physical response (user-confirmed while watching the preview): stage movement → image
  shifted; focus change → sharpness changed; illumination change → brightness changed.
- No browser crash, no uncontrolled request loop, no camera-busy loop during the whole session.

## 3. Capture — PASS

Three real captures taken through the UI (CAPTURE IMAGE button):

| # | Staged file | Result |
|---|-------------|--------|
| 1 | microscope_20261001-111110.png | staged instantly, "Captured successfully — starting analysis…", READY TO ANALYZE |
| 2 | microscope_20261001-112143.png | same |
| 3 | microscope_20261001-114036.png | same |

Each capture corresponds to the current microscope field (user had just positioned it via
the live preview), dimensions 2592×1944 PNG, no corruption (see §4/§7 checks).

## 4. Real specimen quality — PASS

| Condition | Capture | Frontend hint | Backend gate | Outcome |
|-----------|---------|---------------|--------------|---------|
| Properly focused | #1 | none (correct) | accepted | full result |
| Slightly defocused | #2 | none (correct) | accepted | full result |
| Too-dark illumination (reduced lamp) | #3 | none (correct — frame was dark-but-structured, mean 35.6, not lens-cap black) | accepted | full result |
| Too-bright | — | — | — | **not physically possible** with this lamp/specimen; engine saturation handling covered by the 293-test suite |
| Lens-cap black (from Phase 2/3 baseline + today's E2E) | — | "Image appears too dark. Check microscope illumination." | rejected gracefully: "Not a valid microstructure image — the engine could not segment graphite particles from this photo." | no crash, no hang, no fake result |

No bypass of the existing validity gate at any point.

## 5. Real analysis — PASS (software integration)

| Capture | Analysis ID | count | ISO % | JIS % | accuracy | confidence | processing |
|---------|------------|-------|-------|-------|----------|------------|-----------|
| #1 focused | ANL-71BA41 | 10 | 14.91 | 53.0 | 100 | 100 | ~3 s |
| #2 defocused | ANL-45A983 | 11 | 14.06 | 52.73 | 100 | 100 | 2.55 s |
| #3 dim field | ANL-5C2FCB | 17 | 31.39 | 54.71 | 100 | 100 | ~3 s |

Full result UI rendered for each: masks, roundness histogram, ISO 945 graphite forms
(dominant Form III — compacted/vermicular signature), estimated properties
(~370 MPa, EN-GJS-400-15 nearest grade, "estimate, not a measurement").

**Metallurgical correctness is NOT declared** — no independent ground truth for this
specimen. The accuracy/confidence shown are the engine's own self-check (reference
segmentation consistency), not a metallographic verdict. Software-integration correctness
(A) = PASS; metallurgical correctness (B) = out of scope without ground truth.

## 6. Upload vs microscope parity — PASS (byte-identical, same server process)

Capture #1's exact PNG bytes (content-addressed: `server_data/uploads/5c03b80ecd4cba27.png`,
md5 `0139cfe6430c38e75a9be9b523a1c3ec`) re-uploaded through the normal upload funnel
(ANL-AB7402) and compared against the microscope-path run (ANL-71BA41):

| Metric | Microscope path | Upload path (same bytes) |
|--------|-----------------|--------------------------|
| count | 10 | **10** |
| ISO nodularity % | 14.91 | **14.91** |
| JIS % | 53.0 | **53.0** |
| accuracy % | 100 | **100** |
| confidence % | 100 | **100** |

Identical. The real microscope image follows exactly the same funnel and engine.

## 7. Physical image checks — PASS

On capture #1's stored PNG (2592×1944, 3.95 MB):
- No black frame / lens-cap artifact (mean 35.5, structure present; lens-cap frames measure mean ≈ 10.7).
- No clipping: 0.00 % of pixels <5, 0.00 % >250.
- Channel means B 46.6 / G 37.5 / R 27.2 — smooth illumination tint, no channel scrambling.
- Stride integrity: adjacent-row diff 0.42 == adjacent-col diff 0.42 (a 4-byte-stride bug would shear rows); no vertical banding (column-profile std 5.03).
- Orientation and field: matched the live preview the user had positioned (user-confirmed).
- No pixel manipulation of any kind in the pipeline (no sharpening/enhancement — per scope).

Observation: the field is dim (gray max 77/255) — brighter illumination would likely improve
grain-level detail; purely a physical/optical knob, out of software scope.

## 8. Disconnect/reconnect — PASS (with one documented finding)

Live hardware test (user unplugged USB, then replugged):
- While unplugged: `/status` kept reporting `connected:true` with `resolution:null`
  (stale DeviceManager enumeration), and `/preview` returned **409** (agent's busy-type
  error). The UI stays alive; RETRY is offered; no crash.
- After replug: full recovery within seconds — `connected:true`, resolution restored,
  preview 200. No agent restart needed.
- Contrast: during Phase 3's involuntary USB-bus drop (PnP removal), `/status` correctly
  showed `connected:false` + clean 503. So driver-level removal presents correctly; a clean
  unplug can linger as "connected" with busy-type errors until the driver refreshes.
- **Finding (documented, not fixed per scope):** clean-unplug is surfaced with the
  busy-style message rather than "disconnected". Typed, recoverable, no crash. Future work:
  re-enumeration trigger on open-failure to distinguish vanished-device from busy.

Busy-ownership: live second-app test skipped by user; covered by today's earlier
holder-based E2E (Phase 3, 09:58–10:00): 409 + friendly "being used by another
application" + RETRY + preview-loop self-recovery + successful capture after release.
ImpactControlCenter busy→free transition also observed live at 11:01→11:07 (§1).

## 9. Full user workflow — PASS

Complete user-style flow performed without developer shortcuts:
start Flask → start Vite → start camera agent → open NODIQ-X → release camera from
ImpactControlCenter → open 🔬 MICROSCOPE panel → place/focus specimen (physical) →
adjust illumination (physical) → confirm live preview → CAPTURE → analysis → results UI.

Friction recorded (none blocking):
1. ImpactControlCenter holding the camera at session start (expected single-client behavior; user closes it when done).
2. "Captured successfully — starting analysis…" message appears but analysis actually starts
   only after clicking START ANALYSIS (minor wording mismatch, cosmetic).
3. Clean-unplug reports busy-style message instead of "disconnected" (§8 finding).

## 10. Known limitations

Software:
- Clean-unplug enumeration staleness (§8 finding).
- "starting analysis…" wording (§9.2).
- Stale busy/error text can persist in the panel until the next action (cosmetic, Phase 3 note).

Microscope/optical:
- Field brightness controlled only by physical illumination (no software exposure/gain — per scope).
- Too-bright condition not physically reachable with this lamp.

Metallurgical validation:
- No ground-truth specimen available → no metallurgical accuracy claim. Only engine
  self-check consistency (100 % on all three captures) is reported.

## 11. Final status

**PASS — Real microscope integration validated**

A real metallurgical microscope + MATRIX VISION camera was used from NODIQ-X to capture
real microstructure images, and those exact images flowed unchanged through the existing
analysis pipeline to full results, with byte-identical upload-path parity, graceful handling
of every physical condition tested, and instant recovery from hardware events.

Regression gate (end of phase): **293/293 pytest (includes the 56 pinning tests; pinning
subset also passed standalone earlier today) · oxlint 0 errors · npm build OK · camera
integration live-verified this session.**

STOP — Phase 4 complete.
