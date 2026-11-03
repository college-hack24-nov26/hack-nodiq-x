"""Reproducible Training and Fine-Tuning Pipeline for Gray Cast Iron Flake Segmentation.

Based on S-metallograph-segmentation (Luengo et al., Information Fusion 78, 2022).
Enables transfer learning and fine-tuning with PyTorch & segmentation-models-pytorch.

Scientific & Data Integrity Policy:
- If suitable expert-labeled gray cast iron micrographs are not present, do not invent masks,
  do not train on unrelated steel phases, and do not claim model is trained.
- Checkpoints are saved with full metadata (architecture, backbone, validation IoU, Dice, Precision, Recall).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, Dataset
except ImportError:
    torch = None
    DataLoader = None
    Dataset = object

    class _NNMock:
        Module = object

    nn = _NNMock()

try:
    import segmentation_models_pytorch as smp
except ImportError:
    smp = None


class GrayCastIronDataset(Dataset):
    """Dataset for paired gray cast iron micrographs and binary graphite flake masks."""

    def __init__(self, images_dir: Path, masks_dir: Path, img_size: int = 512, augment: bool = True):
        self.images_dir = Path(images_dir)
        self.masks_dir = Path(masks_dir)
        self.img_size = img_size
        self.augment = augment

        valid_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
        self.image_files = sorted([
            f for f in self.images_dir.iterdir()
            if f.suffix.lower() in valid_exts and (self.masks_dir / (f.stem + ".png")).exists()
        ]) if self.images_dir.exists() and self.masks_dir.exists() else []

    def __len__(self) -> int:
        return len(self.image_files)

    def __getitem__(self, idx: int):
        img_path = self.image_files[idx]
        mask_path = self.masks_dir / (img_path.stem + ".png")

        # Load image (RGB)
        img = cv2.imread(str(img_path))
        if img is None:
            raise RuntimeError(f"Failed to read image: {img_path}")
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        # Load mask (binary: 255 for graphite flake, 0 for matrix)
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            raise RuntimeError(f"Failed to read mask: {mask_path}")

        # Resize to fixed dimension
        img = cv2.resize(img, (self.img_size, self.img_size), interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask, (self.img_size, self.img_size), interpolation=cv2.INTER_NEAREST)

        # Data augmentations (flips & orthogonal rotations)
        if self.augment:
            if np.random.rand() > 0.5:
                img = np.fliplr(img).copy()
                mask = np.fliplr(mask).copy()
            if np.random.rand() > 0.5:
                img = np.flipud(img).copy()
                mask = np.flipud(mask).copy()
            k = np.random.randint(0, 4)
            if k > 0:
                img = np.rot90(img, k).copy()
                mask = np.rot90(mask, k).copy()

        # Normalize image to [0, 1] and CHW format
        img_t = torch.from_numpy(img.transpose(2, 0, 1)).float() / 255.0
        # Binary mask: {0.0, 1.0}
        mask_t = torch.from_numpy((mask > 127).astype(np.float32)).unsqueeze(0)

        return img_t, mask_t


class CombinedLoss(nn.Module):
    """Dice Loss + Binary Cross Entropy Loss for crisp flake boundary convergence."""

    def __init__(self, dice_weight: float = 0.5, bce_weight: float = 0.5, smooth: float = 1e-6):
        super().__init__()
        self.dice_weight = dice_weight
        self.bce_weight = bce_weight
        self.smooth = smooth
        self.bce = nn.BCEWithLogitsLoss()

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        bce_loss = self.bce(logits, targets)
        probs = torch.sigmoid(logits)
        intersection = (probs * targets).sum(dim=(2, 3))
        union = probs.sum(dim=(2, 3)) + targets.sum(dim=(2, 3))
        dice_score = (2.0 * intersection + self.smooth) / (union + self.smooth)
        dice_loss = 1.0 - dice_score.mean()
        return self.bce_weight * bce_loss + self.dice_weight * dice_loss


def build_model(arch: str = "fpn", encoder: str = "resnet34"):
    """Instantiate S-metallograph-segmentation model architecture."""
    if smp is None:
        raise RuntimeError("segmentation_models_pytorch is required to train S-metallograph-segmentation.")

    arch_lower = arch.lower()
    if arch_lower == "fpn":
        model = smp.FPN(
            encoder_name=encoder,
            encoder_weights="imagenet",
            in_channels=3,
            classes=1,
            activation=None,
        )
    elif arch_lower in ("unet", "unetplusplus", "unet++"):
        model = smp.UnetPlusPlus(
            encoder_name=encoder,
            encoder_weights="imagenet",
            in_channels=3,
            classes=1,
            activation=None,
        )
    else:
        raise ValueError(f"Unsupported architecture: {arch}. Choose 'fpn' or 'unetplusplus'.")

    return model


try:
    from nodiq.services.gray_cast_iron.validate_dataset import (
        validate_gray_cast_iron_dataset,
        print_validation_report,
    )
except ImportError:
    try:
        from validate_dataset import (
            validate_gray_cast_iron_dataset,
            print_validation_report,
        )
    except ImportError:
        validate_gray_cast_iron_dataset = None
        print_validation_report = None


def check_dataset_readiness(data_dir: Path) -> Tuple[bool, str]:
    """Verify presence and validity of expert-labeled gray cast iron training data."""
    if validate_gray_cast_iron_dataset is not None:
        results = validate_gray_cast_iron_dataset(data_dir)
        if not results["is_valid"]:
            train_img_dir = data_dir / "train" / "images"
            train_mask_dir = data_dir / "train" / "masks"
            err_summary = "\n".join(f"  - {e}" for e in results.get("overall_errors", [])[:5])
            if not err_summary:
                for s in results.get("splits", {}).values():
                    if s.get("errors"):
                        err_summary = "\n".join(f"  - {e}" for e in s["errors"][:5])
                        break
            msg = (
                f"[DATASET BLOCKER] Dataset validation failed for {data_dir}:\n"
                f"{err_summary if err_summary else '  - Zero paired micrographs and masks found.'}\n\n"
                f"REQUIRED PREREQUISITES TO PROCEED:\n"
                f"1. Minimum 30-50 optical micrographs of gray cast iron (100x/200x unetched or nital).\n"
                f"2. Paired expert-reviewed binary masks (255 = graphite flake, 0 = matrix).\n"
                f"3. Train/Val/Test partitions split strictly by source specimen (not random cropping).\n"
                f"4. Verified absence of split leakage, duplicate images, and non-binary pixel values.\n"
                f"Scientific Integrity Policy: No synthetic masks were fabricated and no unrelated steel-phase weights were applied."
            )
            return False, msg
        total_p = results["summary"].get("total_paired", 0)
        return True, f"Found {total_p} paired training micrographs and masks passing all integrity checks."

    train_img_dir = data_dir / "train" / "images"
    train_mask_dir = data_dir / "train" / "masks"

    if not train_img_dir.exists() or not train_mask_dir.exists():
        msg = (
            f"[DATASET BLOCKER] Missing training directories:\n"
            f"  - Images: {train_img_dir} (exists: {train_img_dir.exists()})\n"
            f"  - Masks:  {train_mask_dir} (exists: {train_mask_dir.exists()})\n"
            f"REQUIRED PREREQUISITES TO PROCEED:\n"
            f"1. Minimum 30–50 optical micrographs of gray cast iron (100x/200x unetched or nital).\n"
            f"2. Paired expert-reviewed binary masks (255 = graphite flake, 0 = matrix).\n"
            f"3. Train/Val/Test partitions split strictly by source specimen (not random cropping).\n"
            f"Scientific Integrity Policy: No synthetic masks were fabricated and no unrelated steel-phase weights were applied."
        )
        return False, msg

    valid_exts = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
    pairs = [
        f for f in train_img_dir.iterdir()
        if f.suffix.lower() in valid_exts and (train_mask_dir / (f.stem + ".png")).exists()
    ]

    if len(pairs) == 0:
        msg = (
            f"[DATASET BLOCKER] Training directory {train_img_dir} contains 0 paired image/mask files.\n"
            f"Expert annotations are required before training can be initiated."
        )
        return False, msg

    return True, f"Found {len(pairs)} paired training micrographs and masks."


def train(
    data_dir: Path,
    output_dir: Path,
    arch: str = "fpn",
    encoder: str = "resnet34",
    epochs: int = 50,
    batch_size: int = 8,
    lr: float = 1e-4,
    device_name: str = "cuda" if torch and torch.cuda.is_available() else "cpu",
    dry_run: bool = False,
) -> Optional[Dict[str, Any]]:
    """Run full training loop with validation metrics, checkpointing, and missing-data verification."""
    if torch is None or smp is None:
        print("[ERROR] PyTorch and segmentation-models-pytorch must be installed.")
        return None

    device = torch.device(device_name)
    print(f"[INFO] Using compute device: {device}")

    # Missing dataset audit
    if not dry_run:
        ready, message = check_dataset_readiness(data_dir)
        print(message)
        if not ready:
            print("[ABORT] Cannot proceed without verified expert-labeled gray cast iron training data.")
            return None

    model = build_model(arch=arch, encoder=encoder).to(device)
    criterion = CombinedLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-6)

    output_dir.mkdir(parents=True, exist_ok=True)
    best_dice = 0.0
    best_checkpoint_path = None

    if dry_run:
        print("[DRY-RUN] Executing 1 synthetic dry-run epoch to verify pipeline and checkpoint serialization...")
        # Create small synthetic batch
        x = torch.rand(2, 3, 256, 256, device=device)
        y = (torch.rand(2, 1, 256, 256, device=device) > 0.8).float()

        model.train()
        optimizer.zero_grad()
        out = model(x)
        loss = criterion(out, y)
        loss.backward()
        optimizer.step()

        # Validation metrics on synthetic batch
        model.eval()
        with torch.no_grad():
            preds = (torch.sigmoid(model(x)) > 0.5).float()
            inter = (preds * y).sum().item()
            union = preds.sum().item() + y.sum().item()
            val_dice = (2.0 * inter + 1e-6) / (union + 1e-6)
            val_iou = (inter + 1e-6) / (union - inter + 1e-6)
            tp = inter
            fp = preds.sum().item() - inter
            fn = y.sum().item() - inter
            val_prec = (tp + 1e-6) / (tp + fp + 1e-6)
            val_rec = (tp + 1e-6) / (tp + fn + 1e-6)

        best_path = output_dir / f"s_metalseg_{arch}_dry_run.pt"
        torch.save({
            "epoch": 1,
            "model_state_dict": model.state_dict(),
            "arch": arch,
            "encoder": encoder,
            "classes": 1,
            "val_dice": round(val_dice, 4),
            "val_iou": round(val_iou, 4),
            "val_precision": round(val_prec, 4),
            "val_recall": round(val_rec, 4),
            "val_loss": round(loss.item(), 4),
            "hyperparameters": {"lr": lr, "batch_size": batch_size, "dry_run": True},
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }, str(best_path))
        print(f"[DRY-RUN SUCCESS] Pipeline verified. Mock checkpoint saved to: {best_path}")
        return {
            "checkpoint_path": str(best_path),
            "val_dice": val_dice,
            "val_iou": val_iou,
            "val_loss": loss.item(),
        }

    # Real training path
    train_img_dir = data_dir / "train" / "images"
    train_mask_dir = data_dir / "train" / "masks"
    val_img_dir = data_dir / "val" / "images"
    val_mask_dir = data_dir / "val" / "masks"

    train_ds = GrayCastIronDataset(train_img_dir, train_mask_dir, augment=True)
    val_ds = (
        GrayCastIronDataset(val_img_dir, val_mask_dir, augment=False)
        if val_img_dir.exists() and val_mask_dir.exists()
        else None
    )

    print(f"[INFO] Found {len(train_ds)} training images and {len(val_ds) if val_ds else 0} validation images.")
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = (
        DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=0)
        if val_ds and len(val_ds) > 0
        else None
    )

    print(f"\n[START] Beginning fine-tuning {arch.upper()} for {epochs} epochs...")
    for epoch in range(1, epochs + 1):
        t0 = time.time()
        model.train()
        train_loss = 0.0

        for images, masks in train_loader:
            images = images.to(device)
            masks = masks.to(device)

            optimizer.zero_grad()
            logits = model(images)
            loss = criterion(logits, masks)
            loss.backward()
            optimizer.step()

            train_loss += loss.item() * images.size(0)

        scheduler.step()
        train_loss /= max(len(train_ds), 1)

        # Validation
        val_dice = 0.0
        val_iou = 0.0
        val_prec = 0.0
        val_rec = 0.0
        val_loss = 0.0

        if val_loader:
            model.eval()
            total_dice, total_iou, total_prec, total_rec = 0.0, 0.0, 0.0, 0.0
            with torch.no_grad():
                for images, masks in val_loader:
                    images = images.to(device)
                    masks = masks.to(device)
                    logits = model(images)
                    loss = criterion(logits, masks)
                    val_loss += loss.item() * images.size(0)

                    preds = (torch.sigmoid(logits) > 0.5).float()
                    inter = (preds * masks).sum().item()
                    union = preds.sum().item() + masks.sum().item()
                    total_dice += (2.0 * inter + 1e-6) / (union + 1e-6)
                    total_iou += (inter + 1e-6) / (union - inter + 1e-6)

                    tp = inter
                    fp = preds.sum().item() - inter
                    fn = masks.sum().item() - inter
                    total_prec += (tp + 1e-6) / (tp + fp + 1e-6)
                    total_rec += (tp + 1e-6) / (tp + fn + 1e-6)

            n_val = len(val_loader)
            val_dice = total_dice / n_val
            val_iou = total_iou / n_val
            val_prec = total_prec / n_val
            val_rec = total_rec / n_val
            val_loss /= max(len(val_ds), 1)

        elapsed = time.time() - t0
        print(
            f"Epoch [{epoch:02d}/{epochs:02d}] - Loss: {train_loss:.4f} - "
            f"Val Dice: {val_dice:.4f} - Val IoU: {val_iou:.4f} ({elapsed:.1f}s)"
        )

        # Save best model
        if val_dice >= best_dice:
            best_dice = val_dice
            best_path = output_dir / f"s_metalseg_{arch}_best.pt"
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.state_dict(),
                "arch": arch,
                "encoder": encoder,
                "classes": 1,
                "val_dice": round(val_dice, 4),
                "val_iou": round(val_iou, 4),
                "val_precision": round(val_prec, 4),
                "val_recall": round(val_rec, 4),
                "val_loss": round(val_loss, 4),
                "hyperparameters": {"lr": lr, "batch_size": batch_size},
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }, str(best_path))
            best_checkpoint_path = str(best_path)
            print(f"  --> Saved new best checkpoint to {best_path}")

    print("\n[SUCCESS] Training finished. Checkpoints saved to:", output_dir)
    return {
        "checkpoint_path": best_checkpoint_path,
        "val_dice": best_dice,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train S-metallograph-segmentation on Gray Cast Iron.")
    parser.add_argument("--data_dir", type=str, default="./dataset/gray_cast_iron", help="Dataset directory")
    parser.add_argument("--output_dir", type=str, default="checkpoints/s_metalseg", help="Checkpoint save directory")
    parser.add_argument("--arch", type=str, default="fpn", choices=["fpn", "unetplusplus"], help="Model architecture")
    parser.add_argument("--encoder", type=str, default="resnet34", help="Backbone encoder")
    parser.add_argument("--epochs", type=int, default=50, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=8, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-4, help="Learning rate")
    parser.add_argument("--dry_run", action="store_true", help="Run 1 synthetic dry-run epoch to verify pipeline")
    parser.add_argument("--validate_only", action="store_true", help="Run dataset validator and report without training")
    args = parser.parse_args()

    if args.validate_only:
        data_path = Path(args.data_dir)
        if validate_gray_cast_iron_dataset is not None:
            results = validate_gray_cast_iron_dataset(data_path)
            if print_validation_report is not None:
                print_validation_report(results)
            sys.exit(0 if results["is_valid"] else 1)
        else:
            ready, msg = check_dataset_readiness(data_path)
            print(msg)
            sys.exit(0 if ready else 1)

    train(
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        arch=args.arch,
        encoder=args.encoder,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        dry_run=args.dry_run,
    )
