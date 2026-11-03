import torch
import random
from pathlib import Path
from torch.utils.data import Dataset
from torch.utils.data import DataLoader
from torch.utils.data import random_split
from torchvision.transforms import GaussianBlur


### dataset class for loading and augmenting image tiles ###
class SEMTileDataset(Dataset):

    def __init__(self, image_dir: Path, label_dir: Path, train=True):
        self.image_dir = image_dir
        self.label_dir = label_dir
        self.train = train

        self.image_files = sorted(image_dir.glob("*"))
        self.label_files = sorted(label_dir.glob("*"))

        assert len(self.image_files) == len(self.label_files), "mismatch between image and label count."

    def __len__(self):
        return len(self.image_files)

    def __getitem__(self, idx: int):
        image = torch.load(self.image_files[idx])  # [2, H, W]
        label = torch.load(self.label_files[idx])  # [1, H, W] or [H, W]

        # channel seperation
        se2 = image[0].unsqueeze(0)  # [1, H, W]
        inlens = image[1].unsqueeze(0)  # [1, H, W]
        image = torch.cat([se2, inlens], dim=0)  # [2, H, W]

        label = label.float() / 255.0

        if label.ndim == 2:
            label = label.unsqueeze(0)  # [1, H, W]

        if self.train:
            image, label = self.transform(image, label)

        return image, label

    def transform(self, image: torch.tensor, label: torch.tensor):
        k = random.randint(0, 3)
        image = torch.rot90(image, k, dims=[1, 2])
        label = torch.rot90(label, k, dims=[1, 2])

        # flip
        if random.random() > 0.5:
            image = torch.flip(image, dims=[2])
            label = torch.flip(label, dims=[2])

        g = random.random()
        if g < 0.33:
            # add noise
            noise_level = random.uniform(0.005, 0.1)
            noise = torch.randn_like(image) * noise_level
            image = image + noise
        elif g < 0.66:
            # apply Gaussian blur
            blur = GaussianBlur(kernel_size=3, sigma=(0.1, 2.0))
            image = blur(image)

        return image, label


### split data into three sets: train, validation, and test ###


def split_data(dataset, batch_size=16, train_ratio=0.8, val_ratio=0.1):
    train_size = int(train_ratio * len(dataset))
    val_size = int(val_ratio * len(dataset))
    test_size = len(dataset) - train_size - val_size
    train_dataset, val_dataset, test_dataset = random_split(dataset, [train_size, val_size, test_size])

    val_dataset.dataset.train = False
    test_dataset.dataset.train = False

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size)
    test_loader = DataLoader(test_dataset, batch_size=batch_size)
    return train_loader, val_loader, test_loader
