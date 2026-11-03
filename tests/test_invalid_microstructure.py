import sys
from pathlib import Path

import numpy as np


from nodiq.pipelines.nodularity_pipeline import analyze_image, evaluate_microstructure_validity


def _random_photo(w=1200, h=900, seed=0):
    rng = np.random.default_rng(seed)
    img = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    return img


def _micrograph_like(w=1200, h=900, seed=0):
    rng = np.random.default_rng(seed)
    img = np.full((h, w), 200, dtype=np.uint8)
    for _ in range(120):
        r = int(rng.integers(5, 20))
        cx = int(rng.integers(r + 5, w - r - 5))
        cy = int(rng.integers(r + 5, h - r - 5))
        shade = int(rng.integers(20, 80))
        yy, xx = np.ogrid[:h, :w]
        mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r ** 2
        img[mask] = shade
    return img


def test_random_photo_is_rejected():
    photo = _random_photo()
    res = analyze_image(photo)
    gate = evaluate_microstructure_validity(photo, res)
    assert gate["valid"] is False
    assert gate["status"] == "invalid_microstructure"
    assert gate["reason"]
    assert res["count"] >= 0


def test_black_and_white_images_are_rejected():
    for value in (0, 255):
        img = np.full((600, 800, 3), value, dtype=np.uint8)
        res = analyze_image(img)
        gate = evaluate_microstructure_validity(img, res)
        assert gate["valid"] is False
        assert gate["status"] == "invalid_microstructure"


def test_micrograph_like_image_passes_gate():
    img = _micrograph_like()
    res = analyze_image(img)
    gate = evaluate_microstructure_validity(img, res)
    assert gate["valid"] is True
    assert gate["status"] in {"complete", "valid"}


import cv2


def _colored_landscape_photo(w=1200, h=900, seed=3):
    """Regression case (user report): bright, blue-tinted terrain with a dark
    crack network (salt-flat-like photograph). Passes every pre-color gate
    rule (textured, many dark components, mostly bright) yet is not a
    micrograph and must not yield a nodularity prediction."""
    rng = np.random.default_rng(seed)
    h_sky = int(h * 0.18)
    grid = np.mgrid[0:h, 0:w].astype(np.float32)
    yy, xx = grid[0], grid[1]
    mottle = np.sin(xx / 47.0) * np.cos(yy / 61.0)
    img = np.empty((h, w, 3), np.float32)
    img[..., 0] = 185 + 12 * mottle + rng.normal(0, 6, (h, w))   # B: blue-dominant
    img[..., 1] = 140 + 10 * mottle + rng.normal(0, 6, (h, w))   # G
    img[..., 2] = 90 + 8 * mottle + rng.normal(0, 6, (h, w))     # R
    ridge = (h_sky + 28 * np.sin(xx[0] / 91.0)).astype(np.int32)
    img[:h_sky, :, :] += 40.0
    for x in range(w):
        img[:ridge[x], x, :] = 205.0                              # bright sky
    img = np.clip(img, 0, 255)
    cracks = np.zeros((h, w), np.uint8)
    for _ in range(300):
        pts = [(int(rng.integers(0, w)),
                int(h_sky + rng.integers(0, h - h_sky)))]
        for _ in range(int(rng.integers(4, 15))):
            x0 = pts[-1][0] + int(rng.integers(-55, 56))
            y0 = pts[-1][1] + int(rng.integers(-16, 17))
            pts.append((int(np.clip(x0, 0, w - 1)),
                        int(np.clip(y0, h_sky, h - 1))))
        cv2.polylines(cracks, [np.array(pts, np.int32)], False, 1, 3)
    img[cracks > 0] = (45, 45, 45)
    return img.astype(np.uint8)


def test_colored_natural_photo_is_rejected():
    photo = _colored_landscape_photo()
    res = analyze_image(photo)
    gate = evaluate_microstructure_validity(photo, res)
    assert gate["valid"] is False, gate
    assert gate["status"] == "invalid_microstructure"
    assert "colored" in gate["reason"], gate


def test_mildly_tinted_micrograph_still_passes_gate():
    img = cv2.cvtColor(_micrograph_like(), cv2.COLOR_GRAY2BGR)
    img[..., 0] = np.clip(img[..., 0].astype(np.int16) + 14, 0, 255).astype(np.uint8)
    gate = evaluate_microstructure_validity(img)
    assert gate["valid"] is True, gate
