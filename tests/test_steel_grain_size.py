"""Steel Grain-Size Analysis tests.

Two kinds of coverage, clearly separated:

* REAL-ENGINE tests — ``test_gsat_*`` and ``test_service_*`` execute the
  actual GSAT repository code (``grain-size-analysis-tools-main/``) on a
  synthetic steel micrograph. No engine output is mocked.
* Honesty/API tests — the ASTM estimator is only asserted through its real
  prerequisite contract: when cellpose + weights are absent it must report
  ``unavailable`` with zero fabricated measurements; when present it may
  complete. Nothing is faked either way.

The Cast Iron Nodularity product is regression-checked: a request without
``analysis_type`` must still run the original pipeline.
"""
import io
import sys
import time
from pathlib import Path

import numpy as np
import pytest


import cv2

from nodiq.services.grain_size import astm_estimator_adapter as astm_adapter
from nodiq.services.grain_size import gsat_adapter
from nodiq.pipelines.steel_grain_size_pipeline import (ANALYSIS_METHODS,
                                       ARTIFACT_LABELS as
                                       ANALYSIS_ARTIFACT_LABELS,
                                       analyze_image, engines_availability,
                                       validate_input_image)

_gsat_dir = Path(__file__).resolve().parent.parent / "third_party" / "grain-size-analysis-tools"
GSAT_EXAMPLE = (_gsat_dir / "ex_segmentation" / "optical_etched" / "grains_steel_highlighted.tif")


# --------------------------------------------------------------------------- #
# synthetic steel micrograph (Voronoi grains with etched dark boundaries)
# --------------------------------------------------------------------------- #

def make_steel_micrograph(size=400, grains=90, seed=3):
    rng = np.random.default_rng(seed)
    centers = rng.integers(20, size - 20, size=(grains, 2))
    yy, xx = np.mgrid[0:size, 0:size]
    # squared distance to every center -> Voronoi assignment
    d2 = ((yy[..., None] - centers[None, :, 0]) ** 2 +
          (xx[..., None] - centers[None, :, 1]) ** 2)
    labels = np.argmin(d2, axis=-1)
    img = 150 + (rng.integers(0, 60, size=(grains,))[labels])
    # etched boundaries: label change -> dark lines
    edge = np.zeros_like(labels, dtype=np.uint8)
    edge[:-1, :] |= (labels[1:, :] != labels[:-1, :]).astype(np.uint8)
    edge[:, :-1] |= (labels[:, 1:] != labels[:, :-1]).astype(np.uint8)
    edge = cv2.dilate(edge, np.ones((3, 3), np.uint8))
    img = img.astype(np.float32)
    img[edge > 0] = 35
    img += rng.normal(0, 5, img.shape).astype(np.float32)
    return np.clip(img, 0, 255).astype(np.uint8)


@pytest.fixture(scope="module")
def micrograph_png():
    gray = make_steel_micrograph()
    ok, buf = cv2.imencode(".png", gray)
    assert ok
    return buf.tobytes()


# --------------------------------------------------------------------------- #
# REAL GSAT engine tests
# --------------------------------------------------------------------------- #

def test_gsat_availability_reports_real_engine():
    av = gsat_adapter.availability()
    assert av["available"] is True, av
    assert av["engine"] == "gsat"
    assert av["implementation_fingerprint"]


def test_gsat_real_segmentation_produces_boundary_mask():
    gray = make_steel_micrograph()
    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    seg = gsat_adapter.segment_gsat(bgr)
    mask = seg["mask"]
    assert mask.shape == gray.shape
    assert set(np.unique(mask)).issubset({0, 255})
    # boundaries are a thin minority after polarity normalization
    assert 0.002 < (mask > 0).mean() < 0.5
    assert seg["boundary_density_pct"] > 0.2
    assert "polarity_decision" in seg["parameters"]


