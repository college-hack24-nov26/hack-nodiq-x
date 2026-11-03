"""
Step 4: ASTM Jeffries Planimetric Evaluation
--------------------------------------------
Calculates the ASTM E112-25 Grain Size Number (G) using dynamic inscribed circles.
Modes:
  - superimposed: Uses the GT mask to determine the optimal circle and copies it to the prediction.
  - independent: Calculates the optimal circle for GT and Prediction autonomously (Section 4.2.1).
"""

import os
import cv2
import argparse
import numpy as np
import pandas as pd
from scipy import ndimage

def get_optimal_radius(dists_max, target, max_r):
    for r in range(10, int(max_r), 2):
        if np.sum(dists_max < r) >= target:
            return r
    return max_r

def calculate_jeffries(img_path, target, mode="independent", optimal_r_gt=None, pixels_per_um=2.26):
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None: return None
    
    h, w = img.shape
    cx, cy = w // 2, h // 2
    Y, X = np.ogrid[:h, :w]
    dist_from_center = np.sqrt((X - cx)**2 + (Y - cy)**2)
    max_possible_r = min(cx, cy)

    _, thresh = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
    num_labels, labels = cv2.connectedComponents(thresh)
    
    if num_labels < 2: return None

    grain_indices = np.arange(1, num_labels)
    min_dists = ndimage.minimum(dist_from_center, labels, index=grain_indices)
    max_dists = ndimage.maximum(dist_from_center, labels, index=grain_indices)

    if mode == "superimposed" and optimal_r_gt is not None:
        r = optimal_r_gt
    else:
        r = get_optimal_radius(max_dists, target, max_possible_r)

    internal_grains = np.sum(max_dists < r)
    intercepted_grains = np.sum((min_dists <= r) & (max_dists >= r))
    
    circle_area_mm2 = (np.pi * (r ** 2)) / (pixels_per_um ** 2) / 1_000_000
    dynamic_f = 1.0 / circle_area_mm2 if circle_area_mm2 > 0 else 0
    na = dynamic_f * (internal_grains + (intercepted_grains / 2.0))
    g = (3.321928 * np.log10(na) - 2.954) if na > 0 else 0.0

    return {'r': r, 'internal': internal_grains, 'intercepted': intercepted_grains, 'na': na, 'g': g}

def main(args):
    os.makedirs(args.output_dir, exist_ok=True)
    results, summary_data = [], []
    targets = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

    for target in targets:
        for gt_file in os.listdir(args.gt_dir):
            if not gt_file.endswith(('.png', '.tif')): continue
            base_id = gt_file.split('_')[0]
            
            # Find matching prediction
            pred_file = next((p for p in os.listdir(args.pred_dir) if p.startswith(base_id)), None)
            if not pred_file: continue

            gt_res = calculate_jeffries(os.path.join(args.gt_dir, gt_file), target, mode="independent")
            if not gt_res: continue
            
            pred_res = calculate_jeffries(
                os.path.join(args.pred_dir, pred_file), target, 
                mode=args.mode, optimal_r_gt=gt_res['r']
            )
            if not pred_res: continue

            results.append({
                'target': target, 'image': base_id,
                'Na_gt': gt_res['na'], 'G_gt': gt_res['g'],
                'Na_pred': pred_res['na'], 'G_pred': pred_res['g']
            })

    df = pd.DataFrame(results)
    df.to_csv(os.path.join(args.output_dir, f"jeffries_{args.mode}_full.csv"), index=False)

    for target, group in df.groupby('target'):
        g_gt, g_pred = group['G_gt'], group['G_pred']
        valid = g_gt > 0
        mape = np.mean(np.abs((g_pred[valid] - g_gt[valid]) / g_gt[valid])) * 100 if valid.any() else np.nan
        
        summary_data.append({'Target': target, 'G_GT': g_gt.mean(), 'G_Pred': g_pred.mean(), 'G_MAPE': mape})

    pd.DataFrame(summary_data).to_csv(os.path.join(args.output_dir, f"jeffries_{args.mode}_summary.csv"), index=False)
    print(f"Evaluation complete. Results saved to {args.output_dir}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gt_dir", type=str, required=True)
    parser.add_argument("--pred_dir", type=str, required=True, help="Directory containing binary output masks from step 3")
    parser.add_argument("--output_dir", type=str, required=True)
    parser.add_argument("--mode", type=str, choices=["superimposed", "independent"], required=True)
    args = parser.parse_args()
    main(args)