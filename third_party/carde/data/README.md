# Dataset for the Manuscript: **Data-efficient U-Net for Segmentation of Carbide Microstructures in SEM Images of Steel Alloys**

This dataset contains scanning electron microscopy (SEM) images of steel alloys, including paired secondary electron (SE2) and in-lens (InLens) channels, with corresponding binary segmentation labels. The data supports full reproduction of results presented in the referenced manuscript.

---

## Dataset Description

- **Content:** 13 pairs of SEM images of two reactor pressure vessel (RPV) steels:
  - *JFL*: IAEA reference RPV base metal steel
  - *ANP-10*: Western type RPV steel
  - *ANP-3*: Western type RPV steel
- **Acquisition:**  
  - *JFL*: Zeiss NVision 40 microscope  
  - *ANP-10*: Zeiss Ultra 55 microscope  
  - *ANP-3*: Zeiss Ultra 55 microscope
  - Both SE and InLens detectors used simultaneously.
- **Resolution:** 2048 × 1404 pixels per image  
  - 2048 px width corresponds to 14.3 µm (JFL) or 11.5 µm (ANP-10).

---

## Downloading the dataset

The dataset can be [downloaded from Rodare](https://rodare.hzdr.de/record/4124).

Download the zip file into the `data/` subdirectory of the code repository and extract the archive:

```bash
cd data/
unzip data.zip
```


## Dataset Structure

These directories contain the relevant data for the manuscript:

```
cloud/
├-─ preprocessed/
│   ├── hold-out/
│   ├── images/
│   └── labels/
├── processed_tiles/
│   ├── images/
│   └── labels/
├── tb_logs/
│   ├── unet_model/
```

### Preprocessed

pre-processed whole images and corresponding labels

### Processed Tiles

tiled images and labels

### tb_logs

trained model
