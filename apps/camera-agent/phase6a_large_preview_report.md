# Phase 6A — Large Microscope Live Preview

Date: 2026-10-01
Branch: `supabase-migration`
Camera: MATRIX VISION mvBlueFOX-ML/IGC205C · S/N 29605128 · Agent 127.0.0.1:8765

Baseline honored: Phases 1–5 frozen. **No engine changes. No second pipeline. No capture
or preview data changes.** Pure UI-size enhancement of the existing microscope panel.

---

## 1. Why the preview was enlarged

The operator uses the live preview to focus, position the field, and judge illumination.
The old panel lived inside the 560px `.upload-content` column with its own 420px cap,
leaving an ~445×333 display area — too small for comfortable focusing on a desktop
display. Phase 6A makes the preview the dominant element of the microscope panel, as
requested.

**Scope note (per spec §D):** the larger on-screen view does NOT change the physical
field of view, magnification, or the number of nodules captured. It only improves
operator visibility. No claim of "more nodules because the preview is bigger" is made.

## 2. Change made (one presentation change, one structural move)

File: [Analysis.jsx](../nodiq-x/src/pages/Analysis.jsx) — the only file changed.

1. Microscope panel `maxWidth: "420px"` → `"860px"` (the wide-panel cap already used by
   the dataset picker in this page).
2. The panel was moved from inside `.upload-content` (a centered 560px column) to be a
   **full-width sibling of the upload zone** inside the same `!uploaded` branch (wrapped
   in a fragment). It now spans the card's content width up to 860px; below 860px of
   available width it shrinks responsively.

The preview element itself already had the correct responsive recipe — unchanged:
`width: 100%` + `aspect-ratio: 4 / 3` + inner `<img>` with `objectFit: "contain"`.

## 3. Before / after (measured in the live DOM, real camera session)

| Viewport | Before (measured) | After (measured) | Gain |
|---|---|---|---|
| 1600px window | 445 × 333 px | **825 × 618 px** | ~3.4× area |
| 1024px window | ~445 × 333 (capped) | **790 × 592 px** | ~3.2× area, still shrinking |
| 840px window | 445 × 333 | 445 × 333 (same — column-bound) | equal; no overflow |

Measured aspect ratio after: **1.334 (4:3 = 1.333)** — no stretching
(`stretched: false` check against a 2% tolerance). No page-level horizontal scrolling at
840/1024/1600 (`scrollWidth == clientWidth` in all cases).

Layout after the change (matches the requested sketch):

```
MICROSCOPE   ● Connected
Camera: mvBlueFOX-ML/IGC205C · S/N 29605128 · 2592 × 1944
┌─────────────────────────────────────────────┐
│          LARGE LIVE PREVIEW (4:3)           │
└─────────────────────────────────────────────┘
PREVIEW: LIVE (1 s refresh)
[ CAPTURE IMAGE ]
```

## 4. Camera data — unchanged (verification)

| Item | Evidence |
|---|---|
| `/preview` still ~1024×768 JPEG | Verified this session, before the hardware drop: HTTP 200, 50 760 B, **(1024, 768)** via PIL |
| Capture still full-resolution | `captureFromMicroscope` → `/capture` path byte-for-byte unchanged (git diff shows no changes to any capture/analysis handler); Phase 5 captured 2592×1944 PNG through this exact path, and no camera-side code has been modified since (file mtimes: camera.py 09-30, agent_server.py 12:47 today = Phase 5) |
| RGBx stride handling | camera.py untouched (mtime 2026-09-30 15:41) |
| Analysis pipeline | nodularity_pipeline.py (09-30 18:07), analysis_child.py (09-24) untouched; no `/api/analyze-microscope` created |
| Frontend funnel | `captureImage() → Blob → File → runOnFile() → startAnalysis() → api.analyzeUpload()` — diff contains zero changes to this chain |
| No artificial upscaling | The same 1024×768 JPEG frame is rendered larger by CSS (`object-fit: contain`). No AI/sharpen/interpolate/enhance anywhere. |

