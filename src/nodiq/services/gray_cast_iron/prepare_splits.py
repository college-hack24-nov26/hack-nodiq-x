"""Automated Specimen-Level Train/Val/Test Splitter for Gray Cast Iron Datasets.

Enforces zero-data-leakage partitioning by grouping micrographs by specimen/heat ID
before assigning them to Train (70%), Val (15%), and Test (15%) splits.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import os
from pathlib import Path
import random
import shutil
import sys
from typing import Any, Dict, List, Tuple

from nodiq.services.gray_cast_iron.validate_dataset import (
    extract_specimen_id,
    validate_gray_cast_iron_dataset,
    print_validation_report,
    VALID_IMAGE_EXTS,
    VALID_MASK_EXTS,
)


def create_specimen_level_split(
    source_dir: Path,
    output_dir: Path,
    train_ratio: float = 0.70,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    seed: int = 42,
    copy_files: bool = True,
) -> Dict[str, Any]:
    """Partition paired images and masks into train/val/test by specimen ID."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)

    src_img_dir = source_dir / "images"
    src_mask_dir = source_dir / "masks"

    if not src_img_dir.exists() or not src_mask_dir.exists():
        raise FileNotFoundError(f"Source directory must contain 'images' and 'masks' subdirectories: {source_dir}")

    # Discover paired files
    img_files = sorted([f for f in src_img_dir.iterdir() if f.suffix.lower() in VALID_IMAGE_EXTS])
    mask_files = {f.stem: f for f in src_mask_dir.iterdir() if f.suffix.lower() in VALID_MASK_EXTS}

    pairs: List[Tuple[Path, Path]] = []
    for img_path in img_files:
        if img_path.stem in mask_files:
            pairs.append((img_path, mask_files[img_path.stem]))

    if not pairs:
        raise ValueError(f"No paired images and masks found in {source_dir}")

    # Group by specimen ID
    specimen_groups: Dict[str, List[Tuple[Path, Path]]] = defaultdict(list)
    for img_path, mask_path in pairs:
        spec_id = extract_specimen_id(img_path.name)
        specimen_groups[spec_id].append((img_path, mask_path))

    specimen_ids = sorted(list(specimen_groups.keys()))
    rng = random.Random(seed)
    rng.shuffle(specimen_ids)

    n_specs = len(specimen_ids)
    if n_specs < 3:
        print(f"[WARN] Only {n_specs} distinct specimens detected. For full train/val/test isolation, >= 3 distinct specimens are required.")
        n_train = max(1, int(n_specs * train_ratio))
        train_specs = specimen_ids[:n_train]
        val_specs = specimen_ids[n_train:]
        test_specs = []
    else:
        n_train = max(1, int(n_specs * train_ratio))
        n_val = max(1, int(n_specs * val_ratio))
        train_specs = specimen_ids[:n_train]
        val_specs = specimen_ids[n_train : n_train + n_val]
        test_specs = specimen_ids[n_train + n_val :]
        if not test_specs and len(val_specs) > 1:
            test_specs = [val_specs.pop()]

    split_map = {
        "train": train_specs,
        "val": val_specs,
        "test": test_specs,
    }

    # Create target directories
    for split_name in ("train", "val", "test"):
        (output_dir / split_name / "images").mkdir(parents=True, exist_ok=True)
        (output_dir / split_name / "masks").mkdir(parents=True, exist_ok=True)

    transferred = {"train": 0, "val": 0, "test": 0}

    for split_name, specs in split_map.items():
        for spec_id in specs:
            for img_path, mask_path in specimen_groups[spec_id]:
                dest_img = output_dir / split_name / "images" / img_path.name
                dest_mask = output_dir / split_name / "masks" / mask_path.name
                if copy_files:
                    shutil.copy2(img_path, dest_img)
                    shutil.copy2(mask_path, dest_mask)
                else:
                    # Create symlinks where supported
                    try:
                        os.symlink(img_path.resolve(), dest_img)
                        os.symlink(mask_path.resolve(), dest_mask)
                    except (OSError, NotImplementedError):
                        shutil.copy2(img_path, dest_img)
                        shutil.copy2(mask_path, dest_mask)
                transferred[split_name] += 1

    print("=" * 76)
    print("  SPECIMEN-LEVEL PARTITIONING SUMMARY")
    print("=" * 76)
    print(f"Total Specimens : {n_specs}")
    print(f"Total Pairs     : {len(pairs)}")
    print(f"Train Split     : {len(train_specs)} specimens ({transferred['train']} micrographs)")
    print(f"Val Split       : {len(val_specs)} specimens ({transferred['val']} micrographs)")
    print(f"Test Split      : {len(test_specs)} specimens ({transferred['test']} micrographs)")
    print("=" * 76)

    # Automatically run validator to confirm zero leakage
    validation_res = validate_gray_cast_iron_dataset(output_dir)
    print_validation_report(validation_res)

    return {
        "output_dir": str(output_dir),
        "specimens": split_map,
        "transferred": transferred,
        "is_valid": validation_res["is_valid"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Partition raw gray cast iron micrographs by specimen ID.")
    parser.add_argument("--source_dir", type=str, required=True, help="Folder containing raw 'images' and 'masks'")
    parser.add_argument("--output_dir", type=str, default="data/gray_cast_iron", help="Target partitioned directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for repeatable splitting")
    parser.add_argument("--train_ratio", type=float, default=0.70, help="Train split ratio (default: 0.70)")
    parser.add_argument("--val_ratio", type=float, default=0.15, help="Validation split ratio (default: 0.15)")
    parser.add_argument("--test_ratio", type=float, default=0.15, help="Test split ratio (default: 0.15)")
    args = parser.parse_args()

    res = create_specimen_level_split(
        source_dir=Path(args.source_dir),
        output_dir=Path(args.output_dir),
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        test_ratio=args.test_ratio,
        seed=args.seed,
    )
    sys.exit(0 if res["is_valid"] else 1)