def test_gsat_real_e112_intercept_measurements():
    gray = make_steel_micrograph()
    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    seg = gsat_adapter.segment_gsat(bgr)
    res = gsat_adapter.e112_intercept_gsat(seg["mask"], color_bgr=bgr,
                                           um_per_px=1.5)
    assert res["available"] is True, res
    m = res["measurements"]
    assert m["grain_segments"] > 10
    assert m["boundary_intersections"] >= m["grain_segments"]
    assert m["mean_lineal_intercept_px"] > 0
    # calibrated run reports physical intercept + ASTM-related estimate
    assert m["mean_lineal_intercept_um"] == pytest.approx(
        m["mean_lineal_intercept_px"] * 1.5, rel=1e-3)
    assert isinstance(m["astm_grain_size_number"], float)
    assert "not a certified" in m["astm_grain_size_number_basis"].lower()
    # real images: native GSAT marked output + overlay on the original
    assert res["images"]["intercept"].ndim == 2
    assert res["images"]["overlay"].shape == bgr.shape


def test_gsat_reference_image_cross_check():
    """Run the repo's own bundled steel micrograph and sanity-check the
    intercept statistics against the reference CSV the repo ships."""
    if not GSAT_EXAMPLE.exists():
        pytest.skip("GSAT example image not bundled")
    img = cv2.imread(str(GSAT_EXAMPLE), cv2.IMREAD_COLOR)
    seg = gsat_adapter.segment_gsat(img)
    res = gsat_adapter.e112_intercept_gsat(seg["mask"], color_bgr=img)
    m = res["measurements"]
    ref = np.loadtxt(GSAT_EXAMPLE.parent.parent.parent /
                     "ex_grain_intercept" / "optical_etched" /
                     "grains_steel_highlighted_distances_e112.csv",
                     delimiter=",", skiprows=1)
    # same order of magnitude as the repository's own run (segmentation is
    # re-derived here, so exact equality is not expected)
    assert abs(m["mean_lineal_intercept_px"] - ref[:, 1].mean()) < \
        0.15 * ref[:, 1].mean()


# --------------------------------------------------------------------------- #
# orchestrator (service) tests — real GSAT, honest ASTM reporting
# --------------------------------------------------------------------------- #

def test_service_gsat_mode(micrograph_png):
    p = analyze_image(micrograph_png, method="gsat")
    assert p["analysis_type"] == "steel_grain_size"
    assert p["status"] in ("completed", "partial")
    gsat = p["pipelines"]["gsat"]
    assert gsat["status"] == "completed"
    assert gsat["intercept"]["measurements"]["grain_segments"] > 0
    kinds = {a["kind"] for a in p["artifacts"]}
    assert {"gsat_mask", "gsat_overlay", "gsat_intercept"} <= kinds
    for im in p["images"].values():
        assert isinstance(im, np.ndarray)
    assert "astm_estimator" not in p["pipelines"]


def test_service_uncalibrated_run_has_no_physical_values(micrograph_png):
    p = analyze_image(micrograph_png, method="gsat")
    assert p["calibration"]["available"] is False
    m = p["pipelines"]["gsat"]["intercept"]["measurements"]
    assert "mean_lineal_intercept_um" not in m
    assert "astm_grain_size_number" not in m
    assert any("calibration" in w.lower() for w in p["warnings"])


def test_service_rejects_bad_method(micrograph_png):
    with pytest.raises(ValueError):
        analyze_image(micrograph_png, method="definitely_not_a_method")


def test_service_input_validation():
    bad = validate_input_image(b"not-an-image")
    assert bad["valid"] is False


