"""
Step 2: Fine-Tuning Cellpose-SAM
--------------------------------
Utilizes aggressive data augmentation and specific hyperparameter tuning 
for few-shot domain adaptation on microscopic metallurgical images.
"""

import os
import csv
import shutil
import argparse
from pathlib import Path
import numpy as np
import albumentations as A
from PIL import Image
from tifffile import imread as tiff_imread, imwrite as tiff_imwrite
from cellpose import io, models, train

io.logger_setup()

def get_augmentations():
    """Aggressive augmentation for few-shot scaling (Section 3.5)."""
    return A.Compose([
        A.HorizontalFlip(p=0.5),
        A.VerticalFlip(p=0.5),
        A.RandomRotate90(p=0.5),
        A.ElasticTransform(alpha=60, sigma=8, p=0.4),
        A.GridDistortion(num_steps=5, distort_limit=0.2, p=0.3),
        A.RandomBrightnessContrast(brightness_limit=0.3, contrast_limit=0.3, p=0.8),
        A.RandomGamma(gamma_limit=(70, 130), p=0.5),
        A.CLAHE(clip_limit=3.0, tile_grid_size=(8, 8), p=0.4),
        A.GaussianBlur(blur_limit=(3, 7), p=0.4),
        A.GaussNoise(var_limit=(10.0, 60.0), p=0.5),
        A.CoarseDropout(max_holes=6, max_height=32, max_width=32, fill_value=0, p=0.3),
    ])

def prepare_augmented_data(csv_path, img_dir, mask_dir, work_dir, aug_multiplier=30):
    train_dir, test_dir = work_dir / "train", work_dir / "test"
    os.makedirs(train_dir, exist_ok=True)
    os.makedirs(test_dir, exist_ok=True)
    
    transform = get_augmentations()

    with open(csv_path, mode='r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            img_file, mask_file, split_type = row['image_filename'], row['mask_filename'], row['split']
            stem = Path(img_file).stem.replace("_img", "")
            
            raw_img = np.array(Image.open(img_dir / img_file).convert("RGB"))
            labelled = tiff_imread(mask_dir / mask_file)

            if split_type == "train":
                for i in range(aug_multiplier):
                    if i == 0:
                        img_out, lbl_out = raw_img, labelled
                    else:
                        aug = transform(image=raw_img, mask=labelled.astype(np.int32))
                        img_out, lbl_out = aug["image"], aug["mask"].astype(labelled.dtype)
                    
                    Image.fromarray(img_out).save(train_dir / f"{stem}_aug{i}_img.png")
                    tiff_imwrite(str(train_dir / f"{stem}_aug{i}_masks.tif"), lbl_out.astype(np.uint16))
            else:
                Image.fromarray(raw_img).save(test_dir / f"{stem}_img.png")
                tiff_imwrite(str(test_dir / f"{stem}_masks.tif"), labelled.astype(np.uint16))
                
    return train_dir, test_dir

def main(args):
    work_dir = Path(f"./cellpose_run_{args.split}")
    
    print("Preparing augmented data...")
    train_dir, test_dir = prepare_augmented_data(
        Path(args.csv_file), Path(args.img_dir), Path(args.mask_dir), work_dir, args.aug_multiplier
    )

    output = io.load_train_test_data(
        str(train_dir), str(test_dir), image_filter="_img", mask_filter="_masks", look_one_level_down=False
    )
    images, labels, _, test_images, test_labels, _ = output

    print(f"Initializing Cellpose-SAM model. Training on {len(images)} augmented images.")
    model = models.CellposeModel(gpu=True, pretrained_model="cpsam")

    model_path, _, _ = train.train_seg(
        model.net, train_data=images, train_labels=labels, test_data=test_images, test_labels=test_labels,
        weight_decay=0.2, learning_rate=1e-6, n_epochs=args.epochs, batch_size=args.batch_size,
        model_name="cellpose_grain_316L", save_path=str(work_dir / "models")
    )
    print(f"Training complete. Model saved to {model_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--img_dir", type=str, required=True, help="Directory with processed images")
    parser.add_argument("--mask_dir", type=str, required=True, help="Directory with processed masks")
    parser.add_argument("--csv_file", type=str, required=True, help="Path to the split CSV file")
    parser.add_argument("--split", type=str, default="custom_split", help="Name of the split for output folder")
    parser.add_argument("--batch_size", type=int, default=2)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--aug_multiplier", type=int, default=30)
    args = parser.parse_args()
    main(args)