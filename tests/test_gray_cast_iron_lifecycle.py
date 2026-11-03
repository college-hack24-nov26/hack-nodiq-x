"""Comprehensive Lifecycle and Quality Assurance Tests for Gray Cast Iron Analysis.

Verifies:
1. Missing-checkpoint handling: classical baseline execution and honest labeling (never labeled as AI).
2. Checkpoint loading: fine-tuned weights discovery, load state dict, and is_trained_ai flag.
3. Output mask dimensions consistency across varied micrograph resolutions.
4. Scale-bar and annotation exclusion verification across multiple representative micrographs.
5. Spatial calibration measurement and micrometer unit conversion.
6. Quantitative metric calculations and explicit diagnostic summaries.
7. Strict preservation of the experimental/unvalidated industrial release disclaimer and ISO/ASTM compliance disclaimers.
"""
from __future__ import annotations

import math
from pathlib import Path
import tempfile
import cv2
import numpy as np
import pytest

from nodiq.services.gray_cast_iron import s_metalseg_adapter
from nodiq.services.gray_cast_iron import scale_calibration
from nodiq.services.gray_cast_iron import pipeline
from nodiq.services.gray_cast_iron import train_gray_cast_iron


from nodiq.core.config import DATA_DIR

TEST_MICROGRAPH_PATH = DATA_DIR / "uploads" / "52f1fb7e8433136a.jpg"


@pytest.fixture(scope="module")
def genuine_micrograph():
    if not TEST_MICROGRAPH_PATH.is_file():
        pytest.skip(f"Genuine micrograph not found at {TEST_MICROGRAPH_PATH}")
    img = cv2.imread(str(TEST_MICROGRAPH_PATH))
    assert img is not None
    return img


@pytest.fixture(scope="module")
def synthetic_micrograph_no_scalebar():
    """Create a synthetic high-contrast micrograph without any scale bar."""
    img = np.full((400, 400, 3), 220, dtype=np.uint8)
    # Draw several dark flake-like features in the upper/middle regions
    cv2.ellipse(img, (150, 150), (45, 8), 25, 0, 360, (40, 40, 40), -1)
    cv2.ellipse(img, (260, 200), (35, 6), 60, 0, 360, (45, 45, 45), -1)
    cv2.circle(img, (80, 280), 12, (35, 35, 35), -1)
    return img


def test_missing_checkpoint_honest_labeling(genuine_micrograph, monkeypatch):
    """Verify that when no checkpoint is present, system executes classical baseline and never claims trained AI."""
    # Ensure find_checkpoint_path returns None
    monkeypatch.setattr(s_metalseg_adapter, "find_checkpoint_path", lambda: None)

    res = s_metalseg_adapter.run_graphite_flake_analysis(genuine_micrograph, method="s_metalseg_fpn")
    assert res["status"] == "completed"

    # Must be explicitly identified as classical thresholding, NOT trained AI
    assert res["is_trained_ai"] is False
    assert res["inference_engine_type"] == "classical_thresholding_baseline"
    assert "Classical Baseline" in res["model_architecture"]
    assert res["directly_measured_features"]["is_trained_ai_model"] is False

    # Checkpoint status must state no checkpoint loaded
    algo = res["algorithm_predictions"]
    assert algo["is_trained_ai"] is False
    assert "NO TRAINED CHECKPOINT" in algo["checkpoint_status"]

    # Warnings must inform user of classical baseline
    assert any("classical Otsu thresholding baseline" in w for w in res["warnings"])


def test_checkpoint_loading_and_inference(genuine_micrograph, tmp_path, monkeypatch):
    """Verify reproducible checkpoint creation, discovery, and loading into adapter."""
    ckpt_dir = tmp_path / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    ckpt_file = ckpt_dir / "best_flake_model.pt"

    import subprocess
    venv_py = s_metalseg_adapter._venv_python()
    if venv_py is None:
        pytest.skip("Isolated venv python with smp runtime not found")
    
    code = f'''
import torch
import segmentation_models_pytorch as smp
model = smp.FPN(encoder_name="resnet34", encoder_weights=None, in_channels=3, classes=1)
torch.save({{
    "epoch": 1,
    "model_state_dict": model.state_dict(),
    "arch": "fpn",
    "encoder": "resnet34",
    "classes": 1,
    "val_dice": 0.92,
    "val_iou": 0.85,
}}, r"{ckpt_file}")
'''
    subprocess.run([venv_py, "-c", code], check=True)

    # Monkeypatch checkpoint finder to point to this checkpoint
    monkeypatch.setattr(s_metalseg_adapter, "find_checkpoint_path", lambda: ckpt_file)

    # Run inference on tile for speed
    tile = cv2.resize(genuine_micrograph, (256, 256))
    res = s_metalseg_adapter.run_graphite_flake_analysis(tile, method="s_metalseg_fpn")
    assert res["status"] == "completed"

    # Must be labeled as trained model
    assert res["is_trained_ai"] is True
    assert res["inference_engine_type"] == "trained_deep_learning_model"
    assert "Trained Model" in res["model_architecture"]
    assert ckpt_file.name in res["checkpoint_identifier"]
    assert res["directly_measured_features"]["is_trained_ai_model"] is True