def test_astm_estimator_honesty(micrograph_png):
    """Whatever the environment, the estimator must never fabricate."""
    p = analyze_image(micrograph_png, method="astm_estimator")
    est = p["pipelines"]["astm_estimator"]
    av = astm_adapter.availability()
    if not av["available"]:
        assert p["status"] == "failed"
        assert est["status"] == "unavailable"
        assert est["measurements"] == {}
        assert est["images"] == {}
        assert "cellpose" in (av.get("missing") or []) or av.get("error")
        assert any("did not complete" in w or "failed" in w
                   for w in p["warnings"])
    else:
        assert est["status"] in ("completed", "failed", "unavailable")
        if est["status"] != "completed":
            assert est["measurements"] == {}
        else:
            assert est["measurements"]["grain_count"] >= 1
            # Jeffries requires calibration: with none, it must be off
            assert est["jeffries"]["available"] is False


def test_service_compare_preserves_partial_success(micrograph_png):
    p = analyze_image(micrograph_png, calibration=1.5, method="compare")
    assert set(p["pipelines"]) == {"gsat", "astm_estimator"}
    assert p["comparison"] is not None
    assert p["comparison"]["methodological_differences"]
    est = p["pipelines"]["astm_estimator"]
    gsat = p["pipelines"]["gsat"]
    if est["status"] != "completed":
        # partial success: GSAT results survive, comparison is incomplete
        assert gsat["status"] == "completed"
        assert p["status"] == "partial"
        assert p["comparison"]["complete"] is False
        assert any("INCOMPLETE" in n for n in p["comparison"]["notes"])
    else:
        assert p["status"] == "completed"
        assert p["comparison"]["complete"] is True


def test_storage_kinds_cover_steel_artifacts():
    """Persistent storage whitelist must accept every steel artifact kind
    (the live Supabase upload path validates kinds)."""
    from nodiq.services import storage
    assert set(ANALYSIS_ARTIFACT_LABELS) <= set(storage._KIND_EXT)


def test_engine_availability_endpoint_payload():
    av = engines_availability()
    assert av["gsat"]["available"] is True
    assert "astm_estimator" in av
    assert set(av["methods"]) == set(ANALYSIS_METHODS)


# --------------------------------------------------------------------------- #
# HTTP contract — steel via the SAME async funnel as nodularity
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def api_env(tmp_path_factory):
    import nodiq.api.server as server
    _rl_saved = server.RATE_LIMITS_ENABLED
    server.RATE_LIMITS_ENABLED = False

    import nodiq.services.auth as auth_svc
    import nodiq.services.context as context_svc
    import nodiq.services.db as store

    root = tmp_path_factory.mktemp("steel-api")
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
    email = f"steel-{time.time_ns()}@test.local"
    resp = client.post("/api/auth/signup", json={
        "email": email, "password": "password1", "name": "Steel Tester"})
    assert resp.status_code == 201
    token = resp.headers.get("Set-Cookie", "").split(
        "nodiq_session=", 1)[1].split(";", 1)[0]
    return {"headers": {"Authorization": f"Bearer {token}"}}


def _poll(client, headers, analysis_id, deadline_s=90):
    deadline = time.time() + deadline_s
    detail = None
    status = None
    while time.time() < deadline:
        detail = client.get(f"/api/analyses/{analysis_id}",
                            headers=headers).get_json()
        status = (detail.get("status")
                  or detail.get("record", {}).get("status"))
        assert status in ("processing", "completed", "failed"), detail
        if status != "processing":
            break
        time.sleep(0.2)
    return status, detail


def test_steel_engines_endpoint(api_env, account):
    client, _ = api_env
    resp = client.get("/api/steel/engines", headers=account["headers"])
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["gsat"]["available"] is True
    # anonymous callers (FRESH client without the session cookie) get
    # 401/403, never engine internals
    anon = api_env[1].app.test_client()
    assert anon.get("/api/steel/engines").status_code in (401, 403)


