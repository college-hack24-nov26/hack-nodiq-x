"""Tests for White Cast Iron (Carbide) and Gray Cast Iron (Graphite Flake) Analysis Modes.

Validates:
A. Local repository discovery, licenses, dependencies, weights, and availability contracts.
B. Genuine segmentation, measurement calculations, calibration units, and invalid inputs.
C. Strict pipeline and data separation from nodularity and steel pipelines.
D. API routing, persistence, artifact access, and engine diagnostics.
E. Dedicated reporting (JSON, PDF, CSV) and strict zero-leakage of ISO/JIS nodularity.
"""
from __future__ import annotations

import io
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pytest


from nodiq.services.white_cast_iron import carde_adapter
from nodiq.services.white_cast_iron import pipeline as white_pipeline
from nodiq.services.gray_cast_iron import graphite_flake_adapter as eg_adapter
from nodiq.services.gray_cast_iron import pipeline as gray_pipeline
import nodiq.reports.report_builder as report_builder


# --------------------------------------------------------------------------- #
# Test Fixtures & Micrographs
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def sample_micrograph():
    """Create a synthetic high-contrast micrograph for pipeline smoke tests."""
    img = np.full((300, 300, 3), 180, dtype=np.uint8)
    # Draw several distinct bright carbide-like patches
    cv2.circle(img, (80, 80), 20, (245, 245, 245), -1)
    cv2.circle(img, (200, 100), 25, (250, 250, 250), -1)
    cv2.ellipse(img, (150, 220), (35, 15), 30, 0, 360, (240, 240, 240), -1)
    return img


@pytest.fixture(scope="module")
def sample_micrograph_png(sample_micrograph):
    ok, buf = cv2.imencode(".png", sample_micrograph)
    assert ok
    return buf.tobytes()


@pytest.fixture(scope="module")
def real_eg_micrograph():
    """Load genuine test micrograph from third_party/EG_Pore_Segmentation/data/test/images/161.jpg."""
    path = Path(__file__).resolve().parents[1] / "third_party" / "EG_Pore_Segmentation" / "data" / "test" / "images" / "161.jpg"
    assert path.is_file(), f"Expected test image at {path}"
    img = cv2.imread(str(path))
    assert img is not None
    # Resize to 512x512 tile for fast smoke testing
    return cv2.resize(img, (512, 512))


@pytest.fixture(scope="module")
def api_env(tmp_path_factory):
    import nodiq.api.server as server
    _rl_saved = server.RATE_LIMITS_ENABLED
    server.RATE_LIMITS_ENABLED = False

    import nodiq.services.auth as auth_svc
    import nodiq.services.context as context_svc
    import nodiq.services.db as store

    root = tmp_path_factory.mktemp("cast-iron-api")
    saved = (store.DATA_DIR, store.DB_PATH, store._CONN,
             context_svc.FULL_DIR, server.UPLOAD_DIR, server.ai_chat)
    if store._CONN is not None:
        try:
            store._CONN.close()
        except Exception:
            pass
        store._CONN = None
    store.DATA_DIR = root / "server_data"
    store.DATA_DIR.mkdir()
    store.DB_PATH = store.DATA_DIR / "test.db"
    context_svc.FULL_DIR = store.DATA_DIR / "analyses_full"
    context_svc.FULL_DIR.mkdir()
    server.UPLOAD_DIR = store.DATA_DIR / "uploads"
    server.UPLOAD_DIR.mkdir()
    store.init_db()
    auth_svc._user_conn()
    server.ai_chat = lambda messages: {"content": "ok", "provider": "test"}
    try:
        yield server.app.test_client(), server
    finally:
        server.RATE_LIMITS_ENABLED = _rl_saved
        temp_conn = store._CONN
        (store.DATA_DIR, store.DB_PATH, store._CONN,
         context_svc.FULL_DIR, server.UPLOAD_DIR, server.ai_chat) = saved
        if temp_conn is not None and temp_conn is not store._CONN:
            temp_conn.close()


@pytest.fixture(scope="module")
def account(api_env):
    client, _ = api_env
    email = f"iron-{time.time_ns()}@test.local"
    resp = client.post("/api/auth/signup", json={
        "email": email, "password": "password1", "name": "Cast Iron Tester"})
    assert resp.status_code == 201
    token = resp.headers.get("Set-Cookie", "").split(
        "nodiq_session=", 1)[1].split(";", 1)[0]
    return {"headers": {"Authorization": f"Bearer {token}"}}


