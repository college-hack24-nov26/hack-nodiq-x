"""scripts/tools/run_merge_experiment.py — Phase 9B/9D/9G-9M experiment runner.

Controlled OFFLINE touching-particle split experiment.  Production is never
modified: this tool runs the unchanged production pipeline, keeps its result
as BASELINE, applies services/experimental/touching_split.py to candidate
particles, and compares BASELINE vs SPLITTER against the Phase 8 ground
truth documents.

Honesty: the Phase 8 GT documents are AI PRE-ANNOTATION PROPOSALS with
provenance E.  Every result computed here is EXPLORATORY ONLY and never a
real-world accuracy claim.  The Phase 8 honesty gate is untouched.

Tracks (both evaluated; deployment uses Track A):

* Track A (GT-blind candidates): a production particle is a candidate when
  the splitter's own evidence gate fires (elongation or multi-peak waist).
* Track B (GT-informed recall ceiling): candidates = production particles
  overlapping >= 2 GT particles at IoU 0.5 — an upper bound on what any
  splitter could recover, not deployable without GT.

Usage:
    python scripts/tools/run_merge_experiment.py                 # sweep + report
    python scripts/tools/run_merge_experiment.py --quick         # 2 configs
    python scripts/tools/run_merge_experiment.py --images p1,p2  # subset
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]

from nodiq.services.experimental.touching_split import (        # noqa: E402
    AREA_CONSERVATION_TOLERANCE, SplitParams, split_particle_mask)
from nodiq.services.ground_truth import (                        # noqa: E402
    GT_DIR, gt_nodularity_from_geometry, load_all_ground_truth)
from nodiq.services import gt_benchmark as gb                    # noqa: E402
from nodiq.pipelines.nodularity_pipeline import analyze_image              # noqa: E402

from nodiq.core.config import OUTPUTS_DIR
OUT_DIR = OUTPUTS_DIR / "merge_experiment"
IOU = 0.50

# Baseline reference numbers from reports/ground_truth/summary_v1.json
# (Phase 8): F1@0.5 0.6122, ISO MAE 9.83 pp, JIS MAE 17.25 pp.

# Phase 9F — small documented grid, not a brute-force search.
SWEEP = [
    {"label": "concavity-default",
     "params": {"technique": "concavity"}},
    {"label": "watershed-default",
     "params": {"technique": "watershed"}},
    {"label": "concavity-conservative",
     "params": {"technique": "concavity", "min_concavity_depth": 0.15}},
    {"label": "watershed-conservative",
     "params": {"technique": "watershed", "neck_ratio_min": 1.4}},
    {"label": "concavity-aggressive",
     "params": {"technique": "concavity", "min_concavity_depth": 0.07,
                "elongation_min": 1.15}},
    {"label": "watershed-aggressive",
     "params": {"technique": "watershed", "neck_ratio_min": 1.1,
                "elongation_min": 1.15, "dt_marker_prominence": 0.15}},
]


def _commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT),
            text=True).strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# per-image experiment
# ---------------------------------------------------------------------------

def _masks_of_contours(contours, shape):
    masks = []
    for c in contours:
        m = np.zeros(shape[:2], np.uint8)
        arr = np.asarray(c)
        cv2.drawContours(m, [arr.astype(np.int64)], -1, 255, -1)
        masks.append(m)
    return masks


def _gt_bboxes(gt_masks):
    """Tight bboxes (x0, y0, x1, y1) of the GT masks (None for empty)."""
    return [_bbox_of(gm) for gm in gt_masks]

def _bbox_hits(pred_mask, boxes):
    """Indices of GT bboxes intersecting the prediction's bbox."""
    ys, xs = np.nonzero(pred_mask > 0)
    if not len(xs):
        return []
    px0, py0, px1, py1 = int(xs.min()), int(ys.min()), \
        int(xs.max()) + 1, int(ys.max()) + 1
    return [i for i, b in enumerate(boxes)
            if b is not None and not (b[2] < px0 or px1 < b[0] or
                                      b[3] < py0 or py1 < b[1])]


def _overlaps_gt_ge2(pred_mask, gt_masks, boxes=None, areas=None):
    """True when the prediction overlaps >= 2 GT particles (IoU-0.5 sense:
    overlap fraction of the smaller mask >= 0.10, matching the benchmark's
    relation definition).  Bbox-prefiltered + cropped for speed."""
    boxes = boxes if boxes is not None else _gt_bboxes(gt_masks)
    areas = areas if areas is not None else [int(np.count_nonzero(g))
                                             for g in gt_masks]
    p_area = int((pred_mask > 0).sum())
    hits = 0
    for gi in _bbox_hits(pred_mask, boxes):
        x0, y0, x1, y1 = boxes[gi]
        inter = int(np.count_nonzero(pred_mask[y0:y1, x0:x1] & gt_masks[gi][y0:y1, x0:x1]))
        if inter <= 0:
            continue
        smaller = min(p_area, areas[gi])
        if smaller > 0 and inter / smaller >= 0.10:
            hits += 1
            if hits >= 2:
                return True
    return False


