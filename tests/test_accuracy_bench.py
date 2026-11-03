#!/usr/bin/env python3
"""Phase 6 accuracy-benchmark regression tests.

Locks down the evaluation FRAMEWORK (not any claimed accuracy):

  * ground-truth source classification stays honest (A unavailable,
    model-generated labels never treated as GT),
  * the GT schema nulls unknown fields instead of estimating them,
  * expert YOLO ground truth, when added, is loaded and matched (IoU),
  * instance matching produces the exact TP/FP/FN on controlled geometry,
  * the synthetic known-geometry cases score against analytic truth,
  * the human-review probe reports the measured FP/TP carryover,
  * sensitivity sweeps restore patched production constants exactly.

These tests verify implementation consistency; they do NOT claim real-world
nodularity accuracy (no independent expert ground truth exists in-repo).
"""
import csv
import math
import sys
from pathlib import Path

import numpy as np
import pytest


cv2 = pytest.importorskip("cv2")

from nodiq.services import accuracy_bench as bench  # noqa: E402


# ------------------------------------------------- source classification ----
def test_expert_ground_truth_is_reported_unavailable():
    """evaluation/ground_truth/ contains only README.txt -> category A must
    be unavailable.  If real expert annotations are ever added, this test
    flags that the honest classification needs updating (intentional tripwire)."""
    sources = bench.classify_data_sources()
    if sources["A_independent_expert"]["available"]:
        pytest.fail("expert YOLO ground truth now exists in "
                    "evaluation/ground_truth/ — update the benchmark to "
                    "score real accuracy (Phase 6 CASE A/B path)")
    assert sources["D_model_generated"]["usable_as_ground_truth"] is False


def test_review_labels_are_the_only_human_annotations():
    sources = bench.classify_data_sources()
    b = sources["B_independently_annotated"]
    assert b["labels"]["true_nodule"] == 5
    assert b["labels"]["false_positive"] == 120
    assert b["note"], "limitation must be documented, not hidden"


def test_ground_truth_schema_nulls_unknown_fields(tmp_path):
    rec = bench.ground_truth_record("panel_01",
                                    bench.INPUT_IMAGES / "panel_01.png",
                                    source="E", annotation_type="none")
    assert rec["width"] == 277 and rec["height"] == 277  # real, from file
    assert rec["pixel_scale_um_per_px"] is None          # never guessed
    assert rec["ground_truth_nodule_count"] is None
    assert rec["ground_truth_nodularity_pct"] is None
    assert rec["ground_truth_masks"] is None
    assert rec["source"] == "E"


# ----------------------------------------------------- YOLO load + match ----
def _write_yolo(tmp_path, lines, stem="probe"):
    gt = tmp_path / "gt"
    gt.mkdir()
    (gt / (stem + ".txt")).write_text("\n".join(lines), encoding="utf-8")
    return gt


