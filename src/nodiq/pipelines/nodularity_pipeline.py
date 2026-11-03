#!/usr/bin/env python3
"""
nodularity_pipeline.py — reusable ductile-iron nodule analysis pipeline.

One call works on ANY image (any size, color or grayscale):

    from nodiq.pipelines.nodularity_pipeline import analyze_image, analyze_file
    res = analyze_image("some_random_micrograph.png")
    res["count"], res["iso_pct"], res["jis_pct"], res["accuracy"]

Pipeline (imported stages, frozen detector never edited):
  1. frozen hybrid detector (nodularity_adaptive)
  2. recovery of missed nodules (borders, mottled/Gaussian-surface interiors)
  3. consolidate_joined  — dividing nodules (neck-connected lobes) = ONE
  4. fill_owned_blobs    — one physical dark blob = ONE nodule, whole blob
  5. independent reference segmentation + particle-level accuracy
     (precision / recall / F1 / counting accuracy)

analyze_file() additionally writes mask, annotated overlay (stats banner on
top) and per-nodule CSV for the given image.
"""
import base64
import csv
import math
import sys
from pathlib import Path

import cv2
import numpy as np

from nodiq.core.config import REPO_ROOT, THIRD_PARTY_NODULARITY, DATA_RAW_DIR

PROJECT_ROOT = REPO_ROOT
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
_nodularity_main = THIRD_PARTY_NODULARITY
if _nodularity_main.is_dir() and str(_nodularity_main) not in sys.path:
    sys.path.insert(0, str(_nodularity_main))

from nodiq.pipelines.analyze_with_recovery import (  # noqa: E402
    detect_frozen, recover_and_merge, consolidate_joined, fill_owned_blobs,
    dominant_label, max_half_length, jis_bucket, draw_banner,
    physical_blob_map, area_floor, largest_contour_of,
    AREA_FLOOR_RATIO, CONSISTENCY_KEEP_FRAC)

try:
    import nodularity as legacy  # type: ignore # noqa: E402
except (ImportError, ModuleNotFoundError):
    class LegacyDefaults:
        pic_width = 1920
        marumi_ratio = 0.6
    legacy = LegacyDefaults()

MARUMI_ISO = getattr(legacy, "marumi_ratio", 0.6)  # 0.6

# CONSISTENCY_KEEP_FRAC: a detection whose own area is almost entirely LIGHT in
# the human-view blob map (median+Otsu) is phantom texture, not graphite.
# Measured across the 1000-image batch: real particles have dark fraction ~1.0
# while phantoms on faint mottling sit near 0. Partial catches of a real
# particle stay (threshold well below their ~0.8 typical minimum).


# ------------- figure-annotation overlays (scale bar / label / stats box) ----
# Published micrographs carry baked-in figure furniture: a black scale bar, a
# white panel-label box ("a"), and a dark statistics panel. None of that is
# microstructure, but every threshold stage happily counts it as giant
# graphite particles (a stats panel alone can outweigh the whole field and
# collapse nodularity). The detector below finds near-perfect SOLID
# RECTANGLES of near-CONSTANT intensity near the frame edges and blanks them
# to matrix-white before segmentation. Real graphite never passes all four
# tests at once (particles are round-ish: bbox fill 0.785; textured: std >
# 18), and the detector is deliberately conservative — when in doubt, do
# not blank.
ANNOT_MIN_AREA_FRAC = 0.002      # component >= 0.2% of the image area
ANNOT_MIN_DIM_FRAC = 0.03        # ... and not tiny on both axes
ANNOT_MIN_FILL = 0.85            # bbox fill (a circle scores 0.785)
ANNOT_MAX_STD = 18.0             # constant intensity inside the component
ANNOT_MAX_BOXES = 8              # more than this = figure furniture implausible
ANNOT_CENTER_BAND = (0.35, 0.65) # fully central components are never touched
ANNOT_BAR_KERNEL = (11, 41)      # opening kernel for the bar second pass
                                 # (rows, cols) — 11x41 = HORIZONTAL bar;
                                 # the transpose covers vertical bars
ANNOT_BAR_MIN_FILL = 0.97        # bar cores are near-perfect rectangles
ANNOT_BAR_MIN_ASPECT = 2.0       # ... and elongated (scale bars)
ANNOT_DARK_PANEL_MIN_DIM = 300   # dark PANEL furniture spans >=300px on BOTH
                                 # axes (measured: 612x475 stats panel; the
                                 # largest real particle in the 1000-image
                                 # dataset reaches only 388 on one axis and
                                 # 219 on the other). Compact/tall dark blobs
                                 # are real graphite — never blank them.
ANNOT_BAR_MIN_MAX_DIM = 200      # bar cores: >=200px long (scale bars;
                                 # a 260px bar erodes to a 220px core)
ANNOT_PANEL_KERNEL = 61          # square opening kernel for panel cores
ANNOT_PANEL_MIN_CORE = 300       # panel cores span >=300px on BOTH axes
                                 # (kernel eats ~60px off the raw panel:
                                 # 612x475 -> ~459x340 core)
ANNOT_PANEL_MIN_FILL = 0.72      # coarse prefilter; the TRIM test below
                                 # is the real discriminator
ANNOT_PANEL_MAX_ASPECT = 1.8     # panels are squat; elongated cores are
                                 # stringers (real graphite) — never blank
ANNOT_PANEL_DOMINANCE = 0.85     # the solid rectangle must hold >=85% of
                                 # the component (a disk's inscribed square
                                 # holds only ~64% -> protected)

# Recovery darkness ceiling: the frozen 60 (1920-scale, dark-etched fields)
# rejects real mid-gray graphite on lighter 10x fields. A ceiling derived
# from the matrix brightness (matrix median - 40, clamped to [60, 110])
# keeps the historical behavior on dark fields while recovering genuinely
# missed small nodules on lighter ones. Shape gates (solidity, skirt,
# scratch) still reject texture — only the darkness test is relaxed.
RECOVERY_MAX_MED_GRAY = None     # set per-image in analyze_image()

# Touching-doublet split: introduced for the small-particle recall
# experiment (sub-800px doublets on dense fine fields). With the historical
# 800px@1920 count floor restored (locked bench: fp_carried<=6, count
# invariant to min_grainsize), its target population is excluded upstream
# and the stage made the final count sensitive to min_grainsize (split
# firing 8x vs 6x across the sweep = exactly the +1 that broke the lock).
# It also contradicts the documented large-particle convention that
# neck-connected dividing nodules are ONE nodule. Gated off; flip to True
# only together with SMALL_AREA_FLOOR_RATIO and a re-locked bench.
SPLIT_TOUCHING_PAIRS = False


# ----------------------------------------------------------------- core ----
def load_grayscale(path_or_bgr):
    """Accept a path, file bytes, or an ndarray; return pipeline-scale gray.

    Robust to frontend inputs: any OpenCV-readable format from disk, raw
    bytes of png/jpg/webp from an upload, or an ndarray that is gray, BGR,
    BGRA or 16-bit.
    """
    if isinstance(path_or_bgr, (str, Path)):
        bgr = cv2.imread(str(path_or_bgr), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError(f"cannot read image: {path_or_bgr}")
    elif isinstance(path_or_bgr, (bytes, bytearray)):
        arr = cv2.imdecode(np.frombuffer(path_or_bgr, np.uint8),
                           cv2.IMREAD_COLOR)
        if arr is None:
            raise ValueError("cannot decode image bytes")
        bgr = arr
    else:
        bgr = path_or_bgr
        if bgr.ndim == 2:
            bgr = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
        elif bgr.ndim == 3 and bgr.shape[2] == 4:
            bgr = cv2.cvtColor(bgr, cv2.COLOR_BGRA2BGR)
        if bgr.dtype == np.uint16:
            # scientific-camera format: scale the full 16-bit range, never
            # clip (clipping maps everything >= 255 to white -> empty mask)
            bgr = (bgr / 257.0).round().astype(np.uint8)
        elif bgr.dtype != np.uint8:
            bgr = np.clip(bgr, 0, 255).astype(np.uint8)
    src_h, src_w = bgr.shape[:2]
    if src_h <= 0 or src_w <= 0:
        raise ValueError("empty image")
    height = max(1, int(legacy.pic_width * src_h / src_w))
    # default (LINEAR) resize — same as analyze_with_recovery / original batch
    color = cv2.resize(bgr, (legacy.pic_width, height))
    return color, cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)


