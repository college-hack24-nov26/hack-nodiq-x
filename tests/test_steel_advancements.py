"""Unit tests for the Metallurgical Advancements in NODIQ-X Steel Grain Size Analysis:
1. Auto Scale-Bar Detector
2. Target Spec QC Conformance Engine
3. Phase Fraction Stereology (ASTM E562 / Fe-C Lever Rule)
4. Grain Elongation & Aspect Ratio Profiling
5. Virtual Tensile Test & Hall-Petch Mechanical Predictor
6. Micrograph Quality & Focus Health Gate
"""
import io
import sys
from pathlib import Path
import cv2
import numpy as np
import pytest


from nodiq.services.scale_bar import detect_scale_bar_from_image, detect_scale_bar_from_bytes
from nodiq.services.image_qc import evaluate_micrograph_health
from nodiq.pipelines.steel_grain_size_pipeline import (
    compute_steel_phase_fractions,
    compute_grain_anisotropy,
    evaluate_target_specification,
    predict_mechanical_properties,
    SPEC_PRESETS,
    analyze_image,
)


def _create_mock_micrograph():
    """Create synthetic steel micrograph with scale bar at the bottom."""
    img = np.full((600, 800, 3), 200, dtype=np.uint8)
    # Add random grains (dark boundaries)
    cv2.circle(img, (200, 200), 80, (40, 40, 40), 3)
    cv2.circle(img, (400, 250), 90, (40, 40, 40), 3)
    cv2.circle(img, (600, 200), 70, (40, 40, 40), 3)
    cv2.circle(img, (300, 400), 85, (40, 40, 40), 3)

    # Scale bar in bottom 15%: 200px horizontal bar
    cv2.rectangle(img, (500, 560), (700, 568), (0, 0, 0), -1)
    # Scale label "200 um"
    cv2.putText(img, "200 um", (520, 550), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    return img


def test_scale_bar_detection():
    img = _create_mock_micrograph()
    res = detect_scale_bar_from_image(img)
    assert res["detected"] is True
    assert res["bar_width_px"] == pytest.approx(200, abs=8)
    assert res["um_per_px"] > 0
    assert len(res["options"]) >= 1

    _, buf = cv2.imencode(".png", img)
    res_bytes = detect_scale_bar_from_bytes(buf.tobytes())
    assert res_bytes["detected"] is True
    assert res_bytes["bar_width_px"] == res["bar_width_px"]


def test_phase_fraction_stereology():
    img = _create_mock_micrograph()
    res = compute_steel_phase_fractions(img)
    assert res["available"] is True
    assert 0 <= res["ferrite_pct"] <= 100
    assert 0 <= res["pearlite_pct"] <= 100
    assert pytest.approx(res["ferrite_pct"] + res["pearlite_pct"], 1e-1) == 100.0
    assert res["estimated_carbon_wt_pct"] > 0
    assert "Ferrite" in res["phase_ratio"]


def test_grain_anisotropy_profiling():
    # Synthetic label map with elongated and equiaxed grains
    labels = np.zeros((300, 300), dtype=np.int32)
    # Grain 1: equiaxed (circular)
    cv2.circle(labels, (80, 80), 40, 1, -1)
    # Grain 2: elongated ellipse
    cv2.ellipse(labels, (200, 200), (80, 25), 45, 0, 360, 2, -1)

    res = compute_grain_anisotropy(labels)
    assert res["available"] is True
    assert res["mean_aspect_ratio"] >= 1.0
    assert len(res["aspect_ratio_buckets"]) == 5
    assert (res["equiaxed_pct"] + res["elongated_pct"]) == pytest.approx(100.0, 1e-1)


def test_spec_presets_and_evaluation():
    assert "astm_a36" in SPEC_PRESETS
    assert "aisi_1045" in SPEC_PRESETS
    assert "aisi_316l" in SPEC_PRESETS

    # Evaluate passing specimen for ASTM A36 (requires G >= 6.0, d <= 45 um)
    eval_pass = evaluate_target_specification({
        "astm_grain_size_number": 7.2,
        "mean_equiv_grain_diameter_um": 32.0,
        "ferrite_pct": 78.0,
        "pearlite_pct": 22.0,
    }, spec_id="astm_a36")
    assert eval_pass["verdict"] == "PASS"
    assert eval_pass["conformance_pct"] == 100.0
    assert len(eval_pass["criteria"]) >= 2

    # Evaluate failing specimen for ASTM A36 (coarse G = 4.0)
    eval_fail = evaluate_target_specification({
        "astm_grain_size_number": 4.0,
        "mean_equiv_grain_diameter_um": 80.0,
    }, spec_id="astm_a36")
    assert eval_fail["verdict"] == "FAIL"
    assert eval_fail["conformance_pct"] < 100.0


def test_virtual_tensile_properties_predictor():
    """Verify Hall-Petch mechanical strength and hardness prediction."""
    # Fine grain specimen (ASTM G = 8.0, d = 22 um)
    res_fine = predict_mechanical_properties(
        mean_diam_um=22.0,
        astm_g=8.0,
        ferrite_pct=75.0,
        pearlite_pct=25.0
    )
    assert res_fine["available"] is True
    assert res_fine["yield_strength_mpa"] >= 240.0
    assert res_fine["tensile_strength_mpa"] > res_fine["yield_strength_mpa"]
    assert res_fine["hardness_hbw"] > 100.0
    assert 0.50 <= res_fine["yield_to_tensile_ratio"] <= 0.90
    assert res_fine["ductility_compliant"] is True
    assert "High" in res_fine["toughness_tier"]

    # Coarse grain specimen (ASTM G = 3.5, d = 110 um)
    res_coarse = predict_mechanical_properties(
        mean_diam_um=110.0,
        astm_g=3.5,
        ferrite_pct=75.0,
        pearlite_pct=25.0
    )
    # Hall-Petch confirms finer grains yield higher strength
    assert res_fine["yield_strength_mpa"] > res_coarse["yield_strength_mpa"]
    assert "Low" in res_coarse["toughness_tier"] or "Standard" in res_coarse["toughness_tier"]


def test_micrograph_quality_health_gate():
    """Verify focus sharpness, illumination uniformity, and scratch detection."""
    img = _create_mock_micrograph()
    qc_sharp = evaluate_micrograph_health(img)
    assert qc_sharp["available"] is True
    assert qc_sharp["focus_score"] > 25.0
    assert qc_sharp["illumination_uniformity_pct"] > 50.0

    # Defocused / Blurry image test
    blurry = cv2.GaussianBlur(img, (25, 25), 0)
    qc_blurry = evaluate_micrograph_health(blurry)
    assert qc_blurry["focus_score"] < qc_sharp["focus_score"]

    # Image with severe scratch artifacts
    scratch_img = img.copy()
    cv2.line(scratch_img, (50, 100), (750, 100), (0, 0, 0), 3)
    cv2.line(scratch_img, (50, 200), (750, 200), (0, 0, 0), 3)
    cv2.line(scratch_img, (50, 300), (750, 300), (0, 0, 0), 3)
    qc_scratch = evaluate_micrograph_health(scratch_img)
    assert qc_scratch["scratch_density"] > qc_sharp["scratch_density"]


def test_pipeline_integration_with_all_advancements():
    img = _create_mock_micrograph()
    _, buf = cv2.imencode(".png", img)
    result = analyze_image(buf.tobytes(), method="gsat", calibration=1.0)
    assert result["status"] in ("completed", "partial")

    # Advancements outputs present in top-level payload
    assert "auto_scale" in result
    assert "phase_fractions" in result
    assert "anisotropy" in result
    assert "conformance" in result
    assert "image_qc" in result
    assert "mechanical_properties" in result

    assert result["phase_fractions"]["available"] is True
    assert result["anisotropy"]["available"] is True
    assert result["image_qc"]["available"] is True
    assert result["mechanical_properties"]["available"] is True
    assert result["mechanical_properties"]["yield_strength_mpa"] > 0
    assert "verdict" in result["conformance"]
