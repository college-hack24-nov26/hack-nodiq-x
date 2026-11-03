#!/usr/bin/env python3
"""Phase 2 cleanup diagnostic — WHERE do the extra detections come from?

Runs the exact bench paths (run_production + score_against_review) and, for
every carried human FP, prints the matching production contour's source tag
(frozen / recovered / merged / joined / blobfill / salvaged / split /
completed) plus its area. Then the min_grainsize sweep rows on panel_01 with
per-source counts.

Read-only investigation; prints, decides nothing, changes nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

import nodiq.services.accuracy_bench as bench  # noqa: E402
from nodiq.services.accuracy_bench import (  # noqa: E402
    REVIEW_LABELED_IMAGES, REVIEW_MATCH_IOU, run_production,
    score_against_review, _candidate_boxes, _contour_mask, _bbox_of_mask,
    _box_mask, _boxes_overlap, mask_iou)


def carried_fp_sources() -> None:
    print("=" * 72)
    print("TEST 1 evidence — carried human FPs by production source tag")
    print("=" * 72)
    total = carried = 0
    for name in REVIEW_LABELED_IMAGES:
        run = run_production(bench.INPUT_IMAGES / (name + ".png"))
        contours, shape = run["contours"], run["shape"]
        rows = run["rows"]
        probe = score_against_review(run["image_id"], contours, shape)
        if not probe.get("available"):
            print(f"{name}: no review labels")
            continue
        # recompute which candidates carried, but keep the CONTOUR too
        labeled = _candidate_boxes(run["image_id"])
        pred_masks = [_contour_mask(c, shape) for c in contours]
        pred_bboxes = [_bbox_of_mask(m) for m in pred_masks]
        img_total = img_carried = 0
        for cand in labeled:
            if cand["label"] != "false_positive":
                continue
            bm = _box_mask(cand["box"], shape)
            cb = _bbox_of_mask(bm)
            best, best_i = 0.0, None
            if cb is not None:
                for pi, pm in enumerate(pred_masks):
                    pb = pred_bboxes[pi]
                    if pb is None or not _boxes_overlap(cb, pb, pad=4):
                        continue
                    iou = mask_iou(bm, pm)
                    if iou > best:
                        best, best_i = iou, pi
            img_total += 1
            if best >= REVIEW_MATCH_IOU:
                img_carried += 1
                row = rows[best_i] if best_i is not None and best_i < len(rows) else {}
                print(f"  {name}: FP cand#{cand['candidate_id']} "
                      f"IoU={best:.2f} source={row.get('source')!r} "
                      f"area={row.get('area_px')} marumi={row.get('marumi')}")
        print(f"{name}: fp_total={img_total} carried={img_carried}")
        total += img_total
        carried += img_carried
    print(f"TOTAL fp_total={total} carried={carried} (test asserts <= 6)")


def sweep_sources() -> None:
    print()
    print("=" * 72)
    print("TEST 2 evidence — min_grainsize sweep on panel_01 by source tag")
    print("=" * 72)
    import nodularity as legacy  # noqa: E402  (frozen, patched in-process)
    from nodiq.pipelines.nodularity_pipeline import analyze_image

    path = bench.INPUT_IMAGES / "panel_01.png"
    baseline = legacy.min_grainsize
    try:
        for factor in (0.5, 1.0, 1.5):
            legacy.min_grainsize = baseline * factor
            res = analyze_image(str(path), with_accuracy=False,
                                stem="panel_01")
            srcs = {}
            for r in res["rows"]:
                srcs[r["source"]] = srcs.get(r["source"], 0) + 1
            print(f"factor={factor}: count={res['count']} iso={res['iso_pct']}"
                  f" jis={res['jis_pct']} sources={srcs}")
    finally:
        legacy.min_grainsize = baseline


if __name__ == "__main__":
    carried_fp_sources()
    sweep_sources()