def load_with_source(path_or_bgr):
    """load_grayscale, but also returns the original (width, height)."""
    if isinstance(path_or_bgr, (str, Path)):
        probe = cv2.imread(str(path_or_bgr), cv2.IMREAD_UNCHANGED)
        src_w, src_h = (probe.shape[1], probe.shape[0]) if probe is not None \
            else (0, 0)
    elif isinstance(path_or_bgr, (bytes, bytearray)):
        probe = cv2.imdecode(np.frombuffer(path_or_bgr, np.uint8),
                             cv2.IMREAD_UNCHANGED)
        src_w, src_h = (probe.shape[1], probe.shape[0]) if probe is not None \
            else (0, 0)
    else:
        src_h, src_w = path_or_bgr.shape[:2]
    color, gray = load_grayscale(path_or_bgr)
    return color, gray, (int(src_w), int(src_h))


def blob_label_map(blob):
    """Label the human-view blob map once; reuse for gates and accuracy."""
    n, lab = cv2.connectedComponents(blob)
    return lab.astype(np.int32), n - 1


def find_annotation_overlays(gray):
    """Find figure-annotation overlays baked into the micrograph.

    Returns a list of dicts {x, y, w, h, kind} for dark or white solid
    rectangles (scale bars, panel-label boxes, statistics panels). A connected
    component qualifies only if it is large, fills its bounding box like a
    rectangle (fill >= ANNOT_MIN_FILL after hole-filling — a scale bar with
    white "50 µm" lettering is still a solid bar; a circle scores 0.785), is
    near-constant in intensity over its own material, and is not fully
    central in the frame.
    """
    h, w = gray.shape
    min_area = max(ANNOT_MIN_AREA_FRAC * h * w, 400.0)
    lo, hi = ANNOT_CENTER_BAND
    boxes = []
    med = cv2.medianBlur(gray, 5)
    for kind, m in (("dark", med < 90), ("white", med > 235)):
        m8 = m.astype(np.uint8)
        if float(m8.mean()) > 0.30:
            # high-key / low-key image: the fixed cuts are unreliable there
            continue
        # fill holes INSIDE components so lettering/ticks cut into a bar do
        # not defeat the rectangle test (findContours + flood fill)
        cnts, _ = cv2.findContours(m8, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(m8)
        cv2.drawContours(filled, cnts, -1, 1, -1)
        boxes.extend(_solid_rect_components(filled, gray, kind, min_area,
                                            lo, hi))
        # second pass: a scale bar often TOUCHES a real particle and merges
        # into one blobby component (fill << 0.85), invisible to pass 1.
        # Opening with a bar-shaped kernel dissolves round/irregular graphite
        # but keeps a solid bar's core whole. The bar core is then identified
        # by SHAPE alone — fill ~1.00 and elongated: intensity uniformity is
        # useless here because the "50 µm" lettering's anti-aliased edges
        # inflate the std of the very component that letters were filled
        # into. Real graphite opened cores max out near fill 0.9 (roundish
        # shapes) and are rarely elongated; when in doubt, do not blank.
        for kernel in (np.ones(ANNOT_BAR_KERNEL, np.uint8),
                       np.ones(ANNOT_BAR_KERNEL[::-1], np.uint8)):
            opened = cv2.morphologyEx(filled, cv2.MORPH_OPEN, kernel)
            n_o, lab_o, stats_o, _ = cv2.connectedComponentsWithStats(
                opened, 8)
            for i in range(1, n_o):
                x, y, bw, bh, area = (int(v) for v in stats_o[i])
                if area < min_area:
                    continue
                if max(bw, bh) < ANNOT_BAR_MIN_MAX_DIM:
                    continue    # too short for furniture (protects stringers)
                fill = area / float(bw * bh)
                if fill < ANNOT_BAR_MIN_FILL:
                    continue
                if max(bw, bh) / max(1, min(bw, bh)) < ANNOT_BAR_MIN_ASPECT:
                    continue
                cx, cy = (x + bw / 2.0) / w, (y + bh / 2.0) / h
                if lo <= cx <= hi and lo <= cy <= hi:
                    continue
                b = {"x": x, "y": y, "w": bw, "h": bh, "kind": kind}
                if not any(_contains(a, b) for a in boxes):
                    boxes.append(b)
        # fourth pass: THIN baked-in scale bars at a frame corner. The
        # classic "100 um" JPEG bar is ~126x4px at 1920 — far below the
        # 11x41 kernel above (which erases it to nothing) and far below the
        # 200px core minimum. Open with thin bar kernels instead; grow the
        # core back to the full bar. Corner + near-perfect rectangle +
        # elongated (on BOTH the core and the regrown bar) + solid black
        # cannot simultaneously hold for real graphite in a corner.
        for (kk_h, kk_v) in ((3, 21), (21, 3)):
            opened = cv2.morphologyEx(filled, cv2.MORPH_OPEN,
                                      np.ones((kk_h, kk_v), np.uint8))
            n_o, lab_o, stats_o, _ = cv2.connectedComponentsWithStats(
                opened, 8)
            for i in range(1, n_o):
                x, y, bw, bh, area = (int(v) for v in stats_o[i])
                if area < 100:
                    continue                    # dust
                fill = area / float(bw * bh)
                if fill < ANNOT_BAR_MIN_FILL:
                    continue
                if max(bw, bh) / max(1, min(bw, bh)) < ANNOT_BAR_MIN_ASPECT:
                    continue
                cx, cy = (x + bw / 2.0) / w, (y + bh / 2.0) / h
                corner = (cx < 0.25 or cx > 0.75) and (cy < 0.2 or cy > 0.8)
                if not corner:
                    continue                    # only corner bars
                med_in = float(np.median(gray[y:y + bh, x:x + bw]))
                if kind == "dark" and med_in >= 110:
                    continue                    # not solid black
                # regrow to the full bar in local ROI before blanking (avoids 120 full-frame dilations)
                pad_r = 30
                ry0, ry1 = max(0, y - pad_r), min(h, y + bh + pad_r)
                rx0, rx1 = max(0, x - pad_r), min(w, x + bw + pad_r)
                core_roi = (lab_o[ry0:ry1, rx0:rx1] == i).astype(np.uint8)
                filled_roi = filled[ry0:ry1, rx0:rx1]
                grow = np.ones((3, 3), np.uint8)
                for _ in range(120):
                    d = cv2.dilate(core_roi, grow) & filled_roi
                    if not d.any():
                        break
                    core_roi |= d
                cnts_g, _ = cv2.findContours(core_roi, cv2.RETR_EXTERNAL,
                                             cv2.CHAIN_APPROX_SIMPLE)
                if not cnts_g:
                    continue
                lgx, lgy, gw, gh = cv2.boundingRect(cnts_g[0])
                gx, gy = rx0 + lgx, ry0 + lgy
                if min(gw, gh) > 12:
                    continue    # too thick for a bar: real graphite cluster
                if gw < 0.02 * w and gh < 0.02 * w:
                    continue                    # too short for any scale bar
                if max(gw, gh) / max(1, min(gw, gh)) < ANNOT_BAR_MIN_ASPECT:
                    continue    # regrown shape not elongated: real graphite
                b = {"x": gx, "y": gy, "w": gw, "h": gh, "kind": kind}
                if not any(_contains(a, b) for a in boxes):
                    boxes.append(b)
                    # the bar usually sits inside a WHITE label box with
                    # lettering ("100 um") that fails the std test — blank
                    # the whole enclosing white box so its text specks never
                    # become phantom particles
                    wy0, wy1 = max(0, gy - 8), min(h, gy + gh + 8)
                    wx0, wx1 = max(0, gx - 8), min(w, gx + gw + 8)
                    zone = filled[wy0:wy1, wx0:wx1]
                    if kind == "dark" and zone.size:
                        wm = (cv2.medianBlur(gray, 5)[wy0:wy1, wx0:wx1] > 235)
                        if wm.any():
                            wn, wl, ws, _ = cv2.connectedComponentsWithStats(
                                wm.astype(np.uint8), 8)
                            bcx, bcy = gx + gw / 2.0, gy + gh / 2.0
                            for j in range(1, wn):
                                jx, jy, jw, jh, ja = (int(v) for v in ws[j])
                                if (jx <= bcx - wx0 < jx + jw
                                        and jy <= bcy - wy0 < jy + jh
                                        and ja >= 400):
                                    b2 = {"x": wx0 + jx, "y": wy0 + jy,
                                          "w": jw, "h": jh, "kind": "white"}
                                    if not any(_contains(a, b2)
                                               for a in boxes):
                                        boxes.append(b2)
                                    break
        if kind == "dark":
            # third pass (dark only): a stats PANEL that touches a particle
            # merges into one component (fill ~0.8 -> invisible to pass 1).
            # Square-opening keeps the panel's solid core (a near-perfect
            # rectangle) while dissolving the round particle; the core then
            # passes the panel-shape test on its own.
            opened = cv2.morphologyEx(
                filled, cv2.MORPH_OPEN,
                np.ones((ANNOT_PANEL_KERNEL, ANNOT_PANEL_KERNEL), np.uint8))
            n_o, lab_o, stats_o, _ = cv2.connectedComponentsWithStats(
                opened, 8)
            for i in range(1, n_o):
                x, y, bw, bh, area = (int(v) for v in stats_o[i])
                if bw < ANNOT_PANEL_MIN_CORE or bh < ANNOT_PANEL_MIN_CORE:
                    continue
                if max(bw, bh) / max(1, min(bw, bh)) > ANNOT_PANEL_MAX_ASPECT:
                    continue    # elongated: a stringer, not a panel
                # Maximal-rectangle trim: shave the lowest-density border
                # row/col until the remaining box is nearly solid. A panel
                # core (possibly with attached-particle bumps) collapses to
                # its solid rectangle and DOMINATES the component's area; a
                # round particle's core collapses to its inscribed square,
                # which holds far too little of the component (a disk keeps
                # only ~64%) to pass the dominance floor. Intensity tests
                # cannot make this distinction; geometry can.
                # Local cropped sub-array for component i (avoids 600 full-frame scans)
                comp_sub = (lab_o[y:y + bh, x:x + bw] == i)
                rx_rel, ry_rel, rw, rh = 0, 0, bw, bh
                for _ in range(600):
                    if rw < ANNOT_PANEL_MIN_CORE or rh < ANNOT_PANEL_MIN_CORE:
                        break           # shrank below the panel floor
                    sub_box = comp_sub[ry_rel:ry_rel + rh, rx_rel:rx_rel + rw]
                    box_px = float(sub_box.sum())
                    if box_px / float(rw * rh) >= ANNOT_BAR_MIN_FILL:
                        break
                    top = float(sub_box[0, :].mean())
                    bot = float(sub_box[-1, :].mean())
                    lef = float(sub_box[:, 0].mean())
                    rig = float(sub_box[:, -1].mean())
                    m = min(top, bot, lef, rig)
                    if m == top:
                        ry_rel += 1
                        rh -= 1
                    elif m == bot:
                        rh -= 1
                    elif m == lef:
                        rx_rel += 1
                        rw -= 1
                    else:
                        rw -= 1
                if rw < ANNOT_PANEL_MIN_CORE or rh < ANNOT_PANEL_MIN_CORE:
                    continue
                rx = x + rx_rel
                ry = y + ry_rel
                box_px = float(comp_sub[ry_rel:ry_rel + rh, rx_rel:rx_rel + rw].sum())
                if box_px / float(rw * rh) < ANNOT_BAR_MIN_FILL:
                    continue            # never converged to a solid rect
                if box_px / max(1.0, float(area)) < ANNOT_PANEL_DOMINANCE:
                    continue            # rectangle is a minor part: not a panel
                # Publishers never clip a stats panel with the frame, but a
                # third of real graphite particles touch an edge (measured on
                # the 1000-image dataset): any core reaching the frame border
                # is a large edge particle — protected.
                if (rx <= 1 or ry <= 1 or rx + rw >= w - 1
                        or ry + rh >= h - 1):
                    continue
                cx, cy = (rx + rw / 2.0) / w, (ry + rh / 2.0) / h
                if lo <= cx <= hi and lo <= cy <= hi:
                    continue
                b = {"x": rx, "y": ry, "w": rw, "h": rh, "kind": kind}
                if not any(_contains(a, b) for a in boxes):
                    boxes.append(b)
    if len(boxes) > ANNOT_MAX_BOXES:
        return []                   # implausible for real figure furniture
    return boxes


def _contains(a, b):
    """True if box a fully contains box b (dedupe across the two passes)."""
    return (a["x"] <= b["x"] and a["y"] <= b["y"]
            and a["x"] + a["w"] >= b["x"] + b["w"]
            and a["y"] + a["h"] >= b["y"] + b["h"])


def _solid_rect_components(mask, gray, kind, min_area, lo, hi):
    """Rectangle-test the components of a binary mask (see
    find_annotation_overlays for the acceptance rules)."""
    h, w = gray.shape
    boxes = []
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for i in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        if area < min_area:
            continue
        if bw < ANNOT_MIN_DIM_FRAC * w and bh < ANNOT_MIN_DIM_FRAC * h:
            continue
        if kind == "dark" and (bw < ANNOT_DARK_PANEL_MIN_DIM
                               or bh < ANNOT_DARK_PANEL_MIN_DIM):
            # not panel-shaped: real graphite (particles are uniform too,
            # so uniformity alone cannot separate them from furniture)
            continue
        fill = area / float(bw * bh)
        if fill < ANNOT_MIN_FILL:
            continue
        cx, cy = (x + bw / 2.0) / w, (y + bh / 2.0) / h
        if lo <= cx <= hi and lo <= cy <= hi:
            continue            # fully central: assume real structure
        comp = (lab[y:y + bh, x:x + bw] == i)
        if kind == "white":
            # A DRAWN white box has a sharp intensity step to its
            # surroundings (framed label box: 250 vs ~8; unframed on matrix:
            # 250 vs ~205 — both far apart). Bright glare at the frame edge
            # FADES into the matrix (step <= ~15) — protected.
            x0, y0 = max(0, x - 8), max(0, y - 8)
            x1, y1 = min(w, x + bw + 8), min(h, y + bh + 8)
            ring = np.ones((y1 - y0, x1 - x0), bool)
            ring[y - y0:y - y0 + bh, x - x0:x - x0 + bw] = False
            surroundings = gray[y0:y1, x0:x1][ring]
            if surroundings.size:
                step = abs(float(np.median(gray[y:y + bh, x:x + bw]))
                           - float(np.median(surroundings)))
                if step < 25:
                    continue    # gradual fade: glare, not a label box
        vals = gray[y:y + bh, x:x + bw][comp]
        # uniformity over the component's own MATERIAL only: holes are
        # the opposite polarity (white lettering in a black bar), so
        # ignore pixels that are not of this component's polarity before
        # measuring std
        if kind == "dark":
            material = vals[vals < 128]
        else:
            material = vals[vals >= 128]
        if material.size == 0:
            continue
        if float(material.std()) > ANNOT_MAX_STD:
            continue            # textured: graphite, not an overlay
        boxes.append({"x": x, "y": y, "w": bw, "h": bh, "kind": kind})
    return boxes


def blank_figure_annotations(gray):































    
    """Blank detected figure-annotation overlays to matrix white.

    Returns (gray, boxes). Whole bounding boxes are blanked (this also removes
    lettering inside a label box) and dilated so anti-aliased edges and
    adjacent tick marks cannot seed small detections.
    """
    boxes = find_annotation_overlays(gray)
    if not boxes:
        return gray, []
    # grow each box before blanking: absorbs the thin bracket/tick lines and
    # axis ticks that sit NEXT to a scale bar but never connect to it (the
    # uniformity/fill tests cannot see them as part of the component)
    blank = np.zeros(gray.shape, np.uint8)
    for b in boxes:
        x0 = max(0, b["x"] - 10)
        y0 = max(0, b["y"] - 10)
        x1 = min(gray.shape[1], b["x"] + b["w"] + 10)
        y1 = min(gray.shape[0], b["y"] + b["h"] + 10)
        blank[y0:y1, x0:x1] = 255
    blank = cv2.dilate(blank, cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (13, 13)))
    # absorb thin furniture fragments touching the blanked region: panel
    # frame strips, bracket remnants and drop shadows split off the main
    # component (or sit a few px outside it) and fail the size/fill tests
    # above. They are mid-gray to black (shadows are lighter than graphite),
    # always ELONGATED or TINY, and always ADJACENT to a blanked box — real
    # particles are roundish, darker, and none of the round ones survive
    # next to blanked furniture intact anyway (the halo clips them).
    med2 = cv2.medianBlur(gray, 5)
    leftover = ((med2 < 140) & (blank == 0)).astype(np.uint8)
    n_l, lab_l, stats_l, _ = cv2.connectedComponentsWithStats(leftover, 8)
    for i in range(1, n_l):
        x, y, bw, bh, area = (int(v) for v in stats_l[i])
        elongated = max(bw, bh) / max(1, min(bw, bh)) >= 2.5
        # elongated debris may be long AND moderately thick (frame shadows,
        # bracket remnants); compact debris must stay small. A roundish real
        # particle grazing the halo (aspect ~1) keeps the compact limits.
        if not elongated and (min(bw, bh) > 35 or area > 900):
            continue            # compact + substantial: leave for the gate
        # does it touch the blanked region (8-neighborhood)?
        x0, y0 = max(0, x - 6), max(0, y - 6)
        x1, y1 = min(gray.shape[1], x + bw + 6), min(gray.shape[0], y + bh + 6)
        if not (blank[y0:y1, x0:x1] > 0).any():
            continue
        blank[y:y + bh, x:x + bw] = 255
    out = gray.copy()
    out[blank > 0] = 255
    return out, boxes


