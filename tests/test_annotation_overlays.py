import sys
from pathlib import Path

import numpy as np
import cv2


from nodiq.pipelines.nodularity_pipeline import (
    analyze_image, find_annotation_overlays, blank_figure_annotations)


def _micrograph(w=1920, h=1338, seed=7):
    """Synthetic polished-iron matrix with round graphite particles."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w), 205, dtype=np.uint8)
    # faint matrix mottling
    noise = rng.normal(0, 6, (h, w))
    img = np.clip(img.astype(np.int16) + noise.astype(np.int16), 0, 255)\
        .astype(np.uint8)
    for _ in range(90):
        r = int(rng.integers(18, 60))
        cx = int(rng.integers(r + 5, w - r - 5))
        cy = int(rng.integers(r + 5, h - r - 5))
        shade = int(rng.integers(25, 70))
        yy, xx = np.ogrid[:h, :w]
        img[(xx - cx) ** 2 + (yy - cy) ** 2 <= r ** 2] = shade
    return img


def _add_stats_panel(img, x, y, w=520, h=420):
    """Dark statistics panel like the ones publishers bake into figures."""
    img[y:y + h, x:x + w] = 28
    return img


def _add_scale_bar(img, x, y, w=260, h=80):
    """Black scale bar with glyph-like white lettering, as publishers bake
    into figures (text on the bar, NOT a window cut through it — and placed
    in clear matrix, where real scale bars live)."""
    img[y:y + h, x:x + w] = 20
    # "50 um" as three glyph patches in the bar's center band
    for gx in (x + 40, x + 110, x + 180):
        img[y + 22:y + h - 22, gx:gx + 45] = 245
    return img


def _add_label_box(img, x, y, s=140):
    """White panel-label box with a dark letter."""
    img[y:y + s, x:x + s] = 250
    img[y + 25:y + s - 25, x + 35:x + s - 35] = 30
    return img


def test_stats_panel_is_blanked():
    img = _micrograph()
    # wipe the region: real panels sit over clear matrix (hi5's panel raw
    # fill is 0.91), so the random field must not deeply overlap it
    img[900:1330, 1400:1880] = 205
    img = _add_stats_panel(img, 1450, 950)
    res = analyze_image(img)
    assert res["annotation_overlays"], "stats panel not detected"
    kinds = [b["kind"] for b in res["annotation_overlays"]]
    assert "dark" in kinds
    # without the fixture the count must not include the panel: the biggest
    # detection's area must stay far below the panel's area
    assert max(r["area_px"] for r in res["rows"]) < 300 * 300


def test_panel_bitten_by_particle_is_blanked():
    # hi5-sized panel with a big particle biting one corner -> the merged
    # component's fill drops below pass-1's 0.85, so the square-opening
    # pass must recover the panel core (L-shape keeps 3 solid corners)
    img = _micrograph()
    img[750:1330, 1200:1920] = 205
    img = _add_stats_panel(img, 1250, 800, w=612, h=475)
    yy, xx = np.ogrid[:img.shape[0], :img.shape[1]]
    img[(xx - 1250) ** 2 + (yy - 800) ** 2 <= 115 ** 2] = 35
    res = analyze_image(img)
    panel = [b for b in res["annotation_overlays"]
             if b["x"] >= 1150 and b["y"] >= 700
             and b["w"] >= 400 and b["h"] >= 300]
    assert panel, f"overlapped panel not detected: {res['annotation_overlays']}"


def test_scale_bar_is_blanked():
    img = _micrograph()
    # real scale bars sit in clear matrix: wipe the region first so the
    # random particle field cannot deeply overlap the bar
    img[1100:1330, 100:530] = 205
    img = _add_scale_bar(img, 150, 1180)
    res = analyze_image(img)
    boxes = res["annotation_overlays"]
    assert boxes, "scale bar not detected"
    bar = [b for b in boxes if b["x"] <= 150 + 40 and b["y"] >= 1180 - 40]
    assert bar, "scale bar location not among blanked overlays"


def test_label_box_is_blanked():
    img = _micrograph()
    img = _add_label_box(img, 20, 1120)
    res = analyze_image(img)
    assert res["annotation_overlays"], "label box not detected"
    assert any(b["kind"] == "white" for b in res["annotation_overlays"])


def test_clean_micrograph_is_untouched():
    img = _micrograph()
    boxes = find_annotation_overlays(img)
    assert boxes == [], f"clean micrograph flagged: {boxes}"
    _, out_boxes = blank_figure_annotations(img)
    assert out_boxes == []


def test_bar_touching_a_particle_is_blanked():
    # hi5-style: the scale bar GRAZES a real particle at its end. The opening
    # pass must still recover the bar's solid core. (A bar DEEPLY overlapped
    # by a large particle is out of scope — no publisher figure does that.)
    img = _micrograph()
    img[1100:1330, 100:620] = 205
    yy, xx = np.ogrid[:img.shape[0], :img.shape[1]]
    img[(xx - 468) ** 2 + (yy - 1215) ** 2 <= 56 ** 2] = 35   # grazes bar end
    img = _add_scale_bar(img, 150, 1180)
    res = analyze_image(img)
    bar = [b for b in res["annotation_overlays"]
           if b["x"] <= 150 + 40 and b["y"] >= 1180 - 40]
    assert bar, "bar grazing a particle not detected"


def test_large_edge_particle_is_not_blanked():
    # a big graphite particle clipped by the frame edge is REAL graphite:
    # it must survive even though it is large and dark
    img = _micrograph()
    img[900:1300, 100:320] = 30          # 220x400 blob at the left region
    res = analyze_image(img)
    hits = [b for b in res["annotation_overlays"]
            if b["x"] < 400 and b["y"] > 800]
    assert hits == [], f"real particle blanked: {hits}"


def test_warning_emitted_for_overlays():
    img = _micrograph()
    img[900:1330, 1400:1880] = 205
    img = _add_stats_panel(img, 1450, 950)
    res = analyze_image(img)
    assert any("annotation" in w.lower() for w in res["warnings"])