_PROD_CACHE = {}
_GT_GEO_CACHE = {}
_BASE_EVAL_CACHE = {}


PROD_DISK_CACHE = OUT_DIR / "_prod_cache"


def _production_cached(image_path, use_disk=True):
    """Production is deterministic; run it once per image and reuse the
    identical result dict across configurations (same behavior as
    re-running analyze_image each time).  An optional disk cache lets
    batched invocations skip the pipeline cost; the cache is keyed by the
    image path + git commit and holds ONLY the experiment's working copy
    (production itself is never touched).  Delete _prod_cache/ to clear."""
    key = str(image_path)
    if key in _PROD_CACHE:
        return _PROD_CACHE[key]
    disk = None
    if use_disk:
        import pickle
        PROD_DISK_CACHE.mkdir(parents=True, exist_ok=True)
        disk = PROD_DISK_CACHE / (Path(image_path).stem + ".pkl")
        if disk.is_file():
            try:
                with open(disk, "rb") as fh:
                    res = pickle.load(fh)
                if res.get("_cache_key") == key + "@" + _commit():
                    _PROD_CACHE[key] = res
                    return res
            except Exception:
                pass
    res = analyze_image(str(image_path), with_accuracy=False,
                        stem=Path(image_path).stem)
    if use_disk and disk is not None:
        import pickle
        try:
            res["_cache_key"] = key + "@" + _commit()
            with open(disk, "wb") as fh:
                pickle.dump(res, fh)
        except Exception:
            pass
    _PROD_CACHE[key] = res
    return res