def _split_touching_pair(cnt, min_child_area):
    """Split a contour when it is TWO round lobes joined by a narrow neck.

    Small nodules one pixel apart are bridged by the dark map's morphological
    close and measured as ONE elongated nodule (marumi ~0.3-0.5, class
    "irregular"), although two joined spheroidal nodules are two nodules.
    Erode until the mask falls apart; accept ONLY when it yields exactly two
    lobes, each >= min_child_area and each round on its own (marumi >= 0.6)
    once grown back inside the parent. Anything else returns None and the
    contour stays exactly as it is (genuine irregulars are never split).
    """
    area = cv2.contourArea(cnt)
    r = max_half_length(cnt)
    if r <= 0 or area / (math.pi * r * r) >= MARUMI_ISO:
        return None                       # already round: nothing to fix
    x, y, w, h = cv2.boundingRect(cnt)
    pad = 2
    m = np.zeros((h + 2 * pad, w + 2 * pad), np.uint8)
    shifted = cnt.astype(np.int32) - np.array([x - pad, y - pad], np.int32)
    cv2.drawContours(m, [shifted], -1, 255, -1)
    lobes = None
    for k in range(1, 13):
        er = cv2.erode(m, np.ones((3, 3), np.uint8), iterations=k)
        n, lab = cv2.connectedComponents(er)
        if n >= 3:                        # background + 2..N round lobes
            lobes = tuple(lab == i for i in range(1, n))
            break
    if lobes is None:
        return None
    # Competitive regrowth (watershed-style): both lobes dilate back into the
    # parent mask simultaneously; where their fronts meet (the neck) neither
    # takes the pixel, so each child recovers exactly its own lobe plus half
    # the neck — growing one at a time would let them reconnect instead.
    fronts = [l.astype(np.uint8) for l in lobes]
    kernel = np.ones((3, 3), np.uint8)
    for _ in range(max(w, h) + 4):
        others = [cv2.dilate(f, kernel) for f in fronts]
        grew = False
        for i, f in enumerate(fronts):
            block = np.zeros_like(m)
            for j, o in enumerate(others):
                if j != i:
                    block |= o
            d = cv2.dilate(f, kernel) & m & ~block
            if d.any():
                grew = True
            fronts[i] = f | d
        if not grew:
            break
    out = []
    ox, oy = x - pad, y - pad             # crop -> image offset
    for ch in fronts:
        c = largest_contour_of(ch.astype(bool))
        if c is None:
            return None
        out.append((c, cv2.contourArea(c)))
    # every child must be a real particle, and the LARGEST child must be
    # round on its own. Requiring roundness of every child rejected the
    # common big+small pairs (the regrown small lobe inherits neck
    # asymmetry and lands just under 0.6). Size-asymmetric pairs with a
    # non-round dominant lobe (solid irregulars, crescents) still fail the
    # largest-lobe test and stay untouched.
    if min(a for _, a in out) < min_child_area:
        return None
    big_c, big_a = max(out, key=lambda t: t[1])
    rr = max_half_length(big_c)
    if rr <= 0 or big_a / (math.pi * rr * rr) < MARUMI_ISO:
        return None                       # dominant lobe not round: keep as-is
    return [c + np.array([ox, oy], dtype=np.int32) for c, _ in out]


