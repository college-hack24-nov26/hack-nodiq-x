# S-metallograph-segmentation: Gray Cast Iron Flake Training & Retraining Protocol

## 1. Domain Background & Scientific Attribution
The **S-metallograph-segmentation** framework was authored by **Luengo et al.** (*Information Fusion 78, 2022*) in research collaboration with **ArcelorMittal**.

### Original Upstream Scope:
The repository was originally engineered and benchmarked for:
- Dual-phase steel microstructures (MetalDAM)
- Ultra-high carbon steels (UHCS)
- Additive manufacturing titanium alloys (Ti-6Al-4V)

### Industrial Gray Cast Iron Limitation:
The upstream repository does not provide pre-trained weights for lamellar graphite flakes in gray cast iron out of the box. Running inference on gray cast iron without custom fine-tuning must strictly display the **EXPERIMENTAL / UNVALIDATED** disclaimer.

This document details how to curate, annotate, and fine-tune models to graduate the engine to validated production release.

---

## 2. Dataset Preparation & Annotation Format

### Recommended Directory Structure:
```text
dataset/gray_cast_iron/
├── train/
│   ├── images/
│   │   ├── sample_001.png
│   │   ├── sample_002.png
│   │   └── ...
│   └── masks/
│       ├── sample_001.png
│       ├── sample_002.png
│       └── ...
└── val/
    ├── images/
    │   ├── sample_val_001.png
    │   └── ...
    └── masks/
        ├── sample_val_001.png
        └── ...
```

### Mask Encoding:
- **Single-channel 8-bit PNG images**:
  - Pixel Value `255`: Graphite flake (Foreground Target)
  - Pixel Value `0`: Matrix phase (Background Ferrite/Pearlite)
- Annotation tools: CVAT, Labelme, or ImageJ thresholding with manual review.

---

## 3. Data Augmentation Pipeline

Micrographs exhibit illumination gradients, specimen polishing relief, and arbitrary orientation. The training pipeline applies:
1. **Random Horizontal & Vertical Flips** ($p = 0.5$)
2. **Orthogonal Rotations** ($90^\circ, 180^\circ, 270^\circ$)
3. **Intensity Scaling & Contrast Jitter**
4. **Resolution Normalization**: Standard patch size of $512 \times 512$ px with preserve-aspect padding.

---

## 4. Hyperparameters & Optimization

| Hyperparameter | Value / Policy | Rationale |
| :--- | :--- | :--- |
| **Architectures** | FPN (`smp.FPN`), UNet++ (`smp.UnetPlusPlus`) | FPN excels at multi-scale flake branches; UNet++ captures fine tips |
| **Encoder Backbone** | `resnet34` / `efficientnet-b3` | Pre-trained ImageNet feature extractors |
| **Loss Function** | Combined Dice Loss ($0.5$) + BCE Loss ($0.5$) | Prevents foreground-background class imbalance collapse |
| **Optimizer** | `AdamW` ($\text{lr} = 10^{-4}$, weight decay $= 10^{-4}$) | Stable weight updates with regularization |
| **LR Scheduler** | `CosineAnnealingLR` ($T_{\max} = 50$, $\eta_{\min} = 10^{-6}$) | Smooth convergence |
| **Batch Size** | 8 | Fits comfortably in 8GB VRAM |
| **Epochs** | 50 – 100 | Early stopping patience of 10 epochs |

---

## 5. Execution Script

Run fine-tuning using the training script:

```bash
python services/gray_cast_iron/train_gray_cast_iron.py \
    --data_dir ./dataset/gray_cast_iron \
    --arch fpn \
    --encoder resnet34 \
    --epochs 50 \
    --batch_size 8 \
    --lr 1e-4 \
    --output_dir checkpoints/s_metalseg
```

---

## 6. Checkpoint Deployment in NODIQ-X

When training concludes, copy the best checkpoint into the production directory:

```bash
mkdir -p checkpoints/s_metalseg
cp checkpoints/s_metalseg/s_metalseg_fpn_best.pt checkpoints/s_metalseg/best_flake_model.pt
```

`services/gray_cast_iron/s_metalseg_adapter.py` automatically scans:
1. `checkpoints/s_metalseg/best_flake_model.pt`
2. `checkpoints/s_metalseg/*.pt`
3. Local upstream checkpoints directory

The adapter will automatically load the fine-tuned weights and update the `checkpoint_identifier` field in both the API response and the Industrial Metallurgical Report.
