#!/usr/bin/env python3
"""Calibration-aware ISO 945-4 10 um particle-size filtering (Phase 11+).

Deterministic tests for: conversion validation, the <10 um rule (exactly
10.0 stays included), feret um exposure, ISO size-qualified calculation,
border+size interaction, invalid-calibration rejection, backward
compatibility, persistence, report methodology text and Copilot context.
"""
import json
import math
import sys
import time
from pathlib import Path

import pytest


from nodiq.services.calibration import (Calibration, ISO_MIN_FERET_UM,
                                  feret_size_status, make_calibration,
                                  manual_calibrate, size_filter_metadata,
                                  validate_um_per_px)
from nodiq.services.context import build_contract, save_full_analysis
import nodiq.reports.report_builder as rb

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


# --------------------------------------------------------------- TEST 1 ----
def test_pixel_to_micron_conversion_exact():
    cal = make_calibration(0.1, source="manual")
    assert cal.available
    assert cal.microns_per_pixel == pytest.approx(0.1)
    assert 100 * cal.microns_per_pixel == pytest.approx(10.0)


# ---------------------------------------------------------- TESTS 2,3,4 ----
def test_size_rule_threshold_boundaries():
    # strictly-below excludes; exactly-at and above include
    assert feret_size_status(99.9, 0.1) == "excluded_below_10um"   # 9.99 um
    assert feret_size_status(100.0, 0.1) == "included"             # 10.0 um
    assert feret_size_status(100.1, 0.1) == "included"             # 10.01 um


def test_threshold_is_10um_strictly_less_than():
    assert ISO_MIN_FERET_UM == 10.0


# --------------------------------------------------------------- TEST 5 ----
def test_no_calibration_not_evaluable_no_fabrication():
    assert feret_size_status(500.0, None) == "not_evaluable"
    assert feret_size_status(500.0, 0.0) == "not_evaluable"
    assert feret_size_status(None, 0.1) == "not_evaluable"
    meta = size_filter_metadata(None, 0, 0)
    assert meta["available"] is False and meta["applied"] is False
    assert meta["reason"] == "Physical calibration unavailable"
    assert meta["excluded_count"] is None


# --------------------------------------------------------------- TEST 6 ----
def _synthetic(mixed_sizes=True):
    """White 2000x2000 canvas, well-separated interior particles:
    two big circles r=80 (round), one ellipse 90x30 (irregular) and —
    when mixed_sizes — one small circle r=20 (Feret ~38 px, round).
    With a 0.1 um/px TEST calibration the small circle is the only
    below-10 um particle."""
    img = np.full((2000, 2000), 255, np.uint8)
    cv2.circle(img, (400, 400), 80, 0, -1)
    cv2.ellipse(img, (1200, 900), (90, 30), 0, 0, 360, 0, -1)
    cv2.circle(img, (700, 1600), 80, 0, -1)
    if mixed_sizes:
        cv2.circle(img, (1600, 1600), 20, 0, -1)
    return img


@pytest.fixture(scope="module")
def engine():
    from nodiq.pipelines.nodularity_pipeline import analyze_image, apply_size_filter_and_iso
    res = analyze_image(_synthetic())
    apply_size_filter_and_iso(res, None)          # uncalibrated first
    return res


def test_iso_denominator_excludes_sub10um_particle():
    """With a TEST calibration of 0.1 um/px the small particle (Feret
    16 px = 1.6 um) must contribute to NEITHER numerator NOR denominator,
    while the three 16 um particles qualify."""
    from nodiq.pipelines.nodularity_pipeline import analyze_image, apply_size_filter_and_iso
    res = analyze_image(_synthetic())
    sq = apply_size_filter_and_iso(res, 0.1)

    small = next(r for r in res["rows"] if r["feret_diameter_px"] < 50)
    assert small["size_filter_status"] == "excluded_below_10um"
    assert small["feret_diameter_um"] == pytest.approx(3.84, abs=0.1)
    assert sum(1 for r in res["rows"]
               if r["size_filter_status"] == "included") == 3
    assert res["size_filter"]["applied"] is True
    assert res["size_filter"]["excluded_count"] == 1
    assert res["size_filter"]["included_count"] == 3

    # excluded particle's area is in neither ISO term: the size-qualified
    # value is the area ratio over the three qualifying particles only
    a_round = sum(r["area_px"] for r in res["rows"]
                  if r["size_filter_status"] == "included"
                  and r["iso_class"] == "V/VI")
    a_all = sum(r["area_px"] for r in res["rows"]
                if r["size_filter_status"] == "included")
    assert sq == pytest.approx(a_round / a_all * 100, abs=0.01)
    # and the filter demonstrably changed the composition vs the unfiltered
    # headline value (the tiny ROUND particle was helping the average)
    assert res["iso_pct"] != res["iso_size_qualified_pct"]