# --------------------------------------------------------------------------- #
# A. Repository Discovery, Licenses, Weights & Dependencies
# --------------------------------------------------------------------------- #

def test_carde_repository_and_license_discovery():
    repo_dir = carde_adapter.find_carde_repo()
    assert repo_dir is not None
    assert repo_dir.exists()
    assert (repo_dir / "README.md").exists() or (repo_dir / "docs" / "README.md").exists()

    meta = carde_adapter.get_upstream_metadata()
    assert meta["license"] == "BSD-3-Clause"
    assert "Till Korten" in meta["attribution"]
    assert "CARDE" in meta["name"]


def test_s_metalseg_repository_and_license_discovery():
    repo_dir = eg_adapter.find_s_metalseg_repo()
    assert repo_dir is not None
    assert repo_dir.exists()
    assert (repo_dir / "README.md").exists()
    assert (repo_dir / "LICENSE").exists()

    meta = eg_adapter.get_upstream_metadata()
    assert "Luengo" in meta["attribution"]
    assert "S-metallograph-segmentation" in meta["name"]
    assert "ArcelorMittal" in meta["collaboration"]


def test_carde_availability_contract():
    av = carde_adapter.availability()
    assert "available" in av
    assert av["engine"] == "carde"
    assert "classical_otsu" in av["methods"]
    assert "unet" in av["methods"]
    # U-Net weights not pre-cached in repo
    assert av["weights"]["available"] is False
    assert "missing_checkpoint" in av["weights"]["note"]


def test_s_metalseg_availability_contract():
    av = eg_adapter.availability()
    assert "available" in av
    assert av["engine"] in ("s_metallograph_segmentation", "eg_pore_segmentation", "eg_fpn_watershed")
    assert "s_metalseg_fpn" in av["methods"]
    assert "validation_status" in av
    assert "EXPERIMENTAL" in av["validation_status"]


def test_carde_missing_repo_handling(monkeypatch, tmp_path):
    fake_empty = tmp_path / "non_existent_carde"
    monkeypatch.setattr(carde_adapter, "REPO_DIR", fake_empty)
    av = carde_adapter.availability()
    assert av["available"] is False
    assert "repository_dir" in av["missing"]


def test_s_metalseg_missing_repo_handling(monkeypatch, tmp_path):
    fake_empty = tmp_path / "non_existent_s_metalseg"
    monkeypatch.setattr(eg_adapter, "REPO_DIR", fake_empty)
    av = eg_adapter.availability()
    assert av["available"] is False
    assert "repository_dir" in av["missing"]


# --------------------------------------------------------------------------- #
# B. Genuine Segmentation, Measurements & Calibration
# --------------------------------------------------------------------------- #

def test_carde_genuine_carbide_segmentation_and_measurements(sample_micrograph):
    res = carde_adapter.run_carde_carbide_analysis(sample_micrograph, calibration=0.5)
    assert res["status"] == "completed"
    assert res["carbide_count"] > 0
    assert "carde_mask" in res["images"]
    assert "carde_overlay" in res["images"]

    mask = res["images"]["carde_mask"]
    assert mask.shape == sample_micrograph.shape[:2]
    assert set(np.unique(mask)).issubset({0, 255})

    m = res["measurements"]
    assert m["total_regions"] == res["carbide_count"]
    assert m["total_area_px2"] > 0
    assert 0 < m["area_fraction_pct"] <= 100.0
    assert m["mean_equiv_diameter_px"] > 0
    assert m["mean_solidity"] > 0

    # Calibrated physical units
    assert m["total_area_um2"] == pytest.approx(m["total_area_px2"] * (0.5 ** 2), rel=1e-3)
    assert m["mean_equiv_diameter_um"] == pytest.approx(m["mean_equiv_diameter_px"] * 0.5, rel=1e-3)

    # Metallurgical disclosures
    exp = res["experimental_interpretations"]
    assert "UNVALIDATED" in exp["cementite_identification"]
    assert "UNVALIDATED" in exp["ledeburite_presence"]


