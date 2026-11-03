# Gray Cast Iron Graphite Flake Segmentation: Dataset Curation & Workflow Specification

**Standard & Regulatory Context:** Metallurgical Image Analysis | ISO 945-1 / ASTM A247 Compliance Roadmap  
**Document Status:** Technical Specification & Data Governance Standard  

---

## 1. Missing Data Declaration & Scientific Integrity

> [!IMPORTANT]
> **Current Repository Status: NO COMPATIBLE GROUND TRUTH EXISTS**
> - The current repository contains **zero** expert-annotated ground-truth binary masks for gray cast iron lamellar graphite flakes.
> - Upstream **S-metallograph-segmentation** weights were trained on **dual-phase steel (MetalDAM)**, **ultrahigh-carbon steel (UHCS spheroidite)**, and **titanium alloys**, **NOT** lamellar graphite in cast iron.
> - **Zero Tolerance for Data Invention:** In accordance with ISO 17025 and industrial metallographic standards, synthetic masks have **not** been fabricated, and unrelated steel-phase labels have **not** been substituted.
> - Until the dataset described below is acquired and validated, the engine operates on a verified **Classical Metallographic Baseline (Otsu bimodal inversion + morphological smoothing)**, and is explicitly labeled as such.

---

## 2. Prerequisites & Missing Data Inventory

To train and validate an industrial-grade Feature Pyramid Network (FPN) or UNet++ model for production release, the following data is required:

| Item | Minimum Requirement | Recommended Specification | Status |
| :--- | :--- | :--- | :---: |
| **Unique Micrographs** | 30 independent specimens | 100+ casting specimens (multiple heats/foundries) | **Missing** |
| **Resolution** | Minimum $1024 \times 1024$ px | $2048 \times 1536$ px optical sensor | **Missing** |
| **Flake Morphology Coverage** | ASTM A247 Type A (uniform) | Types A, B (rosette), C (kish), D (interdendritic), E | **Missing** |
| **Matrix Conditions** | Polished unetched | Both unetched and light 2% nital etched | **Missing** |
| **Paired Binary Masks** | 30 expert-reviewed masks | 100+ dual-reviewed ground-truth masks | **Missing** |
| **Spatial Calibration** | Known µm/px on every field | Certified stage micrometer calibration | **Missing** |

---

## 3. Micrograph Acquisition Protocol

### 3.1 Specimen Preparation
- **Metallographic Polish:** Metallographic preparation per ASTM E3. Final polishing with $0.05\ \mu\text{m}$ colloidal silica.
- **Etching State:**
  - **Unetched:** Strongly preferred for graphite flake area fraction and ASTM A247 flake length classification to eliminate matrix pearlite lamellae boundary interference.
  - **Light Nital (2% $\text{HNO}_3$ in ethanol, 3–5 seconds):** Permitted only when matrix phase decomposition (ferrite vs. pearlite ratio) is simultaneously required.
- **Graphite Retention:** Polishing must prevent graphite pull-out cavities and polishing drag tails.

### 3.2 Optical Microscopy Settings
- **Magnification:** Standard $100\times$ total magnification (objective $10\times$, optical zoom $1\times$) per ASTM A247 and ISO 945-1. Optional $200\times$ for fine Type D/E eutectic flakes.
- **Illumination:** Uniform Köhler illumination, green optical contrast filter ($540\ \text{nm}$), aperture diaphragm adjusted to $70\text{–}80\%$ to avoid halo diffraction artifacts around flake tips.
- **Image Format:** Lossless 8-bit grayscale or 24-bit RGB (TIFF or PNG format, uncompressed). JPEG compression artifacts along flake edges are strictly prohibited.

---

## 4. Expert Ground-Truth Annotation Protocol

### 4.1 Mask Encoding Specification
- **Format:** Single-channel 8-bit PNG images with identical spatial dimensions ($H \times W$) to the raw micrograph.
- **Pixel Values:**
  - `255` (White): **Lamellar Graphite Flakes** (Foreground Target).
  - `0` (Black): **Matrix Phase** (Background Ferrite, Pearlite, Steadite).

### 4.2 Annotation Rules
1. **Flake Boundary Tracing:** Trace the true outer physical perimeter of the graphite flake. Do not dilate into the optical reflection halo at matrix boundaries.
2. **Narrow Flake Tips:** Trace thin dendritic flake branches down to optical resolution limit ($> 1\ \text{px}$).
3. **Artifact Rejection:**
   - **Porosity / Pull-outs:** Spherical or jagged dark cavities without graphite carbon content must be labeled as background (`0`).
   - **Scratches & Polishing Debris:** Fine linear preparation marks must be rejected.
   - **Pearlite Lamellae:** Dark cementite lamellae in etched pearlite must **not** be segmented as graphite flakes.
4. **Scale Bar & Stamp Area:** Microscope data stamps, text annotations, and burned-in micron bars must be marked with a dedicated `ignore_index` or pre-cropped out before training.

---

## 5. Source-Specimen Partitioning (Anti-Leakage Strategy)

> [!CAUTION]
> **Never Split Tiles by Random Cropping from the Same Micrograph**
> Splitting overlapping or neighboring $512 \times 512$ tiles from the same physical micrograph into train and test sets leads to massive data leakage and artificially inflated accuracy scores.

### 5.1 Partitioning Structure:
All data must be split **at the physical specimen / casting heat level**:

```text
dataset/gray_cast_iron/
├── train/          (70% of unique specimen ingots)
│   ├── images/
│   │   ├── specimen_01_field_01.png
│   │   ├── specimen_01_field_02.png
│   │   └── ...
│   └── masks/
│       ├── specimen_01_field_01.png
│       └── ...
├── val/            (15% of unique specimen ingots)
│   ├── images/
│   │   ├── specimen_05_field_01.png
│   │   └── ...
│   └── masks/
│       ├── specimen_05_field_01.png
│       └── ...
└── test/           (15% of unique specimen ingots)
    ├── images/
    │   ├── specimen_08_field_01.png
    │   └── ...
    └── masks/
        ├── specimen_08_field_01.png
        └── ...
```

---

## 6. Dataset Licensing & Data Governance

1. **Permissive Open Metallurgical License:** Datasets curated under this initiative should be released under **Creative Commons Attribution 4.0 International (CC BY 4.0)** or **OpenRAIL-M** to facilitate reproducible metallurgical benchmark evaluation.
2. **Attribution:** Any publication utilizing this benchmark must cite Luengo et al. (*Information Fusion*, 2022) for the underlying S-metallograph-segmentation framework and the contributing foundry/laboratory for the microstructural ground truth.
3. **Confidentiality:** Proprietary casting alloy codes and customer part numbers must be anonymized before inclusion in the dataset.

---

## 7. ASTM A247 & ISO 945-1 Compliance Roadmap

Under current state, the application strictly displays:
`UNVALIDATED (ISO 945-1 / ASTM A247 flake classification requires reference chart evaluation)`

### Formal Validation Prerequisites:
To graduate from unvalidated baseline to certified compliance, the following three components must be completed and audited:
1. **Trained & Benchmarked FPN/UNet++ Model:** Achieving validation IoU $> 0.85$ and Dice $> 0.90$ across all ASTM A247 flake distributions.
2. **Flake Separation & Morphological Classifier:** Implementation of marker-controlled watershed segmentation to separate touching rosette clusters into individual flake branches, followed by automated length classification against ASTM A247 Size Classes 1 through 8.
3. **Inter-Laboratory Comparison:** Comparative empirical audit against certified reference metallograms and manual visual rating by at least two qualified metallurgical engineers.
