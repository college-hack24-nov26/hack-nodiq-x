#!/usr/bin/env python3
"""
tests/test_pillar2_pillar5.py — Verification of Pillar 2 (Mechanical Properties)
and Pillar 5 (Tamper-Proof Cryptographic Verification) across all 4 material families.
"""

import io
import json
import sys
from pathlib import Path


import pytest
from nodiq.services.properties import (
    estimate_ductile_iron_properties,
    estimate_gray_iron_properties,
    estimate_white_iron_properties,
    estimate_steel_properties,
    estimate_mechanical_properties,
)
from nodiq.services.security.crypto_verification import (
    generate_cryptographic_fingerprint,
    generate_qr_code_png_bytes,
    verify_canonical_manifest,
    verify_pdf_document,
)
import nodiq.reports.report_builder as report_builder


# ============================================================================
# PILLAR 2: MECHANICAL PROPERTIES PREDICTION TESTS
# ============================================================================

def test_ductile_iron_predictions_and_verdict():
    """Verify Ductile Iron ISO 1083 / ASTM A536 mechanical properties & verdict."""
    res = estimate_ductile_iron_properties(
        nodularity_pct=92.0,
        graphite_area_pct=11.2,
        pearlite_pct=45.0,
        nodule_density_mm2=250.0,
        target_grade="EN-GJS-500-7"
    )
    assert res["available"] is True
    assert res["material_family"] == "Ductile / Spheroidal Graphite Cast Iron"
    
    # Check predictions
    rm = res["estimated_tensile_strength_mpa"]["estimate"]
    rp = res["estimated_yield_strength_mpa"]["estimate"]
    el = res["estimated_elongation_pct"]["estimate"]
    hbw = res["estimated_hardness_hbw"]["estimate"]
    
    assert 480 <= rm <= 650, f"Expected Rm in [480, 650], got {rm}"
    assert 300 <= rp <= 450, f"Expected Rp in [300, 450], got {rp}"
    assert 4.0 <= el <= 15.0, f"Expected Elongation in [4.0, 15.0], got {el}"
    assert 170 <= hbw <= 250, f"Expected HBW in [170, 250], got {hbw}"
    
    # Check verdict
    verd = res["acceptance_verdict"]
    assert verd["status"] in ("COMPLIANT", "MARGINAL")
    assert "EN-GJS-500-7" in verd["statement"]
    assert verd["tensile_margin_pct"] >= 0


def test_gray_iron_predictions_and_verdict():
    """Verify Gray Cast Iron ASTM A48 / ISO 185 mechanical properties."""
    res = estimate_gray_iron_properties(
        flake_type="A",
        flake_size=4,
        flake_area_pct=10.0,
        pearlite_pct=85.0,
        target_grade="ASTM Class 30"
    )
    assert res["available"] is True
    assert res["material_family"] == "Gray Cast Iron (Flake Graphite)"
    
    rm = res["estimated_tensile_strength_mpa"]["estimate"]
    comp = res["estimated_compressive_strength_mpa"]["estimate"]
    hbw = res["estimated_hardness_hbw"]["estimate"]
    
    assert 180 <= rm <= 320, f"Expected Rm in [180, 320], got {rm}"
    assert comp >= rm * 3.0, "Compressive strength should be at least 3x tensile in gray iron"
    assert 170 <= hbw <= 260
    assert res["damping_capacity_index"] >= 5.0
    
    verd = res["acceptance_verdict"]
    assert "ASTM Class 30" in verd["statement"]


def test_white_iron_predictions_and_verdict():
    """Verify White Cast Iron ASTM A532 / ISO 21988 hardness & wear index."""
    res = estimate_white_iron_properties(
        carbide_volume_fraction_pct=30.0,
        mean_spacing_um=12.0,
        matrix="martensitic",
        target_grade="ASTM A532 Class III Type A (25% Cr)"
    )
    assert res["available"] is True
    assert res["material_family"] == "White Cast Iron (Wear-Resistant Carbides)"
    
    hrc = res["estimated_rockwell_hardness_hrc"]["estimate"]
    hbw = res["estimated_hardness_hbw"]["estimate"]
    wri = res["abrasion_wear_resistance_index"]
    k_ic = res["estimated_fracture_toughness_kic_mpa_m05"]
    
    assert 55 <= hrc <= 68, f"Expected HRC in [55, 68], got {hrc}"
    assert 550 <= hbw <= 700
    assert wri > 100.0, "Wear resistance index should be substantial"
    assert 14.0 <= k_ic <= 25.0


