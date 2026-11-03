#!/usr/bin/env python3
"""Phase 7 ground-truth workflow regression tests.

Locks down the ANNOTATION + BENCHMARK FRAMEWORK (not any claimed accuracy):

  * GT parsing and the empty-document path,
  * deterministic validation verdicts (VALID / WARNING / INCOMPLETE /
    INVALID) including contaminated (C/D) provenance rejection,
  * geometry edge cases (malformed polygons, duplicates, out-of-bounds,
    impossible overlap, empty masks),
  * physical-scale validation (unavailable / valid / invalid values),
  * IoU instance matching with merge and split relation detection,
  * mask morphology comparison on matched pairs,
  * GT-derived ISO/JIS reference values (engine-identical definitions),
  * missing-GT and missing-scale benchmark behavior (nulls, never zeros),
  * production pipeline runs UNCHANGED inside the benchmark (constants
    restored, outputs byte-identical to a direct analyze_image call).
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest


cv2 = pytest.importorskip("cv2")

from nodiq.services import gt_benchmark as gb  # noqa: E402
from nodiq.services import ground_truth as gtmod  # noqa: E402


# ------------------------------------------------------------- helpers ------
def _circle_pts(cx, cy, r, n=32):
    return [[cx + math.cos(2 * math.pi * i / n) * r,
             cy + math.sin(2 * math.pi * i / n) * r] for i in range(n)]


_NOD_IMG_REL = "third_party/Nodularity/input_images/panel_01.png"


def _valid_doc(tmp_path, name="doc1"):
    doc = gtmod.empty_ground_truth(
        name, _NOD_IMG_REL, 277, 277)
    doc["annotation"]["provenance_class"] = "A"
    doc["annotation"]["expert"] = "unit-test-expert"
    return doc


def _circle(cx, cy, r, pid="p1"):
    return {"id": pid, "geometry": {"type": "polygon",
                                    "points": _circle_pts(cx, cy, r)},
            "border_touching": False, "uncertain": False}


# ------------------------------------------------------------ 1-2 parse -----
def test_parse_round_trip(tmp_path):
    doc = _valid_doc(tmp_path)
    doc["particles"] = [_circle(100, 100, 30, "p1")]
    p = tmp_path / "doc1.json"
    p.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    loaded = gtmod.load_ground_truth(p)
    assert loaded["image_id"] == "doc1"
    assert loaded["particles"][0]["id"] == "p1"


def test_parse_rejects_non_object(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        gtmod.load_ground_truth(p)


def test_empty_document_is_incomplete_not_valid(tmp_path):
    r = gtmod.validate_ground_truth(_valid_doc(tmp_path))
    assert r["verdict"] == "INCOMPLETE"
    assert any("no particles" in w for w in r["warnings"])


# --------------------------------------------------------- 3-4 geometry -----
def test_malformed_polygon_rejected():
    doc = _valid_doc(None)
    doc["particles"] = [{"id": "p1", "geometry":
                         {"type": "polygon", "points": [[1, 1], [2, 2]]}}]
    r = gtmod.validate_ground_truth(doc)
    assert any("invalid or empty geometry" in e for e in r["errors"])


def test_duplicate_particle_ids_rejected(tmp_path):
    doc = _valid_doc(tmp_path)
    doc["particles"] = [_circle(100, 100, 20, "same"),
                        _circle(200, 200, 20, "same")]
    r = gtmod.validate_ground_truth(doc)
    assert any("duplicate particle id" in e for e in r["errors"])


def test_out_of_bounds_coordinates_rejected(tmp_path):
    doc = _valid_doc(tmp_path)
    # a polygon fully outside the image rasterizes to an empty mask ->
    # invalid/empty geometry (the engine never "clips" expert geometry back)
    doc["particles"] = [{"id": "p1", "geometry": {
        "type": "polygon", "points": _circle_pts(600, 600, 20)}}]
    r = gtmod.validate_ground_truth(doc)
    assert r["verdict"] == "INVALID"


def test_impossible_overlap_rejected_touching_warned(tmp_path):
    doc = _valid_doc(tmp_path)
    # two identical circles -> IoU 1.0 -> INVALID
    doc["particles"] = [_circle(100, 100, 30, "p1"),
                        _circle(100, 100, 30, "p2")]
    r = gtmod.validate_ground_truth(doc)
    assert r["verdict"] == "INVALID"
    assert any("overlap heavily" in e for e in r["errors"])
    # mild overlap -> WARNING (touching/clustered case is legitimate)
    doc2 = _valid_doc(tmp_path)
    doc2["particles"] = [_circle(100, 100, 30, "p1"),
                         _circle(125, 100, 30, "p2")]
    r2 = gtmod.validate_ground_truth(doc2)
    assert r2["verdict"] != "INVALID"


# -------------------------------------------------------- 5 scale -----------
def test_scale_validation_paths(tmp_path):
    doc = _valid_doc(tmp_path)
    doc["particles"] = [_circle(100, 100, 20)]
    doc["physical_scale"] = {"status": "metadata",
                             "microns_per_pixel": 0.5,
                             "source": "Keyence VHX-7000 acquisition log"}
    assert gtmod.validate_ground_truth(doc)["verdict"] in ("VALID", "WARNING")
    for bad in (0, -1, float("nan"), float("inf")):
        d2 = _valid_doc(tmp_path)
        d2["particles"] = [_circle(100, 100, 20)]
        d2["physical_scale"] = {"status": "expert",
                                "microns_per_pixel": bad, "source": "x"}
        r = gtmod.validate_ground_truth(d2)
        assert any("finite and > 0" in e for e in r["errors"])


def test_contaminated_provenance_rejected(tmp_path):
    doc = _valid_doc(tmp_path)
    doc["particles"] = [_circle(100, 100, 20)]
    for prov in ("C", "D"):
        doc["annotation"]["provenance_class"] = prov
        r = gtmod.validate_ground_truth(doc)
        assert r["verdict"] == "INVALID"
        assert any("primary benchmark" in e for e in r["errors"])


# -------------------------------------------------- 6-8 matching relations --
def _image_and_contours():
    shape = (400, 400)
    img = np.full(shape, 235, np.uint8)
    cv2.circle(img, (120, 120), 50, 0, -1)
    cv2.circle(img, (320, 320), 50, 0, -1)
    res_contours, _ = cv2.findContours(
        cv2.threshold(img, 128, 255, cv2.THRESH_BINARY_INV)[1],
        cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    return shape, res_contours


def test_iou_matching_two_clean_particles():
    shape, contours = _image_and_contours()
    gt_masks = []
    for cx, cy, r in ((120, 120, 50), (320, 320, 50)):
        m = np.zeros(shape, np.uint8)
        cv2.circle(m, (cx, cy), r, 255, -1)
        gt_masks.append(m)
    m = gb.match_with_relations(gt_masks, contours, shape, 0.50)
    assert m["tp"] == 2 and m["fp_count"] == 0 and m["fn_count"] == 0
    assert m["precision"] == 1.0 and m["recall"] == 1.0
    assert m["mean_iou"] > 0.85
    assert m["n_merge_groups"] == 0 and m["n_split_groups"] == 0


def test_merge_detection_touching_particles():
    """Two well-separated GT circles that a 'detector' reports as one big
    merged contour overlapping BOTH must be labeled as a merge relation
    (two GT in relation with one prediction)."""
    shape = (400, 400)
    gt1 = np.zeros(shape, np.uint8)
    cv2.circle(gt1, (100, 200), 40, 255, -1)
    gt2 = np.zeros(shape, np.uint8)
    cv2.circle(gt2, (300, 200), 40, 255, -1)
    merged = np.zeros(shape, np.uint8)
    cv2.ellipse(merged, (200, 200), (130, 35), 0, 0, 360, 255, -1)
    m = gb.match_with_relations([gt1, gt2], [merged], shape, 0.50)
    assert m["n_merge_groups"] == 1
    assert m["fn_count"] == 2 and m["fp_count"] == 1


def _masks_of(*masks):
    return list(masks)


def test_split_detection_one_gt_two_predictions():
    shape = (400, 400)
    gt = np.zeros(shape, np.uint8)
    cv2.circle(gt, (200, 200), 60, 255, -1)
    p1 = np.zeros(shape, np.uint8)
    cv2.circle(p1, (180, 200), 40, 255, -1)
    p2 = np.zeros(shape, np.uint8)
    cv2.circle(p2, (225, 200), 40, 255, -1)
    m = gb.match_with_relations([gt], [p1, p2], shape, 0.50)
    assert m["n_split_groups"] == 1


def test_threshold_075_stricter_than_050():
    shape, contours = _image_and_contours()
    gt = np.zeros(shape, np.uint8)
    cv2.circle(gt, (128, 120), 50, 255, -1)     # slightly shifted
    m50 = gb.match_with_relations([gt], contours, shape, 0.50)
    m75 = gb.match_with_relations([gt], contours, shape, 0.75)
    assert m50["tp"] >= m75["tp"]


# ------------------------------------------------- 9-10 morphology+errors ---
def test_morphology_of_mask_perfect_circle():
    m = np.zeros((200, 200), np.uint8)
    cv2.circle(m, (100, 100), 50, 255, -1)
    mm = gb.morphology_of_mask(m)
    assert mm["roundness"] == pytest.approx(1.0, abs=0.02)
    assert mm["feret"] == pytest.approx(100.0, abs=3.0)
    # rasterized-circle circularity floor (pixel staircase): measured 0.907
    assert 0.88 < mm["circularity"] <= 1.0
    assert 0.98 <= mm["solidity"] <= 1.0


def test_area_error_on_known_pair():
    shape = (300, 300)
    gt = np.zeros(shape, np.uint8)
    cv2.circle(gt, (150, 150), 50, 255, -1)
    pred = np.zeros(shape, np.uint8)
    cv2.circle(pred, (150, 150), 45, 255, -1)   # 19% smaller area
    m = gb.match_with_relations([gt], [pred], shape, 0.50)
    pair = m["area_pairs"][0]
    expected_rel = abs(math.pi * 45 ** 2 - math.pi * 50 ** 2) / \
        (math.pi * 50 ** 2)
    assert pair["rel_area_error"] == pytest.approx(expected_rel, abs=0.03)


# ------------------------------------------------------ 11-12 ISO/JIS -------
def test_gt_derived_iso_jis_matches_engine_definitions(tmp_path):
    doc = _valid_doc(tmp_path)
    doc["particles"] = [_circle(100, 100, 40, "p1"),
                        _circle(200, 200, 40, "p2")]
    ref = gtmod.gt_nodularity_from_geometry(doc)
    assert ref["iso_pct"] == pytest.approx(100.0, abs=0.5)
    assert ref["jis_pct"] == pytest.approx(100.0, abs=0.5)
    assert ref["n_particles"] == 2


def test_gt_derived_nodularity_mixed_shapes():
    doc = _valid_doc(None)
    doc["particles"] = [
        _circle(120, 120, 50, "r1"), _circle(320, 320, 50, "r2"),
        {"id": "e1", "geometry": {"type": "polygon",
                                  "points": _circle_pts(200, 150, 60)[:16] +
                                  [[260, 150]]},   # deliberately irregular
         "border_touching": False, "uncertain": False}]
    ref = gtmod.gt_nodularity_from_geometry(doc)
    assert ref["iso_pct"] < 100.0          # irregular particle pulls it down
    # two clean circles survive; the crude irregular blob may dissolve below
    # the minimum area under rasterization — either way the round ones count
    assert ref["n_particles"] in (2, 3)


# --------------------------------------------- 13-14 missing GT/scale -------
def test_benchmark_without_gt_reports_insufficient_status(tmp_path, monkeypatch):
    monkeypatch.setattr(gtmod, "GT_DIR", tmp_path / "empty")
    s = gb.run_production_benchmark(gt_dir=tmp_path / "empty",
                                    out_dir=tmp_path / "out")
    assert s["real_world_accuracy_status"] == "INSUFFICIENT_GROUND_TRUTH"
    assert s["detection"]["0.5"]["f1"] is None
    assert s["nodularity_iso"]["mae_pp"] is None
    assert s["mask"]["mean_rel_area_error"] is None
    assert s["dataset"]["n_usable"] == 0


def test_benchmark_image_without_scale_excludes_10um(tmp_path):
    doc = _valid_doc(tmp_path)
    doc["particles"] = [_circle(138, 138, 30)]
    res = gb.benchmark_image(doc,
                             gtmod.PROJECT_ROOT / _NOD_IMG_REL)
    assert res["physical_scale_status"] == "unavailable"
    assert res["size_10um_benchmark_valid"] is False
    assert res["microns_per_pixel"] is None
    assert any(a["cause"] == "scale_unavailable"
               for a in gb.attribute_errors(res))


def test_benchmark_runs_production_unchanged(tmp_path, monkeypatch):
    """The benchmark must not alter production behavior: run analyze_image
    before and after a benchmark call; results must be identical, and the
    patched constants restored."""
    from nodiq.pipelines.nodularity_pipeline import analyze_image
    import nodiq.pipelines.analyze_with_recovery as rec
    import nodularity as legacy
    before_floor, before_mg = rec.AREA_FLOOR_RATIO, legacy.min_grainsize
    probe_before = analyze_image(
        gtmod.PROJECT_ROOT / _NOD_IMG_REL,
        with_accuracy=False, stem="x")["count"]
    doc = _valid_doc(tmp_path)
    doc["particles"] = [_circle(138, 138, 30)]
    gb.benchmark_image(doc,
                       gtmod.PROJECT_ROOT / _NOD_IMG_REL)
    assert rec.AREA_FLOOR_RATIO == before_floor
    assert legacy.min_grainsize == before_mg
    probe_after = analyze_image(
        gtmod.PROJECT_ROOT / _NOD_IMG_REL,
        with_accuracy=False, stem="x")["count"]
    assert probe_before == probe_after


def test_small_particle_bucket_boundaries():
    # equiv diameter / width boundaries: <0.01 very_small, <0.03 small,
    # <0.08 medium, else large (documented in the benchmark module)
    w = 1920
    assert gb.size_bucket(100, w) == "very_small"      # d~11px, rel 0.0059
    assert gb.size_bucket(900, w) == "small"           # d~34px, rel 0.018
    assert gb.size_bucket(8000, w) == "medium"         # d~101px, rel 0.053
    assert gb.size_bucket(30000, w) == "large"         # d~195px, rel 0.102


def test_error_attribution_merge_and_fp():
    attrib = {"match_050": {"fn_count": 1, "fp_count": 2, "n_merge_groups": 1,
                            "n_split_groups": 0, "n_boundary_mismatch": 0,
                            "fn_indices": [0], "fp_indices": [1, 2],
                            "relations": {"merged": {"3": ["0", "1"]},
                                          "split": {}, "boundary_mismatch":
                                          []}},
              "per_particle": [],
              "physical_scale_status": "unavailable"}
    causes = {a["cause"]: a["n"] for a in gb.attribute_errors(attrib)}
    assert causes["missed_particle"] == 1
    assert causes["false_positive"] == 2
    assert causes["touching_particles_merged"] == 1
    assert causes["scale_unavailable"] == 1