def test_steel_analysis_end_to_end(api_env, account, micrograph_png):
    client, _ = api_env
    resp = client.post(
        "/api/analyze",
        data={
            "image": (io.BytesIO(micrograph_png), "steel_test.png"),
            "analysis_type": "steel_grain_size",
            "method": "gsat",
            "microns_per_pixel": "1.5",
            "input_source": "microscope",
        },
        content_type="multipart/form-data",
        headers=account["headers"],
    )
    assert resp.status_code == 202, resp.get_json()
    aid = resp.get_json()["analysis_id"]

    status, detail = _poll(client, account["headers"], aid)
    assert status == "completed", detail

    record = detail["record"]
    assert record["type"] == "Steel Grain-Size Analysis"
    assert record["analysis_type"] == "steel_grain_size"
    assert record["method"] == "gsat"
    assert record["input_source"] == "microscope"

    payload = detail["analysis"]
    assert payload["pipelines"]["gsat"]["status"] == "completed"
    assert payload["calibration"]["available"] is True
    m = payload["pipelines"]["gsat"]["intercept"]["measurements"]
    assert m["grain_segments"] > 0
    assert "mean_lineal_intercept_um" in m

    # artifact URLs are attached and stream REAL png bytes
    kinds = {a["kind"] for a in payload["artifacts"]}
    assert "gsat_mask" in kinds and "gsat_overlay" in kinds
    url = payload["gsat_mask_url"]
    art = client.get(url, headers=account["headers"])
    assert art.status_code == 200
    assert art.headers["Content-Type"].startswith("image/")
    assert art.data[:8] == b"\x89PNG\r\n\x1a\n"
    # ownership: anonymous access (fresh client, no session cookie) is denied
    anon = api_env[1].app.test_client()
    assert anon.get(url).status_code in (401, 403, 404)

    # report generation uses the steel report layout
    rep = client.post("/api/reports/generate",
                      json={"analysis_id": aid},
                      headers=account["headers"])
    assert rep.status_code == 201, rep.get_json()
    report = rep.get_json()
    full = report["full_report"]
    assert full["report_meta"]["report_kind"] == "steel_grain_size"
    assert "steel_grain_size" in full
    # Critical requirement: steel reports must NEVER display cast iron nodularity or ISO/JIS tables
    assert "iso_nodularity_pct" not in full
    assert "iso_jis_classification" not in full
    assert "graphite_forms" not in full
    assert "detection_results" not in full
    assert "nodularity_pct" not in report.get("metrics", {})
    assert "nodule_count" not in report.get("metrics", {})
    assert full["steel_grain_size"]["gsat"]["measurements"]["grain_segments"] \
        == m["grain_segments"]
    pdf = client.get(report["downloads"]["pdf"],
                     headers=account["headers"])
    assert pdf.status_code == 200
    assert pdf.data[:4] == b"%PDF"
    import zlib, re
    text_chunks = [pdf.data]
    for m in re.finditer(rb'stream[\r\n]+(.*?)[\r\n]+endstream', pdf.data, re.DOTALL):
        try:
            text_chunks.append(zlib.decompress(m.group(1)))
        except Exception:
            pass
    pdf_text = b"\n".join(text_chunks)
    assert b"Steel Grain-Size" in pdf_text or b"NODIQ-X Steel" in pdf_text
    assert b"ISO 945-4" not in pdf_text
    assert b"Graphite Form" not in pdf_text
    csv_resp = client.get(report["downloads"]["csv"],
                          headers=account["headers"])
    assert csv_resp.status_code == 200
    assert b"gsat,grain_segments" in csv_resp.data
    assert b"iso_nodularity_pct" not in csv_resp.data


def test_invalid_steel_params_rejected(api_env, account, micrograph_png):
    client, _ = api_env
    resp = client.post(
        "/api/analyze",
        data={
            "image": (io.BytesIO(micrograph_png), "x.png"),
            "analysis_type": "steel_grain_size",
            "method": "nope",
        },
        content_type="multipart/form-data",
        headers=account["headers"],
    )
    assert resp.status_code == 400
    resp = client.post(
        "/api/analyze",
        data={
            "image": (io.BytesIO(micrograph_png), "x.png"),
            "analysis_type": "something_else",
        },
        content_type="multipart/form-data",
        headers=account["headers"],
    )
    assert resp.status_code == 400


