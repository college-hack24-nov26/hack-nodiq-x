"""Unit tests for tools/mask_reviewer.py.

Verifies:
1. Screen-to-canvas coordinate mapping under zoom and pan.
2. Simulated continuous brush strokes (drawing 255 white foreground).
3. Simulated continuous eraser strokes (clearing to 0 black background).
4. Mask array validation: shape (1944, 2592), uint8, strictly binary {0, 255}.
5. Safe atomic saving: atomic replacement, overwrite confirmation, path traversal defense, protected files.
6. Security policy: server binds strictly to 127.0.0.1 and rejects external interfaces.
7. End-to-end HTTP endpoints (/api/status, /api/save) with base64 PNG payload.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import cv2
import numpy as np
import pytest

from scripts.tools.mask_reviewer import (
    validate_mask_array,
    validate_mask_file,
    save_reviewed_mask_atomically,
    check_staging_prerequisites,
    screen_to_canvas_coords,
    apply_brush_stroke,
    run_reviewer_server,
    resolve_sample_paths,
    get_dataset_samples_manifest,
    EXPECTED_SHAPE,
    ALLOWED_MASKS_DIR,
    PROTECTED_FILENAMES,
)


@pytest.fixture
def temp_workspace():
    d = Path(tempfile.mkdtemp(prefix="test_reviewer_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_screen_to_canvas_coordinate_mapping():
    """Verify coordinate conversion from screen to full-resolution canvas under zoom & pan."""
    # 1. 1:1 scale with no offset
    cx, cy = screen_to_canvas_coords(500, 300, offset_x=0, offset_y=0, scale=1.0)
    assert cx == 500
    assert cy == 300

    # 2. 2.5x zoom with positive pan
    cx, cy = screen_to_canvas_coords(625, 450, offset_x=100, offset_y=50, scale=2.5)
    # (625 - 100) / 2.5 = 210, (450 - 50) / 2.5 = 160
    assert pytest.approx(cx) == 210.0
    assert pytest.approx(cy) == 160.0

    # 3. 0.4x zoom with negative pan
    cx, cy = screen_to_canvas_coords(200, 100, offset_x=-50, offset_y=-20, scale=0.4)
    # (200 - (-50)) / 0.4 = 625, (100 - (-20)) / 0.4 = 300
    assert pytest.approx(cx) == 625.0
    assert pytest.approx(cy) == 300.0


def test_brush_stroke_draws_white_foreground():
    """Verify brush stroke applies value 255 (white) within radius."""
    h, w = EXPECTED_SHAPE
    mask = np.zeros((h, w), dtype=np.uint8)

    # Stroke from (500, 500) to (550, 500) with radius 20
    edited = apply_brush_stroke(mask, pt1=(500, 500), pt2=(550, 500), radius=20, value=255)

    # Center points must be 255
    assert edited[500, 500] == 255
    assert edited[500, 525] == 255
    assert edited[500, 550] == 255

    # Within radius must be 255
    assert edited[515, 500] == 255
    assert edited[485, 500] == 255

    # Far away points must remain 0
    assert edited[400, 400] == 0
    assert edited[600, 600] == 0

    # Mask must remain binary uint8
    assert set(np.unique(edited)).issubset({0, 255})
    assert edited.shape == (h, w)


def test_eraser_stroke_clears_to_black_background():
    """Verify eraser stroke clears foreground pixels to 0 (black)."""
    h, w = EXPECTED_SHAPE
    # Initially fully white region
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[450:600, 450:650] = 255

    # Erase stroke through center
    edited = apply_brush_stroke(mask, pt1=(500, 500), pt2=(550, 500), radius=25, value=0)

    # Erased points must now be 0
    assert edited[500, 500] == 0
    assert edited[500, 525] == 0
    assert edited[500, 550] == 0
    assert edited[515, 500] == 0

    # Points outside eraser radius must remain 255
    assert edited[580, 580] == 255
    assert edited[460, 460] == 255

    # Mask must remain binary uint8
    assert set(np.unique(edited)).issubset({0, 255})
    assert edited.shape == (h, w)


def test_validate_mask_array_success():
    h, w = EXPECTED_SHAPE
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[100:200, 100:200] = 255

    ok, msg, meta = validate_mask_array(mask)
    assert ok is True
    assert meta["width"] == w
    assert meta["height"] == h
    assert meta["unique_values"] == [0, 255]
    assert meta["area_fraction_pct"] > 0.0


def test_validate_mask_array_rejects_invalid_inputs():
    h, w = EXPECTED_SHAPE

    # 1. Non-binary values
    bad_val_mask = np.zeros((h, w), dtype=np.uint8)
    bad_val_mask[10, 10] = 128
    ok, msg, _ = validate_mask_array(bad_val_mask)
    assert ok is False
    assert "non-binary" in msg.lower()

    # 2. Wrong dimensions
    wrong_dim = np.zeros((512, 512), dtype=np.uint8)
    ok, msg, _ = validate_mask_array(wrong_dim)
    assert ok is False
    assert "dimension mismatch" in msg.lower()

    # 3. Multi-channel
    rgb_mask = np.zeros((h, w, 3), dtype=np.uint8)
    ok, msg, _ = validate_mask_array(rgb_mask)
    assert ok is False
    assert "single-channel" in msg.lower()

    # 4. None / wrong type
    ok, msg, _ = validate_mask_array(None)
    assert ok is False


def test_check_staging_prerequisites(temp_workspace):
    img_path = temp_workspace / "sample_test.bmp"
    mask_path = temp_workspace / "mask_test.png"

    # Missing image
    ok, msg, _ = check_staging_prerequisites(img_path, mask_path)
    assert ok is False
    assert "micrograph not found" in msg.lower()

    # Create image
    img = np.ones((EXPECTED_SHAPE[0], EXPECTED_SHAPE[1], 3), dtype=np.uint8) * 180
    cv2.imwrite(str(img_path), img)

    # Missing mask
    ok, msg, _ = check_staging_prerequisites(img_path, mask_path)
    assert ok is False
    assert "draft mask not found" in msg.lower()

    # Dimension mismatch
    wrong_mask = np.zeros((512, 512), dtype=np.uint8)
    cv2.imwrite(str(mask_path), wrong_mask)
    ok, msg, _ = check_staging_prerequisites(img_path, mask_path)
    assert ok is False
    assert "dimension mismatch" in msg.lower()

    # Matching dimensions
    good_mask = np.zeros(EXPECTED_SHAPE, dtype=np.uint8)
    cv2.imwrite(str(mask_path), good_mask)
    ok, msg, status = check_staging_prerequisites(img_path, mask_path)
    assert ok is True
    assert status["dimensions_match"] is True


def test_save_reviewed_mask_atomically_safeguards():
    h, w = EXPECTED_SHAPE
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[50:150, 50:150] = 255

    target_path = ALLOWED_MASKS_DIR / "sample_1_test_reviewed_temp.png"
    if target_path.exists():
        target_path.unlink()

    # 1. Clean first save succeeds
    ok, msg, meta = save_reviewed_mask_atomically(mask, target_path, overwrite=False)
    assert ok is True
    assert target_path.exists()
    assert meta["width"] == w
    assert meta["height"] == h

    # 2. Existing file prevents silent overwrite
    ok, msg, meta = save_reviewed_mask_atomically(mask, target_path, overwrite=False)
    assert ok is False
    assert meta.get("requires_confirmation") is True

    # 3. Explicit overwrite succeeds
    ok, msg, meta = save_reviewed_mask_atomically(mask, target_path, overwrite=True)
    assert ok is True

    # 4. Protected file names are blocked
    for protected in ("sample_1.bmp", "sample_1_draft.png", "sample_1_draft_v2.png"):
        bad_path = ALLOWED_MASKS_DIR / protected
        ok, msg, _ = save_reviewed_mask_atomically(mask, bad_path, overwrite=True)
        assert ok is False
        assert "protected file" in msg.lower()

    # 5. Path traversal is blocked
    traversal_path = ALLOWED_MASKS_DIR / ".." / ".." / "evil.png"
    ok, msg, _ = save_reviewed_mask_atomically(mask, traversal_path, overwrite=True)
    assert ok is False
    assert "security violation" in msg.lower()

    # Clean up test artifact
    if target_path.exists():
        target_path.unlink()


def test_server_security_binds_to_localhost_only():
    with pytest.raises(ValueError, match="Security policy"):
        run_reviewer_server(host="0.0.0.0", port=5099, open_browser=False)

    with pytest.raises(ValueError, match="Security policy"):
        run_reviewer_server(host="192.168.1.100", port=5099, open_browser=False)


def test_server_save_endpoint_with_base64_payload():
    """Verify HTTP POST /api/save accepts canvas data URL, validates, and atomically writes mask."""
    server_port = 5062
    target_reviewed_path = ALLOWED_MASKS_DIR / "sample_1_api_test_reviewed.png"
    if target_reviewed_path.exists():
        target_reviewed_path.unlink()

    server = run_reviewer_server(
        host="127.0.0.1",
        port=server_port,
        open_browser=False,
        reviewed_path=target_reviewed_path,
    )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)

    try:
        # Create full-res 2592x1944 binary mask with edited strokes
        h, w = EXPECTED_SHAPE
        test_mask = np.zeros((h, w), dtype=np.uint8)
        test_mask[200:400, 200:400] = 255

        # Encode as PNG data URL (as sent by frontend canvas)
        ok, buf = cv2.imencode(".png", test_mask)
        assert ok is True
        b64_png = base64.b64encode(buf.tobytes()).decode("utf-8")
        data_url = f"data:image/png;base64,{b64_png}"

        # POST to /api/save
        payload = json.dumps({"image_data": data_url, "overwrite": True}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{server_port}/api/save",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert data["width"] == w
            assert data["height"] == h
            assert data["unique_values"] == [0, 255]

        # Verify saved file on disk
        assert target_reviewed_path.exists()
        saved_img = cv2.imread(str(target_reviewed_path), cv2.IMREAD_UNCHANGED)
        assert saved_img.shape == (h, w)
        assert saved_img.ndim == 2
        assert saved_img.dtype == np.uint8
        assert set(np.unique(saved_img)).issubset({0, 255})
    finally:
        server.shutdown()
        server.server_close()
        if target_reviewed_path.exists():
            target_reviewed_path.unlink()


def test_resolve_sample_paths():
    """Verify sample path resolution for Sample 1, Sample 2, and edge case identifiers."""
    # Sample 1 variants
    for key in (None, "", "1", "sample_1", "sample_1.bmp"):
        img, draft, rev, s_name = resolve_sample_paths(key)
        assert s_name == "sample_1"
        assert img.name == "sample_1.bmp"
        assert draft.name == "sample_1_draft_v2.png"
        assert rev.name == "sample_1_reviewed.png"

    # Sample 2 variants
    for key in ("2", "sample_2", "sample_2.bmp"):
        img, draft, rev, s_name = resolve_sample_paths(key)
        assert s_name == "sample_2"
        assert img.name == "sample_2.bmp"
        assert draft.name == "sample_2_draft_v2.png"
        assert rev.name == "sample_2_reviewed.png"


def test_sample_2_prerequisites_and_protection():
    """Verify Sample 2 staging prerequisites, cross-sample protection, and draft immutability."""
    img_2, draft_2, rev_2, _ = resolve_sample_paths("2")
    assert img_2.is_file(), f"Expected sample_2.bmp to exist at {img_2}"
    assert draft_2.is_file(), f"Expected sample_2_draft_v2.png to exist at {draft_2}"

    # 1. Prerequisites check
    ok, msg, status = check_staging_prerequisites(img_2, draft_2)
    assert ok is True
    assert status["dimensions_match"] is True
    assert status["image_dims"] == [EXPECTED_SHAPE[1], EXPECTED_SHAPE[0]]
    assert status["mask_dims"] == [EXPECTED_SHAPE[1], EXPECTED_SHAPE[0]]

    # 2. Protection of sample_2 raw image and draft mask
    h, w = EXPECTED_SHAPE
    dummy_mask = np.zeros((h, w), dtype=np.uint8)

    bad_draft = ALLOWED_MASKS_DIR / "sample_2_draft_v2.png"
    ok, msg, _ = save_reviewed_mask_atomically(dummy_mask, bad_draft, overwrite=True)
    assert ok is False
    assert "protected file" in msg.lower()

    # 3. Cross-sample protection: sample 2 review must never overwrite sample 1 reviewed mask
    sample_1_rev = ALLOWED_MASKS_DIR / "sample_1_reviewed.png"
    ok, msg, _ = save_reviewed_mask_atomically(dummy_mask, sample_1_rev, overwrite=True, current_sample="sample_2")
    assert ok is False
    assert "cannot overwrite sample 1 reviewed mask" in msg.lower()

    # 4. Cross-sample protection: sample 1 review must never overwrite sample 2 reviewed mask
    sample_2_rev = ALLOWED_MASKS_DIR / "sample_2_reviewed.png"
    ok, msg, _ = save_reviewed_mask_atomically(dummy_mask, sample_2_rev, overwrite=True, current_sample="sample_1")
    assert ok is False
    assert "cannot overwrite sample 2 reviewed mask" in msg.lower()


def test_server_handles_sample_2_endpoints():
    """Verify server status, image, mask, and save endpoints for Sample 2."""
    server_port = 5064
    target_reviewed_path = ALLOWED_MASKS_DIR / "sample_2_api_test_reviewed.png"
    if target_reviewed_path.exists():
        target_reviewed_path.unlink()

    server = run_reviewer_server(
        host="127.0.0.1",
        port=server_port,
        open_browser=False,
        sample="2",
        reviewed_path=target_reviewed_path,
    )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)

    try:
        # 1. GET /api/status?sample=2
        with urllib.request.urlopen(f"http://127.0.0.1:{server_port}/api/status?sample=2") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert data["sample"] == "sample_2"
            assert data["dimensions_match"] is True

        # 2. GET /api/image?sample=2
        with urllib.request.urlopen(f"http://127.0.0.1:{server_port}/api/image?sample=2") as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "image/png"
            img_bytes = resp.read()
            assert len(img_bytes) > 100_000

        # 3. GET /api/mask?sample=2
        with urllib.request.urlopen(f"http://127.0.0.1:{server_port}/api/mask?sample=2") as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "image/png"
            mask_bytes = resp.read()
            assert len(mask_bytes) > 50_000

        # 4. POST /api/save with sample 2
        h, w = EXPECTED_SHAPE
        test_mask = np.zeros((h, w), dtype=np.uint8)
        test_mask[300:500, 300:500] = 255

        ok, buf = cv2.imencode(".png", test_mask)
        assert ok is True
        b64_png = base64.b64encode(buf.tobytes()).decode("utf-8")
        data_url = f"data:image/png;base64,{b64_png}"

        payload = json.dumps({"image_data": data_url, "overwrite": True, "sample": "2"}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{server_port}/api/save",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            res_data = json.loads(resp.read().decode("utf-8"))
            assert res_data["ok"] is True
            assert res_data["unique_values"] == [0, 255]

        # Verify disk save
        assert target_reviewed_path.exists()
        saved = cv2.imread(str(target_reviewed_path), cv2.IMREAD_UNCHANGED)
        assert saved.shape == (h, w)
        assert saved.dtype == np.uint8
        assert set(np.unique(saved)).issubset({0, 255})
    finally:
        server.shutdown()
        server.server_close()
        if target_reviewed_path.exists():
            target_reviewed_path.unlink()


def test_sample_3_prerequisites_and_protection():
    """Verify Sample 3 staging prerequisites, cross-sample protection of 1 & 2, and draft immutability."""
    img_3, draft_3, rev_3, _ = resolve_sample_paths("3")
    assert img_3.is_file(), f"Expected sample_3.bmp to exist at {img_3}"
    assert draft_3.is_file(), f"Expected sample_3_draft_v2.png to exist at {draft_3}"

    # 1. Check existing reviewed masks for Sample 1 and 2 exist and are intact
    sample_1_rev = ALLOWED_MASKS_DIR / "sample_1_reviewed.png"
    sample_2_rev = ALLOWED_MASKS_DIR / "sample_2_reviewed.png"
    assert sample_1_rev.is_file(), "sample_1_reviewed.png must exist"
    assert sample_2_rev.is_file(), "sample_2_reviewed.png must exist"

    # 2. Prerequisites check for sample 3
    ok, msg, status = check_staging_prerequisites(img_3, draft_3)
    assert ok is True
    assert status["dimensions_match"] is True
    assert status["image_dims"] == [EXPECTED_SHAPE[1], EXPECTED_SHAPE[0]]
    assert status["mask_dims"] == [EXPECTED_SHAPE[1], EXPECTED_SHAPE[0]]

    # 3. Protection of sample_3 raw image and draft mask
    h, w = EXPECTED_SHAPE
    dummy_mask = np.zeros((h, w), dtype=np.uint8)

    bad_draft = ALLOWED_MASKS_DIR / "sample_3_draft_v2.png"
    ok, msg, _ = save_reviewed_mask_atomically(dummy_mask, bad_draft, overwrite=True)
    assert ok is False
    assert "protected file" in msg.lower()

    # 4. Cross-sample protection: sample 3 review must never overwrite sample 1 or sample 2 reviewed masks
    ok1, _, _ = save_reviewed_mask_atomically(dummy_mask, sample_1_rev, overwrite=True, current_sample="sample_3")
    assert ok1 is False

    ok2, _, _ = save_reviewed_mask_atomically(dummy_mask, sample_2_rev, overwrite=True, current_sample="sample_3")
    assert ok2 is False


def test_server_handles_sample_3_endpoints():
    """Verify server status, image, mask, and save endpoints for Sample 3."""
    server_port = 5065
    target_reviewed_path = ALLOWED_MASKS_DIR / "sample_3_api_test_reviewed.png"
    if target_reviewed_path.exists():
        target_reviewed_path.unlink()

    server = run_reviewer_server(
        host="127.0.0.1",
        port=server_port,
        open_browser=False,
        sample="3",
        reviewed_path=target_reviewed_path,
    )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)

    try:
        # 1. GET /api/status?sample=3
        with urllib.request.urlopen(f"http://127.0.0.1:{server_port}/api/status?sample=3") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert data["sample"] == "sample_3"
            assert data["dimensions_match"] is True

        # 2. GET /api/image?sample=3
        with urllib.request.urlopen(f"http://127.0.0.1:{server_port}/api/image?sample=3") as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "image/png"
            img_bytes = resp.read()
            assert len(img_bytes) > 100_000

        # 3. GET /api/mask?sample=3
        with urllib.request.urlopen(f"http://127.0.0.1:{server_port}/api/mask?sample=3") as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "image/png"
            mask_bytes = resp.read()
            assert len(mask_bytes) > 50_000

        # 4. POST /api/save with sample 3
        h, w = EXPECTED_SHAPE
        test_mask = np.zeros((h, w), dtype=np.uint8)
        test_mask[400:600, 400:600] = 255

        ok, buf = cv2.imencode(".png", test_mask)
        assert ok is True
        b64_png = base64.b64encode(buf.tobytes()).decode("utf-8")
        data_url = f"data:image/png;base64,{b64_png}"

        payload = json.dumps({"image_data": data_url, "overwrite": True, "sample": "3"}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{server_port}/api/save",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            res_data = json.loads(resp.read().decode("utf-8"))
            assert res_data["ok"] is True
            assert res_data["unique_values"] == [0, 255]

        # Verify disk save
        assert target_reviewed_path.exists()
        saved = cv2.imread(str(target_reviewed_path), cv2.IMREAD_UNCHANGED)
        assert saved.shape == (h, w)
        assert saved.dtype == np.uint8
        assert set(np.unique(saved)).issubset({0, 255})
    finally:
        server.shutdown()
        server.server_close()
        if target_reviewed_path.exists():
            target_reviewed_path.unlink()


def test_validate_mask_file_disk_validation():
    """Verify disk-level validation for 2592x1944 single-channel uint8 binary {0, 255} masks."""
    # 1. Existing verified reviewed masks (Samples 1, 2, and 3)
    for rev_name in ("sample_1_reviewed.png", "sample_2_reviewed.png", "sample_3_reviewed.png"):
        p = ALLOWED_MASKS_DIR / rev_name
        ok, msg, meta = validate_mask_file(p)
        assert ok is True, f"Validation failed for {rev_name}: {msg}"
        assert meta["width"] == EXPECTED_SHAPE[1]
        assert meta["height"] == EXPECTED_SHAPE[0]
        assert set(meta["unique_values"]).issubset({0, 255})
        assert meta["area_fraction_pct"] > 0.0

    # 2. Draft mask for sample 3
    draft_3 = ALLOWED_MASKS_DIR / "sample_3_draft_v2.png"
    ok, msg, meta = validate_mask_file(draft_3)
    assert ok is True, f"Validation failed for sample_3_draft_v2.png: {msg}"
    assert meta["width"] == EXPECTED_SHAPE[1]
    assert meta["height"] == EXPECTED_SHAPE[0]
    assert set(meta["unique_values"]).issubset({0, 255})
    assert pytest.approx(meta["area_fraction_pct"], abs=0.1) == 14.13


def test_dataset_samples_manifest():
    """Verify that get_dataset_samples_manifest correctly categorizes all 20 samples."""
    manifest = get_dataset_samples_manifest()
    assert len(manifest) == 20

    status_counts = {"REVIEWED": 0, "AWAITING_REVIEW": 0, "MISSING_SOURCE": 0, "FAILED": 0}
    for item in manifest:
        status_counts[item["status"]] += 1

    # Verify counts: exactly 3 reviewed, 1 missing (sample_12), 16 awaiting review, 0 failed
    assert status_counts["REVIEWED"] == 3
    assert status_counts["MISSING_SOURCE"] == 1
    assert status_counts["AWAITING_REVIEW"] == 16
    assert status_counts["FAILED"] == 0

    # Verify sample 12 specifically
    sample_12 = manifest[11]
    assert sample_12["id"] == "12"
    assert sample_12["sample_name"] == "sample_12"
    assert sample_12["status"] == "MISSING_SOURCE"
    assert sample_12["image_exists"] is False

    # Verify samples 1, 2, 3 specifically
    for idx in (1, 2, 3):
        s = manifest[idx - 1]
        assert s["status"] == "REVIEWED"
        assert s["reviewed_exists"] is True


def test_cross_sample_protection_all_samples():
    """Verify that edits on any sample cannot overwrite any other sample's reviewed mask."""
    h, w = EXPECTED_SHAPE
    dummy_mask = np.zeros((h, w), dtype=np.uint8)

    # When reviewing sample 4, attempts to write to sample 1, 2, or 3 reviewed masks must fail
    for target_idx in (1, 2, 3):
        target_path = ALLOWED_MASKS_DIR / f"sample_{target_idx}_reviewed.png"
        ok, msg, _ = save_reviewed_mask_atomically(
            dummy_mask, target_path, overwrite=True, current_sample="sample_4"
        )
        assert ok is False
        assert f"sample {target_idx} reviewed mask" in msg.lower() or "cross-sample" in msg.lower()

    # When reviewing sample 10, attempts to write to sample 4 reviewed mask must fail
    sample_4_rev = ALLOWED_MASKS_DIR / "sample_4_reviewed.png"
    ok, msg, _ = save_reviewed_mask_atomically(
        dummy_mask, sample_4_rev, overwrite=True, current_sample="sample_10"
    )
    assert ok is False

    # Protection of any sample's raw image or draft
    for sample_num in (4, 15, 20):
        bad_draft = ALLOWED_MASKS_DIR / f"sample_{sample_num}_draft_v2.png"
        ok, msg, _ = save_reviewed_mask_atomically(dummy_mask, bad_draft, overwrite=True)
        assert ok is False
        assert "protected file" in msg.lower()


