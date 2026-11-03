"""
Step 1: Dataset Preparation
---------------------------
1. Stitches localized microscopy patches into full-field micrographs.
2. Converts binary boundary masks into instance-labeled TIFF masks.
3. Generates CSV files for nested training splits (5%, 10%, 25%, 50%, 75%).
"""

import os
import re
import csv
import shutil
import argparse
import random
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from skimage import morphology
from tifffile import imwrite as tiff_imwrite

def stitch_images(input_folder, output_folder, is_mask=False):
    """Stitches image tiles based on the pattern: Name_Row_Col.ext"""
    os.makedirs(output_folder, exist_ok=True)
    groups = {}
    filename_pattern = re.compile(r'^([^_]+)_(\d+)_(\d+)\.(png|jpg|jpeg|bmp|tiff)$', re.IGNORECASE)

    files = os.listdir(input_folder)
    print(f"Scanning {len(files)} files in '{input_folder}' for stitching...")
    
    for filename in files:
        match = filename_pattern.match(filename)
        if match:
            source_id = match.group(1)
            row, col = int(match.group(2)), int(match.group(3))
            if source_id not in groups:
                groups[source_id] = []
            groups[source_id].append({'row': row, 'col': col, 'path': os.path.join(input_folder, filename)})

    for source_id, tiles in groups.items():
        if not tiles: continue
        
        max_row = max(t['row'] for t in tiles)
        max_col = max(t['col'] for t in tiles)
        
        first_image = Image.open(tiles[0]['path'])
        tile_w, tile_h = first_image.size
        
        canvas_width, canvas_height = max_col * tile_w, max_row * tile_h
        mode = 'L' if is_mask else 'RGB'
        bg_color = 'black' if is_mask else 'white'
        stitched_image = Image.new(mode, (canvas_width, canvas_height), bg_color)

        for tile in tiles:
            img = Image.open(tile['path']).convert(mode)
            if img.size != (tile_w, tile_h):
                img = img.resize((tile_w, tile_h))
            x, y = (tile['col'] - 1) * tile_w, (tile['row'] - 1) * tile_h
            stitched_image.paste(img, (x, y))

        out_ext = ".png"
        output_path = os.path.join(output_folder, f"{source_id}_stitched{out_ext}")
        stitched_image.save(output_path)

def boundary_to_instance(mask_path, boundary_thresh=128, erode=True):
    """Converts a binary boundary mask into a 2-D integer instance array."""
    img = np.array(Image.open(mask_path).convert("L"))
    interior = img >= boundary_thresh
    labelled, n_grains = ndi.label(interior)

    if erode:
        eroded = np.zeros_like(labelled)
        for gid in range(1, n_grains + 1):
            grain_mask = labelled == gid
            grain_mask = morphology.binary_erosion(grain_mask, morphology.disk(1))
            eroded[grain_mask] = gid
        labelled = eroded

    # Size exclusion filter (as per Section 3.4 of the paper)
    labelled = morphology.remove_small_objects(labelled, min_size=200)
    return labelled.astype(np.int32)

def generate_splits(image_dir, mask_dir, output_base, train_fractions=[0.05, 0.10, 0.25, 0.50, 0.75]):
    out_images = output_base / "all_processed_images"
    out_masks = output_base / "all_processed_masks"
    out_images.mkdir(parents=True, exist_ok=True)
    out_masks.mkdir(parents=True, exist_ok=True)

    pairs = []
    for img_path in sorted(image_dir.glob("*.png")):
        stem = img_path.stem.replace("_stitched", "")
        mask_path = mask_dir / f"{stem}_stitched.png" # Adjust based on naming
        if mask_path.exists():
            pairs.append((img_path, mask_path))

    processed_records = []
    for img_path, mask_path in pairs:
        stem = img_path.stem
        out_img_name, out_mask_name = f"{stem}_img.png", f"{stem}_masks.tif"
        
        Image.open(img_path).convert("RGB").save(out_images / out_img_name)
        labelled = boundary_to_instance(mask_path)
        tiff_imwrite(str(out_masks / out_mask_name), labelled.astype(np.uint16))
        
        processed_records.append({"image_file": out_img_name, "mask_file": out_mask_name})

    # Fixed Test Set
    rng = random.Random(42)
    rng.shuffle(processed_records)
    total_images = len(processed_records)
    test_start_idx = int(total_images * 0.75) # Reserve 25% for test
    test_set = processed_records[test_start_idx:]

    for frac in train_fractions:
        train_count = max(1, int(total_images * frac))
        train_set = processed_records[:train_count]
        
        csv_filename = output_base / f"split_{int(frac * 100):02d}_percent.csv"
        with open(csv_filename, mode='w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["image_filename", "mask_filename", "split"])
            for r in train_set: writer.writerow([r["image_file"], r["mask_file"], "train"])
            for r in test_set: writer.writerow([r["image_file"], r["mask_file"], "test"])

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_patches", type=str, required=True, help="Raw image patches directory")
    parser.add_argument("--input_masks", type=str, required=True, help="Raw binary mask patches directory")
    parser.add_argument("--output_dir", type=str, required=True, help="Output directory for processed data")
    args = parser.parse_args()

    out_path = Path(args.output_dir)
    stitched_img_dir = out_path / "stitched_images"
    stitched_mask_dir = out_path / "stitched_masks"

    print("Stitching images...")
    stitch_images(args.input_patches, stitched_img_dir, is_mask=False)
    print("Stitching masks...")
    stitch_images(args.input_masks, stitched_mask_dir, is_mask=True)
    
    print("Converting masks to instances and generating splits...")
    generate_splits(stitched_img_dir, stitched_mask_dir, out_path / "cellpose_splits")
    print("Dataset preparation complete.")