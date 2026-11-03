"""
Step 3: Inference and Segmentation Evaluation
-------------------------------------------
Runs inference using a specified Cellpose model, generates boundary visualizations,
and computes Instance Segmentation AP and Boundary F1 scores.
"""

import os
import csv
import argparse
from pathlib import Path
import numpy as np
from PIL import Image
from skimage import segmentation, morphology
from tifffile import imread as tiff_imread
from cellpose import models, metrics

def boundary_f1(pred_bd, gt_bd, tolerance=3):
    gt_dilated = morphology.binary_dilation(gt_bd, morphology.disk(tolerance))
    pred_dilated = morphology.binary_dilation(pred_bd, morphology.disk(tolerance))
    tp_pred = np.logical_and(pred_bd, gt_dilated).sum()
    tp_gt = np.logical_and(gt_bd, pred_dilated).sum()
    precision = tp_pred / (pred_bd.sum() + 1e-7)
    recall = tp_gt / (gt_bd.sum() + 1e-7)
    f1 = 2 * precision * recall / (precision + recall + 1e-7)
    return precision, recall, f1

def main(args):
    input_dir, gt_dir, out_dir = Path(args.input_dir), Path(args.gt_dir), Path(args.output_dir)
    bin_dir, vis_dir = out_dir / "binary_masks", out_dir / "visualizations"
    for d in [out_dir, bin_dir, vis_dir]: d.mkdir(parents=True, exist_ok=True)

    print(f"Loading model: {args.model_path}")
    model = models.CellposeModel(gpu=True, pretrained_model=args.model_path)
    
    all_gt, all_pred, boundary_scores, count_errors, csv_log = [], [], [], [], []
    iou_thresh = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]

    for img_path in input_dir.glob("*_img.*"):
        img = np.array(Image.open(img_path).convert("RGB"))
        pred_masks, _, _ = model.eval(img, diameter=0, channels=[0, 0])
        
        boundaries = morphology.binary_dilation(segmentation.find_boundaries(pred_masks, mode="outer"), morphology.disk(2))
        binary_output = np.full(pred_masks.shape, 255, dtype=np.uint8)
        binary_output[boundaries] = 0
        binary_output[pred_masks == 0] = 0
        Image.fromarray(binary_output).save(bin_dir / f"{img_path.stem}_mask.png")

        gt_mask_path = gt_dir / f"{img_path.stem.replace('_img', '')}_masks.tif"
        if gt_mask_path.exists():
            gt_labels = tiff_imread(str(gt_mask_path))
            all_gt.append(gt_labels); all_pred.append(pred_masks)
            
            n_pred, n_gt = int(pred_masks.max()), int(gt_labels.max())
            csv_log.append({"image": img_path.name, "pred": n_pred, "gt": n_gt, "error": n_pred - n_gt})
            count_errors.append(n_pred - n_gt)

            gt_bd = morphology.binary_dilation(segmentation.find_boundaries(gt_labels, mode="outer"), morphology.disk(2))
            boundary_scores.append(boundary_f1(boundaries, gt_bd))

    if all_gt:
        ap, _, _, _ = metrics.average_precision(all_gt, all_pred, threshold=iou_thresh)
        mAP = np.nanmean(np.nanmean(ap, axis=0))
        mean_f1 = np.mean([s[2] for s in boundary_scores])
        
        report = f"mAP (0.5-0.95): {mAP:.4f} | Boundary F1: {mean_f1:.4f} | Mean Count Err: {np.mean(count_errors):.1f}"
        print(f"\n{report}")
        with open(out_dir / "metrics.txt", "w") as f: f.write(report)
        
        with open(out_dir / "counts.csv", "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["image", "pred", "gt", "error"])
            writer.writeheader(); writer.writerows(csv_log)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_dir", type=str, required=True)
    parser.add_argument("--gt_dir", type=str, required=True)
    parser.add_argument("--model_path", type=str, required=True, help="'cpsam' for zero-shot or path to fine-tuned weights")
    parser.add_argument("--output_dir", type=str, required=True)
    args = parser.parse_args()
    main(args)