def contour_dark_fraction(cnt, blob_labels):
    """Fraction of a contour's own area that is dark in the human-view map.

    Rasterizes the contour inside its bounding box only (fast, no full-frame
    masks).
    """
    x, y, w, h = cv2.boundingRect(cnt)
    own = np.zeros((h, w), np.uint8)
    shifted = cnt.astype(np.int32) - np.array([x, y], np.int32)
    cv2.drawContours(own, [shifted], -1, 1, -1)
    vals = blob_labels[y:y + h, x:x + w][own > 0]
    return float((vals > 0).mean())


def reference_particles(gray, blob=None, min_area=None):
    """Independent reference: median + raw Otsu + connected components.

    One connected component = one particle (joined blob = one nodule).
    min_area: the particle-size floor; defaults to the historical floor for
    backward compatibility, callers running the full pipeline pass the
    adaptive small-particle floor so fine micrographs count their real
    particles.
    """
    if blob is None:
        blob = physical_blob_map(gray)
    blob = cv2.morphologyEx(blob, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(blob)
    if min_area is None:
        min_area = area_floor(AREA_FLOOR_RATIO, blob.shape[0], blob.shape[1])
    keep = np.zeros_like(blob)
    max_particle_area = int(0.08 * blob.shape[0] * blob.shape[1])
    for i in range(1, n):
        area_i = stats[i, cv2.CC_STAT_AREA]
        bw_i = stats[i, cv2.CC_STAT_WIDTH]
        bh_i = stats[i, cv2.CC_STAT_HEIGHT]
        if min_area <= area_i <= max_particle_area and not (bw_i > 0.6 * blob.shape[1] and bh_i > 0.6 * blob.shape[0]):
            keep[lab == i] = 255
    n2, lab2 = cv2.connectedComponents(keep)
    return lab2.astype(np.int32), n2 - 1


# Strongly-colored-photo rejection threshold for the validity gate. Calibrated
# by scanning all 1,000 dataset micrographs (2026-10): max colorfulness 20.6,
# p99 17.9. Natural photographs score 40-120 (salt-flat landscape: 102).
COLORFULNESS_MAX = 45.0


def _colorfulness_metric(bgr):
    """Hasler-Süsstrunk opponent-color colorfulness (0 = pure grayscale)."""
    b, g, r = (bgr[:, :, i].astype(np.float32) for i in range(3))
    rg = r - g
    yb = 0.5 * (r + g) - b
    rg_root = math.sqrt(float(rg.var()) + float(rg.mean()) ** 2)
    yb_root = math.sqrt(float(yb.var()) + float(yb.mean()) ** 2)
    return (math.sqrt(rg_root ** 2 + yb_root ** 2)
            + 0.3 * math.sqrt(float(rg.var()) + float(yb.var())))


def evaluate_microstructure_validity(image, result=None):
    """Decide whether an image is a valid polished ductile-iron micrograph.

    Random photographs, flat fields, or other non-microstructure images are
    rejected before any nodularity metrics are trusted. The gate uses the same
    human-view graphite threshold used by the detector to distinguish actual
    graphite particles from ordinary photo texture, and rejects strongly
    colored photographs (polished micrographs are grayscale).
    """
    try:
        color, gray, _ = load_with_source(image)
    except Exception as exc:
        return {
            "valid": False,
            "status": "invalid_microstructure",
            "reason": f"unable to read image: {exc}",
            "details": {"error": str(exc)},
        }

    gray = np.asarray(gray)
    if gray.size == 0:
        return {
            "valid": False,
            "status": "invalid_microstructure",
            "reason": "empty image",
            "details": {"shape": list(gray.shape)},
        }

    std = float(gray.std())
    dark_frac = float(np.mean(gray < 100))
    light_frac = float(np.mean(gray > 200))
    if gray.ndim != 2:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

    if std < 8.0 or np.ptp(gray) < 10:
        return {
            "valid": False,
            "status": "invalid_microstructure",
            "reason": "image is nearly uniform; not a polished micrograph",
            "details": {"std": round(std, 3), "range": int(np.ptp(gray))},
        }

    # Polished ductile-iron micrographs are grayscale; natural photographs
    # (sky, vegetation, terrain) carry strong chroma no polished specimen
    # exhibits. Across all 1,000 dataset micrographs the Hasler-Süsstrunk
    # colorfulness metric never exceeded 20.6, so 45 rejects only strongly
    # colored photos while tolerating uniform acquisition tints. Computed on
    # a <=512px copy for speed (threshold calibrated at that scale).
    cf_bgr = color
    cf_h, cf_w = cf_bgr.shape[:2]
    cf_sc = 512 / max(cf_h, cf_w)
    if cf_sc < 1.0:
        cf_bgr = cv2.resize(cf_bgr, (int(round(cf_w * cf_sc)),
                                     int(round(cf_h * cf_sc))),
                            interpolation=cv2.INTER_AREA)
    colorfulness = _colorfulness_metric(cf_bgr)
    if colorfulness > COLORFULNESS_MAX:
        return {
            "valid": False,
            "status": "invalid_microstructure",
            "reason": ("image is a strongly colored photograph, not a "
                       "grayscale polished micrograph"),
            "details": {"colorfulness": round(colorfulness, 2),
                        "colorfulness_max": COLORFULNESS_MAX},
        }

    blobmap = physical_blob_map(gray)
    dark_blob_frac = float((blobmap > 0).mean())
    n_blob, _ = cv2.connectedComponents(blobmap)
    n_blob = int(n_blob - 1)

    reasons = []
    if dark_blob_frac < 0.02:
        reasons.append("insufficient graphite signal in the image")
    if dark_blob_frac > 0.55:
        reasons.append("image is overwhelmingly dark and not a polished graphite micrograph")
    if n_blob < 12 and dark_blob_frac < 0.15:
        reasons.append("too few graphite particle components to be a valid microstructure")
    if dark_frac > 0.70 and light_frac > 0.10:
        reasons.append("random photograph texture is not a valid ductile-iron microstructure")

    if reasons:
        return {
            "valid": False,
            "status": "invalid_microstructure",
            "reason": "; ".join(reasons),
            "details": {
                "std": round(std, 3),
                "dark_blob_frac": round(dark_blob_frac, 4),
                "connected_components": int(n_blob),
                "dark_frac": round(dark_frac, 4),
                "light_frac": round(light_frac, 4),
            },
        }

    if result is not None:
        count = int((result or {}).get("count", 0))
        if count <= 0 and dark_blob_frac <= 0.10:
            return {
                "valid": False,
                "status": "invalid_microstructure",
                "reason": "no graphite particles detected in a non-flat image",
                "details": {"count": count, "dark_blob_frac": round(dark_blob_frac, 4)},
            }

    return {
        "valid": True,
        "status": "complete",
        "reason": "microstructure signal is consistent with a valid graphite micrograph",
        "details": {
            "std": round(std, 3),
            "dark_blob_frac": round(dark_blob_frac, 4),
            "connected_components": int(n_blob),
            "colorfulness": round(colorfulness, 2),
        },
    }


def analyze_image(path_or_bgr, with_accuracy=True, stem=""):
    """Full pipeline on one image. Returns a result dict (no file writes)."""
    color, gray, (src_w, src_h) = load_with_source(path_or_bgr)
    # figure furniture (scale bars, panel labels, stats panels) is not
    # microstructure — blank it before any threshold stage sees it
    gray, annotation_boxes = blank_figure_annotations(gray)
    h, w = gray.shape

    # human-view blob map + labels: computed once, shared by the joining
    # stages, the consistency gate and the accuracy reference
    med = cv2.medianBlur(gray, 7)
    blobmap = physical_blob_map(gray, med)
    blob_labels, n_blob = blob_label_map(blobmap)

    matrix_med = float(np.median(med))
    recovery_max_med = min(110.0, max(60.0, matrix_med - 40.0))
    frozen = detect_frozen(gray, w, h)[0]
    contours, sources, border = recover_and_merge(
        gray, frozen,
        min_recover_area=area_floor(AREA_FLOOR_RATIO, h, w),
        max_med_gray=recovery_max_med)
    contours, sources, border, n_joined = consolidate_joined(
        gray, contours, sources, border, blob=blobmap)
    contours, sources, border, n_filled = fill_owned_blobs(
        gray, contours, sources, border, blob=blobmap)

    # --- scale-free particle-size floors -------------------------------
    # historical floor (tuned on large-particle fields) + a small-particle
    # floor for dense, fine micrographs; the union of both defines the
    # "real particle" floor for EVERYTHING that feeds the final count (gate,
    # salvage, split, completed, reference): the historical AREA_FLOOR_RATIO
    # (800px@1920). The locked bench proves the small-particle floor (150px)
    # lets reviewed human FPs through the gate (36 vs <=6 carried) and makes
    # the count sensitive to min_grainsize. The small floor remains only in
    # the recovery stage's candidate area (analyze_with_recovery), whose
    # output still passes every gate below.
    min_nodule_area = area_floor(AREA_FLOOR_RATIO, h, w)

    # Consistency gate against the human-view blob map: drop detections that
    # are smaller than the minimum particle size OR cover almost no dark area
    # (phantom texture on faint mottling / partial interior texture).
    # Consistency gate against the reference-grade (opened) dark map: keep a
    # detection only if it is anchored to graphite substantial enough that the
    # independent reference also sees it as a particle (opened-map component
    # >= the particle floor), i.e. it covers >= 50% of one such particle or
    # >= 50% of its own area lies on such particles. Phantom texture on faint
    # mottling dissolves into sub-floor fragments under the opening -> dropped;
    # boundary jitter that shrank a real contour below the floor -> rescued.
    opened = cv2.morphologyEx(blobmap, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n_open, open_lab, open_stats, _ = cv2.connectedComponentsWithStats(opened)
    kept = []
    salvage = set()
    for i, cnt in enumerate(contours):
        x, y, bw2, bh2 = cv2.boundingRect(cnt)
        sub = open_lab[y:y + bh2, x:x + bw2]
        cmask = np.zeros((bh2, bw2), np.uint8)
        cv2.drawContours(cmask, contours, i, 255, -1, offset=(-x, -y))
        filled = float((cmask > 0).sum())
        if filled <= 0:
            continue
        on_dark = (sub > 0) & (cmask > 0)
        if float(on_dark.sum()) < CONSISTENCY_KEEP_FRAC * filled:
            # A contour that is mostly background: reject it, but salvage any
            # reference-grade particle it swallowed (the stages/frozen detector
            # sometimes emit a large blob spanning a particle + matrix).
            # Floor = the HISTORICAL count floor: salvage feeds the final
            # count, where the locked bench requires the 800px@1920 floor.
            max_comp_area = 0.08 * h * w
            for lab in np.unique(sub[on_dark]):
                comp_area = int(open_stats[lab, cv2.CC_STAT_AREA])
                bw_c = int(open_stats[lab, cv2.CC_STAT_WIDTH])
                bh_c = int(open_stats[lab, cv2.CC_STAT_HEIGHT])
                if comp_area < min_nodule_area or comp_area > max_comp_area or (bw_c > 0.6 * w and bh_c > 0.6 * h):
                    continue
                if float(((sub == lab) & (cmask > 0)).sum()) >= 0.5 * comp_area:
                    salvage.add(int(lab))
            continue
        max_comp_area = 0.08 * h * w
        for lab in np.unique(sub[on_dark]):
            comp_area = int(open_stats[lab, cv2.CC_STAT_AREA])
            bw_c = int(open_stats[lab, cv2.CC_STAT_WIDTH])
            bh_c = int(open_stats[lab, cv2.CC_STAT_HEIGHT])
            if comp_area < min_nodule_area or comp_area > max_comp_area or (bw_c > 0.6 * w and bh_c > 0.6 * h):
                continue
            cov = float(((sub == lab) & (cmask > 0)).sum())
            if cov >= 0.5 * filled or cov >= 0.5 * comp_area:
                kept.append(i)
                break
    if salvage:
        # add salvaged particles not already covered by a kept contour
        kept_mask = np.zeros(gray.shape, np.uint8)
        for i in kept:
            cv2.drawContours(kept_mask, contours, i, 255, -1)
        for lab in salvage:
            comp = (open_lab == lab)
            comp_area = int(open_stats[lab, cv2.CC_STAT_AREA])
            bw_c = int(open_stats[lab, cv2.CC_STAT_WIDTH])
            bh_c = int(open_stats[lab, cv2.CC_STAT_HEIGHT])
            if comp_area > 0.08 * h * w or (bw_c > 0.6 * w and bh_c > 0.6 * h):
                continue
            if float((kept_mask[comp] > 0).sum()) >= 0.5 * comp_area:
                continue
            cnt = largest_contour_of(comp)
            if cnt is None or cv2.contourArea(cnt) > 0.08 * h * w:
                continue
            x, y, bw2, bh2 = cv2.boundingRect(cnt)
            contours = contours + [cnt]
            sources = sources + ["salvaged"]
            border = border + [x <= 1 or y <= 1 or x + bw2 >= w - 1
                               or y + bh2 >= h - 1]
            kept.append(len(contours) - 1)
    contours = [contours[i] for i in kept]
    sources = [sources[i] for i in kept]
    border = [border[i] for i in kept]

    # ---- touching-doublet split -----------------------------------------
    # GATED OFF for the validated count path (see SPLIT_TOUCHING_PAIRS above
    # for the bench-measured why). The code is kept intact and reversible.
    split_c, split_s, split_b = contours, sources, border
    n_split = 0
    if SPLIT_TOUCHING_PAIRS:
        split_c, split_s, split_b = [], [], []
        for idx, cnt in enumerate(contours):
            parts = _split_touching_pair(cnt, min_nodule_area)
            if parts is None:
                split_c.append(cnt)
                split_s.append(sources[idx])
                split_b.append(border[idx])
                continue
            n_split += 1
            for c in parts:
                xx, yy, ww, hh = cv2.boundingRect(c)
                split_c.append(c)
                split_s.append("split")
                split_b.append(xx <= 1 or yy <= 1 or xx + ww >= w - 1
                               or yy + hh >= h - 1)
        contours, sources, border = split_c, split_s, split_b
    # The independent reference segmentation sees every Otsu particle >= the
    # historical count floor; the multi-stage chain can still miss low-contrast
    # ones (nothing rejects them — they simply never got a contour). Any
    # reference-grade particle not covered by the accepted set is added here,
    # gated on solidity so scratches/smears/pores stay out.
    acc_mask = np.zeros(gray.shape, np.uint8)
    for c in contours:
        cv2.drawContours(acc_mask, [c], -1, 255, -1)
    n_added = 0
    max_comp_area = 0.08 * h * w
    for lab in range(1, n_open):
        comp_area = int(open_stats[lab, cv2.CC_STAT_AREA])
        bw_c = int(open_stats[lab, cv2.CC_STAT_WIDTH])
        bh_c = int(open_stats[lab, cv2.CC_STAT_HEIGHT])
        if comp_area < min_nodule_area or comp_area > max_comp_area or (bw_c > 0.6 * w and bh_c > 0.6 * h):
            continue
        comp = open_lab == lab
        if float((acc_mask[comp] > 0).sum()) >= 0.5 * comp_area:
            continue                      # already owned by a nodule
        cnt = largest_contour_of(comp)
        if cnt is None or cv2.contourArea(cnt) > max_comp_area:
            continue
        hull_area = cv2.contourArea(cv2.convexHull(cnt))
        if hull_area <= 0 or cv2.contourArea(cnt) / hull_area < 0.85:
            continue                      # smear/scratch, not a particle
        x, y, bw2, bh2 = cv2.boundingRect(cnt)
        contours = contours + [cnt]
        sources = sources + ["completed"]
        border = border + [x <= 1 or y <= 1 or x + bw2 >= w - 1
                           or y + bh2 >= h - 1]
        cv2.drawContours(acc_mask, [cnt], -1, 255, -1)
        n_added += 1

    # Safety guard: reject any contour that is not a nodule (e.g. background aperture)
    filtered_c, filtered_s, filtered_b = [], [], []
    for idx, cnt in enumerate(contours):
        c_area = cv2.contourArea(cnt)
        bx, by, bw_i, bh_i = cv2.boundingRect(cnt)
        if c_area > max_comp_area or (bw_i > 0.6 * w and bh_i > 0.6 * h):
            continue
        filtered_c.append(cnt)
        filtered_s.append(sources[idx])
        filtered_b.append(border[idx])
    contours, sources, border = filtered_c, filtered_s, filtered_b

    mask = np.zeros(gray.shape, np.uint8)
    n_contours = len(contours)
    if n_contours:
        for i in range(n_contours):
            cv2.drawContours(mask, contours, i, 255, -1)    # ---- per-particle metrics + aggregate nodularity (formula reference) ----
    # Per particle:  marumi ("roundness") = area / (pi * r_hull^2), where
    #   r_hull = half the largest point-pair distance of the CONVEX HULL
    #   (legacy get_graphite_length). A perfect circle scores 1.0.
    #   This matches the ISO 945-4:2019 definition of roundness (clause 3.2):
    #   rho = 4A / (pi * l_m^2), l_m = maximum Feret diameter.
    # ISO nodularity (ISO 945-4:2019 Formula-2 analogue, clause 6.4):
    #   ISO  = sum(area[marumi >= 0.6]) / sum(area[all]) * 100
    #   -> AREA-weighted over ALL detected particles, INCLUDING
    #      border-touching ones. Threshold 0.6 is normative: ISO 945-4
    #      clause 3.3 defines spheroidal graphite as roundness >= 0.6.
    # ISO in-frame (strict ISO 945-4 Formula 2):
    #   sum(area[round, non-border]) / sum(area[non-border]) * 100
    #   -> the standard REQUIRES excluding particles that intersect the
    #      border of the area of view (clause 6.4, A_all definition), so
    #      iso_inframe_pct is the standards-compliant value; the headline
    #      iso_pct additionally retains border particles for maximum
    #      particle-count robustness (border particles risk a biased class
    #      because clipping lowers the measured roundness).
    # JIS nodularity (JIS G5502:2022 JIS-method, count-based):
    #   JIS  = (0.3*N_2 + 0.7*N_3 + 0.9*N_4 + 1.0*N_5) / N_all * 100
    #   jis_bucket(marumi): <=0.2 -> 1 (weight 0), <=0.4 -> 2, <=0.7 -> 3,
    #   <=0.8 -> 4, >0.8 -> 5. The 0.3/0.7/0.9/1.0 weights and the
    #   0.2/0.4/0.7/0.8 class boundaries (upper-inclusive) match the JIS
    #   G5502:2022 formula quoted in peer-reviewed literature (J. Japan
    #   Inst. Met. Mater. 89(12) 2025, doi:10.2320/jinstmet.J202529).
    #   COUNT-weighted over ALL particles (border included); no area term.
    # Verified against: the official ISO 945-4:2019 standard preview
    #   (clauses 3.2, 3.3, 6.3, 6.4) and the peer-reviewed JIS G5502:2022
    #   description above. Full standard texts remain paywalled; treat
    #   this as "ISO 945-based" methodology, not a certification.
    rows = []
    area_total = area_round = area_round_in = area_total_in = 0.0
    jis_counts = [0, 0, 0, 0, 0]
    for idx, cnt in enumerate(contours, 1):
        area = cv2.contourArea(cnt)
        r = max_half_length(cnt)
        feret_px = 2.0 * r                     # diameter of the same circle
        marumi = area / ((r ** 2) * math.pi) if r > 0 else 0.0
        bucket = jis_bucket(marumi)

        jis_counts[bucket - 1] += 1
        is_round = marumi >= MARUMI_ISO
        area_total += area
        if not border[idx - 1]:
            area_total_in += area
            if is_round:
                area_round_in += area
        if is_round:
            area_round += area
        x, y, bw, bh = cv2.boundingRect(cnt)
        rows.append({
            "nodule_id": idx,
            "source": sources[idx - 1],
            "touches_border": bool(border[idx - 1]),
            "center_x": round((x + bw / 2) / w, 6),
            "center_y": round((y + bh / 2) / h, 6),
            "area_px": round(area, 1),
            "equiv_diameter_px": round(2 * math.sqrt(area / math.pi), 2),
            "feret_diameter_px": round(feret_px, 2),
            "roundness": round(marumi, 4),
            "iso_class": "V/VI" if is_round else "irregular",
            "jis_bucket": bucket,
        })

    iso_pct = area_round / area_total * 100 if area_total else 0.0
    iso_inframe = (area_round_in / area_total_in * 100
                   if area_total_in else 0.0)
    n_total = len(rows)
    jis_pct = ((0.3 * jis_counts[1] + 0.7 * jis_counts[2]
                + 0.9 * jis_counts[3] + jis_counts[4]) / n_total * 100
               if n_total else 0.0)

    warnings = []
    if 0 < src_w < 600:
        warnings.append(
            f"input width {src_w}px is below ~600px: smallest particles may "
            "be below resolution and counts can include sub-resolution specks")
    dark_frac = float((blobmap > 0).mean())
    if n_contours == 0 and dark_frac < 0.01:
        warnings.append("no graphite particles detected in this image")
    if dark_frac > 0.6:
        warnings.append(
            "image is mostly dark: this does not look like a polished "
            "ductile-iron micrograph; nodularity values may not be meaningful")
    if annotation_boxes:
        kinds = sorted({b["kind"] for b in annotation_boxes})
        warnings.append(
            f"figure annotation overlay ({'/'.join(kinds)}) blanked before "
            "analysis: scale bar / label / stats panel excluded from metrics")

    result = {
        "color": color, "gray": gray, "mask": mask,
        "contours": contours, "sources": sources, "border": border,
        "rows": rows,
        "count": n_contours,
        "annotation_overlays": [
            {"x": b["x"], "y": b["y"], "w": b["w"], "h": b["h"],
             "kind": b["kind"]} for b in annotation_boxes],
        "source_width": int(src_w),
        "source_height": int(src_h),
        "warnings": warnings,
        "frozen_count": len(frozen),
        "n_recovered": sources.count("recovered") + sources.count("merged"),
        "n_unified": sources.count("joined") + sources.count("blobfill"),
        "n_completed": n_added,
        "n_split": n_split,
        "iso_pct": round(iso_pct, 2),
        "iso_inframe_pct": round(iso_inframe, 2),
        "jis_pct": round(jis_pct, 2),
        "microstructure_validity": evaluate_microstructure_validity(path_or_bgr, {"count": n_contours}),
    }

    if with_accuracy:
        ref_lab, n_ref = reference_particles(gray, blob=blobmap,
                                             min_area=min_nodule_area)
        result.update(accuracy_vs_reference(gray, contours, ref_lab,
                                            n_ref))

    # annotated overlay with stats banner (used by analyze_file / reports)
    annotated = color.copy()
    for idx, cnt in enumerate(contours, 1):
        src = sources[idx - 1]
        is_round = rows[idx - 1]["iso_class"] == "V/VI"
        if src == "frozen":
            outline, th = ((0, 0, 255) if is_round else (255, 200, 0)), 2
        elif src == "merged":
            outline, th = (0, 140, 255), 3
        elif src in ("joined", "blobfill"):
            outline, th = (255, 0, 255), 3
        else:
            th = 4 if border[idx - 1] else 3
            outline = (0, 140, 255)
        cv2.drawContours(annotated, contours, idx - 1, outline, th)
    line1 = ("{}  |  Nodules: {}  (frozen detector said {} — {} dividing "
             "unified, {} recovered, {} completed)  |  Nodularity: {:.1f}%  "
             "(ISO view)  |  JIS view: {:.1f}%").format(
        stem or "{stem}", n_contours, len(frozen), result["n_unified"],
        result["n_recovered"], result.get("n_completed", 0), iso_pct, jis_pct)
    line2 = ("Accuracy vs independent reference: count {:.1f}% | P {:.1f}% "
             "| R {:.1f}% | F1 {:.1f}%").format(
        result.get("count_accuracy_pct", 0.0),
        result.get("precision_pct", 0.0),
        result.get("recall_pct", 0.0),
        result.get("f1_pct", 0.0))
    result["annotated"] = draw_banner(annotated, line1, line2)
    return result


def apply_size_filter_and_iso(result, microns_per_pixel=None):
    """Calibration-aware ISO 945-4 10 um size rule (clause 6.3).

    Reuses the SAME maximum Feret diameter that feeds the roundness
    formula (feret_diameter_px = 2 * r_hull). When a valid physical
    calibration is provided:

      * each particle gets feret_diameter_um and size_filter_status
        ("included" / "excluded_below_10um"); a particle is excluded
        when feret_um < 10.0 (exactly 10.0 stays INCLUDED);
      * iso_size_qualified_pct is the ISO area ratio over size-qualified,
        non-border particles (clause 6.4 border rule + clause 6.3 size
        rule combined: qualifying spheroidal area / qualifying total
        graphite area);
      * size_filter metadata records applied/excluded/included counts.

    When no valid calibration is provided, feret_diameter_um stays None,
    every particle is "not_evaluable", iso_size_qualified_pct is None and
    the metadata states the reason — nothing is fabricated and the
    headline iso_pct / iso_inframe_pct values are left untouched.

    Returns the ISO 945-4 size-qualified nodularity in percent (or None
    when the size rule is not evaluable).
    """
    from nodiq.services.calibration import (validate_um_per_px, feret_size_status,
                                      size_filter_metadata, ISO_MIN_FERET_UM)
    mpp = validate_um_per_px(microns_per_pixel)
    rows = result["rows"]
    if mpp is None:
        for row in rows:
            row["feret_diameter_um"] = None
            row["size_filter_status"] = "not_evaluable"
        result["iso_size_qualified_pct"] = None
        result["size_filter"] = size_filter_metadata(None, 0, 0)
        return None

    area_q_all = area_q_round = 0.0
    excluded = included = 0
    for row in rows:
        feret_um = row["feret_diameter_px"] * mpp
        row["feret_diameter_um"] = round(feret_um, 3)
        status = feret_size_status(row["feret_diameter_px"], mpp)
        row["size_filter_status"] = status
        if status == "excluded_below_10um":
            excluded += 1
            continue
        included += 1
        # ISO 945-4 clause 6.4: A_all excludes border-intersecting particles
        if not row["touches_border"]:
            area_q_all += row["area_px"]
            if row["iso_class"] == "V/VI":
                area_q_round += row["area_px"]

    result["iso_size_qualified_pct"] = (
        round(area_q_round / area_q_all * 100, 2) if area_q_all else None)
    result["size_filter"] = size_filter_metadata(mpp, excluded, included)
    result["size_filter"]["threshold_um"] = ISO_MIN_FERET_UM
    return result["iso_size_qualified_pct"]


def accuracy_vs_reference(gray, contours, ref_lab=None, n_ref=None):
    """Particle-level accuracy of the model against the independent ref."""
    if ref_lab is None:
        ref_lab, n_ref = reference_particles(gray)
    n_mod = len(contours)

    ref_hits = {}
    matched_model = 0
    for i in range(1, n_mod + 1):
        own = np.zeros(gray.shape, np.uint8)
        cv2.drawContours(own, contours, i - 1, 1, -1)
        rl = dominant_label(ref_lab, own.astype(bool), n_ref + 1)
        if rl > 0:
            matched_model += 1
            ref_hits.setdefault(rl, []).append(i)

    ref_matched = len(ref_hits)
    dup_extra = sum(len(v) - 1 for v in ref_hits.values())  # double counts

    precision = matched_model / n_mod * 100 if n_mod else 0.0
    recall = ref_matched / n_ref * 100 if n_ref else 100.0
    f1 = 2 * precision * recall / (precision + recall) \
        if precision + recall else 0.0
    count_acc = max(0.0, (1 - abs(n_mod - n_ref) / max(n_ref, 1)) * 100)

    return {
        "reference_count": n_ref,
        "count_accuracy_pct": round(count_acc, 2),
        "precision_pct": round(precision, 2),
        "recall_pct": round(recall, 2),
        "f1_pct": round(f1, 2),
        "double_counts": dup_extra,
    }


# ------------------------------------------------------------ file mode ----------------------------------------------------------------------
def analyze_file(path, out_dir=None, prefix=""):
    """Analyze an image file; optionally write mask/annotated/CSV outputs.

    Returns the analyze_image() dict (with "stem" added).
    """
    path = Path(path)
    stem = prefix + path.stem
    res = analyze_image(path, stem=stem)
    res["stem"] = stem

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = res["stem"]
        cv2.imwrite(str(out_dir / f"{stem}_mask.png"), res["mask"])
        cv2.imwrite(str(out_dir / f"{stem}_annotated.png"), res["annotated"])
        with open(out_dir / f"{stem}_nodule_stats.csv", "w", newline="",
                  encoding="utf-8") as f:
            if res["rows"]:
                writer = csv.DictWriter(f, fieldnames=list(res["rows"][0]))
                writer.writeheader()
                writer.writerows(res["rows"])
            else:
                f.write("nodule_id,source,touches_border,center_x,center_y,"
                        "area_px,equiv_diameter_px,roundness,iso_class,"
                        "jis_bucket\n")
    return res


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else str(
        Path(r"C:/Users/Atharv/Downloads/ductile_cast_iron_1000_unique_micrographs")
        / "micrograph_0993.png")
    outd = (DATA_RAW_DIR / "nodularity_1000_fixed") if len(sys.argv) <= 2 else Path(sys.argv[2])
    r = analyze_file(target, outd)
    print(f"{r['stem']}: nodules={r['count']} (frozen {r['frozen_count']}, "
          f"unified {r['n_unified']}, recovered {r['n_recovered']}) "
          f"ISO={r['iso_pct']}% JIS={r['jis_pct']}% | ref={r['reference_count']} "
          f"count_acc={r['count_accuracy_pct']}% P={r['precision_pct']}% "
          f"R={r['recall_pct']}% F1={r['f1_pct']}%")


# ----------------------------------------------------- frontend API -------
def analyze_for_frontend(image, with_masks=True, with_accuracy=True,
                         res=None):
    """JSON-ready analysis for a web frontend.

    Accepts a file path, raw image bytes (png/jpg/webp upload), or an
    ndarray. Optionally accepts a precomputed analyze_image() result dict
    (integration hook so callers can also derive quality from the same
    engine pass without re-running the pipeline; output is identical).
    Returns a dict of JSON-safe scalars plus, optionally, the two
    visual outputs as base64 PNGs (data-URI ready):
      - "mask_b64":      binary graphite mask (white = nodule area)
      - "annotated_b64": original image with per-nodule contour overlay
                         and the stats banner (as shown in reports)
    Mask/annotated raw ndarrays stay available as "mask"/"annotated" when
    with_masks=True (drop them from the JSON payload server-side).
    """
    if res is None:
        res = analyze_image(image, with_accuracy=with_accuracy)
    out = {
        "nodule_count": int(res["count"]),
        # PRIMARY term: "nodularity" (the single number a metallurgist asks
        # for).  It is the ISO 945-4 area-weighted value; ISO/JIS stay
        # available as separate standard views for reporting.
        "nodularity_pct": res["iso_pct"],
        "nodularity_basis": ("ISO 945-4 area-weighted (spheroidal area / "
                             "total graphite area)"),
        "iso_nodularity_pct": res["iso_pct"],
        "iso_nodularity_inframe_pct": res["iso_inframe_pct"],
        "jis_nodularity_pct": res["jis_pct"],
        "class_counts": {
            "round_V_VI": sum(1 for r in res["rows"]
                              if r["iso_class"] == "V/VI"),
            "irregular": sum(1 for r in res["rows"]
                             if r["iso_class"] != "V/VI"),
        },
        "border_touching": sum(1 for b in res["border"] if b),
        "nodules": res["rows"],
        "source_width": int(res.get("source_width", 0)),
        "source_height": int(res.get("source_height", 0)),
        "warnings": list(res.get("warnings", [])),
    }
    if with_accuracy:
        out["self_check"] = {
            "reference_count": int(res["reference_count"]),
            "count_accuracy_pct": res["count_accuracy_pct"],
            "precision_pct": res["precision_pct"],
            "recall_pct": res["recall_pct"],
            "f1_pct": res["f1_pct"],
            "double_counts": int(res["double_counts"]),
        }
    if with_masks:
        ok, buf = cv2.imencode(".png", res["mask"])
        if not ok:
            raise RuntimeError("failed to encode mask")
        out["mask_b64"] = base64.b64encode(buf.tobytes()).decode("ascii")
        ok, buf = cv2.imencode(".png", res["annotated"])
        if not ok:
            raise RuntimeError("failed to encode annotated overlay")
        out["annotated_b64"] = base64.b64encode(buf.tobytes()).decode("ascii")
        out["mask"] = res["mask"]          # ndarray: keep server-side only
        out["annotated"] = res["annotated"]  # ndarray: keep server-side only
    return out


def analyze_for_frontend_json(image, with_masks=True, with_accuracy=True,
                              data_uri=True, res=None):
    """analyze_for_frontend with everything JSON-serializable.

    Drops the raw ndarrays and returns (payload, error). Base64 masks are
    prefixed as data URIs so a browser can use them directly in <img src>.
    """
    try:
        res = analyze_for_frontend(image, with_masks=with_masks,
                                   with_accuracy=with_accuracy, res=res)
    except Exception as exc:  # degrade gracefully for the frontend
        return None, str(exc)
    res.pop("mask", None)
    res.pop("annotated", None)
    if data_uri:
        for key in ("mask_b64", "annotated_b64"):
            if key in res:
                res[key] = "data:image/png;base64," + res[key]
    return res, None
