"""Generate Illumination-Corrected Draft Mask (V2) for sample_3.bmp.

Performs:
1. Large-scale Gaussian background estimation (kernel 151x151) to model optical vignetting.
2. Local contrast extraction via background subtraction (bg - gray).
3. Contrast-guided thresholding (t=11) + 3x3 elliptical morphological opening.
4. Small noise speckle rejection (<15 px²).

Outputs:
- data/gray_cast_iron_raw/masks/sample_3_draft_v2.png (single-channel 8-bit PNG, {0, 255})
- data/gray_cast_iron_raw/sample_3_v2_comparison_preview.png (3-panel comparison preview)
- data/gray_cast_iron_raw/sample_3_v2_diagnostics.json
"""
from __future__ import annotations

import json
from pathlib import Path
import cv2
import numpy as np

from nodiq.core.config import GRAY_CAST_IRON_RAW_DIR

SRC_IMAGE_PATH = GRAY_CAST_IRON_RAW_DIR / "images" / "sample_3.bmp"
V2_MASK_PATH = GRAY_CAST_IRON_RAW_DIR / "masks" / "sample_3_draft_v2.png"
OUT_PREVIEW_PATH = GRAY_CAST_IRON_RAW_DIR / "sample_3_v2_comparison_preview.png"
ARTIFACT_DIR = Path(r"C:\Users\Atharv\.gemini\antigravity-ide\brain\9e971599-989c-4da2-9410-50537f25ee4d")

# Safeguards: verified existing reviewed masks
PROTECTED_REVIEWED = [
    GRAY_CAST_IRON_RAW_DIR / "masks" / "sample_1_reviewed.png",
    GRAY_CAST_IRON_RAW_DIR / "masks" / "sample_2_reviewed.png",
]