def test_eg_genuine_graphite_flake_segmentation_and_measurements(real_eg_micrograph):
    res = eg_adapter.run_graphite_flake_analysis(real_eg_micrograph, calibration=0.5)
    assert res["status"] == "completed"
    assert res["flake_count"] > 0
    assert "flake_mask" in res["images"]
    assert "flake_overlay" in res["images"]

    mask = res["images"]["flake_mask"]
    assert mask.shape == real_eg_micrograph.shape[:2]
    assert set(np.unique(mask)).issubset({0, 255})

    m = res["measurements"]
    assert m["total_flakes"] == res["flake_count"]
    assert m["total_graphite_area_px2"] > 0
    assert 0 < m["graphite_area_fraction_pct"] <= 100.0
    assert m["mean_aspect_ratio"] >= 1.0

    # Calibrated physical units
    assert m["total_graphite_area_um2"] == pytest.approx(m["total_graphite_area_px2"] * (0.5 ** 2), rel=1e-3)
    assert m["mean_equiv_diameter_um"] == pytest.approx(m["mean_equiv_diameter_px"] * 0.5, rel=1e-3)

    # Metallurgical disclosures
    exp = res["experimental_interpretations"]
    assert "UNVALIDATED" in exp["iso_graphite_classification"]
    assert "UNAVAILABLE" in exp["flake_thickness_3d"]


def test_uncalibrated_measurements_report_pixel_units_only(sample_micrograph):
    res_w = carde_adapter.run_carde_carbide_analysis(sample_micrograph, calibration=None)
    assert res_w["status"] == "completed"
    assert res_w["measurements"]["total_area_um2"] is None
    assert res_w["measurements"]["mean_equiv_diameter_um"] is None
    assert any("calibration unavailable" in u.lower() for u in res_w["warnings"])

    empty_mask = np.zeros((100, 100), dtype=np.uint8)
    res_g = eg_adapter.compute_flake_measurements(empty_mask, calibration=None)
    assert res_g["total_graphite_area_um2"] is None
    assert res_g["mean_equiv_diameter_um"] is None


def test_invalid_calibration_rejection():
    for bad_cal in (0, -1.5, float("nan"), float("inf"), "invalid_scale"):
        with pytest.raises(ValueError):
            white_pipeline.validate_calibration(bad_cal)
        with pytest.raises(ValueError):
            gray_pipeline.validate_calibration(bad_cal)


def test_empty_segmentation_handled_honestly():
    empty_mask = np.zeros((100, 100), dtype=np.uint8)

    meas_w = carde_adapter.compute_carbide_measurements(empty_mask, calibration=None)
    assert meas_w["total_regions"] == 0
    assert meas_w["total_area_px2"] == 0
    assert meas_w["area_fraction_pct"] == 0.0

    meas_g = eg_adapter.compute_flake_measurements(empty_mask, calibration=None)
    assert meas_g["total_flakes"] == 0
    assert meas_g["total_graphite_area_px2"] == 0
    assert meas_g["graphite_area_fraction_pct"] == 0.0


def test_invalid_image_handled_honestly():
    tiny = np.zeros((10, 10, 3), dtype=np.uint8)
    p_w = white_pipeline.analyze_image(tiny)
    assert p_w["status"] == "failed"
    assert "too small" in p_w["error"].lower()

    p_g = gray_pipeline.analyze_image(tiny)
    assert p_g["status"] == "failed"
    assert "too small" in p_g["error"].lower()


# --------------------------------------------------------------------------- #
# C. Strict Separation from Existing Nodularity & Steel Pipelines
# --------------------------------------------------------------------------- #

def test_white_cast_iron_never_produces_nodularity_metrics(sample_micrograph_png):
    res = white_pipeline.analyze_image(sample_micrograph_png, calibration=1.0)
    assert res["status"] == "completed"
    assert res["analysis_type"] == "white_cast_iron_carbide"

    # Must NOT contain nodularity fields
    assert "nodularity_pct" not in res
    assert "nodule_count" not in res
    assert "iso_nodularity_pct" not in res
    assert "jis_nodularity_pct" not in res
    assert "steel_grain_size" not in res


def test_gray_cast_iron_never_produces_nodularity_metrics(real_eg_micrograph):
    ok, buf = cv2.imencode(".png", real_eg_micrograph)
    assert ok
    res = gray_pipeline.analyze_image(buf.tobytes(), calibration=1.0)
    assert res["status"] == "completed"
    assert res["analysis_type"] == "gray_cast_iron_graphite_flake"

    # Must NOT contain nodularity fields
    assert "nodularity_pct" not in res
    assert "nodule_count" not in res
    assert "iso_nodularity_pct" not in res
    assert "jis_nodularity_pct" not in res
    assert "steel_grain_size" not in res


# --------------------------------------------------------------------------- #
# D. Server Routing, Engine Diagnostics & Artifact Access
# --------------------------------------------------------------------------- #