def run_image_experiment(gt, params: SplitParams, track="A",
                         prod=None):
    """Run one image: baseline production -> optional split -> metrics.

    Returns (result_dict, image_arrays_for_overlay) or (None, reason) when
    the image cannot be used.  The splitter is called EXACTLY ONCE per
    candidate parent; its SplitResult feeds both the aggregate experiment
    set and the per-split detail (identical decisions by construction).
    """
    image_path = PROJECT_ROOT / gt["image_file"]
    if not image_path.is_file():
        return None, f"missing image file: {gt['image_file']}"
    res = prod if prod is not None else _production_cached(image_path)
    work_shape = res["gray"].shape
    scale = work_shape[1] / float(res["source_width"])
    gt_items = gt_particles_to_masks_local(gt, work_shape, scale)
    if not gt_items:
        return None, "no GT particles"
    gt_masks = [it["mask"] for it in gt_items]
    gt_boxes = _gt_bboxes(gt_masks)
    gt_areas = [int(np.count_nonzero(g)) for g in gt_masks]
    src_img = res.get("color")

    base_contours = list(res["contours"])
    base_masks = _masks_of_contours(base_contours, work_shape)

    # baseline evaluation is config-independent: compute once per image
    key = (gt.get("image_id"),)
    if key not in _BASE_EVAL_CACHE:
        _BASE_EVAL_CACHE[key] = evaluate_contour_set(base_contours,
                                                     gt_masks, gt,
                                                     work_shape)

    # ---- single splitter pass per candidate parent --------------------------
    decisions = []            # (is_candidate, SplitResult)
    for pm in base_masks:
        if track == "B":
            is_cand = _overlaps_gt_ge2(pm, gt_masks, gt_boxes, gt_areas)
        else:
            is_cand = tsplit.passes_evidence(pm, params)
        r = split_particle_mask(pm, params) if is_cand else None
        decisions.append((is_cand, r))

    n_candidates = sum(1 for c, _ in decisions if c)
    n_split = sum(1 for _, r in decisions
                  if r is not None and r.split_performed)
    n_unchanged = len(decisions) - n_split
    splits_per_particle = [len(r.children_masks) for _, r in decisions
                           if r is not None and r.split_performed]

    # experimental contour set: children where split, parent otherwise
    exp_contours, exp_sources = [], []
    for (is_cand, r), pm in zip(decisions, base_masks):
        if r is not None and r.split_performed:
            for ch in r.children_masks:
                exp_contours.append(largest_contour_local(ch))
                exp_sources.append("split")
        else:
            exp_contours.append(largest_contour_local(pm))
            exp_sources.append("unchanged")

    baseline = _BASE_EVAL_CACHE[key]
    experiment = evaluate_contour_set(exp_contours, gt_masks, gt,
                                      work_shape)

    # ---- per-split detail (9H/9I), reusing the SAME SplitResults ----------
    per_split = []
    for pi, (is_cand, r) in enumerate(decisions):
        if r is None or not r.split_performed or len(r.children_masks) < 2:
            continue
        pm = base_masks[pi]
        kids = r.children_masks
        parent_area = int((pm > 0).sum())
        child_area = int(r.children_areas and sum(r.children_areas) or
                         sum(int(np.count_nonzero(c)) for c in kids))
        entry = {
            "parent_pred_id": pi + 1,
            "n_children": len(kids),
            "technique": params.technique,
            "parent_area": parent_area,
            "children_area": child_area,
            "area_ratio": child_area / parent_area if parent_area else None,
            "area_conserved": parent_area > 0 and
                              abs(child_area / parent_area - 1.0) <=
                              AREA_CONSERVATION_TOLERANCE,
            "children_below_min_area": sum(
                1 for a in (r.children_areas or
                            [int(np.count_nonzero(c)) for c in kids])
                if a < params.min_area),
        }
        parent_m = _morph_cached(pm)
        entry["parent_roundness"] = round(parent_m["roundness"], 4)
        child_m = [_morph_cached(c) for c in kids]
        entry["children_mean_roundness"] = round(
            float(np.mean([m["roundness"] for m in child_m])), 4)
        entry["children_round"] = sum(
            1 for m in child_m if m["roundness"] >= 0.6)
        # match children to best-overlap GT particles (bbox-prefiltered)
        best = []
        for c, cb in zip(kids, (r.children_bboxes or [None] * len(kids))):
            c_area = int(np.count_nonzero(c))
            bi, biou = None, 0.0
            if cb is not None:
                hits = [gi for gi, gb_ in enumerate(gt_boxes)
                        if gb_ is not None and
                        not (gb_[2] < cb[0] or cb[0] + cb[2] < gb_[0] or
                             gb_[3] < cb[1] or cb[1] + cb[3] < gb_[1])]
            else:
                hits = _bbox_hits(c, gt_boxes)
            for gi in hits:
                gm = gt_masks[gi]
                x0, y0, x1, y1 = gt_boxes[gi]
                inter = int(np.count_nonzero(c[y0:y1, x0:x1] & gm[y0:y1, x0:x1]))
                if inter == 0:
                    continue
                union = c_area + gt_areas[gi] - inter
                iou = inter / union
                if iou > biou:
                    bi, biou = gi, iou
            best.append((bi, biou))
        rows = []
        for (bi, biou), cm in zip(best, child_m):
            gmi = _morph_cached(gt_masks[bi]) if bi is not None \
                else None
            rows.append({
                "gt_id": bi, "iou": round(biou, 4),
                "area_err": (abs(cm["area"] - gmi["area"]) / gmi["area"])
                if gmi and gmi["area"] else None,
                "feret_err": (abs(cm["feret"] - gmi["feret"])
                              if gmi else None),
                "roundness_err": (abs(cm["roundness"] - gmi["roundness"])
                                  if gmi else None),
                "circularity_err": (abs(cm["circularity"] -
                                        gmi["circularity"]) if gmi else None),
                "solidity_err": (abs(cm["solidity"] - gmi["solidity"])
                                 if gmi else None),
                "child_roundness": round(cm["roundness"], 4),
                "gt_roundness": round(gmi["roundness"], 4)
                if gmi else None,
            })
        entry["children"] = rows
        per_split.append(entry)

    # ---- 9L small-particle safety ------------------------------------------
    def small_stats(masks):
        if not masks:
            return {"n": 0, "below_100px": 0, "frac_below_100px": None,
                    "area_share_below_100px": None}
        areas = [int(np.count_nonzero(m)) for m in masks]
        small = [a for a in areas if a < 100]
        tot = sum(areas) or 1
        return {"n": len(areas), "below_100px": len(small),
                "frac_below_100px": len(small) / len(areas),
                "area_share_below_100px": sum(small) / tot}

    result = {
        "image_id": gt.get("image_id"),
        "provenance": (gt.get("annotation") or {}).get("provenance_class"),
        "track": track,
        "technique": params.technique,
        "baseline": baseline,
        "experiment": experiment,
        "delta": {
            "precision": _d(baseline["detection"]["precision"],
                            experiment["detection"]["precision"]),
            "recall": _d(baseline["detection"]["recall"],
                         experiment["detection"]["recall"]),
            "f1": _d(baseline["detection"]["f1"],
                     experiment["detection"]["f1"]),
            "iso_abs_err_pp": _d(baseline["iso"]["abs_err_pp"],
                                 experiment["iso"]["abs_err_pp"]),
            "jis_abs_err_pp": _d(baseline["jis"]["abs_err_pp"],
                                 experiment["jis"]["abs_err_pp"]),
        },
        "candidates": n_candidates,
        "splits": n_split,
        "unchanged": n_unchanged,
        "splits_per_particle": splits_per_particle,
        "count": {
            "gt": len(gt_masks),
            "baseline_pred": len(base_masks),
            "experiment_pred": len(exp_contours),
        },
        "per_split": per_split,
        "small_particles": {
            "baseline": small_stats(base_masks),
            "experiment": small_stats(
                _masks_of_contours(exp_contours, work_shape)),
        },
    }
    arrays = {"work_shape": work_shape, "src": src_img,
              "base_contours": base_contours, "exp_contours": exp_contours,
              "gt_masks": gt_masks}
    return result, arrays


