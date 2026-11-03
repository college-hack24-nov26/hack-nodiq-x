#!/usr/bin/env python3
"""
analyze_with_recovery.py — frozen detector + recovery of missed nodules.

The frozen hybrid detector (nodularity_adaptive, imported never edited) rejects:
  * any candidate touching the image border  (image_artifact)
  * large mottled/Gaussian-surface nodules whose interior thresholding only
    yields fragments (fragments fail shape gates, parent blob is lost)

Recovery stage (this script):
  1. dark-region map (background subtraction + Otsu, same idea as robust
     detection); missed = dark minus frozen mask
  2. filter slivers/faint texture/scratches/smears
  3. CRITICAL — same-nodule resolution:
       * a missed region that ENCLOSES a frozen partial detection (ring around
         an interior fragment) is UNIONED into that detection, not counted twice
       * a missed region hugging a frozen partial detection (bulk left next to
         an edge sliver) is likewise merged
       * only genuinely separate dark regions become NEW recovered nodules
  4. recompute count / ISO / JIS on the final contour set

Colors: red = nodular, cyan = irregular (frozen, untouched);
        orange = merged remainder or newly recovered nodule.
"""
import csv
import math
import sys
from pathlib import Path

import cv2
import numpy as np

from nodiq.core.config import REPO_ROOT, THIRD_PARTY_NODULARITY

PROJECT_ROOT = REPO_ROOT
_nodularity_main = THIRD_PARTY_NODULARITY
if _nodularity_main.is_dir() and str(_nodularity_main) not in sys.path:
    sys.path.insert(0, str(_nodularity_main))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import nodularity as legacy          # type: ignore # noqa: E402  (frozen)
except (ImportError, ModuleNotFoundError):
    import importlib.util
    _nod_file = _nodularity_main / "nodularity.py"
    if _nod_file.is_file():
        spec = importlib.util.spec_from_file_location("nodularity", str(_nod_file))
        legacy = importlib.util.module_from_spec(spec)
        sys.modules["nodularity"] = legacy
        spec.loader.exec_module(legacy)
    else:
        class LegacyDefaults:
            pic_width = 1920
            marumi_ratio = 0.6
            @staticmethod
            def get_graphite_length(hull):
                import math
                max_distance = 0.0
                x = y = 0.0
                for i in range(len(hull)):
                    for j in range(i + 1, len(hull)):
                        dis_x = float(hull[j][0][0] - hull[i][0][0])
                        dis_y = float(hull[j][0][1] - hull[i][0][1])
                        dis = math.sqrt(dis_x**2 + dis_y**2)
                        if dis > max_distance:
                            max_distance = dis
                            x = dis_x * 0.5 + float(hull[i][0][0])
                            y = dis_y * 0.5 + float(hull[i][0][1])
                return x, y, max_distance * 0.5
        legacy = LegacyDefaults()

try:
    import nodularity_adaptive as na     # type: ignore # noqa: E402  (frozen)
except (ImportError, ModuleNotFoundError):
    import importlib.util
    _na_file = _nodularity_main / "nodularity_adaptive.py"
    if _na_file.is_file():
        spec = importlib.util.spec_from_file_location("nodularity_adaptive", str(_na_file))
        na = importlib.util.module_from_spec(spec)
        sys.modules["nodularity_adaptive"] = na
        spec.loader.exec_module(na)
    else:
        raise

# Scale-free area floors (fractions of image area, equal the historical
# 1920-wide absolute px values) — single source of truth for the pipeline.
AREA_FLOOR_RATIO = 800.0 / (1920.0 * 1920.0)     # min nodule / ref particle
BLOB_AREA_RATIO = 4000.0 / (1920.0 * 1920.0)     # substantial physical blob
# Small-particle floor: dense, fine micrographs (e.g. 10x fields with ~650
# nodules per frame) legitimately carry particles far below the historical
# 800px(1920) floor. Anything the detector accepts that sits on a dark
# component of at least this size is real graphite, not texture.
SMALL_AREA_FLOOR_RATIO = 150.0 / (1920.0 * 1920.0)