def test_engine_diagnostics_endpoints(api_env, account):
    client, _ = api_env

    resp_w = client.get("/api/white-cast-iron/engines", headers=account["headers"])
    assert resp_w.status_code == 200
    w_json = resp_w.get_json()
    assert w_json["analysis_type"] == "white_cast_iron_carbide"
    assert "carde" in w_json

    resp_g = client.get("/api/gray-cast-iron/engines", headers=account["headers"])
    assert resp_g.status_code == 200
    g_json = resp_g.get_json()
    assert g_json["analysis_type"] == "gray_cast_iron_graphite_flake"
    assert "eg_fpn" in g_json


def _poll(client, headers, analysis_id, deadline_s=90):
    deadline = time.time() + deadline_s
    detail = None
    status = None
    while time.time() < deadline:
        detail = client.get(f"/api/analyses/{analysis_id}", headers=headers).get_json()
        status = detail.get("status") or detail.get("record", {}).get("status")
        if status in ("completed", "failed"):
            break
        time.sleep(0.5)
    return status, detail


def test_white_cast_iron_upload_and_artifact_serving(api_env, account, sample_micrograph_png):
    client, _ = api_env
    resp = client.post(
        "/api/analyze",
        data={
            "image": (io.BytesIO(sample_micrograph_png), "white_iron_sample.png"),
            "analysis_type": "white_cast_iron_carbide",
            "method": "carde_otsu",
            "microns_per_pixel": "0.75",
            "input_source": "upload",
        },
        content_type="multipart/form-data",
        headers=account["headers"],
    )
    assert resp.status_code == 202
    aid = resp.get_json()["analysis_id"]

    status, detail = _poll(client, account["headers"], aid)
    assert status == "completed", detail
    rec = detail["record"]
    assert rec["analysis_type"] == "white_cast_iron_carbide"
    assert rec["type"] == "White Cast Iron Carbide Analysis"

    anl = detail["analysis"]
    assert "carde_mask_url" in anl
    assert "carde_overlay_url" in anl

    # Fetch visual artifact through authenticated route
    art_resp = client.get(anl["carde_mask_url"], headers=account["headers"])
    assert art_resp.status_code == 200
    assert art_resp.content_type == "image/png"


def test_gray_cast_iron_upload_and_artifact_serving(api_env, account, real_eg_micrograph):
    ok, buf = cv2.imencode(".png", real_eg_micrograph)
    assert ok
    client, _ = api_env
    resp = client.post(
        "/api/analyze",
        data={
            "image": (io.BytesIO(buf.tobytes()), "gray_iron_sample.png"),
            "analysis_type": "gray_cast_iron_graphite_flake",
            "method": "eg_fpn_watershed",
            "microns_per_pixel": "0.5",
            "input_source": "upload",
        },
        content_type="multipart/form-data",
        headers=account["headers"],
    )
    assert resp.status_code == 202
    aid = resp.get_json()["analysis_id"]

    status, detail = _poll(client, account["headers"], aid)
    assert status == "completed", detail
    rec = detail["record"]
    assert rec["analysis_type"] == "gray_cast_iron_graphite_flake"
    assert rec["type"] == "Gray Cast Iron Graphite Flake Analysis"

    anl = detail["analysis"]
    assert "flake_mask_url" in anl
    assert "flake_overlay_url" in anl

    # Fetch visual artifact through authenticated route
    art_resp = client.get(anl["flake_mask_url"], headers=account["headers"])
    assert art_resp.status_code == 200
    assert art_resp.content_type == "image/png"


def test_gray_cast_iron_upload_with_s_metalseg_fpn(api_env, account, real_eg_micrograph):
    ok, buf = cv2.imencode(".png", real_eg_micrograph)
    assert ok
    client, _ = api_env
    resp = client.post(
        "/api/analyze",
        data={
            "image": (io.BytesIO(buf.tobytes()), "gray_iron_sample_fpn.png"),
            "analysis_type": "gray_cast_iron_graphite_flake",
            "method": "s_metalseg_fpn",
            "microns_per_pixel": "0.5",
            "input_source": "upload",
        },
        content_type="multipart/form-data",
        headers=account["headers"],
    )
    assert resp.status_code == 202
    aid = resp.get_json()["analysis_id"]

    status, detail = _poll(client, account["headers"], aid)
    assert status == "completed", detail
    rec = detail["record"]
    assert rec["analysis_type"] == "gray_cast_iron_graphite_flake"
    assert rec["type"] == "Gray Cast Iron Graphite Flake Analysis"