# --------------------------------------------------------------- TEST 7 ----
def test_border_and_size_interaction_independent():
    """border particle + below-10um particle + valid in-frame particle are
    handled independently: only the qualifying non-border particle counts
    toward the size-qualified ISO value."""
    from nodiq.pipelines.nodularity_pipeline import analyze_image, apply_size_filter_and_iso
    img = np.full((2000, 2000), 255, np.uint8)
    cv2.circle(img, (5, 1000), 80, 0, -1)      # border-clipped, large
    cv2.circle(img, (1600, 1600), 20, 0, -1)   # small, interior
    cv2.circle(img, (400, 400), 80, 0, -1)     # large, interior
    res = analyze_image(img)
    sq = apply_size_filter_and_iso(res, 0.1)   # TEST calibration

    border_row = next(r for r in res["rows"] if r["touches_border"])
    small_row = next(r for r in res["rows"]
                     if r["feret_diameter_px"] < 50)
    inside_row = next(r for r in res["rows"]
                      if not r["touches_border"]
                      and r["feret_diameter_px"] >= 50)
    assert border_row["size_filter_status"] == "included"   # 16 um
    assert small_row["size_filter_status"] == "excluded_below_10um"
    assert inside_row["size_filter_status"] == "included"

    # numerator/denominator: only the interior qualifying particle
    assert sq == pytest.approx(100.0)
    assert res["size_filter"]["included_count"] == 2   # border + inside
    assert res["size_filter"]["excluded_count"] == 1


# --------------------------------------------------------------- TEST 8 ----
def test_invalid_calibration_values_rejected():
    for bad in (0, -1, -0.5, float("nan"), float("inf"),
                float("-inf"), "abc", {}, []):
        assert validate_um_per_px(bad) is None, bad
        cal = make_calibration(bad)
        assert not cal.available
    assert validate_um_per_px(None) is None
    assert validate_um_per_px("0.07") == pytest.approx(0.07)  # numeric str ok


def test_manual_calibrate_bar_still_works():
    cal = manual_calibrate(bar_length_px=215, bar_length_um=100)
    assert cal.available and cal.um_per_px == pytest.approx(100 / 215)


# --------------------------------------------------------------- TEST 9 ----
def test_backward_compatible_uncalibrated_output(engine):
    """Uncalibrated analysis: legacy fields unchanged, new fields present
    with explicit not-evaluable metadata."""
    for legacy in ("iso_pct", "iso_inframe_pct", "jis_pct", "count", "rows"):
        assert legacy in engine
    assert engine["iso_size_qualified_pct"] is None
    assert engine["size_filter"]["applied"] is False
    assert engine["size_filter"]["reason"] == "Physical calibration unavailable"
    assert all(r["feret_diameter_um"] is None for r in engine["rows"])
    assert all(r["size_filter_status"] == "not_evaluable"
               for r in engine["rows"])
    # feret_diameter_px is always measured (it is half the roundness basis)
    assert all(r["feret_diameter_px"] > 0 for r in engine["rows"])


def test_feret_matches_roundness_basis(engine):
    """feret_diameter_px must be the SAME l_m used by eta = 4A/(pi l_m^2)."""
    for row in engine["rows"]:
        expected = (4 * row["area_px"]
                    / (math.pi * row["feret_diameter_px"] ** 2))
        assert row["roundness"] == pytest.approx(expected, abs=2e-3)


# -------------------------------------------------------------- TEST 10 ----
def test_persistence_roundtrip_preserves_calibration_metadata(api_tmp):
    """A calibrated analysis survives storage/retrieval with all filter
    metadata intact (JSON full-store + Copilot contract)."""
    payload = {
        "nodule_count": 2, "iso_nodularity_pct": 90.0,
        "iso_nodularity_inframe_pct": 90.0,
        "iso_size_qualified_pct": 100.0,
        "jis_nodularity_pct": 80.0,
        "class_counts": {"round_V_VI": 2, "irregular": 0},
        "border_touching": 0,
        "nodules": [
            {"nodule_id": 1, "area_px": 20000.0, "roundness": 0.98,
             "iso_class": "V/VI", "jis_bucket": 5,
             "feret_diameter_px": 160.0, "feret_diameter_um": 16.0,
             "size_filter_status": "included"},
            {"nodule_id": 2, "area_px": 200.0, "roundness": 0.95,
             "iso_class": "V/VI", "jis_bucket": 5,
             "feret_diameter_px": 16.0, "feret_diameter_um": 1.6,
             "size_filter_status": "excluded_below_10um"},
        ],
        "calibration": {"available": True, "um_per_px": 0.1,
                        "microns_per_pixel": 0.1, "source": "manual",
                        "bar_length_um": None, "bar_length_px": None,
                        "notes": "test calibration"},
        "size_filter": {"available": True, "threshold_um": 10.0,
                        "applied": True, "excluded_count": 1,
                        "included_count": 1, "reason": None},
        "warnings": [], "filename": "calibrated.png",
        "source_width": 2000, "source_height": 2000,
    }
    save_full_analysis("ANL-CAL-TEST", payload)
    loaded = json.loads(
        (Path(api_tmp) / "analyses_full" / "ANL-CAL-TEST.json")
        .read_text(encoding="utf-8"))
    assert loaded["calibration"]["available"] is True
    assert loaded["calibration"]["microns_per_pixel"] == pytest.approx(0.1)
    assert loaded["size_filter"]["applied"] is True
    assert loaded["iso_size_qualified_pct"] == 100.0
    assert loaded["nodules"][1]["size_filter_status"] == "excluded_below_10um"

    contract = build_contract("ANL-CAL-TEST")
    assert contract["iso945"]["size_filter"]["applied"] is True
    assert contract["iso945"]["nodularity_size_qualified_pct"] == 100.0
    assert contract["calibration"]["available"] is True