def area_floor(ratio, h, w):
    """Absolute px floor for an image size (rounded; >= 1)."""
    return max(1, int(round(ratio * float(h) * float(w))))

INPUTS = [
    PROJECT_ROOT / "nodularity_1000_batch" / "inputs" / "micrograph_0993.png",
    PROJECT_ROOT / "nodularity_1000_batch" / "inputs" / "micrograph_0995.png",
]
OUT_DIR = PROJECT_ROOT / "nodularity_report_0993_0995"
MARUMI_ISO = legacy.marumi_ratio
FONT = cv2.FONT_HERSHEY_SIMPLEX
BANNER_H = 84

MIN_RECOVER_AREA = 800      # px, at 1920-wide scale
MAX_MED_GRAY = 60           # graphite is much darker than matrix
SKIRT_OVERLAP = 0.70        # >70% inside dilated frozen mask + thin = skirt
SKIRT_MAX_EXTENT = 0.30
SCRATCH_ASPECT = 8.0
SCRATCH_MAX_EXTENT = 0.25
MIN_SOLIDITY = 0.35

# same-nodule merge logic: a frozen contour covering < this fraction of its
# dark component is a PARTIAL catch (fragment); missed dark regions from the
# same component are its remainder and must be merged, not counted twice.
FRAGMENT_COVERAGE = 0.75

# Consistency gate (applied by nodularity_pipeline): a detection whose own
# area is almost entirely LIGHT in the human-view blob map (median+Otsu) is
# phantom texture, not graphite. Measured across the 1000-image batch: real
# particles have dark fraction ~1.0 while phantoms on faint mottling sit near
# 0. Partial catches of a real particle stay (their typical minimum is ~0.8).
CONSISTENCY_KEEP_FRAC = 0.30


def detect_frozen(gray, width, height):
    om, oc = na.original_detection(gray, width, height)
    rm, rc, _, _, bg = na.robust_detection(gray, width, height)
    contours, method, texture, stats = na.choose_detection(
        gray, bg, oc, rc, width, height)
    return contours, method, texture


def max_half_length(contour):
    hull = cv2.convexHull(contour)
    _, _, radius = legacy.get_graphite_length(hull)
    return radius


def jis_bucket(marumi):
    if marumi <= 0.2:
        return 1
    if marumi <= 0.4:
        return 2
    if marumi <= 0.7:
        return 3
    if marumi <= 0.8:
        return 4
    return 5


def physical_blob_map(gray, med=None):
    """The human view of graphite: median denoise + raw Otsu on gray."""
    if med is None:
        med = cv2.medianBlur(gray, 7)
    _, blob = cv2.threshold(med, 0, 255,
                            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return cv2.morphologyEx(blob, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))


def largest_contour_of(mask_bool):
    m = (mask_bool.astype(np.uint8)) * 255
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return max(cnts, key=cv2.contourArea) if cnts else None


def dominant_label(label_map, region_mask, n_labels):
    """Most common nonzero label of label_map inside region_mask; 0 if none."""
    vals = label_map[region_mask]
    vals = vals[vals > 0]
    if vals.size == 0:
        return 0
    counts = np.bincount(vals, minlength=n_labels + 1)
    return int(np.argmax(counts))