def generate_v2_sample_3():
    # 1. Verification of inputs and existing reviewed masks
    if not SRC_IMAGE_PATH.exists():
        raise FileNotFoundError(f"Source image not found: {SRC_IMAGE_PATH}")

    for r_path in PROTECTED_REVIEWED:
        if not r_path.exists():
            raise FileNotFoundError(f"Required existing reviewed mask not found: {r_path}")
        print(f"[VERIFIED] Existing reviewed mask preserved: {r_path} ({r_path.stat().st_size:,} bytes)")

    # 2. Load image
    img = cv2.imread(str(SRC_IMAGE_PATH))
    if img is None:
        raise ValueError(f"Failed to read image at {SRC_IMAGE_PATH}")
    h, w = img.shape[:2]
    total_pixels = h * w

    # 3. Illumination Background Estimation
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bg = cv2.GaussianBlur(gray, (151, 151), 0).astype(np.float32)

    # 4. Local Dark Feature Extraction (Difference = Background - Gray)
    diff = cv2.subtract(bg.astype(np.uint8), gray)

    # 5. Local Contrast Thresholding (t=11)
    _, m_raw = cv2.threshold(diff, 11, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    m_clean = cv2.morphologyEx(m_raw, cv2.MORPH_OPEN, kernel)

    # 6. Filter out tiny superficial noise (< 15 px²)
    num_cc, labels, stats, centroids = cv2.connectedComponentsWithStats(m_clean, 8)
    v2_mask = np.zeros_like(m_clean)
    for i in range(1, num_cc):
        if stats[i, cv2.CC_STAT_AREA] >= 15:
            v2_mask[labels == i] = 255

    # 7. Verify single-channel 8-bit binary constraints
    assert v2_mask.shape == (h, w), f"Shape mismatch: {v2_mask.shape} vs ({h}, {w})"
    assert v2_mask.dtype == np.uint8, f"Dtype mismatch: {v2_mask.dtype}"
    unique_vals = set(np.unique(v2_mask))
    assert unique_vals.issubset({0, 255}), f"Non-binary values found: {unique_vals}"

    # 8. Save V2 draft mask without overwriting any original images or existing masks
    V2_MASK_PATH.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(V2_MASK_PATH), v2_mask)
    print(f"[OK] Saved V2 draft mask: {V2_MASK_PATH} ({w}x{h}, single-channel 8-bit PNG)")

    # 9. Build V2 Overlay (Cyan highlight B=255, G=220, R=0, alpha=0.45)
    overlay_v2 = img.copy()
    color_mask = np.zeros_like(overlay_v2)
    color_mask[v2_mask == 255] = (255, 220, 0)
    alpha = 0.45
    blended = cv2.addWeighted(color_mask, alpha, overlay_v2, 1.0 - alpha, 0)
    overlay_v2[v2_mask == 255] = blended[v2_mask == 255]

    contours, _ = cv2.findContours(v2_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay_v2, contours, -1, (0, 255, 120), 1, cv2.LINE_AA)

    # 10. Build 3-panel comparison preview:
    # Panel 1: Original Micrograph
    # Panel 2: V2 Illumination-Corrected Draft Mask
    # Panel 3: V2 Overlay Preview
    prev_w = 800
    prev_h = int(h * (prev_w / w))

    p1 = cv2.resize(img, (prev_w, prev_h), interpolation=cv2.INTER_AREA)
    v2_bgr = cv2.cvtColor(v2_mask, cv2.COLOR_GRAY2BGR)
    p2 = cv2.resize(v2_bgr, (prev_w, prev_h), interpolation=cv2.INTER_NEAREST)
    p3 = cv2.resize(overlay_v2, (prev_w, prev_h), interpolation=cv2.INTER_AREA)

    header_h = 64
    header_color = (25, 28, 35)
    text_color = (255, 255, 255)
    font = cv2.FONT_HERSHEY_DUPLEX

    def add_header(panel, title, subtitle):
        canvas = np.full((prev_h + header_h, prev_w, 3), header_color, dtype=np.uint8)
        canvas[header_h:, :] = panel
        cv2.putText(canvas, title, (16, 28), font, 0.65, text_color, 2, cv2.LINE_AA)
        cv2.putText(canvas, subtitle, (16, 48), font, 0.40, (180, 190, 205), 1, cv2.LINE_AA)
        return canvas

    v2_fg = int(np.count_nonzero(v2_mask == 255))
    v2_pct = (v2_fg / total_pixels) * 100.0

    p1_hdr = add_header(p1, "1. Original Micrograph", "sample_3.bmp (2592x1944 px)")
    p2_hdr = add_header(p2, "2. V2 Draft Mask", f"sample_3_draft_v2.png ({v2_pct:.2f}% FG Area Fraction)")
    p3_hdr = add_header(p3, "3. V2 Segmentation Overlay", "Cyan: Segmented Graphite | Green: Flake Boundaries")

    preview_3panel = np.hstack([p1_hdr, p2_hdr, p3_hdr])

    cv2.imwrite(str(OUT_PREVIEW_PATH), preview_3panel)
    print(f"[OK] Saved 3-panel comparison preview: {OUT_PREVIEW_PATH}")

    if ARTIFACT_DIR.exists():
        art_preview = ARTIFACT_DIR / "sample_3_v2_comparison_preview.png"
        cv2.imwrite(str(art_preview), preview_3panel)
        print(f"[OK] Copied preview to artifact directory: {art_preview}")

    # 11. Quantitative Comparison & Diagnostic Metrics
    num_cc_v2, _, stats_v2, _ = cv2.connectedComponentsWithStats(v2_mask, 8)
    areas_v2 = stats_v2[1:, cv2.CC_STAT_AREA]
    n_v2 = len(areas_v2)

    diag = {
        "sample": "sample_3",
        "dimensions": f"{w} x {h}",
        "total_pixels": total_pixels,
        "v2_corrected_draft": {
            "graphite_pixels": v2_fg,
            "area_fraction_pct": round(v2_pct, 2),
            "total_components": n_v2,
            "area_min_px2": int(np.min(areas_v2)) if n_v2 else 0,
            "area_max_px2": int(np.max(areas_v2)) if n_v2 else 0,
            "area_median_px2": float(np.median(areas_v2)) if n_v2 else 0,
            "area_mean_px2": round(float(np.mean(areas_v2)), 1) if n_v2 else 0,
            "components_gt_5000px": int(np.sum(areas_v2 > 5000)),
            "components_100_to_5000px": int(np.sum((areas_v2 >= 100) & (areas_v2 <= 5000))),
            "components_15_to_100px": int(np.sum((areas_v2 >= 15) & (areas_v2 < 100))),
        },
    }

    diag_path = GRAY_CAST_IRON_RAW_DIR / "sample_3_v2_diagnostics.json"
    with open(diag_path, "w") as f:
        json.dump(diag, f, indent=2)

    print("\n" + "=" * 68)
    print("SAMPLE 3: V2 ILLUMINATION-CORRECTED DRAFT SUMMARY")
    print("=" * 68)
    print(f"Graphite Area Fraction : {v2_pct:.2f}% (Metallurgical norm: 8-18%)")
    print(f"Total Graphite Pixels  : {v2_fg:,} / {total_pixels:,}")
    print(f"Largest Component      : {np.max(areas_v2):,} px²")
    print(f"Flake Components Count : {n_v2}")
    print("=" * 68)

    return diag


if __name__ == "__main__":
    generate_v2_sample_3()
