"""Dataset Validator for Gray Cast Iron Micrograph & Flake Mask Datasets.

Validates that a dataset conforms to metallurgical ground-truth standards:
1. File pairs: Every image has an exact corresponding mask.
2. Dimensions: Image and mask dimensions match exactly (height, width).
3. Mask values: Masks are strictly binary ({0, 255} or {0, 1}), no anti-aliased or soft grayscale edges.
4. Empty/Inverted masks: Flags 0% foreground (empty) or >40% foreground (inverted/corrupt).
5. Duplicate images: Detects identical image content via SHA-256 hashing.
6. Split leakage: Detects specimen/heat cross-contamination between train, val, and test splits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, List, Set

import cv2
import numpy as np

VALID_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
VALID_MASK_EXTS = {".png", ".tif", ".tiff", ".bmp"}


def compute_file_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def extract_specimen_id(filename: str) -> str:
    """Extract specimen/heat identifier from filename.
    
    Examples:
      'specimen01_field02.png' -> 'specimen01'
      'heat_A_roi3.tif'        -> 'heat_A'
      'GCI-400-01-05.png'      -> 'GCI-400-01'
      'sample5.jpg'            -> 'sample5'
    """
    stem = Path(filename).stem
    # Match patterns like specimen_XX, sample_XX, heat_XX, GCI-XX-YY
    parts = re.split(r"[_-](?=field|roi|img|fov|view|f\d|\d+$)", stem, flags=re.IGNORECASE)
    if len(parts) > 1 and parts[0]:
        return parts[0].strip("_-")
    # Fallback: if there are multiple underscores, take everything before the last underscore
    if "_" in stem:
        return stem.rsplit("_", 1)[0]
    return stem


def validate_split_directory(
    images_dir: Path,
    masks_dir: Path,
    split_name: str = "train",
) -> Dict[str, Any]:
    """Validate a single partition (images_dir and masks_dir)."""
    errors: List[str] = []
    warnings: List[str] = []

    if not images_dir.exists():
        return {
            "split": split_name,
            "exists": False,
            "errors": [f"Images directory does not exist: {images_dir}"],
            "warnings": [],
            "image_count": 0,
            "mask_count": 0,
            "paired_count": 0,
            "file_hashes": {},
            "specimen_ids": set(),
        }

    if not masks_dir.exists():
        return {
            "split": split_name,
            "exists": False,
            "errors": [f"Masks directory does not exist: {masks_dir}"],
            "warnings": [],
            "image_count": 0,
            "mask_count": 0,
            "paired_count": 0,
            "file_hashes": {},
            "specimen_ids": set(),
        }

    image_files = sorted([f for f in images_dir.iterdir() if f.suffix.lower() in VALID_IMAGE_EXTS])
    mask_files = sorted([f for f in masks_dir.iterdir() if f.suffix.lower() in VALID_MASK_EXTS])

    image_map = {f.stem: f for f in image_files}
    mask_map = {f.stem: f for f in mask_files}

    # 1. Pairing check
    common_stems = set(image_map.keys()) & set(mask_map.keys())
    orphaned_images = [str(image_map[s].name) for s in image_map.keys() - common_stems]
    orphaned_masks = [str(mask_map[s].name) for s in mask_map.keys() - common_stems]

    if orphaned_images:
        errors.append(f"Found {len(orphaned_images)} images without matching masks: {orphaned_images[:5]}{'...' if len(orphaned_images) > 5 else ''}")
    if orphaned_masks:
        errors.append(f"Found {len(orphaned_masks)} masks without matching images: {orphaned_masks[:5]}{'...' if len(orphaned_masks) > 5 else ''}")

    file_hashes: Dict[str, Path] = {}
    duplicate_images: List[str] = []
    specimen_ids: Set[str] = set()

    dimension_mismatches: List[str] = []
    non_binary_masks: List[str] = []
    empty_masks: List[str] = []
    inverted_masks: List[str] = []

    for stem in sorted(common_stems):
        img_path = image_map[stem]
        mask_path = mask_map[stem]

        # Specimen ID tracking
        spec_id = extract_specimen_id(img_path.name)
        specimen_ids.add(spec_id)

        # Hash check for duplicates
        file_hash = compute_file_sha256(img_path)
        if file_hash in file_hashes:
            dup_msg = f"{img_path.name} is an exact duplicate of {file_hashes[file_hash].name}"
            duplicate_images.append(dup_msg)
            errors.append(f"Duplicate image: {dup_msg}")
        else:
            file_hashes[file_hash] = img_path

        # Read image and mask
        img = cv2.imread(str(img_path))
        if img is None:
            errors.append(f"Corrupt or unreadable image: {img_path.name}")
            continue

        mask = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
        if mask is None:
            errors.append(f"Corrupt or unreadable mask: {mask_path.name}")
            continue

        # 2. Dimensions check
        h_img, w_img = img.shape[:2]
        if mask.ndim == 2:
            h_mask, w_mask = mask.shape
        else:
            h_mask, w_mask = mask.shape[:2]
            warnings.append(f"Mask {mask_path.name} has {mask.ndim} channels; single-channel grayscale mask is recommended.")
            mask = mask[:, :, 0]

        if (h_img, w_img) != (h_mask, w_mask):
            mismatch_desc = f"{stem}: image is ({w_img}x{h_img}), mask is ({w_mask}x{h_mask})"
            dimension_mismatches.append(mismatch_desc)
            errors.append(f"Dimension mismatch in {mismatch_desc}")

        # 3. Mask values binary check
        unique_vals = np.unique(mask)
        # Allow {0, 255} or {0, 1}
        is_binary = True
        for uv in unique_vals:
            if uv not in (0, 1, 255):
                is_binary = False
                break

        if not is_binary:
            err_val = f"Mask {mask_path.name} contains non-binary pixel values: {list(unique_vals[:8])}"
            non_binary_masks.append(err_val)
            errors.append(err_val)

        # 4. Foreground fraction (Empty / Inverted)
        fg_pixels = np.count_nonzero(mask > 0)
        total_pixels = h_mask * w_mask
        fg_ratio = (fg_pixels / total_pixels) if total_pixels > 0 else 0.0

        if fg_pixels == 0:
            empty_desc = f"Mask {mask_path.name} is completely empty (0% graphite foreground)"
            empty_masks.append(empty_desc)
            warnings.append(empty_desc)
        elif fg_ratio > 0.40:
            inv_desc = f"Mask {mask_path.name} has suspicious extreme coverage ({fg_ratio*100:.1f}% foreground); typical gray cast iron graphite is 5-25%. Check for inverted polarity or annotation corruption."
            inverted_masks.append(inv_desc)
            warnings.append(inv_desc)

    return {
        "split": split_name,
        "exists": True,
        "image_count": len(image_files),
        "mask_count": len(mask_files),
        "paired_count": len(common_stems),
        "orphaned_images": orphaned_images,
        "orphaned_masks": orphaned_masks,
        "dimension_mismatches": dimension_mismatches,
        "non_binary_masks": non_binary_masks,
        "empty_masks": empty_masks,
        "inverted_masks": inverted_masks,
        "duplicate_images": duplicate_images,
        "file_hashes": file_hashes,
        "specimen_ids": specimen_ids,
        "errors": errors,
        "warnings": warnings,
    }


def validate_gray_cast_iron_dataset(data_dir: Path) -> Dict[str, Any]:
    """Validate full gray cast iron dataset including split leakage detection."""
    data_dir = Path(data_dir)
    results: Dict[str, Any] = {
        "data_dir": str(data_dir),
        "is_valid": False,
        "is_partitioned": False,
        "splits": {},
        "overall_errors": [],
        "overall_warnings": [],
        "leakage_errors": [],
        "summary": {},
    }

    if not data_dir.exists():
        results["overall_errors"].append(f"Dataset root directory does not exist: {data_dir}")
        return results

    # Determine if dataset is partitioned (train/val/test) or flat
    has_train = (data_dir / "train").exists()
    has_val = (data_dir / "val").exists()
    has_test = (data_dir / "test").exists()

    if has_train:
        results["is_partitioned"] = True
        splits_to_check = ["train"]
        if has_val:
            splits_to_check.append("val")
        if has_test:
            splits_to_check.append("test")

        for sname in splits_to_check:
            s_res = validate_split_directory(
                data_dir / sname / "images",
                data_dir / sname / "masks",
                split_name=sname,
            )
            results["splits"][sname] = s_res

        # 6. Check for specimen-level leakage and duplicate image leakage across splits
        split_names = list(results["splits"].keys())
        for i in range(len(split_names)):
            for j in range(i + 1, len(split_names)):
                s1, s2 = split_names[i], split_names[j]
                res1, res2 = results["splits"][s1], results["splits"][s2]

                # Check hash leakage (same physical image in both splits)
                common_hashes = set(res1["file_hashes"].keys()) & set(res2["file_hashes"].keys())
                for ch in common_hashes:
                    leak_msg = f"Image duplication leakage: {res1['file_hashes'][ch].name} (in '{s1}') is identical to {res2['file_hashes'][ch].name} (in '{s2}')."
                    results["leakage_errors"].append(leak_msg)
                    results["overall_errors"].append(leak_msg)

                # Check specimen ID leakage (different images from same specimen across splits)
                common_specs = res1["specimen_ids"] & res2["specimen_ids"]
                for cspec in common_specs:
                    spec_leak = f"Specimen-level data leakage: Specimen '{cspec}' is present in both '{s1}' and '{s2}' splits. All fields of the same specimen must remain in the same split."
                    results["leakage_errors"].append(spec_leak)
                    results["overall_errors"].append(spec_leak)

    else:
        # Flat dataset
        results["is_partitioned"] = False
        s_res = validate_split_directory(
            data_dir / "images",
            data_dir / "masks",
            split_name="all",
        )
        results["splits"]["all"] = s_res

    # Tally summary
    total_images = sum(s["image_count"] for s in results["splits"].values())
    total_masks = sum(s["mask_count"] for s in results["splits"].values())
    total_paired = sum(s["paired_count"] for s in results["splits"].values())
    all_errors = list(results["overall_errors"])
    all_warnings = list(results["overall_warnings"])

    for s in results["splits"].values():
        all_errors.extend(s["errors"])
        all_warnings.extend(s["warnings"])

    results["summary"] = {
        "total_images": total_images,
        "total_masks": total_masks,
        "total_paired": total_paired,
        "error_count": len(all_errors),
        "warning_count": len(all_warnings),
    }

    # Minimum threshold to be considered a valid dataset:
    # Must have at least 1 paired image, 0 fatal errors
    if total_paired > 0 and len(all_errors) == 0:
        results["is_valid"] = True
    else:
        results["is_valid"] = False

    return results


def print_validation_report(results: Dict[str, Any]) -> None:
    """Print an engineer-friendly ASCII validation report."""
    print("=" * 76)
    print("  GRAY CAST IRON METALLOGRAPHIC DATASET VALIDATION REPORT")
    print("=" * 76)
    print(f"Dataset Path   : {results['data_dir']}")
    print(f"Structure      : {'Partitioned (train/val/test)' if results['is_partitioned'] else 'Flat (images/masks)'}")
    print(f"Total Images   : {results['summary'].get('total_images', 0)}")
    print(f"Total Masks    : {results['summary'].get('total_masks', 0)}")
    print(f"Paired Pairs   : {results['summary'].get('total_paired', 0)}")
    print("-" * 76)

    for sname, sinfo in results.get("splits", {}).items():
        print(f"Split: [{sname.upper()}]")
        print(f"  - Paired Samples : {sinfo['paired_count']}")
        print(f"  - Orphan Images  : {len(sinfo.get('orphaned_images', []))}")
        print(f"  - Orphan Masks   : {len(sinfo.get('orphaned_masks', []))}")
        print(f"  - Unique Specimens: {len(sinfo.get('specimen_ids', []))}")
        if sinfo.get("dimension_mismatches"):
            print(f"  - Dimension Mismatches: {len(sinfo['dimension_mismatches'])}")
        if sinfo.get("non_binary_masks"):
            print(f"  - Non-Binary Masks    : {len(sinfo['non_binary_masks'])}")
        if sinfo.get("empty_masks"):
            print(f"  - Empty Masks (0% FG) : {len(sinfo['empty_masks'])}")
        if sinfo.get("inverted_masks"):
            print(f"  - Extreme/Inverted FG : {len(sinfo['inverted_masks'])}")
        if sinfo.get("duplicate_images"):
            print(f"  - Duplicate Images    : {len(sinfo['duplicate_images'])}")

    if results.get("leakage_errors"):
        print("-" * 76)
        print("[!] DATA LEAKAGE DETECTED BETWEEN SPLITS:")
        for err in results["leakage_errors"]:
            print(f"  [LEAKAGE] {err}")

    # Collect all errors
    all_errs = []
    all_errs.extend(results.get("overall_errors", []))
    for s in results.get("splits", {}).values():
        all_errs.extend(s.get("errors", []))

    all_warns = []
    all_warns.extend(results.get("overall_warnings", []))
    for s in results.get("splits", {}).values():
        all_warns.extend(s.get("warnings", []))

    if all_errs:
        print("-" * 76)
        print(f"[!] VALIDATION ERRORS ({len(all_errs)}):")
        for err in all_errs[:10]:
            print(f"  [ERROR] {err}")
        if len(all_errs) > 10:
            print(f"  ... and {len(all_errs) - 10} more errors.")

    if all_warns:
        print("-" * 76)
        print(f"[*] VALIDATION WARNINGS ({len(all_warns)}):")
        for w in all_warns[:5]:
            print(f"  [WARN]  {w}")

    print("=" * 76)
    if results["is_valid"]:
        print("  STATUS: [PASSED] Dataset is ready for reproducible FPN training.")
    else:
        print("  STATUS: [FAILED / BLOCKED] Dataset cannot be used for training until errors are resolved.")
    print("=" * 76)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate Gray Cast Iron Micrograph and Flake Mask Dataset.")
    parser.add_argument("--data_dir", type=str, default="data/gray_cast_iron", help="Path to dataset directory")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    res = validate_gray_cast_iron_dataset(Path(args.data_dir))
    if args.json:
        # Convert sets to lists for JSON serialization
        json_res = json.loads(json.dumps(res, default=lambda o: list(o) if isinstance(o, set) else str(o)))
        print(json.dumps(json_res, indent=2))
    else:
        print_validation_report(res)

    sys.exit(0 if res["is_valid"] else 1)