def _d(a, b):
    if a is None or b is None:
        return None
    return round(b - a, 6)


# ---------------------------------------------------------------------------
# contour-set evaluation (detection, morphology, ISO, JIS)
# ---------------------------------------------------------------------------

def _fast_match(gt_masks, contours, work_shape, iou_threshold=IOU,
                _morph=None):
    """Crop-based replica of gb.match_with_relations for experiment speed.

    Produces the same greedy IoU matching, TP/FP/FN, precision/recall/F1,
    mean IoU, area_pairs and merge/split relation counts as the benchmark's
    matcher, but computes intersections on GT-bbox crops instead of the
    full canvas (the production matcher itself is untouched).  Equivalence
    is asserted by tests/test_merge_experiment.py::test_fast_match_matches
    _benchmark_matcher.
    """
    boxes = _gt_bboxes(gt_masks)
    areas = [int(np.count_nonzero(g)) for g in gt_masks]
    pred_masks, pred_boxes, pred_areas = [], [], []
    for c in contours:
        m = np.zeros(work_shape[:2], np.uint8)
        arr = np.asarray(c)
        if arr.ndim == 2:
            m = arr.astype(np.uint8)
        else:
            cv2.drawContours(m, [arr.astype(np.int64)], -1, 255, -1)
        pred_masks.append(m)
        pb = _bbox_of(m)
        pred_boxes.append(pb)
        pred_areas.append(int(np.count_nonzero(m[pb[1]:pb[3], pb[0]:pb[2]]))
                          if pb else 0)

    pairs = []                                   # (iou, gi, pi, inter)
    rels = defaultdict(list)                     # gi -> [pi] (relation)
    for pi, pm in enumerate(pred_masks):
        if pred_areas[pi] == 0 or pred_boxes[pi] is None:
            continue
        px0, py0, px1, py1 = pred_boxes[pi]
        for gi, gb_ in enumerate(boxes):
            if gb_ is None or areas[gi] == 0:
                continue
            if gb_[2] < px0 or px1 < gb_[0] or gb_[3] < py0 or py1 < gb_[1]:
                continue
            x0, y0, x1, y1 = (max(px0, gb_[0]), max(py0, gb_[1]),
                              min(px1, gb_[2]), min(py1, gb_[3]))
            inter = int(np.count_nonzero(pm[y0:y1, x0:x1] & gt_masks[gi][y0:y1, x0:x1]))
            if inter <= 0:
                continue
            union = areas[gi] + pred_areas[pi] - inter
            iou = inter / union
            if iou > 0:
                pairs.append((iou, gi, pi, inter))
            smaller = min(areas[gi], pred_areas[pi])
            if smaller > 0 and inter / smaller >= 0.10:
                rels[gi].append(pi)

    pairs.sort(key=lambda t: t[0], reverse=True)
    matched, iou_list, area_pairs = [], [], []
    mg, mp = set(), set()
    for iou, gi, pi, inter in pairs:
        if iou < iou_threshold:
            break
        if gi in mg or pi in mp:
            continue
        mg.add(gi)
        mp.add(pi)
        matched.append((gi, pi))
        iou_list.append(iou)
        area_pairs.append({"gt_id": gi, "pred_id": pi, "iou": iou,
                           "gt_area_px": areas[gi],
                           "pred_area_px": pred_areas[pi]})
    fn = [gi for gi in range(len(gt_masks)) if gi not in mg]
    fp = [pi for pi in range(len(pred_masks)) if pi not in mp]
    precision = len(matched) / (len(matched) + len(fp)) \
        if (len(matched) + len(fp)) else None
    recall = len(matched) / (len(matched) + len(fn)) \
        if (len(matched) + len(fn)) else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall else None)
    pred_rels = defaultdict(list)
    for gi, pis in rels.items():
        for pi in pis:
            pred_rels[pi].append(gi)
    n_merge = sum(1 for pis in pred_rels.values() if len(pis) >= 2)
    n_split = sum(1 for pis in rels.values() if len(pis) >= 2)
    return {
        "tp": len(matched), "fp_count": len(fp), "fn_count": len(fn),
        "fp_indices": fp, "fn_indices": fn,
        "precision": precision, "recall": recall, "f1": f1,
        "mean_iou": (float(np.mean(iou_list)) if iou_list else None),
        "area_pairs": area_pairs,
        "n_merge_groups": n_merge, "n_split_groups": n_split,
        "gt_masks": gt_masks, "pred_masks": pred_masks,
    }