# -------------------------------------------------------------- TEST 11 ----
def test_report_methodology_calibrated_vs_not():
    record = {"id": "ANL-R", "filename": "x.png", "iso_nodularity_pct": 80.0,
              "jis_nodularity_pct": 85.0, "nodule_count": 2,
              "source_width": 10, "source_height": 10,
              "created_at": "2026-01-01"}
    base_full = {"nodules": [], "border_touching": 0,
                 "class_counts": {"round_V_VI": 0, "irregular": 0}}

    uncal = rb.build_report_data(record, dict(base_full))
    m = uncal["iso_jis_classification"]["methodology"]
    assert "could not be evaluated" in m
    assert "ISO 945-4-based" in m

    cal_full = dict(base_full)
    cal_full["calibration"] = make_calibration(0.05,
                                               source="manual").to_dict()
    cal_full["size_filter"] = {"available": True, "threshold_um": 10.0,
                               "applied": True, "excluded_count": 3,
                               "included_count": 36, "reason": None}
    cal_full["iso_size_qualified_pct"] = 88.0
    cal = rb.build_report_data(record, cal_full)
    ij = cal["iso_jis_classification"]
    m2 = ij["methodology"]
    assert "10 um minimum Feret diameter exclusion was applied" in m2
    assert "source: manual" in m2 and "0.05 um/px" in m2
    assert "3 of 39" in m2 and "36 remaining" in m2
    assert ij["size_filter"]["applied"] is True
    assert ij["iso_size_qualified_pct"] == 88.0
    assert "not a certified" in m2 or "not a certified measurement" in m2


# -------------------------------------------------------------- TEST 12 ----
def test_copilot_context_and_tools_expose_real_state():
    """The Copilot contract must carry the actual filter state — applied or
    honestly not-evaluable — and the answer engine must reflect it."""
    from nodiq.ai.fallback_provider import FallbackProvider
    ai = FallbackProvider()

    uncal_ctx = {"iso945": {"nodularity_pct": 53.0,
                            "size_filter": {"available": False,
                                            "applied": False,
                                            "reason": "Physical calibration "
                                                      "unavailable",
                                            "excluded_count": None,
                                            "included_count": None,
                                            "threshold_um": 10.0}},
                 "calibration": {"available": False}}
    a1 = ai.chat([{"role": "user", "content": "Was the 10 µm filter applied?"}],
                 context=uncal_ctx)["content"]
    assert "NOT applied" in a1 or "not applied" in a1.lower()
    assert "calibration" in a1.lower()

    cal_ctx = {"iso945": {"nodularity_pct": 53.0,
                          "nodularity_size_qualified_pct": 61.5,
                          "size_filter": {"available": True, "applied": True,
                                          "excluded_count": 4,
                                          "included_count": 31,
                                          "threshold_um": 10.0}},
               "calibration": {"available": True, "source": "manual",
                               "um_per_px": 0.05}}
    a2 = ai.chat([{"role": "user", "content": "Was the 10 µm filter applied?"}],
                 context=cal_ctx)["content"]
    assert "WAS applied" in a2
    assert "4" in a2 and "31" in a2

    a3 = ai.chat([{"role": "user",
                   "content": "Is this result fully ISO 945-4 compliant?"}],
                  context=uncal_ctx)["content"]
    assert "not evaluable" in a3.lower() or "945-4-based" in a3


@pytest.fixture()
def api_tmp(tmp_path):
    import nodiq.services.context as context_svc
    import nodiq.services.db as store
    old_dir, old_full = store.DATA_DIR, context_svc.FULL_DIR
    store.DATA_DIR = tmp_path
    context_svc.FULL_DIR = tmp_path / "analyses_full"
    context_svc.FULL_DIR.mkdir(parents=True, exist_ok=True)
    context_svc._CACHE.pop("ANL-CAL-TEST", None)
    yield tmp_path
    store.DATA_DIR, context_svc.FULL_DIR = old_dir, old_full
    context_svc._CACHE.pop("ANL-CAL-TEST", None)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
