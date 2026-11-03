"""Generate Draft Mask & Visual Comparison Preview for sample_1.bmp.

Reuses the verified classical thresholding pipeline (inverted Otsu + morphological opening).
Saves:
1. Draft mask: data/gray_cast_iron_raw/masks/sample_1_draft.png (single channel, 8-bit, {0, 255})
2. Comparison preview: data/gray_cast_iron_raw/sample_1_comparison_preview.png (Original | Draft Mask | Overlay)
"""
from __future__ import annotations

import json
from pathlib import Path
import cv2
import numpy as np

from nodiq.core.config import GRAY_CAST_IRON_RAW_DIR
SRC_IMAGE_PATH = GRAY_CAST_IRON_RAW_DIR / "images" / "sample_1.bmp"
OUT_MASK_PATH = GRAY_CAST_IRON_RAW_DIR / "masks" / "sample_1_draft.png"
OUT_PREVIEW_PATH = GRAY_CAST_IRON_RAW_DIR / "sample_1_comparison_preview.png"
ARTIFACT_DIR = Path(r"C:\Users\Atharv\.gemini\antigravity-ide\brain\9e971599-989c-4da2-9410-50537f25ee4d")


def generate_draft():
    if not SRC_IMAGE_PATH.exists():
        raise FileNotFoundError(f"Source image not found: {SRC_IMAGE_PATH}")

    # 1. Load source image
    img = cv2.imread(str(SRC_IMAGE_PATH))
    if img is None:
        raise RuntimeError(f"Failed to read image: {SRC_IMAGE_PATH}")

    h, w = img.shape[:2]
    total_pixels = h * w

    # 2. Replicate classical thresholding pipeline from s_metalseg_adapter.py
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresh_val, otsu_dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned_mask = cv2.morphologyEx(otsu_dark, cv2.MORPH_OPEN, kernel)

    # 3. Verify single-channel 8-bit binary constraints
    assert cleaned_mask.shape == (h, w), f"Shape mismatch: {cleaned_mask.shape} vs ({h}, {w})"
    assert cleaned_mask.dtype == np.uint8, f"Dtype mismatch: {cleaned_mask.dtype}"
    unique_vals = set(np.unique(cleaned_mask))
    assert unique_vals.issubset({0, 255}), f"Non-binary values found: {unique_vals}"

    # 4. Save draft mask separately
    OUT_MASK_PATH.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT_MASK_PATH), cleaned_mask)
    print(f"[OK] Saved draft mask: {OUT_MASK_PATH} ({w}x{h}, single-channel 8-bit PNG)")

    # 5. Build Cyan Overlay (from s_metalseg_adapter.py visualization standard)
    overlay = img.copy()
    color_mask = np.zeros_like(overlay)
    # Cyan highlight: B=255, G=220, R=0
    color_mask[cleaned_mask == 255] = (255, 220, 0)
    alpha = 0.45
    blended = cv2.addWeighted(color_mask, alpha, overlay, 1.0 - alpha, 0)
    overlay[cleaned_mask == 255] = blended[cleaned_mask == 255]

    # Draw fine green contour boundaries (optional crisp detail)
    contours, _ = cv2.findContours(cleaned_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay, contours, -1, (0, 255, 120), 1, cv2.LINE_AA)

    # 6. Generate 3-panel comparison preview: Original | Mask | Overlay
    # Downscale panels to a review resolution (width 1080 per panel, height 810)
    prev_w = 1080
    prev_h = int(h * (prev_w / w))

    p1 = cv2.resize(img, (prev_w, prev_h), interpolation=cv2.INTER_AREA)
    # Mask converted to 3-channel BGR for display
    mask_bgr = cv2.cvtColor(cleaned_mask, cv2.COLOR_GRAY2BGR)
    p2 = cv2.resize(mask_bgr, (prev_w, prev_h), interpolation=cv2.INTER_NEAREST)
    p3 = cv2.resize(overlay, (prev_w, prev_h), interpolation=cv2.INTER_AREA)

    # Add header bars with descriptive labels
    header_h = 60
    header_color = (25, 28, 35)
    text_color = (255, 255, 255)
    font = cv2.FONT_HERSHEY_DUPLEX

    def add_header(panel, title, subtitle):
        canvas = np.full((prev_h + header_h, prev_w, 3), header_color, dtype=np.uint8)
        canvas[header_h:, :] = panel
        cv2.putText(canvas, title, (20, 32), font, 0.75, text_color, 2, cv2.LINE_AA)
        cv2.putText(canvas, subtitle, (20, 52), font, 0.45, (180, 190, 205), 1, cv2.LINE_AA)
        return canvas

    p1_hdr = add_header(p1, "1. Original Micrograph", "sample_1.bmp (2592x1944 Optical Field)")
    p2_hdr = add_header(p2, "2. Draft Otsu Mask", "sample_1_draft.png (Binary: 0=Matrix, 255=Flake)")
    p3_hdr = add_header(p3, "3. Segmentation Overlay", "Cyan: Segmented Flakes | Green: Outer Contours")

    comparison = np.hstack([p1_hdr, p2_hdr, p3_hdr])

    # Save comparison preview
    cv2.imwrite(str(OUT_PREVIEW_PATH), comparison)
    print(f"[OK] Saved comparison preview: {OUT_PREVIEW_PATH}")

    if ARTIFACT_DIR.exists():
        art_preview = ARTIFACT_DIR / "sample_1_comparison_preview.png"
        cv2.imwrite(str(art_preview), comparison)
        print(f"[OK] Copied preview to artifact directory: {art_preview}")

    # 7. Detailed Quantitative Diagnostic Analysis
    fg_pixels = int(np.count_nonzero(cleaned_mask == 255))
    bg_pixels = total_pixels - fg_pixels
    area_fraction = (fg_pixels / total_pixels) * 100.0

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(cleaned_mask, connectivity=8)
    n_components = num_labels - 1
    areas = stats[1:, cv2.CC_STAT_AREA]

    # Identify false positive categories
    tiny_debris = int(np.sum(areas < 20))
    small_pits = int(np.sum((areas >= 20) & (areas < 100)))
    normal_flakes = int(np.sum((areas >= 100) & (areas <= 5000)))
    massive_clusters = int(np.sum(areas > 5000))

    # Edge touching components (vignetting indicators)
    x = stats[1:, cv2.CC_STAT_LEFT]
    y = stats[1:, cv2.CC_STAT_TOP]
    bw = stats[1:, cv2.CC_STAT_WIDTH]
    bh = stats[1:, cv2.CC_STAT_HEIGHT]
    edge_touching = int(np.sum((x <= 2) | (y <= 2) | (x + bw >= w - 2) | (y + bh >= h - 2)))

    diag = {
        "dimensions": f"{w} x {h}",
        "total_pixels": total_pixels,
        "otsu_threshold_value": float(thresh_val),
        "graphite_pixels": fg_pixels,
        "matrix_pixels": bg_pixels,
        "graphite_area_fraction_pct": round(area_fraction, 2),
        "total_detected_components": n_components,
        "area_distribution_px2": {
            "min": int(np.min(areas)) if n_components else 0,
            "max": int(np.max(areas)) if n_components else 0,
            "median": float(np.median(areas)) if n_components else 0,
            "mean": round(float(np.mean(areas)), 1) if n_components else 0,
        },
        "component_breakdown": {
            "tiny_debris_or_noise_lt_20px": tiny_debris,
            "small_pits_or_pores_20_100px": small_pits,
            "isolated_flakes_100_5000px": normal_flakes,
            "massive_merged_clusters_gt_5000px": massive_clusters,
            "edge_touching_components": edge_touching,
        },
    }

    with open(GRAY_CAST_IRON_RAW_DIR / "sample_1_draft_diagnostics.json", "w") as f:
        json.dump(diag, f, indent=2)

    print("\n" + "=" * 60)
    print("DIAGNOSTIC SUMMARY FOR SAMPLE_1 DRAFT MASK")
    print("=" * 60)
    print(f"Otsu Cutoff Threshold  : {thresh_val:.1f} / 255")
    print(f"Graphite Area Fraction : {area_fraction:.2f}% (Typical Gray Cast Iron: 8-20%)")
    print(f"Total Components       : {n_components}")
    print(f"Tiny Debris (<20 px²)  : {tiny_debris} ({tiny_debris/n_components*100:.1f}%)")
    print(f"Massive Merged (>5000) : {massive_clusters} (Largest: {np.max(areas):,} px²)")
    print(f"Edge-Touching Blobs    : {edge_touching}")
    print("=" * 60)

    return diag


if __name__ == "__main__":
    generate_draft()