def test_steel_grain_size_hall_petch():
    """Verify Steel Grain Size Hall-Petch yield strength prediction."""
    res = estimate_steel_properties(
        astm_grain_size_g=9.0,
        mean_intercept_um=16.0,
        target_grade="EN 10025 S355"
    )
    assert res["available"] is True
    assert res["material_family"] == "Steel Grain Size (ASTM E112 / ISO 643)"
    
    rp = res["estimated_yield_strength_mpa"]["estimate"]
    rm = res["estimated_tensile_strength_mpa"]["estimate"]
    dbtt = res["estimated_dbtt_celsius"]
    
    assert 320 <= rp <= 450, f"Expected yield strength in [320, 450], got {rp}"
    assert rm >= rp
    assert dbtt < 0.0, "Fine grain steel should exhibit sub-zero DBTT transition"
    
    verd = res["acceptance_verdict"]
    assert "S355" in verd["target_grade"]


# ============================================================================
# PILLAR 5: TAMPER-PROOF CRYPTOGRAPHIC VERIFICATION TESTS
# ============================================================================

def test_canonical_sha256_reproducibility():
    """Verify SHA-256 root hash is deterministic and tamper-evident."""
    h1, m1 = generate_cryptographic_fingerprint(
        image_bytes_or_hash=b"TEST_IMAGE_BYTES_12345",
        calibration={"um_per_px": 0.452},
        metrics={"nodularity_pct": 88.5},
        mechanical_predictions={"tensile_rm_mpa": 520},
        reviewer={"operator": "Dr. Sarah QA", "status": "APPROVED"},
        timestamp="2026-10-18T10:00:00Z",
        report_id="RPT-TEST01"
    )
    
    h2, m2 = generate_cryptographic_fingerprint(
        image_bytes_or_hash=b"TEST_IMAGE_BYTES_12345",
        calibration={"um_per_px": 0.452},
        metrics={"nodularity_pct": 88.5},
        mechanical_predictions={"tensile_rm_mpa": 520},
        reviewer={"operator": "Dr. Sarah QA", "status": "APPROVED"},
        timestamp="2026-10-18T10:00:00Z",
        report_id="RPT-TEST01"
    )
    assert h1 == h2, "Fingerprint must be 100% deterministic"
    assert verify_canonical_manifest(m1, h1) is True
    
    # Tampering with a single parameter must invalidate the hash
    m_tampered = dict(m1)
    m_tampered["measured_microstructure"] = {"nodularity_pct": 88.6}
    assert verify_canonical_manifest(m_tampered, h1) is False


def test_qr_code_generation():
    """Verify QR code PNG bytes generation."""
    url = "https://nodiq-x.app/verify/8a4fe92b1234567890abcdef"
    png_bytes = generate_qr_code_png_bytes(url)
    assert isinstance(png_bytes, bytes)
    assert len(png_bytes) > 500
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "Must be a valid PNG binary header"


def test_pdf_tamper_detection_pipeline():
    """Verify PDF generator embeds hash & QR, and verify_pdf_document validates it."""
    # 1. Build authentic report
    rec = {"id": "RPT-AUDIT99", "filename": "sample_rotor.png", "sample_id": "ROTOR-B3"}
    full = {
        "iso_nodularity_pct": 91.0,
        "nodules": [{"area_px": 120, "roundness": 0.85}],
        "calibration": {"um_per_px": 0.5, "source": "optical"}
    }
    report = report_builder.build_report_data(rec, full)
    assert "verification" in report
    assert "mechanical_properties" in report
    
    # 2. Render authentic PDF
    pdf_bytes, err = report_builder.to_pdf(report)
    assert err is None
    assert len(pdf_bytes) > 2000
    
    # 3. Test verification against simulated database
    stored_db = {
        "RPT-AUDIT99": {
            "id": "RPT-AUDIT99",
            "sample_id": "ROTOR-B3",
            "verification_hash": report["verification"]["sha256_fingerprint"],
            "full_report": report
        }
    }
    
    def lookup_fn(rpt_id, h):
        if h:
            for r in stored_db.values():
                if r.get("verification_hash") == h:
                    return r
        if rpt_id and rpt_id in stored_db:
            return stored_db[rpt_id]
        return None
        
    audit_res = verify_pdf_document(pdf_bytes, lookup_fn)
    assert audit_res["verified"] is True
    assert audit_res["status"] == "CRYPTOGRAPHICALLY_AUTHENTIC"
    assert audit_res["report_id"] == "RPT-AUDIT99"
    
    # 4. Simulate tampering (corrupted bytes)
    tampered_bytes = pdf_bytes.replace(report["verification"]["sha256_fingerprint"].encode("latin-1"), b"0" * 64)
    tamper_res = verify_pdf_document(tampered_bytes, lookup_fn)
    assert tamper_res["verified"] is False