def test_yolo_boxes_are_loaded_when_present(tmp_path, monkeypatch):
    gt = _write_yolo(tmp_path, ["0 0.5 0.5 0.2 0.2",
                                "0 0.1 0.9 0.1 0.1"])
    monkeypatch.setattr(bench, "GT_DIR", gt)
    boxes = bench._load_yolo_boxes("probe")
    assert boxes == [{"cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2},
                     {"cx": 0.1, "cy": 0.9, "w": 0.1, "h": 0.1}]


def test_yolo_only_class0_loaded(tmp_path, monkeypatch):
    gt = _write_yolo(tmp_path, ["0 0.5 0.5 0.2 0.2",
                                "1 0.1 0.1 0.1 0.1"])
    monkeypatch.setattr(bench, "GT_DIR", gt)
    boxes = bench._load_yolo_boxes("probe")
    assert len(boxes) == 1


def test_instance_matching_exact_tp_fp_fn():
    """Two GT circles, one prediction overlapping GT1 (IoU~1), one spurious
    contour -> at IoU 0.5: TP=1 FP=1 FN=1; the matched pair's area error is
    computed from the same masks used for IoU."""
    shape = (400, 400)
    gt1 = np.zeros(shape, np.uint8)
    cv2.circle(gt1, (120, 120), 50, 255, -1)
    gt2 = np.zeros(shape, np.uint8)
    cv2.circle(gt2, (320, 320), 50, 255, -1)
    pred_ok = np.zeros(shape, np.uint8)
    cv2.circle(pred_ok, (125, 118), 48, 255, -1)      # matches gt1
    pred_spurious = np.zeros(shape, np.uint8)
    cv2.rectangle(pred_spurious, (0, 0), (15, 15), 255, -1)
    m = bench.match_instances([{"mask": gt1}, {"mask": gt2}],
                              [pred_ok, pred_spurious], shape,
                              iou_threshold=0.50)
    assert m["tp"] == 1 and m["fp"] == 1 and m["fn"] == 1
    assert 0.85 < m["mean_iou"] <= 1.0
    pair = m["area_pairs"][0]
    assert pair["gt_area_px"] > 0
    assert pair["rel_area_error"] < 0.2               # near-perfect match
    assert m["precision"] == 0.5 and m["recall"] == 0.5


def test_instance_matching_iou_threshold_075_stricter():
    shape = (400, 400)
    gt = np.zeros(shape, np.uint8)
    cv2.circle(gt, (200, 200), 50, 255, -1)
    shifted = np.zeros(shape, np.uint8)
    cv2.circle(shifted, (225, 200), 50, 255, -1)      # ~55% overlap
    loose = bench.match_instances([{"mask": gt}], [shifted], shape,
                                  iou_threshold=0.50)
    strict = bench.match_instances([{"mask": gt}], [shifted], shape,
                                   iou_threshold=0.75)
    assert loose["tp"] == 1
    assert strict["tp"] == 0 and strict["fn"] == 1 and strict["fp"] == 1


# ------------------------------------------- synthetic analytic benchmark ----
def test_synthetic_clean_round_scores_perfect():
    r = bench.evaluate_synthetic_case("clean_round")
    assert r["matching"]["tp"] == 8
    assert r["matching"]["fp"] == 0 and r["matching"]["fn"] == 0
    assert r["pred"]["iso_pct"] == pytest.approx(r["gt"]["iso_pct"], abs=0.5)
    assert r["pred"]["jis_pct"] == pytest.approx(r["gt"]["jis_pct"], abs=0.5)


def test_synthetic_mixed_round_irregular_matches_hand_calculation():
    """4 circles r=50 + 4 ellipses 70x25 (marumi=b/a=25/70):
    GT ISO = (4*pi*2500) / (4*pi*2500 + 4*pi*1750) * 100 = 2500/4250*100."""
    r = bench.evaluate_synthetic_case("mixed_round_irregular")
    expected_iso = 2500.0 / 4250.0 * 100.0
    assert r["gt"]["iso_pct"] == pytest.approx(expected_iso, abs=0.01)
    assert r["pred"]["iso_pct"] == pytest.approx(expected_iso, abs=1.0)
    assert r["pred"]["count"] == 8
    # JIS: 4 class-5 + 4 class-2 -> (0.3*4 + 1.0*4) / 8 * 100 = 65
    assert r["gt"]["jis_pct"] == pytest.approx(65.0, abs=0.01)


def test_synthetic_touching_pair_documents_merge_mode():
    """KNOWN FAILURE MODE (documented, not fixed): two overlapping r=40
    circles merge into one elongated particle (marumi ~0.57 -> irregular).
    This is a real segmentation-merge behavior the benchmark must expose."""
    r = bench.evaluate_synthetic_case("touching_pair")
    assert r["pred"]["count"] == 1
    assert r["matching"]["fn"] == 1
    assert r["iso_abs_error_pp"] > 50.0


def test_synthetic_size_gradient_finds_majority_of_sizes():
    r = bench.evaluate_synthetic_case("size_gradient")
    assert r["pred"]["count"] >= 4          # r=8 may drop; larger must pass
    assert r["matching"]["tp"] >= 4
    assert r["pred"]["iso_pct"] == pytest.approx(100.0, abs=0.5)


def test_synthetic_border_case_separates_border_particle():
    r = bench.evaluate_synthetic_case("border_case")
    assert r["pred"]["border_count"] == 1
    # in-frame excludes the border particle from both ISO terms -> ISO stays
    # 100 for the three interior circles, headline may differ
    assert r["pred"]["iso_inframe_pct"] == pytest.approx(100.0, abs=0.5)


# ------------------------------------------------------- review FP probe ----
def test_review_probe_carries_no_tiny_tp_but_eliminates_most_fp():
    """Measured behavior on the 4 human-reviewed images: the 5 small human
    TPs are excluded upstream (area/validation chain), while >=95% of the 120
    human FPs are eliminated vs the legacy validator."""
    probes = []
    for name in bench.REVIEW_LABELED_IMAGES:
        run = bench.run_production(bench.INPUT_IMAGES / (name + ".png"))
        probes.append(bench.score_against_review(run["image_id"],
                                                 run["contours"],
                                                 run["shape"]))
    fp_total = sum(p["human_fp_total"] for p in probes)
    fp_carried = sum(p["human_fp_still_produced"] for p in probes)
    assert fp_total == 120
    assert fp_carried <= 6                  # >=95% eliminated
    tp_detected = sum(p["human_tp_detected"] for p in probes)
    assert tp_detected == 0                 # upstream exclusion, documented


# --------------------------------------------------------------- sweeps -----
def test_sensitivity_sweep_restores_production_constants():
    import nodularity as legacy
    before = legacy.min_grainsize
    bench.sensitivity_sweep([bench.INPUT_IMAGES / "panel_01.png"],
                            factors=(0.5, 2.0))
    assert legacy.min_grainsize == before


def test_area_floor_sweep_restores_production_constants():
    import nodiq.pipelines.analyze_with_recovery as rec
    before = rec.AREA_FLOOR_RATIO
    bench.area_floor_sweep([bench.INPUT_IMAGES / "panel_01.png"],
                           ratios=(0.5, 1.0))
    assert rec.AREA_FLOOR_RATIO == before


def test_min_grainsize_sweep_measured_insensitive_on_reference_images():
    """Measured result (locked): 0.5x..1.5x min_grainsize changes neither
    count nor ISO on the two reference images — selectivity lives in the
    adaptive validator + area floor, NOT in this knob.  If this ever
    changes, the detector's parameter story changed and the docs must too."""
    _nod_main = bench.PROJECT_ROOT / "third_party" / "Nodularity"
    rows = bench.sensitivity_sweep(
        [bench.INPUT_IMAGES / "panel_01.png",
         _nod_main /
         "sample1(min_grainsize=0.007).jpg"],
        factors=(0.5, 1.0, 1.5))
    baseline = [r for r in rows if r["factor"] == 1.0]
    for r in rows:
        base = next(b for b in baseline if b["image"] == r["image"])
        assert r["count"] == base["count"], r


def test_summary_does_not_claim_accuracy_without_ground_truth():
    summary = bench.build_summary()
    assert "GROUND_TRUTH_UNAVAILABLE" in summary["ground_truth_status"]
    assert summary["detection"]["precision"] is None
    assert summary["detection"]["recall"] is None
    assert summary["nodularity"]["mae_pp"] is None