def test_backward_compatible_upload_defaults_to_nodularity(api_env, account, sample_micrograph_png):
    client, _ = api_env
    resp = client.post(
        "/api/analyze",
        data={
            "image": (io.BytesIO(sample_micrograph_png), "standard_nodularity.png"),
        },
        content_type="multipart/form-data",
        headers=account["headers"],
    )
    assert resp.status_code == 202
    aid = resp.get_json()["analysis_id"]
    detail = client.get(f"/api/analyses/{aid}", headers=account["headers"]).get_json()
    assert detail["record"]["analysis_type"] == "graphite_nodularity"


# --------------------------------------------------------------------------- #
# E. Dedicated Reporting & Report Separation
# --------------------------------------------------------------------------- #

def test_white_cast_iron_report_data_and_separation():
    record = {"id": "ANL-W01", "filename": "white_iron.png", "analysis_type": "white_cast_iron_carbide"}
    full = {
        "status": "completed",
        "method": "carde_otsu",
        "method_label": "CARDE Classical Carbide Segmentation",
        "white_cast_iron": {
            "engine": "carde_otsu",
            "carbide_count": 42,
            "measurements": {
                "total_regions": 42,
                "area_fraction_pct": 14.5,
                "total_area_px2": 13050,
                "mean_equiv_diameter_px": 19.8,
                "mean_solidity": 0.88,
            },
            "experimental_interpretations": {
                "cementite_identification": "UNVALIDATED / NOT IDENTIFIED",
                "ledeburite_presence": "UNVALIDATED / NOT IDENTIFIED",
            },
            "validation_status": "EXPERIMENTAL / UNVALIDATED on white cast iron micrographs",
        },
        "calibration": {"available": False},
    }
    report = report_builder.build_white_cast_iron_report_data(record, full)
    assert report["report_meta"]["report_kind"] == "white_cast_iron_carbide"
    assert "white_cast_iron_carbide" in report

    # Strict separation assertions
    assert "iso_nodularity_pct" not in report
    assert "jis_nodularity_pct" not in report
    assert "nodules" not in report
    assert "detection_results" not in report
    assert "steel_grain_size" not in report

    # Render PDF
    pdf_bytes, err = report_builder.to_pdf(report)
    assert err is None
    assert pdf_bytes.startswith(b"%PDF")

    # Render CSV
    csv_str = report_builder.to_csv(report)
    assert "carbide_results" in csv_str
    assert "iso_nodularity" not in csv_str


def test_gray_cast_iron_report_data_and_separation():
    record = {"id": "ANL-G01", "filename": "gray_iron.png", "analysis_type": "gray_cast_iron_graphite_flake"}
    full = {
        "status": "completed",
        "method": "eg_fpn_watershed",
        "method_label": "EG FPN + Watershed Segmentation",
        "gray_cast_iron": {
            "engine": "eg_fpn_watershed",
            "flake_count": 68,
            "measurements": {
                "total_flakes": 68,
                "graphite_area_fraction_pct": 11.2,
                "total_graphite_area_px2": 10080,
                "mean_equiv_diameter_px": 13.7,
                "mean_aspect_ratio": 3.4,
                "mean_orientation_deg": 42.1,
            },
            "experimental_interpretations": {
                "iso_graphite_classification": "UNVALIDATED / NOT EVALUATED",
                "flake_thickness_3d": "UNAVAILABLE (2D micrograph only)",
            },
            "validation_status": "EXPERIMENTAL / UNVALIDATED on gray cast iron micrographs",
        },
        "calibration": {"available": False},
    }
    report = report_builder.build_gray_cast_iron_report_data(record, full)
    assert report["report_meta"]["report_kind"] == "gray_cast_iron_graphite_flake"
    assert "gray_cast_iron_graphite_flake" in report

    # Strict separation assertions
    assert "iso_nodularity_pct" not in report
    assert "jis_nodularity_pct" not in report
    assert "nodules" not in report
    assert "detection_results" not in report
    assert "steel_grain_size" not in report

    # Render PDF
    pdf_bytes, err = report_builder.to_pdf(report)
    assert err is None
    assert pdf_bytes.startswith(b"%PDF")

    # Render CSV
    csv_str = report_builder.to_csv(report)
    assert "graphite_results" in csv_str
    assert "iso_nodularity" not in csv_str