def test_nodularity_dispatch_unchanged(api_env, account):
    """A plain request (no analysis_type) must still run the ORIGINAL
    nodularity pipeline — protected product regression check."""
    client, _ = api_env
    resp = client.post("/api/analyze",
                       json={"dataset_image": "micrograph_0001.png"},
                       headers=account["headers"])
    assert resp.status_code == 202
    aid = resp.get_json()["analysis_id"]
    status, detail = _poll(client, account["headers"], aid)
    assert status == "completed", detail
    payload = detail["analysis"]
    assert payload.get("analysis_type") != "steel_grain_size"
    assert "iso_nodularity_pct" in payload
    assert "pipelines" not in payload          # steel-only structure absent
    record = detail["record"]
    assert record["type"] == "Nodularity Analysis"

    # Cast iron report retains its existing nodularity and ISO/JIS sections
    rep = client.post("/api/reports/generate",
                      json={"analysis_id": aid},
                      headers=account["headers"])
    assert rep.status_code == 201
    full = rep.get_json()["full_report"]
    assert "iso_jis_classification" in full
    assert "detection_results" in full
    assert "iso_nodularity_pct" in full["iso_jis_classification"]
    assert "nodularity_pct" in rep.get_json()["metrics"]
    pdf = client.get(rep.get_json()["downloads"]["pdf"],
                     headers=account["headers"])
    assert pdf.status_code == 200
    assert pdf.data[:4] == b"%PDF"


def test_steel_analysis_upload_input(api_env, account, micrograph_png):
    """File upload path generates a dedicated steel grain-size analysis and report."""
    client, _ = api_env
    resp = client.post(
        "/api/analyze",
        data={
            "image": (io.BytesIO(micrograph_png), "steel_uploaded.png"),
            "analysis_type": "steel_grain_size",
            "method": "gsat",
            "input_source": "upload",
        },
        content_type="multipart/form-data",
        headers=account["headers"],
    )
    assert resp.status_code == 202
    aid = resp.get_json()["analysis_id"]
    status, detail = _poll(client, account["headers"], aid)
    assert status == "completed"
    record = detail["record"]
    assert record["analysis_type"] == "steel_grain_size"
    assert record["input_source"] == "upload"

    rep = client.post("/api/reports/generate",
                      json={"analysis_id": aid},
                      headers=account["headers"])
    assert rep.status_code == 201
    full = rep.get_json()["full_report"]
    assert full["report_meta"]["report_kind"] == "steel_grain_size"
    assert "steel_grain_size" in full
    assert "iso_nodularity_pct" not in full
    # Uncalibrated upload: length measurements reported in pixels only
    assert full["scale_calibration"]["available"] is False
    m = full["steel_grain_size"]["gsat"]["measurements"]
    assert "mean_lineal_intercept_px" in m
    assert "mean_lineal_intercept_um" not in m
    assert "astm_grain_size_number" not in m


# --------------------------------------------------------------------------- #
# ASTM estimator deployment, runtime discovery & honesty tests
# --------------------------------------------------------------------------- #

def test_astm_interpreter_discovery(monkeypatch, tmp_path):
    dummy_py = tmp_path / "custom_python.exe"
    dummy_py.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    monkeypatch.setenv("NODIQ_ASTM_PYTHON", str(dummy_py))
    assert astm_adapter._venv_python() == str(dummy_py)

    monkeypatch.setenv("NODIQ_ASTM_PYTHON", str(tmp_path / "non_existent.exe"))
    assert astm_adapter._venv_python() is None