def _bbox_of(mask):
    ys, xs = np.nonzero(mask > 0)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, \
        int(ys.max()) + 1




def _bbox_of_bbox(mask, box):
    """bbox of `mask` restricted to a known outer box (x0,y0,x1,y1) -
    avoids a full-canvas nonzero scan when the box is already known."""
    x0, y0, x1, y1 = box
    sub = mask[y0:y1, x0:x1]
    ys, xs = np.nonzero(sub > 0)
    if not len(xs):
        return None
    return x0 + int(xs.min()), y0 + int(ys.min()),         x0 + int(xs.max()) + 1, y0 + int(ys.max()) + 1


_MORPH_CACHE = {}


def _morph_cached(mask, box=None):
    """bbox-cropped gb.morphology_of_mask, memoized on (shape, bytes).

    Cropping to the mask's own bbox leaves area/feret/roundness/circularity/
    solidity EXACTLY unchanged (every quantity is computed from the contour
    geometry, not from absolute pixel positions), while bounding the cost by
    the particle instead of the 1920-wide canvas.  `box` = already-known
    (x0, y0, x1, y1) to skip the full-canvas scan.
    """
    key = (mask.shape, mask.tobytes())
    if key in _MORPH_CACHE:
        return _MORPH_CACHE[key]
    if box is None:
        ys, xs = np.nonzero(mask > 0)
        if not len(xs):
            out = gb.morphology_of_mask(mask)
            _MORPH_CACHE[key] = out
            return out
        x0, y0, x1, y1 = int(xs.min()), int(ys.min()),             int(xs.max()) + 1, int(ys.max()) + 1
    else:
        x0, y0, x1, y1 = box
    out = gb.morphology_of_mask(np.ascontiguousarray(mask[y0:y1, x0:x1]))
    _MORPH_CACHE[key] = out
    return out

def evaluate_contour_set(contours, gt_masks, gt, work_shape):
    m = _fast_match(gt_masks, contours, work_shape, iou_threshold=IOU)
    # nodularity from the contour set itself (engine-identical formulas)
    area_total = area_round = 0.0
    jis_counts = [0, 0, 0, 0, 0]
    from nodiq.pipelines.analyze_with_recovery import jis_bucket
    for c in contours:
        mm = np.zeros(work_shape[:2], np.uint8)
        arr = np.asarray(c)
        cv2.drawContours(mm, [arr.astype(np.int64)], -1, 255, -1)
        mo = gb.morphology_of_mask(mm)
        if mo["area"] <= 0:
            continue
        area_total += mo["area"]
        if mo["roundness"] >= 0.6:
            area_round += mo["area"]
        jis_counts[jis_bucket(mo["roundness"]) - 1] += 1
    n = sum(jis_counts)
    iso = area_round / area_total * 100 if area_total else None
    jis = ((0.3 * jis_counts[1] + 0.7 * jis_counts[2] +
            0.9 * jis_counts[3] + jis_counts[4]) / n * 100) if n else None

    ref = gt_nodularity_from_geometry(gt)
    ref_iso = ref["iso_pct"] if ref else None
    ref_jis = ref["jis_pct"] if ref else None

    # morphology MAE over matched pairs
    f = defaultdict(list)
    pboxes = m.get("pred_boxes") or [None] * len(m["pred_masks"])
    for pair in m["area_pairs"]:
        gi, pi = pair["gt_id"], pair["pred_id"]   # noqa: B007 (paired loop)
        gmo = _morph_cached(m["gt_masks"][gi])
        pmo = _morph_cached(m["pred_masks"][pi], pboxes[pi])
        f["area"].append(abs(pmo["area"] - gmo["area"]))
        f["feret"].append(abs(pmo["feret"] - gmo["feret"]))
        f["roundness"].append(abs(pmo["roundness"] - gmo["roundness"]))
        f["circularity"].append(abs(pmo["circularity"] -
                                    gmo["circularity"]))
        f["solidity"].append(abs(pmo["solidity"] - gmo["solidity"]))
    mae = {k: (float(np.mean(v)) if v else None) for k, v in f.items()}

    return {
        "detection": {
            "tp": m["tp"], "fp": m["fp_count"], "fn": m["fn_count"],
            "precision": m["precision"], "recall": m["recall"],
            "f1": m["f1"], "mean_iou": m["mean_iou"],
            "n_merge_groups": m["n_merge_groups"],
            "n_split_groups": m["n_split_groups"],
        },
        "morphology_mae": {k: (round(v, 4) if v is not None else None)
                           for k, v in mae.items()},
        "iso": {"value_pct": iso,
                "abs_err_pp": (abs(iso - ref_iso)
                               if iso is not None and ref_iso is not None
                               else None)},
        "jis": {"value_pct": jis,
                "abs_err_pp": (abs(jis - ref_jis)
                               if jis is not None and ref_jis is not None
                               else None),
                "class_counts": jis_counts,
                "ref_class_counts": ref["jis_class_counts"] if ref else None},
        "pred_count": len(contours),
    }