def test_output_mask_dimensions_consistency(genuine_micrograph):
    """Verify returned masks strictly preserve input dimensions across varied resolutions."""
    test_shapes = [
        (256, 256),
        (384, 512),
        (genuine_micrograph.shape[0], genuine_micrograph.shape[1]),
    ]
    for target_h, target_w in test_shapes:
        if (target_h, target_w) == (genuine_micrograph.shape[0], genuine_micrograph.shape[1]):
            test_img = genuine_micrograph
        else:
            test_img = cv2.resize(genuine_micrograph, (target_w, target_h))

        res = s_metalseg_adapter.run_graphite_flake_analysis(test_img, method="s_metalseg_auto")
        assert res["status"] == "completed"

        mask = res["images"]["flake_mask"]
        overlay = res["images"]["flake_overlay"]
        contour = res["images"]["flake_contour"]
        exclusion = res["images"]["flake_exclusion"]

        assert mask.shape[:2] == (target_h, target_w)
        assert overlay.shape[:2] == (target_h, target_w)
        assert contour.shape[:2] == (target_h, target_w)
        assert exclusion.shape[:2] == (target_h, target_w)


def test_annotation_exclusion_multiple_micrographs(genuine_micrograph, synthetic_micrograph_no_scalebar):
    """Verify scale bar exclusion on real micrograph and zero-exclusion on unannotated micrograph."""
    # 1. Genuine micrograph with 50 um scale bar
    res_real = s_metalseg_adapter.run_graphite_flake_analysis(genuine_micrograph, method="s_metalseg_auto")
    assert res_real["status"] == "completed"
    sbi = res_real.get("scale_bar_info")
    assert sbi is not None
    assert sbi["detected"] is True
    assert sbi["bar_length_px"] == 211
    assert sbi["false_positive_pixels_removed"] > 5000
    # Exclusion overlay artifact exists
    assert "flake_exclusion" in res_real["images"]

    # 2. Synthetic micrograph without scale bar
    res_clean = s_metalseg_adapter.run_graphite_flake_analysis(synthetic_micrograph_no_scalebar, method="s_metalseg_auto")
    assert res_clean["status"] == "completed"
    assert res_clean.get("scale_bar_info") is None
    # Verify no genuine features in synthetic micrograph were removed
    diag_clean = res_clean["diagnostic_summary"]
    assert diag_clean["component_filtering_policy"]["silently_removed_components"] == 0
    assert diag_clean["potential_segmentation_errors"]["scale_bar_detected"] is False


def test_calibration_measurement_and_units(genuine_micrograph):
    """Verify optical scale measurement (um/px) and physical area calculation (um^2)."""
    res = pipeline.analyze_image(genuine_micrograph, method="s_metalseg_auto")
    assert res["status"] == "completed"

    cal = res["calibration"]
    assert cal["available"] is True
    assert cal["units"] == "um/px"
    assert pytest.approx(cal["um_per_px"], rel=1e-3) == 0.23697

    meas = res["gray_cast_iron"]["measurements"]
    assert meas["total_graphite_area_um2"] is not None
    assert meas["mean_flake_area_um2"] is not None
    assert meas["mean_equiv_diameter_um"] is not None

    # Formula check: area_um2 == area_px2 * (um_per_px^2)
    expected_um2 = round(meas["total_graphite_area_px2"] * (cal["um_per_px"] ** 2), 2)
    assert pytest.approx(meas["total_graphite_area_um2"], abs=0.5) == expected_um2


def test_metric_calculations_and_diagnostics(genuine_micrograph):
    """Audit area fraction, sum equality, equiv diameter, and diagnostic summary."""
    res = s_metalseg_adapter.run_graphite_flake_analysis(genuine_micrograph, min_area_threshold=15)
    assert res["status"] == "completed"

    meas = res["measurements"]
    tot_px = res["directly_measured_features"]["total_pixels"]
    tgt_px = meas["total_graphite_area_px2"]
    bg_px = meas["background_matrix_area_px2"]

    # 1. Sum identity
    assert tgt_px + bg_px == tot_px
    # 2. Area fraction identity
    assert pytest.approx(meas["graphite_area_fraction_pct"], rel=1e-3) == round((tgt_px / tot_px) * 100.0, 3)

    # 3. Diagnostic summary
    diag = res["diagnostic_summary"]
    assert diag["raw_detected_components_count"] > 0
    assert diag["retained_components_count"] <= diag["raw_detected_components_count"]
    assert diag["component_filtering_policy"]["min_area_threshold_px2"] == 15
    assert diag["component_filtering_policy"]["silently_removed_components"] == 0


def test_no_unvalidated_astm_or_iso_claims(genuine_micrograph):
    """Strictly verify that ISO 945-1 / ASTM A247 compliance is not claimed."""
    res = s_metalseg_adapter.run_graphite_flake_analysis(genuine_micrograph)
    assert res["status"] == "completed"

    exp = res["experimental_interpretations"]
    assert "UNVALIDATED" in exp["iso_graphite_classification"]
    assert "UNVALIDATED" in exp["iso_classification"]
    assert "UNAVAILABLE" in exp["flake_thickness_3d"]

    # Industrial release disclaimer must be intact
    val_status = res["validation_status"]
    assert "EXPERIMENTAL / NOT VALIDATED FOR INDUSTRIAL RELEASE" in val_status
    assert "ISO 945-1 / ASTM A247 graphite classification is not certified" in val_status