## 5. Phase 5 behavior — preserved

- Preview starts on MICROSCOPE click, 1 Hz sequential polls, stops on panel close/unmount
  (`previewRef.current?.stop()` before each start) — untouched.
- CAPTURE IMAGE remains directly below the preview; disabled while `capturing` or
  disconnected. Post-capture wording kept: `✓ Capture ready — click START ANALYSIS to
  analyze.` (Phase 5 fix intact — verified in code).
- Error states untouched: offline (`○ Camera agent offline` + start hint + RETRY),
  disconnected (`○ Camera disconnected` + RETRY), busy (409 + friendly message + RETRY),
  preview error (`PREVIEW: UNAVAILABLE — will retry`).
- No WebSockets / no streaming infrastructure introduced.

Live demonstration during this phase's hardware drop (see §8): the UI kept every state
typed and recoverable — preview flipped to "UNAVAILABLE — will retry", CAPTURE disabled
itself, the page did not crash.

## 6. Real microscope visual validation

**Validated earlier this session (camera still connected, before it dropped off USB):**

- MICROSCOPE click → connected state + live preview (specimen visible) on the **enlarged**
  panel — live preview rendered in the 825×618 area at 1600px.
- Live capture through the enlarged panel → `START ANALYSIS` → full result
  (this is the Phase 5 §5 regression run, performed on today's Phase 5 code, which is
  unchanged by 6A except panel size/position).
- Responsive measurements at 1600/1024/840 px (§3).

**NOT TESTED — hardware removed by user mid-session:**

- Physical focus adjustment observed in the enlarged preview.
- Physical stage movement observed in the enlarged preview.
- Illumination adjustment observed in the enlarged preview.
- A fresh capture + START ANALYSIS on the enlarged layout after the drop.

The camera dropped off the USB bus a third time today (fresh SDK `deviceCount()` = 0)
and the user confirmed it is now unavailable. Per the Phase 4/5 port-hygiene rule the
hardware was not force-recovered; these four checks require the microscope and remain
to be performed next time the camera is connected. Note the underlying behaviors
(live preview freshness, physical response of preview to focus/stage/illumination,
capture→analysis) were all validated in Phases 3–5; what is untested is only their
appearance inside the larger panel.

## 7. Regression results

| Gate | Result |
|---|---|
| `npx oxlint src/pages/Analysis.jsx` | **0 errors** (2 pre-existing warnings) |
| `npm run build` | **PASS** (567 modules, built clean) |
| Full `python -m pytest -q` | **298/298 PASS** in 644 s (includes 56/56 pinning + 5/5 camera-state) |
| Pinning tests | included in the 298 (56/56) |
| Camera-state tests | included in the 298 (5/5) |

## 8. Limitations

1. **Real-hardware checks on the enlarged layout** (focus/stage/illumination response,
   post-drop capture): NOT TESTED — camera unavailable (§6). UI-side and camera-side
   code paths are otherwise fully validated.
2. Camera hardware flakiness (3 USB-bus drops today, `DEV_INTERNAL_ERROR` /
   `deviceCount()=0`) is a physical/driver issue outside software scope; recovery is
   user replug (proven twice today). During such drops the header dot can still show
   `● Connected` while the preview reports unavailable — the documented Phase 5 §8
   residual (stale SDK enumeration); typed and recoverable either way.
3. Panel cap is 860px (matching the dataset picker and staying inside the card without
   horizontal scroll); a full-bleed edge-to-edge preview was not requested and would
   fight the page grid.

## 9. Final status

**PASS with one declared gap** — all software acceptance criteria met (larger preview,
available panel width, exact 4:3, no stretch, responsive, no h-scroll, capture and
pipeline untouched, Phase 5 states preserved, lint/build/pytest green). The four
physical-microscope observations in §6 are NOT TESTED and require the camera.

STOP — no further phase started.
