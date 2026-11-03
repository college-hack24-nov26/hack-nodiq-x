#!/usr/bin/env python3
"""
tests/test_services.py — unit tests for the intelligence services (Phase 40).

Run:  python -m pytest tests/ -q
All tests are deterministic and offline (no LLM, no network).
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest


from nodiq.services.quality import assess_quality
from nodiq.services.calibration import (Calibration, auto_calibrate,
                                  manual_calibrate, convert_areas,
                                  convert_lengths, detect_scale_bar)
from nodiq.services.comparison import compare_analyses
from nodiq.services.analytics import batch_statistics, spc
from nodiq.services.anomalies import assess_analysis, decision_support
from nodiq.services.nodule_data import nodule_confidence, enrich_rows


# ------------------------------------------------------------- quality ----
def _img(w=800, h=600, mean=180, noise=3.0, seed=0):
    """Synthetic micrograph-like image: smooth light matrix + dark blobs."""
    import cv2
    rng = np.random.RandomState(seed)
    base = rng.normal(mean, noise, (h, w)).clip(0, 255).astype(np.uint8)
    base = cv2.GaussianBlur(base, (5, 5), 1.2)   # realistic smooth matrix
    out = base.copy()
    for i in range(30):                           # graphite-like particles
        r = int(rng.randint(8, 24))
        cx, cy = int(rng.randint(r + 2, w - r - 2)), int(rng.randint(r + 2,
                                                                    h - r - 2))
        cv2.circle(out, (cx, cy), r, int(rng.randint(25, 55)), -1)
    return out


def test_quality_good_micrograph_passes():
    gray = _img()
    rep = assess_quality(gray, 1920, 1440)
    assert rep["status"] in ("PASS", "WARNING")
    assert rep["score"] > 50
    assert rep["checks"]["resolution"] == "PASS"


def test_quality_tiny_image_warns_on_resolution():
    gray = _img(100, 80)
    rep = assess_quality(gray, 100, 80)
    assert rep["checks"]["resolution"] in ("WARNING", "REJECT")
    assert any("resolution" in w or "width" in w for w in rep["warnings"])


def test_quality_blank_image_rejects():
    gray = np.full((400, 400), 128, np.uint8)  # perfectly flat = no info
    rep = assess_quality(gray, 800, 800)
    assert rep["checks"]["blur"] in ("WARNING", "REJECT")
    assert rep["status"] in ("WARNING", "REJECT")


def test_quality_dark_image_flags_graphite_presence():
    gray = _img(mean=25, noise=5)
    rep = assess_quality(gray, 1600, 1200)
    assert rep["measurements"]["dark_fraction"] > 0.6
    assert rep["checks"]["graphite_presence"] == "WARNING"


# ---------------------------------------------------------- calibration ----
def test_manual_calibration_math():
    cal = manual_calibrate(bar_length_px=215, bar_length_um=100)
    assert cal.available
    assert abs(cal.um_per_px - 100 / 215) < 1e-9
    lengths, unit = convert_lengths([215, 430], cal)
    assert unit == "µm"
    assert abs(lengths[0] - 100) < 1e-6
    areas, unit2 = convert_areas([1000], cal)
    assert unit2 == "µm²"
    assert abs(areas[0] - 1000 * (100 / 215) ** 2) < 1e-6


def test_unavailable_calibration_never_invents():
    cal = Calibration()
    assert not cal.available
    vals, unit = convert_lengths([123], cal)
    assert vals == [None] and unit == "px"


def test_auto_calibrate_requires_declared_length():
    gray = _img()
    cal = auto_calibrate(gray, declared_bar_um=None)
    assert not cal.available          # no OCR -> honest unavailability
    assert "unavailable" in cal.notes.lower() or cal.notes


def test_scale_bar_detector_finds_solid_bar():
    gray = _img(1200, 800)
    cv = pytest.importorskip("cv2")
    # draw a solid dark bar bottom-right
    cv2 = cv
    cv2.rectangle(gray, (900, 760), (1100, 768), 20, -1)
    found = detect_scale_bar(gray)
    assert found["bar"] is not None
    assert abs(found["bar"]["length_px"] - 200) <= 8


# ---------------------------------------------------------- comparison ----
def _analysis(iso, count, irregular=0.3, area=900.0, aid="ANL-1"):
    n = count
    rows = []
    for i in range(n):
        r = 0.3 if i < int(n * irregular) else 0.9
        rows.append({"nodule_id": i + 1, "area_px": area,
                     "equiv_diameter_px": 2 * math.sqrt(area / math.pi),
                     "roundness": r,
                     "iso_class": "V/VI" if r >= 0.6 else "irregular"})
    return {"analysis_id": aid, "iso_nodularity_pct": iso,
            "jis_nodularity_pct": iso * 1.3, "nodule_count": count,
            "border_touching": 2, "nodules": rows}


def test_comparison_percentage_points():
    a = _analysis(87.4, 100, irregular=0.2)
    b = _analysis(72.1, 100, irregular=0.5, aid="ANL-2")
    comp = compare_analyses(a, b)
    assert comp["nodularity"]["change_pp"] == pytest.approx(-15.3)
    assert comp["irregular_fraction"]["change_pp"] == pytest.approx(30.0)
    assert comp["summary"]


# ------------------------------------------------------ batch + spc ----
def test_batch_statistics():
    records = [{"iso_nodularity_pct": v, "nodule_count": 40}
               for v in (90, 92, 88, 91, 95, 85, 90, 93)]
    stats = batch_statistics(records)
    assert stats["samples"] == 8
    assert stats["pass_rate_pct"] == 100.0
    assert stats["nodularity"]["mean"] == pytest.approx(90.5, abs=0.1)
    assert stats["nodularity"]["std"] > 0


def test_spc_insufficient_data_honest():
    out = spc([80.0, 81.0], metric="nodularity_pct")
    assert not out["sufficient_data"]
    assert "8" in out["note"] or "only" in out["note"]


def test_spc_detects_beyond_3sigma():
    vals = [90.0] * 10 + [10.0]
    out = spc(vals, metric="nodularity_pct")
    assert out["sufficient_data"]
    assert out["violations"] >= 1
    assert any(o["index"] == 10 for o in out["outliers"])


# ------------------------------------------------------------- anomalies ----
def test_anomaly_low_nodularity_with_reason():
    record = {"id": "ANL-X", "iso_nodularity_pct": 55.0,
              "nodule_count": 30, "accuracy_pct": 100.0}
    card = assess_analysis(record, [])
    assert card["is_anomaly"]
    assert card["severity"] in ("MEDIUM", "HIGH")
    assert any("below the 80%" in r for r in card["reasons"])


def test_anomaly_clean_record_passes():
    record = {"id": "ANL-Y", "iso_nodularity_pct": 90.0,
              "nodule_count": 45, "accuracy_pct": 100.0}
    card = assess_analysis(record, [record])
    assert not card["is_anomaly"]
    assert card["reasons"] == []


def test_decision_support_never_claims_cause():
    record = {"id": "ANL-Z", "iso_nodularity_pct": 71.4,
              "nodule_count": 60, "jis_nodularity_pct": 55.0,
              "accuracy_pct": 100.0}
    full = {"nodules": [{"iso_class": "irregular", "roundness": 0.4,
                         "area_px": 500, "jis_bucket": 2}] * 30
            + [{"iso_class": "V/VI", "roundness": 0.9, "area_px": 600,
                "jis_bucket": 5}] * 30}
    chain = decision_support(record, full=full)
    assert chain["measured"] and chain["observed"]
    assert chain["recommendation"]
    text = " ".join(chain["interpretation"] + chain["recommendation"]).lower()
    assert "cannot" in text or "verify" in text


# --------------------------------------------------------- nodule data ----
def test_confidence_bounds_and_honesty():
    hi = nodule_confidence({"roundness": 0.95}, 100.0)
    borderline = nodule_confidence({"roundness": 0.61}, 100.0)
    assert 0.0 <= borderline < hi <= 1.0


def test_enrich_rows_adds_geometry():
    import cv2
    cnt = np.array([[[10, 10]], [[60, 10]], [[60, 60]], [[10, 60]]],
                   dtype=np.int32)
    rows = [{"nodule_id": 1, "roundness": 0.9, "area_px": 2500.0,
             "iso_class": "V/VI"}]
    out = enrich_rows(rows, [cnt], image_f1_pct=100.0)
    assert "perimeter_px" in out[0] and "confidence" in out[0]
    assert out[0]["perimeter_px"] == pytest.approx(200, abs=2)


# --------------------------------------------------------- report builder ----
def test_report_builder_csv_json():
    import nodiq.reports.report_builder as rb
    record = {"id": "ANL-R", "filename": "micrograph_0001.png",
              "iso_nodularity_pct": 85.0, "jis_nodularity_pct": 90.0,
              "nodule_count": 50, "source_width": 1600,
              "source_height": 1200, "created_at": "2026-01-01"}
    full = {"nodules": [{"area_px": 800.0, "roundness": 0.9,
                         "iso_class": "V/VI", "jis_bucket": 5}] * 50,
            "self_check": {"count_accuracy_pct": 100.0, "f1_pct": 100.0},
            "border_touching": 1, "class_counts": {"round_V_VI": 50,
                                                   "irregular": 0},
            "iso_nodularity_inframe_pct": 85.0}
    report = rb.build_report_data(record, full)
    assert report["verdict"]["iso_verdict"] == "ACCEPTABLE"
    assert report["physical_measurements"]["available"] is False
    js = rb.to_json(report)
    assert "NODIQ-X" in js
    csv_text = rb.to_csv(report)
    assert "iso_nodularity_pct" in csv_text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