def recover_and_merge(gray, frozen_contours, min_recover_area=None,
                      max_med_gray=None):
    """Return (final_contours, sources, border_flags).

    sources[i] in {'frozen', 'merged', 'recovered'}.
    min_recover_area: px floor for a recovered region; defaults to the
    historical 800 (1920-scale). Dense fine micrographs pass the
    small-particle floor so genuinely missed small nodules are recovered
    instead of discarded.
    max_med_gray: darkness ceiling for a recovered region; defaults to the
    historical 60. Lighter-etched fields (10x, less contrast) carry real
    graphite well above that, so the pipeline passes a higher ceiling —
    the remaining gates (skirt/scratch/solidity) still filter texture.
    """
    if min_recover_area is None:
        min_recover_area = MIN_RECOVER_AREA
    if max_med_gray is None:
        max_med_gray = MAX_MED_GRAY
    height, width = gray.shape
    mask_frozen = np.zeros(gray.shape, np.uint8)
    frozen_label = np.zeros(gray.shape, np.int32)
    for idx, cnt in enumerate(frozen_contours, 1):
        cv2.drawContours(mask_frozen, frozen_contours, idx - 1, 255, -1)
        cv2.drawContours(frozen_label, frozen_contours, idx - 1, idx, -1)
    n_frozen = len(frozen_contours)
    frozen_areas = np.array([cv2.contourArea(c) for c in frozen_contours])

    # dark map and its connected components (= graphite particles, possibly
    # merging neighbours via the 9x9 close)
    background = cv2.GaussianBlur(gray, (201, 201), 0)
    norm = cv2.subtract(background, gray)
    norm = cv2.normalize(norm, None, 0, 255, cv2.NORM_MINMAX)
    _, dark = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n_dark, dark_labels, dark_stats, _ = cv2.connectedComponentsWithStats(dark)
    dark_area = dark_stats[:, cv2.CC_STAT_AREA]

    # Which frozen contours are partial catches of their dark component?
    # fragments_of[comp] = list of frozen idx whose coverage of that component
    # stays below FRAGMENT_COVERAGE (a component can have SEVERAL fragments;
    # all but the largest get absorbed when the remainder is merged).
    fragments_of = {}
    for idx in range(1, n_frozen + 1):
        comp = dominant_label(dark_labels, frozen_label == idx, n_dark)
        if comp == 0:
            continue
        coverage = frozen_areas[idx - 1] / max(dark_area[comp], 1)
        if coverage < FRAGMENT_COVERAGE:
            fragments_of.setdefault(comp, []).append(idx)

    missed = cv2.subtract(dark, mask_frozen)
    missed = cv2.morphologyEx(missed, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    skirt_zone = cv2.dilate(mask_frozen, np.ones((31, 31), np.uint8))

    n, labels, cstats, _ = cv2.connectedComponentsWithStats(missed)

    # per-frozen-nodule union accumulators (init: the frozen contour itself)
    union_masks = {i: (frozen_label == i) for i in range(1, n_frozen + 1)}
    merged_into = set()   # primary fragment per merged component
    absorbed = set()      # sibling fragments folded into a primary
    new_regions = []  # (mask_bool, is_border)

    for i in range(1, n):
        x, y, w, h, area = cstats[i]
        if area < min_recover_area:
            continue
        region = labels == i
        med_gray = float(np.median(gray[region]))
        if med_gray > max_med_gray:
            continue

        # same-nodule test on the dark-component level: if this missed region
        # shares its dark component with frozen FRAGMENT(S), it is the
        # remainder of that nodule -> merge into the largest fragment and
        # absorb the sibling fragments (bypasses skirt/scratch gates, which
        # would wrongly drop thin rings/crescents around fragments).
        comp = dominant_label(dark_labels, region, n_dark)
        frags = fragments_of.get(comp)
        if frags:
            primary = max(frags, key=lambda k: frozen_areas[k - 1])
            union_masks[primary] |= region
            for other in frags:
                if other != primary:
                    union_masks[primary] |= (frozen_label == other)
                    absorbed.add(other)
            merged_into.add(primary)
            continue

        extent = area / float(w * h)
        overlap = float((skirt_zone[region] > 0).mean())
        if overlap > SKIRT_OVERLAP and extent < SKIRT_MAX_EXTENT:
            continue  # sliver hugging an already-counted nodule
        aspect = max(w / max(h, 1), h / max(w, 1))
        if aspect > SCRATCH_ASPECT and extent < SCRATCH_MAX_EXTENT:
            continue  # scratch-like
        solid_cnt = largest_contour_of(region)
        if solid_cnt is None:
            continue
        hull_area = cv2.contourArea(cv2.convexHull(solid_cnt))
        if hull_area <= 0 or cv2.contourArea(solid_cnt) / hull_area < MIN_SOLIDITY:
            continue  # diffuse smear, not a particle
        is_border = (x <= 1 or y <= 1 or x + w >= width - 1
                     or y + h >= height - 1)
        new_regions.append((region, is_border))

    final_contours, sources, border_flags = [], [], []
    for idx, cnt in enumerate(frozen_contours, 1):
        fidx = idx
        if fidx in absorbed:
            continue  # folded into its component's primary fragment
        if fidx in merged_into:
            merged_cnt = largest_contour_of(union_masks[fidx])
            if merged_cnt is not None:
                final_contours.append(merged_cnt)
                sources.append("merged")
                xb, yb, wb, hb = cv2.boundingRect(merged_cnt)
                border_flags.append(
                    xb <= 1 or yb <= 1 or xb + wb >= width - 1
                    or yb + hb >= height - 1)
                continue
        final_contours.append(cnt)
        sources.append("frozen")
        border_flags.append(False)
    for region, is_border in new_regions:
        cnt = largest_contour_of(region)
        if cnt is None:
            continue
        final_contours.append(cnt)
        sources.append("recovered")
        border_flags.append(is_border)
    return final_contours, sources, border_flags


def consolidate_joined(gray, contours, sources, border_flags, blob=None,
                       min_blob_area=None):
    """One physically joined dark blob = ONE nodule (dividing nodules).

    Two accepted contours that live on the SAME PHYSICAL BLOB (median-filtered
    gray + raw Otsu, the way a human sees "one joined node" — narrow necks and
    smooth gradient lobes stay connected) are unioned into a single nodule.
    Returns (contours, sources, border_flags, n_joined_groups).
    """
    height, width = gray.shape
    if blob is None:
        med = cv2.medianBlur(gray, 7)             # kill stripe texture
        blob = physical_blob_map(gray, med)
    if min_blob_area is None:
        # same floor as the pipeline's substantial-blob constant
        min_blob_area = area_floor(BLOB_AREA_RATIO, height, width)
    n_dark, dark_labels, dstats, _ = cv2.connectedComponentsWithStats(blob)

    nodule_comp = {}
    comp_nodules = {}
    for idx in range(1, len(contours) + 1):
        own = np.zeros(gray.shape, np.uint8)
        cv2.drawContours(own, contours, idx - 1, 1, -1)
        comp = dominant_label(dark_labels, own.astype(bool), n_dark)
        nodule_comp[idx] = comp
        if comp > 0:
            comp_nodules.setdefault(comp, []).append(idx)

    # a shared physical blob only counts as a dividing nodule when the blob is
    # itself substantial (not a few stray texture pixels bridging neighbours)
    to_merge = {c: ids for c, ids in comp_nodules.items()
                if len(ids) > 1 and dstats[c, cv2.CC_STAT_AREA] >= min_blob_area}
    if not to_merge:
        return contours, sources, border_flags, 0

    # pre-build the union contour of each joined group
    unions = {}
    for comp, ids in to_merge.items():
        union = np.zeros(gray.shape, np.uint8)
        touches = False
        for idx in ids:
            cv2.drawContours(union, contours, idx - 1, 255, -1)
            if border_flags[idx - 1]:
                touches = True
        cnt = largest_contour_of(union.astype(bool))
        if cnt is not None:
            unions[comp] = (cnt, touches)

    final_c, final_s, final_b = [], [], []
    emitted = set()
    for idx in range(1, len(contours) + 1):
        if idx in emitted:
            continue
        comp = nodule_comp[idx]
        if comp in to_merge and comp in unions:
            cnt, touches = unions[comp]
            final_c.append(cnt)
            final_s.append("joined")
            final_b.append(touches)
            emitted.update(to_merge[comp])
        else:
            final_c.append(contours[idx - 1])
            final_s.append(sources[idx - 1])
            final_b.append(border_flags[idx - 1])
            emitted.add(idx)
    return final_c, final_s, final_b, len(unions)


def fill_owned_blobs(gray, contours, sources, border_flags,
                     min_own=None, min_new=None, blob=None):
    """Final pass: one physical blob = ONE nodule, covering the WHOLE blob.

    For every substantial physical blob (median+Otsu map — how a human sees
    graphite), the nodules owning it are unioned WITH the entire blob region
    (fixes arc/ring contours that left giant interiors uncovered) and emitted
    as a single nodule. Unowned blobs >= min_new are added as new nodules.
    Returns (contours, sources, border_flags, n_filled).
    """
    height, width = gray.shape
    if min_own is None:
        min_own = area_floor(BLOB_AREA_RATIO, height, width)
    if min_new is None:
        min_new = area_floor(AREA_FLOOR_RATIO, height, width)
    if blob is None:
        blob = physical_blob_map(gray)
    # Open the blob map (same as the independent reference) so one working
    # component = one particle: the whole-blob expansion then cannot bridge
    # two nearby particles into a single contour (which under-counts).
    blob = cv2.morphologyEx(blob, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n_b, blab, bstats, _ = cv2.connectedComponentsWithStats(blob)

    masks = []
    cboxes = []
    for i in range(len(contours)):
        m = np.zeros(gray.shape, np.uint8)
        cv2.drawContours(m, contours, i, 255, -1)
        masks.append(m)
        cboxes.append(cv2.boundingRect(contours[i]))
    mask_areas = [float((m > 0).sum()) for m in masks]

    consumed = set()
    out_c, out_s, out_b = [], [], []
    n_filled = 0
    order = sorted(range(1, n_b), key=lambda i: -int(bstats[i, cv2.CC_STAT_AREA]))
    max_particle_area = int(0.08 * height * width)
    for bi in order:
        barea = int(bstats[bi, cv2.CC_STAT_AREA])
        bw = int(bstats[bi, cv2.CC_STAT_WIDTH])
        bh = int(bstats[bi, cv2.CC_STAT_HEIGHT])
        bx = int(bstats[bi, cv2.CC_STAT_LEFT])
        by = int(bstats[bi, cv2.CC_STAT_TOP])
        if barea < min_new or barea > max_particle_area or (bw > 0.6 * width and bh > 0.6 * height):
            continue
        bmask = (blab == bi)
        owners = []
        for ni in range(len(contours)):
            if ni in consumed:
                continue
            cx, cy, cw, ch = cboxes[ni]
            # Fast Bounding-Box overlap rejection: skips 99% of non-intersecting pairs
            if cx > bx + bw or cx + cw < bx or cy > by + bh or cy + ch < by:
                continue
            ix0, iy0 = max(bx, cx), max(by, cy)
            ix1, iy1 = min(bx + bw, cx + cw), min(by + bh, cy + ch)
            sub_m = masks[ni][iy0:iy1, ix0:ix1]
            sub_b = (blab[iy0:iy1, ix0:ix1] == bi)
            inter = float(((sub_m > 0) & sub_b).sum())
            if inter >= 0.3 * max(mask_areas[ni], 1.0) or inter >= 0.1 * barea:
                owners.append(ni)
        if owners:
            union = bmask.astype(np.uint8) * 255
            for ni in owners:
                union |= masks[ni]
                consumed.add(ni)
            cnt = largest_contour_of(union.astype(bool))
            if cnt is None or cv2.contourArea(cnt) > max_particle_area:
                continue
            out_c.append(cnt)
            # a real "dividing nodule unified" only when >=2 prior nodules
            out_s.append("blobfill" if len(owners) >= 2 else sources[owners[0]])
            if len(owners) >= 2:
                n_filled += 1
            x, y, w2, h2 = cv2.boundingRect(cnt)
            out_b.append(x <= 1 or y <= 1 or x + w2 >= width - 1
                         or y + h2 >= height - 1)
        elif barea >= min_new:
            # nobody detected this blob — a genuine miss
            cnt = largest_contour_of(bmask)
            if cnt is None:
                continue
            out_c.append(cnt)
            out_s.append("recovered")
            x, y, w2, h2 = cv2.boundingRect(cnt)
            out_b.append(x <= 1 or y <= 1 or x + w2 >= width - 1
                         or y + h2 >= height - 1)
    for ni in range(len(contours)):
        if ni not in consumed:
            out_c.append(contours[ni])
            out_s.append(sources[ni])
            out_b.append(border_flags[ni])
    return out_c, out_s, out_b, n_filled


def draw_banner(image, line1, line2):
    banner = np.full((BANNER_H, image.shape[1], 3), 255, dtype=np.uint8)
    cv2.putText(banner, line1, (12, 34), FONT, 0.95, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.putText(banner, line2, (12, 70), FONT, 0.72, (60, 60, 60), 2, cv2.LINE_AA)
    return np.vstack([banner, image])


def analyze(path):
    color = cv2.imread(str(path))
    src_h, src_w = color.shape[:2]
    height = int(legacy.pic_width * src_h / src_w)
    color = cv2.resize(color, (legacy.pic_width, height))
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)

    frozen_contours, method, texture = detect_frozen(gray, legacy.pic_width, height)
    contours, sources, border_flags = recover_and_merge(
        gray, frozen_contours)
    contours, sources, border_flags, n_joined = consolidate_joined(
        gray, contours, sources, border_flags)
    contours, sources, border_flags, n_filled = fill_owned_blobs(
        gray, contours, sources, border_flags)

    mask = np.zeros(gray.shape, np.uint8)
    cv2.drawContours(mask, contours, -1, 255, -1)

    annotated = color.copy()
    rows = []
    area_total = area_round = 0.0
    area_total_inframe = area_round_inframe = 0.0
    jis_counts = [0, 0, 0, 0, 0]
    for idx, cnt in enumerate(contours, 1):
        area = cv2.contourArea(cnt)
        area_total += area
        if not border_flags[idx - 1]:
            area_total_inframe += area
        r = max_half_length(cnt)
        marumi = area / ((r ** 2) * math.pi) if r > 0 else 0.0
        bucket = jis_bucket(marumi)
        jis_counts[bucket - 1] += 1
        is_round = marumi >= MARUMI_ISO
        if is_round:
            area_round += area
            if not border_flags[idx - 1]:
                area_round_inframe += area
        src = sources[idx - 1]
        if src == "frozen":
            outline, thickness = ((0, 0, 255) if is_round else (255, 200, 0)), 2
        elif src == "merged":
            outline, thickness = (0, 140, 255), 3     # orange = merged remainder
        elif src == "joined" or src == "blobfill":
            outline, thickness = (255, 0, 255), 3     # magenta = dividing nodule unified
        else:
            thickness = 4 if border_flags[idx - 1] else 3
            outline = (0, 140, 255)                    # orange = new recovery
        cv2.drawContours(annotated, contours, idx - 1, outline, thickness)
        x, y, w, h = cv2.boundingRect(cnt)
        rows.append({
            "nodule_id": idx,
            "source": src,
            "touches_border": border_flags[idx - 1],
            "center_x": round((x + w / 2) / legacy.pic_width, 6),
            "center_y": round((y + h / 2) / height, 6),
            "area_px": round(area, 1),
            "equiv_diameter_px": round(2 * math.sqrt(area / math.pi), 2),
            "roundness": round(marumi, 4),
            "iso_class": "V/VI" if is_round else "irregular",
            "jis_bucket": bucket,
        })

    iso_pct = area_round / area_total * 100 if area_total else 0.0
    jis_pct = (0.3 * jis_counts[1] + 0.7 * jis_counts[2] + 0.9 * jis_counts[3]
               + jis_counts[4]) / len(contours) * 100 if contours else 0.0
    iso_inframe = (area_round_inframe / area_total_inframe * 100
                   if area_total_inframe else 0.0)

    n_merged = sources.count("merged")
    n_new = sources.count("recovered")
    n_unified = (sources.count("joined") + sources.count("blobfill"))
    line1 = ("{}  |  Nodules: {}  (frozen detector said {} — {} dividing "
             "nodules unified, {} missed recovered)  |  ISO: {:.1f}%  |  JIS: {:.1f}%").format(
        path.stem, len(contours), len(frozen_contours), n_unified, n_new,
        iso_pct, jis_pct)
    line2 = ("Red = nodular / Cyan = irregular (frozen)  |  Orange = recovery  |  "
             "Magenta = dividing nodule (joined lobes = ONE)  |  ISO in-frame: {:.1f}%").format(
        iso_inframe)
    annotated = draw_banner(annotated, line1, line2)

    stem = path.stem
    cv2.imwrite(str(OUT_DIR / (stem + "_recovered_mask.png")), mask)
    cv2.imwrite(str(OUT_DIR / (stem + "_recovered_annotated.png")), annotated)
    with open(OUT_DIR / (stem + "_recovered_stats.csv"), "w", newline="",
              encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    return {
        "stem": stem, "original": color, "mask": mask, "annotated": annotated,
        "count": len(contours), "frozen_count": len(frozen_contours),
        "merged": n_merged, "new": n_new, "joined": n_unified,
        "iso": iso_pct, "jis": jis_pct, "iso_inframe": iso_inframe,
    }


def panel(img, label, size_w=640, size_h=480):
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    img = cv2.resize(img, (size_w, size_h), interpolation=cv2.INTER_AREA)
    header = np.full((34, size_w, 3), 40, dtype=np.uint8)
    cv2.putText(header, label, (10, 24), FONT, 0.62, (255, 255, 255), 2,
                cv2.LINE_AA)
    return np.vstack([header, img])


def build_report(results):
    rows = []
    for r in results:
        line = ("{}  |  Nodules: {} (frozen {} + {} fixed + {} new, {} dividing "
                "unified)  |  ISO: {:.1f}%  |  JIS: {:.1f}%").format(
            r["stem"], r["count"], r["frozen_count"], r["merged"], r["new"],
            r["joined"], r["iso"], r["jis"])
        panel_h = 514
        row = np.hstack([
            panel(r["original"], "Original", size_h=panel_h - 34),
            panel(r["mask"], "Final mask (graphite)", size_h=panel_h - 34),
            panel(r["annotated"].copy(), "Detected + recovered", size_h=panel_h - 34),
        ])
        banner = np.full((52, row.shape[1], 3), 255, dtype=np.uint8)
        cv2.putText(banner, line, (12, 36), FONT, 0.85, (0, 0, 0), 2, cv2.LINE_AA)
        rows.append(np.vstack([banner, row]))
        rows.append(np.full((6, row.shape[1], 3), 200, dtype=np.uint8))
    cv2.imwrite(str(OUT_DIR / "report_recovered_0993_0995.png"),
                np.vstack(rows[:-1]))


def main():
    OUT_DIR.mkdir(exist_ok=True)
    results = []
    for p in INPUTS:
        r = analyze(p)
        results.append(r)
        print("{}: nodules={} (frozen {} + merged {} + new {} + unified {}) "
              "ISO={:.2f}% JIS={:.2f}% ISO_inframe={:.2f}%".format(
                  r["stem"], r["count"], r["frozen_count"], r["merged"],
                  r["new"], r["joined"], r["iso"], r["jis"], r["iso_inframe"]))
    build_report(results)
    print("Outputs written to:", OUT_DIR)


if __name__ == "__main__":
    main()