def gt_particles_to_masks_local(gt, work_shape, scale):
    """GT polygons -> masks at the production work scale (1920-wide)."""
    from nodiq.services.ground_truth import gt_particles_to_masks
    return gt_particles_to_masks(gt, work_shape, scale=scale)


def largest_contour_local(mask):
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    return max(cnts, key=cv2.contourArea) if cnts else None


tsplit = sys.modules["services.experimental.touching_split"]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="only 2 configurations")
    ap.add_argument("--images", default="",
                    help="comma-separated image_id subset")
    ap.add_argument("--track", default="A", choices=["A", "B", "both"])
    ap.add_argument("--configs", default="",
                    help="comma-separated config labels to run (default: all)")
    args = ap.parse_args()

    sweep = SWEEP[:2] if args.quick else SWEEP
    if args.configs:
        wanted_cfg = [s.strip() for s in args.configs.split(",") if s.strip()]
        sweep = [c for c in sweep if c["label"] in wanted_cfg]
    gts = load_all_ground_truth(GT_DIR)
    if not gts:
        print("no GT documents found — nothing to do")
        return
    wanted = [s.strip() for s in args.images.split(",") if s.strip()]
    if wanted:
        gts = {k: v for k, v in gts.items() if k in wanted}
    write_overlays = not args.quick          # 9O: only default configs

    tracks = ["A", "B"] if args.track == "both" else [args.track]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "overlays").mkdir(parents=True, exist_ok=True)

    all_rows, per_particle_rows = [], []
    summary = {
        "experiment": "phase9_touching_split",
        "date": date.today().isoformat(),
        "production_commit": _commit(),
        "production_unchanged": True,
        "honesty": {
            "gt_provenance": "E (AI pre-annotation proposals, NOT expert GT)",
            "status_label": "EXPERIMENTALLY PROMISING — NOT REAL-WORLD "
                            "VERIFIED (at best)",
            "note": "All values are proposal-relative; never cite as "
                    "real-world accuracy.",
        },
        "iou_threshold": IOU,
        "area_conservation_tolerance": AREA_CONSERVATION_TOLERANCE,
        "configs": [], "images": [],
    }

    # Resume support: keep completed configurations from a previous (partial)
    # run so sub-invocations accumulate instead of clobbering earlier results.
    rerun = {f"{c['label']}@{t}" for t in tracks for c in sweep}
    _prev_summary = OUT_DIR / "summary.json"
    if _prev_summary.exists():
        try:
            old = json.loads(_prev_summary.read_text(encoding="utf-8"))
            carried = [s for s in old.get("images", [])
                       if f"{s.get('config')}@{s.get('track')}" not in rerun]
            summary["images"].extend(carried)
            summary["configs"].extend(
                k for k in old.get("configs", [])
                if k not in rerun and k not in summary["configs"])
            all_rows.extend(_load_rows(OUT_DIR / "per_case.csv", rerun))
            per_particle_rows.extend(
                _load_rows(OUT_DIR / "per_particle.csv", rerun))
            if carried:
                print(f"[resume] carrying {len(carried)} completed "
                      f"config@track results from the previous run")
        except Exception as exc:
            print(f"[resume] previous outputs not reusable: {exc}")

    for track in tracks:
        for cfg in sweep:
            params = SplitParams(**cfg["params"])
            label = f"{cfg['label']}@{track}"
            print(f"=== {label} ===")
            cfg_rows = []
            for image_id, gt in sorted(gts.items()):
                prod = _production_cached(PROJECT_ROOT / gt["image_file"])
                res, arrays = run_image_experiment(gt, params, track=track,
                                                   prod=prod)
                if res is None:
                    print(f"  {image_id}: SKIPPED ({arrays})")
                    continue
                res["config"] = cfg["label"]
                res["track"] = track
                cfg_rows.append(res)
                row = {
                    "config": cfg["label"], "track": track,
                    "image_id": image_id,
                    "provenance": res["provenance"],
                    "n_gt": res["count"]["gt"],
                    "base_pred": res["count"]["baseline_pred"],
                    "exp_pred": res["count"]["experiment_pred"],
                    "candidates": res["candidates"],
                    "splits": res["splits"],
                    "base_tp": res["baseline"]["detection"]["tp"],
                    "base_fp": res["baseline"]["detection"]["fp"],
                    "base_fn": res["baseline"]["detection"]["fn"],
                    "base_f1": res["baseline"]["detection"]["f1"],
                    "exp_tp": res["experiment"]["detection"]["tp"],
                    "exp_fp": res["experiment"]["detection"]["fp"],
                    "exp_fn": res["experiment"]["detection"]["fn"],
                    "exp_f1": res["experiment"]["detection"]["f1"],
                    "base_merge": res["baseline"]["detection"][
                        "n_merge_groups"],
                    "exp_merge": res["experiment"]["detection"][
                        "n_merge_groups"],
                    "base_iso": res["baseline"]["iso"]["value_pct"],
                    "exp_iso": res["experiment"]["iso"]["value_pct"],
                    "ref_iso": (gt_nodularity_from_geometry(gt) or {})
                    .get("iso_pct"),
                    "base_iso_err": res["baseline"]["iso"]["abs_err_pp"],
                    "exp_iso_err": res["experiment"]["iso"]["abs_err_pp"],
                    "base_jis_err": res["baseline"]["jis"]["abs_err_pp"],
                    "exp_jis_err": res["experiment"]["jis"]["abs_err_pp"],
                    "base_round_mae": res["baseline"]["morphology_mae"][
                        "roundness"],
                    "exp_round_mae": res["experiment"]["morphology_mae"][
                        "roundness"],
                    "base_area_mae": res["baseline"]["morphology_mae"]["area"],
                    "exp_area_mae": res["experiment"]["morphology_mae"]["area"],
                    "small_frac_base": res["small_particles"]["baseline"][
                        "frac_below_100px"],
                    "small_frac_exp": res["small_particles"]["experiment"][
                        "frac_below_100px"],
                }
                all_rows.append(row)
                if write_overlays and cfg["label"].endswith("default") \
                        and track == "A" and arrays.get("src") is not None:
                    _write_overlay(image_id, cfg["label"], track, arrays)
                for entry in res["per_split"]:
                    for ch in entry["children"]:
                        per_particle_rows.append({
                            "config": cfg["label"], "track": track,
                            "image_id": image_id,
                            "parent_pred_id": entry["parent_pred_id"],
                            "n_children": entry["n_children"],
                            "gt_id": ch["gt_id"], "iou": ch["iou"],
                            "area_ratio": entry["area_ratio"],
                            "area_conserved": entry["area_conserved"],
                            "child_roundness": ch["child_roundness"],
                            "gt_roundness": ch["gt_roundness"],
                            "roundness_err": ch["roundness_err"],
                            "area_err": ch["area_err"],
                            "feret_err": ch["feret_err"],
                            "circularity_err": ch["circularity_err"],
                            "solidity_err": ch["solidity_err"],
                        })
                print(f"  {image_id}: cand={res['candidates']} "
                      f"split={res['splits']} "
                      f"F1 {res['baseline']['detection']['f1']} -> "
                      f"{res['experiment']['detection']['f1']}  "
                      f"ISOerr {res['baseline']['iso']['abs_err_pp']} -> "
                      f"{res['experiment']['iso']['abs_err_pp']}")
            if cfg_rows:
                summary["images"].append({
                    "config": cfg["label"], "track": track,
                    "n_images": len(cfg_rows),
                    "mean_base_f1": _mean([r["baseline"]["detection"]["f1"]
                                           for r in cfg_rows]),
                    "mean_exp_f1": _mean([r["experiment"]["detection"]["f1"]
                                          for r in cfg_rows]),
                    "mean_base_iso_err": _mean([r["baseline"]["iso"][
                        "abs_err_pp"] for r in cfg_rows]),
                    "mean_exp_iso_err": _mean([r["experiment"]["iso"][
                        "abs_err_pp"] for r in cfg_rows]),
                    "mean_base_jis_err": _mean([r["baseline"]["jis"][
                        "abs_err_pp"] for r in cfg_rows]),
                    "mean_exp_jis_err": _mean([r["experiment"]["jis"][
                        "abs_err_pp"] for r in cfg_rows]),
                    "total_splits": sum(r["splits"] for r in cfg_rows),
                    "total_candidates": sum(r["candidates"]
                                            for r in cfg_rows),
                    "fp_delta": _mean([r["experiment"]["detection"]["fp"] -
                                       r["baseline"]["detection"]["fp"]
                                       for r in cfg_rows]),
                    "merge_delta": _mean([r["experiment"]["detection"][
                        "n_merge_groups"] -
                        r["baseline"]["detection"]["n_merge_groups"]
                        for r in cfg_rows]),
                    "over_split_rate": _over_split_rate(cfg_rows),
                    "area_conservation_violations": sum(
                        1 for r in cfg_rows for e in r["per_split"]
                        if not e["area_conserved"]),
                    "small_particle_frac_delta": _mean(
                        [r["small_particles"]["experiment"][
                            "frac_below_100px"] -
                         r["small_particles"]["baseline"][
                             "frac_below_100px"] for r in cfg_rows]),
                })
            summary["configs"].append(label)
            _persist_partial(summary, all_rows, per_particle_rows)
            print(f"  [checkpoint saved: {label}]")

    # ---- CSV outputs --------------------------------------------------------
    import csv
    if all_rows:
        with open(OUT_DIR / "per_case.csv", "w", newline="",
                  encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(all_rows[0].keys()))
            w.writeheader()
            w.writerows(all_rows)
    if per_particle_rows:
        with open(OUT_DIR / "per_particle.csv", "w", newline="",
                  encoding="utf-8") as fh:
            w = csv.DictWriter(fh,
                               fieldnames=list(per_particle_rows[0].keys()))
            w.writeheader()
            w.writerows(per_particle_rows)

    summary["aggregate"] = {
        s["config"] + "@" + s["track"]: s for s in summary["images"]}
    all_labels = {c["label"] for c in SWEEP}
    done = {f"{s.get('config')}@{s.get('track')}"
            for s in summary["images"]}
    summary["partial_run"] = not done >= (
        {f"{lbl}@A" for lbl in all_labels}
        | {f"{lbl}@B" for lbl in all_labels})
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nsummary -> {OUT_DIR / 'summary.json'}"
          f"  (partial_run={summary['partial_run']})")


