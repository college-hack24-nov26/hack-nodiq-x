"""Batch Illumination-Corrected Draft Mask (V2) Generator for Gray Cast Iron Images.

Features:
1. Automatically discovers all source micrographs in data/gray_cast_iron_raw/images/.
2. Identifies missing source images (e.g. sample_12.bmp).
3. Strictly protects existing reviewed masks (sample_1_reviewed.png, sample_2_reviewed.png, sample_3_reviewed.png)
   and existing drafts (sample_1_draft_v2.png, etc.). Never overwrites them.
4. Generates illumination-corrected V2 draft masks for all remaining available samples.
5. Verifies 2592x1944 single-channel uint8 binary {0, 255} constraints.
6. Creates 3-panel comparison previews for visual verification.
7. Generates comprehensive diagnostics JSON summary.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import traceback
from typing import Any, Dict, List

import cv2
import numpy as np

from nodiq.core.config import REPO_ROOT, GRAY_CAST_IRON_RAW_DIR
PROJECT_ROOT = REPO_ROOT
RAW_DIR = GRAY_CAST_IRON_RAW_DIR
IMAGES_DIR = RAW_DIR / "images"
MASKS_DIR = RAW_DIR / "masks"

EXPECTED_SHAPE = (1944, 2592)  # (H, W)


def generate_single_draft_v2(
    img_path: Path,
    out_mask_path: Path,
    out_preview_path: Path,
    out_diag_path: Path,
) -> Dict[str, Any]:
    """Execute illumination-corrected V2 draft algorithm for a single image."""
    img = cv2.imread(str(img_path))
    if img is None:
        raise ValueError(f"Failed to decode image at {img_path}")

    h, w = img.shape[:2]
    total_pixels = h * w

    # 1. Illumination Background Estimation
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bg = cv2.GaussianBlur(gray, (151, 151), 0).astype(np.float32)

    # 2. Local Contrast Difference
    diff = cv2.subtract(bg.astype(np.uint8), gray)

    # 3. Thresholding & Morphology
    _, m_raw = cv2.threshold(diff, 11, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    m_clean = cv2.morphologyEx(m_raw, cv2.MORPH_OPEN, kernel)

    # 4. Small speckle rejection (<15 px²)
    num_cc, labels, stats, centroids = cv2.connectedComponentsWithStats(m_clean, 8)
    v2_mask = np.zeros_like(m_clean)
    for i in range(1, num_cc):
        if stats[i, cv2.CC_STAT_AREA] >= 15:
            v2_mask[labels == i] = 255

    # 5. Strict validation
    if v2_mask.shape != (h, w):
        raise ValueError(f"Shape mismatch: {v2_mask.shape} vs ({h}, {w})")
    if v2_mask.dtype != np.uint8:
        raise ValueError(f"Dtype mismatch: {v2_mask.dtype}")
    unique_vals = set(np.unique(v2_mask))
    if not unique_vals.issubset({0, 255}):
        raise ValueError(f"Non-binary values found: {unique_vals}")

    # 6. Save Draft Mask
    out_mask_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_mask_path), v2_mask)

    # 7. Metrics
    fg_pixels = int(np.count_nonzero(v2_mask == 255))
    af_pct = round((fg_pixels / total_pixels) * 100.0, 2)
    areas = stats[1:, cv2.CC_STAT_AREA]
    valid_areas = [int(a) for a in areas if a >= 15]

    # 8. Build 3-panel comparison preview
    overlay = img.copy()
    color_mask = np.zeros_like(overlay)
    color_mask[v2_mask == 255] = (255, 220, 0)
    alpha = 0.45
    blended = cv2.addWeighted(color_mask, alpha, overlay, 1.0 - alpha, 0)
    overlay[v2_mask == 255] = blended[v2_mask == 255]

    contours, _ = cv2.findContours(v2_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay, contours, -1, (0, 255, 120), 1, cv2.LINE_AA)

    prev_w = 800
    prev_h = int(h * (prev_w / w))
    p1 = cv2.resize(img, (prev_w, prev_h), interpolation=cv2.INTER_AREA)
    v2_bgr = cv2.cvtColor(v2_mask, cv2.COLOR_GRAY2BGR)
    p2 = cv2.resize(v2_bgr, (prev_w, prev_h), interpolation=cv2.INTER_NEAREST)
    p3 = cv2.resize(overlay, (prev_w, prev_h), interpolation=cv2.INTER_AREA)

    header_h = 64
    header_color = (25, 28, 35)
    font = cv2.FONT_HERSHEY_DUPLEX

    def add_header(panel, title, subtitle):
        canvas = np.full((prev_h + header_h, prev_w, 3), header_color, dtype=np.uint8)
        canvas[header_h:, :] = panel
        cv2.putText(canvas, title, (16, 28), font, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, subtitle, (16, 48), font, 0.40, (180, 190, 205), 1, cv2.LINE_AA)
        return canvas

    p1_hdr = add_header(p1, f"1. Micrograph: {img_path.name}", f"{w}x{h} px ({img_path.stat().st_size:,} bytes)")
    p2_hdr = add_header(p2, f"2. V2 Draft Mask", f"Area Fraction: {af_pct:.2f}% ({fg_pixels:,} FG px)")
    p3_hdr = add_header(p3, "3. Segmentation Overlay", "Cyan: Graphite Flakes | Green: Boundaries")

    preview_3panel = np.hstack([p1_hdr, p2_hdr, p3_hdr])
    cv2.imwrite(str(out_preview_path), preview_3panel)

    diag = {
        "sample": img_path.stem,
        "image_file": img_path.name,
        "image_shape": [w, h],
        "total_pixels": total_pixels,
        "graphite_pixels": fg_pixels,
        "area_fraction_pct": af_pct,
        "flake_count": len(valid_areas),
        "largest_flake_px2": int(np.max(valid_areas)) if valid_areas else 0,
        "median_flake_px2": float(np.median(valid_areas)) if valid_areas else 0.0,
        "draft_mask_path": str(out_mask_path),
        "preview_path": str(out_preview_path),
    }

    with open(out_diag_path, "w") as f:
        json.dump(diag, f, indent=2)

    return diag


def process_all_samples() -> Dict[str, Any]:
    """Process all samples 1 through 20."""
    print("=" * 76)
    print("  GRAY CAST IRON: BATCH DRAFT MASK GENERATION (V2 ILLUMINATION-CORRECTED)")
    print("=" * 76)

    manifest: Dict[str, Any] = {
        "total_expected_samples": 20,
        "available_sources": [],
        "missing_sources": [],
        "already_reviewed": [],
        "existing_drafts_preserved": [],
        "newly_generated_drafts": [],
        "failures": [],
        "sample_details": {},
    }

    for idx in range(1, 21):
        sample_name = f"sample_{idx}"
        img_name = f"{sample_name}.bmp"
        img_path = IMAGES_DIR / img_name
        draft_name = f"{sample_name}_draft_v2.png"
        draft_path = MASKS_DIR / draft_name
        reviewed_name = f"{sample_name}_reviewed.png"
        reviewed_path = MASKS_DIR / reviewed_name
        preview_path = RAW_DIR / f"{sample_name}_v2_comparison_preview.png"
        diag_path = RAW_DIR / f"{sample_name}_v2_diagnostics.json"

        # Check source image existence
        if not img_path.is_file():
            print(f"[-] {sample_name}: Source image MISSING ({img_name})")
            manifest["missing_sources"].append(sample_name)
            manifest["sample_details"][sample_name] = {
                "status": "MISSING_SOURCE",
                "image_exists": False,
                "draft_exists": draft_path.is_file(),
                "reviewed_exists": reviewed_path.is_file(),
            }
            continue

        manifest["available_sources"].append(sample_name)

        # Check if reviewed mask already exists
        if reviewed_path.is_file():
            print(f"[!] {sample_name}: Reviewed mask ALREADY EXISTS ({reviewed_name}, {reviewed_path.stat().st_size:,} B) - PRESERVED")
            manifest["already_reviewed"].append(sample_name)

            # Check if draft already exists as well
            if draft_path.is_file():
                manifest["existing_drafts_preserved"].append(sample_name)
            manifest["sample_details"][sample_name] = {
                "status": "REVIEWED_SAVED",
                "image_exists": True,
                "draft_exists": draft_path.is_file(),
                "reviewed_exists": True,
                "reviewed_file": reviewed_name,
            }
            continue

        # Check if draft mask already exists
        if draft_path.is_file():
            print(f"[#] {sample_name}: Draft mask ALREADY EXISTS ({draft_name}, {draft_path.stat().st_size:,} B) - PRESERVED")
            manifest["existing_drafts_preserved"].append(sample_name)
            manifest["sample_details"][sample_name] = {
                "status": "DRAFT_EXISTS_AWAITING_REVIEW",
                "image_exists": True,
                "draft_exists": True,
                "reviewed_exists": False,
            }
            continue

        # Generate new draft mask
        print(f"[+] {sample_name}: Generating V2 illumination-corrected draft mask...")
        try:
            diag = generate_single_draft_v2(img_path, draft_path, preview_path, diag_path)
            print(f"    -> Saved {draft_name} | AF: {diag['area_fraction_pct']}% | Flakes: {diag['flake_count']:,} | Preview: {preview_path.name}")
            manifest["newly_generated_drafts"].append(sample_name)
            manifest["sample_details"][sample_name] = {
                "status": "DRAFT_GENERATED_AWAITING_REVIEW",
                "image_exists": True,
                "draft_exists": True,
                "reviewed_exists": False,
                "draft_file": draft_name,
                "diagnostics": diag,
            }
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}"
            print(f"[x] {sample_name}: FAILED draft generation: {err_msg}")
            traceback.print_exc()
            manifest["failures"].append({"sample": sample_name, "error": err_msg})
            manifest["sample_details"][sample_name] = {
                "status": "DRAFT_GENERATION_FAILED",
                "image_exists": True,
                "draft_exists": False,
                "reviewed_exists": False,
                "error": err_msg,
            }

    # Save summary manifest
    summary_path = RAW_DIR / "draft_generation_summary.json"
    with open(summary_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print("\n" + "=" * 76)
    print("  BATCH GENERATION SUMMARY")
    print("=" * 76)
    print(f"Total Sources Discovered : {len(manifest['available_sources'])} / {manifest['total_expected_samples']}")
    print(f"Missing Sources          : {manifest['missing_sources']}")
    print(f"Already Reviewed Masks   : {len(manifest['already_reviewed'])} ({', '.join(manifest['already_reviewed'])})")
    print(f"Pre-existing Drafts Kept : {len(manifest['existing_drafts_preserved'])}")
    print(f"Newly Generated Drafts   : {len(manifest['newly_generated_drafts'])} ({', '.join(manifest['newly_generated_drafts'])})")
    print(f"Failures                 : {len(manifest['failures'])}")
    print(f"Summary Manifest Saved   : {summary_path}")
    print("=" * 76)

    return manifest


if __name__ == "__main__":
    process_all_samples()