def test_server_handles_sample_manifest_api():
    """Verify server GET /api/samples returns full 20-sample manifest with correct schema."""
    server_port = 5066
    server = run_reviewer_server(
        host="127.0.0.1",
        port=server_port,
        open_browser=False,
        sample="4",
    )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{server_port}/api/samples") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert data["total_samples"] == 20
            assert len(data["samples"]) == 20
            # Check sample 12
            s12 = [s for s in data["samples"] if s["id"] == "12"][0]
            assert s12["status"] == "MISSING_SOURCE"
            # Check sample 4
            s4 = [s for s in data["samples"] if s["id"] == "4"][0]
            assert s4["status"] == "AWAITING_REVIEW"
    finally:
        server.shutdown()
        server.server_close()


def test_all_generated_draft_masks_validation():
    """Verify that all 19 draft masks on disk match (1944, 2592), uint8, and binary {0, 255}."""
    for i in range(1, 21):
        if i == 12:
            continue
        draft_path = ALLOWED_MASKS_DIR / f"sample_{i}_draft_v2.png"
        assert draft_path.is_file(), f"Expected draft mask to exist: {draft_path}"
        ok, msg, meta = validate_mask_file(draft_path)
        assert ok is True, f"Validation failed for sample_{i}_draft_v2.png: {msg}"
        assert meta["width"] == EXPECTED_SHAPE[1]
        assert meta["height"] == EXPECTED_SHAPE[0]
        assert set(meta["unique_values"]).issubset({0, 255})
        assert meta["area_fraction_pct"] > 0.0


def test_reviewed_masks_preservation():
    """Ensure reviewed masks for samples 1, 2, and 3 are present, valid, and uncorrupted."""
    for idx in (1, 2, 3):
        rev_path = ALLOWED_MASKS_DIR / f"sample_{idx}_reviewed.png"
        assert rev_path.is_file(), f"Reviewed mask missing: {rev_path}"
        ok, msg, meta = validate_mask_file(rev_path)
        assert ok is True, f"Reviewed mask invalid: {msg}"
        assert meta["width"] == EXPECTED_SHAPE[1]
        assert meta["height"] == EXPECTED_SHAPE[0]
        assert set(meta["unique_values"]).issubset({0, 255})