def _load_rows(path, rerun):
    """CSV rows from a previous run whose config@track is not re-run here."""
    import csv
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows
            if f"{r.get('config')}@{r.get('track')}" not in rerun]


def _write_overlay(image_id, config, track, arrays):
    """9O before/after/GT overlay. Originals are never modified."""
    src = arrays["src"]
    if src.ndim == 2:
        src = cv2.cvtColor(src, cv2.COLOR_GRAY2BGR)
    base = src.copy()
    cv2.drawContours(base, arrays["base_contours"], -1, (255, 128, 0), 2)
    exp = src.copy()
    cv2.drawContours(exp, arrays["exp_contours"], -1, (0, 200, 0), 2)
    gtc = src.copy()
    for gm in arrays["gt_masks"]:
        cnts, _ = cv2.findContours(gm, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(gtc, cnts, -1, (0, 255, 255), 2)
    h = 28
    for img, txt, col in ((base, "BASELINE (production, unchanged)",
                           (255, 255, 255)),
                          (exp, "EXPERIMENT (offline splitter)",
                           (0, 255, 0)),
                          (gtc, "GT reference (provenance E)",
                           (0, 255, 255))):
        cv2.rectangle(img, (0, 0), (img.shape[1], h), (0, 0, 0), -1)
        cv2.putText(img, txt, (8, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    col, 1, cv2.LINE_AA)
    sep = np.full((6, src.shape[1], 3), 255, np.uint8)
    combo = np.vstack([base, sep, exp, sep, gtc])
    out = OUT_DIR / "overlays" / f"{image_id}_{config}_{track}.png"
    cv2.imwrite(str(out), combo)


def _persist_partial(summary, all_rows, per_particle_rows):
    """Checkpoint outputs after every config so a killed run keeps its
    completed configurations (the final full run rewrites these)."""
    import csv
    summary["partial_run"] = True
    if all_rows:
        with open(OUT_DIR / "per_case.csv", "w", newline="",
                  encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(all_rows[0].keys()))
            w.writeheader()
            w.writerows(all_rows)
    if per_particle_rows:
        with open(OUT_DIR / "per_particle.csv", "w", newline="",
                  encoding="utf-8") as fh:
            w = csv.DictWriter(fh,
                               fieldnames=list(per_particle_rows[0].keys()))
            w.writeheader()
            w.writerows(per_particle_rows)
    summary["aggregate"] = {
        s["config"] + "@" + s["track"]: s for s in summary["images"]}
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(float(np.mean(vals)), 4) if vals else None


def _over_split_rate(cfg_rows):
    """Fraction of split parents whose child count exceeds the number of
    GT particles they overlap (9H over-split evidence)."""
    tot, over = 0, 0
    for r in cfg_rows:
        for e in r["per_split"]:
            tot += 1
            gt_hit = {c["gt_id"] for c in e["children"] if c["gt_id"] is not
                      None}
            if len(gt_hit) < e["n_children"]:
                over += 1
    return round(over / tot, 4) if tot else None


if __name__ == "__main__":
    main()