def test_astm_missing_dependencies(monkeypatch):
    """When interpreter lacks cellpose/torch, availability reports missing dependencies."""
    monkeypatch.setenv("NODIQ_ASTM_PYTHON", sys.executable)
    astm_adapter._VENV_CELLPOSE_CACHE.clear()
    av = astm_adapter.availability()
    assert av["available"] is False
    assert "cellpose" in av["missing"]
    assert "with-astm" in av.get("install_hint", "")


def test_astm_missing_weights(monkeypatch, tmp_path):
    """When weights are not pre-cached and download is not enabled, availability reports missing weights."""
    monkeypatch.setenv("CELLPOSE_LOCAL_MODELS_PATH", str(tmp_path))
    monkeypatch.setenv("NODIQ_ASTM_ALLOW_DOWNLOAD", "0")
    monkeypatch.setattr(astm_adapter, "_venv_python", lambda: sys.executable)
    monkeypatch.setattr(astm_adapter, "_venv_has_cellpose", lambda py: True)
    monkeypatch.setattr(astm_adapter, "_find_cached_weights", lambda ckpt: None)
    av = astm_adapter.availability()
    assert av["available"] is False
    assert "weights" in av["missing"]
    assert av["weights_cached"] is False
    assert "not pre-cached" in av.get("error", "")


def test_astm_model_initialization_failure(monkeypatch, tmp_path):
    """Corrupt model weight or failed initialization produces honest unavailable status."""
    corrupt_ckpt = tmp_path / "corrupt_model.pt"
    corrupt_ckpt.write_bytes(b"corrupted_model_content_header" * 100)
    monkeypatch.setenv("NODIQ_ASTM_CHECKPOINT", str(corrupt_ckpt))
    monkeypatch.setattr(astm_adapter, "_venv_python", lambda: sys.executable)
    monkeypatch.setattr(astm_adapter, "_venv_has_cellpose", lambda py: True)
    astm_adapter._VENV_INIT_CACHE.clear()
    av = astm_adapter.availability()
    assert av["available"] is False
    assert "model_initialization" in av["missing"]
    assert "failed" in av.get("error", "").lower()


def test_astm_docker_env_configuration(monkeypatch, tmp_path):
    """Test environment variable overrides for Docker containers."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    fake_cpsam = models_dir / "cpsam"
    fake_cpsam.write_bytes(b"0" * 2000)
    monkeypatch.setenv("CELLPOSE_LOCAL_MODELS_PATH", str(models_dir))
    found = astm_adapter._find_cached_weights("cpsam")
    assert found == fake_cpsam


def test_astm_successful_inference_when_configured(micrograph_png):
    """When runtime and weights are present, real Cellpose-SAM inference succeeds."""
    av = astm_adapter.availability()
    if not av["available"]:
        pytest.skip(f"ASTM runtime not configured: {av.get('error')}")
    rgb = cv2.imdecode(np.frombuffer(micrograph_png, np.uint8), cv2.IMREAD_COLOR)
    rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB)
    res = astm_adapter.run_astm_estimator(rgb, um_per_px=2.0)
    assert res["status"] == "completed"
    assert res["measurements"]["grain_count"] >= 1
    assert "mask" in res["images"]
    assert "overlay" in res["images"]
    assert "labels" in res["images"]




def test_astm_compare_preserves_partial_on_failure(monkeypatch, micrograph_png):
    """In Compare Both mode, ASTM unavailability preserves GSAT results with status=partial."""
    monkeypatch.setattr(astm_adapter, "availability", lambda: {
        "available": False, "missing": ["cellpose"],
        "error": "Simulated ASTM unavailable in container"
    })
    p = analyze_image(micrograph_png, calibration=1.2, method="compare")
    assert p["status"] == "partial"
    assert p["pipelines"]["gsat"]["status"] == "completed"
    assert p["pipelines"]["astm_estimator"]["status"] == "unavailable"
    assert p["comparison"]["complete"] is False
    assert any("INCOMPLETE" in n for n in p["comparison"]["notes"])

