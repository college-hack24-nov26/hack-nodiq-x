from pathlib import Path
import click
from skimage.io import imread, imsave
from skimage.measure import regionprops_table
import numpy as np
import pandas as pd
import SimpleITK as sitk
from natsort import natsorted
from carde.io import (
    local_data_path,
    image_path,
    label_path,
    tiled_label_path,
    tiled_image_path,
    read_image_pair,
    get_image_number,
    calculate_matching_image_number,
    read_label_number,
)
from warnings import warn
import numpy as np
try:
    import torch
except ImportError:
    torch = None
from skimage.util import view_as_windows
try:
    from sklearn.preprocessing import RobustScaler
except ImportError:
    RobustScaler = None

pixel_size_um = 1 / 180


def get_metadata_index(image):
    """
    Get the index of the metadata in the image so that we can crop the metadata away for further processing.

    This function finds the large bright object containing the metadata in the image and returns the index of the row just before the first row of the object.

    Parameters:
    image (numpy.ndarray): The input image as a NumPy array.

    Returns:
    int: The index of the row just before the first occurrence of 255 in the image.
    """
    mask = sitk.OtsuThreshold(sitk.GetImageFromArray(image), 0, 1)
    mask = sitk.ConnectedComponent(mask)
    mask = sitk.RelabelComponent(mask, minimumObjectSize=10 * image.shape[1])
    label_stats = sitk.LabelShapeStatisticsImageFilter()
    label_stats.Execute(mask)

    largest_label = 0
    largest_label_size = 0
    for label in label_stats.GetLabels():
        if label_stats.GetNumberOfPixels(label) > largest_label_size:
            largest_label = label
            largest_label_size = label_stats.GetNumberOfPixels(label)
    mask = sitk.BinaryThreshold(mask, largest_label, largest_label, 1, 0)
    mask = sitk.GetArrayFromImage(mask)
    return min(np.where(mask)[0]) - 2


def crop_away_metadata(image: np.ndarray, metadata_index: int = None) -> np.ndarray:
    """
    Crops the metadata away from the given image.

    Parameters
    ----------
    image: np.ndarray
        The image to crop.
    metadata_index: int (optional)
        The row index at which the metadata starts in the image. Everything before this index will be cropped away. Defult is to determine the index automatically using get_metadata_index.

    Returns
    -------
    np.ndarray
        The cropped image.
    """
    if metadata_index is None:
        metadata_index = get_metadata_index(image)
    if metadata_index < 0:
        warn("No metadata found in the image. Returning the original image.")
        return image
    return image[:metadata_index, ...]


def preprocess_image(image_path: Path) -> np.ndarray:
    """
    Preprocesses an image by cropping away metadata and optionally processing a corresponding label image.

    Args:
        image_path (Path): The path to the image file to be processed.

    Returns:
        Tuple[np.ndarray, Optional[np.ndarray]]: A tuple containing the cropped image and the cropped label image.
            The cropped label image is None if the corresponding label image file does not exist.
    """
    image = imread(image_path)
    # crop off the metadata
    metadata_index = get_metadata_index(image)
    cropped_image = crop_away_metadata(image, metadata_index)
    label_image_path = image_path.parent.parent.glob("*Image_Filtered*.bmp").__next__()
    if label_image_path.exists():
        # crop off the metadata
        cropped_label_image = crop_away_metadata(imread(label_image_path), metadata_index)
        cropped_label_image = np.bitwise_and(
            cropped_label_image[:, :, 2] == 255,
            cropped_label_image[:, :, 1] == 255,
            cropped_label_image[:, :, 0] == 0,
        )
        assert (
            cropped_image.shape == cropped_label_image.shape
        ), f"Image and label image must have the same shape. Got image shape: {cropped_image.shape} and label image shape: {cropped_label_image.shape}."
    else:
        cropped_label_image = None
    return cropped_image, cropped_label_image


def preprocess_images(
    data_path: Path = local_data_path, target_image_path: Path = image_path, target_label_path: Path = label_path
):
    """
    Preprocess images from the specified data path and save the preprocessed images and labels to the target paths.

    Args:
        data_path (Path): The path to the directory containing the original images.
        target_image_path (Path): The path to the directory where the preprocessed images will be saved.
        target_label_path (Path): The path to the directory where the preprocessed label images will be saved.

    Returns:
        None

    Notes:
        - The function expects the images to be in subdirectories named with digits and containing 'Original' in their names.
        - The preprocessed images are saved in the target_image_path directory with the same name as the original images.
        - If a preprocessed label image is generated, it is saved in the target_label_path directory with '_label.png' appended to the original image name.
    """

    # load the images
    image_paths = data_path.glob("[0-9]*/Original*/*.tif")

    # preprocess the images
    for image_path in image_paths:
        cropped_image, cropped_label_image = preprocess_image(image_path)
        # save the preprocessed image
        target_image_path.mkdir(exist_ok=True, parents=True)
        cropped_image_path = target_image_path / image_path.name
        imsave(cropped_image_path, cropped_image)
        if cropped_label_image is not None:
            # save the preprocessed label image
            target_label_path.mkdir(exist_ok=True, parents=True)
            cropped_label_image_path = target_label_path / (image_path.stem + "_label.png")
            imsave(cropped_label_image_path, np.uint8(cropped_label_image * 255))
        print(f"Preprocessed {image_path.name}")


def segment_otsu(image: np.ndarray, sigma: float = 1.0, radius: float = 30.0, minimum_size: int = 3) -> np.ndarray:
    """
    Segments the given image using Otsu's method.

    Parameters
    ----------
    image: np.ndarray
        The image to segment.
    sigma: float
        The standard deviation of the Gaussian filter.
    radius: float
        The radius of the white tophat background removal operation.
    minimum_size: int
        The minimum size of the objects to keep.

    Returns
    -------
    np.ndarray
        The segmented image.
    """
    # denoise the image

    segmented = sitk.GetImageFromArray(image)
    segmented = sitk.DiscreteGaussian(segmented, variance=[sigma, sigma])
    # subtract the background
    if radius > 0:
        segmented = sitk.WhiteTopHat(segmented, kernelRadius=[30, 30])
    # threshold the image
    segmented = sitk.OtsuThreshold(segmented, 0, 1)
    segmented = sitk.BinaryFillhole(segmented)
    segmented = sitk.ConnectedComponent(segmented)
    segmented = sitk.RelabelComponent(segmented, minimumObjectSize=minimum_size)
    return sitk.GetArrayFromImage(segmented)


def combine_images(image_SE2: np.ndarray, image_inlens: np.ndarray) -> np.ndarray:
    """
    Combines two images by taking the average of their pixel values.

    Parameters
    ----------
    image_SE2: np.ndarray
        The SE2 image.
    image_inlens: np.ndarray
        The inlens image.

    Returns
    -------
    np.ndarray
        The combined image.
    """
    return (image_SE2 // 2) + (image_inlens // 2)


def segment_combined(image_SE2: np.ndarray, image_inlens: np.ndarray, *args, **kwargs) -> np.ndarray:
    """
    Segments the average of two images using Otsu's method.

    Parameters
    ----------
    image_SE2: np.ndarray
        The SE2 image.
    image_inlens: np.ndarray
        The inlens image.
    *args
        Additional arguments for [segment_otsu](#segment_otsu).
    **kwargs
        Additional keyword arguments for [segment_otsu](#segment_otsu).

    Returns
    -------
    np.ndarray
        The segmented image.
    """
    # combine the images
    combined = combine_images(image_SE2, image_inlens)
    return segment_otsu(combined, *args, **kwargs)


def combine_segmentation_with_overlay(image_SE2: np.ndarray, image_inlens: np.ndarray, segmented) -> np.ndarray:
    """
    Combines the SE2 and inlens images with the given segmentation.

    Parameters
    ----------
    image_SE2: np.ndarray
        The SE2 image.
    image_inlens: np.ndarray
        The inlens image.
    *args
        Additional arguments for [segment_otsu](#segment_otsu).
    **kwargs
        Additional keyword arguments for [segment_otsu](#segment_otsu).

    Returns
    -------
    np.ndarray
        The segmented image with overlay as rgb image. Segmented regions are shown in yellow (RGB [255, 255, 0]).
    """
    combined = combine_images(image_SE2, image_inlens)
    result = np.zeros(combined.shape + (3,), dtype=np.uint8)
    result[..., 0] = combined
    result[..., 1] = combined
    result[..., 2] = combined
    result[segmented > 0, 0] = 255
    result[segmented > 0, 1] = 255
    result[segmented > 0, 2] = 0
    return result


def evaluate_segmentation(
    label_image: np.ndarray,
    properties: tuple[str] = (
        "label",
        "area",
        "axis_major_length",
        "axis_minor_length",
        "centroid",
        "orientation",
    ),
) -> pd.DataFrame:
    """
    Evaluates the given segmentation.

    Parameters
    ----------
    label_image: np.ndarray
        The label image.
    properties: tuple[str]
        The properties to evaluate. See [skimage.measure.regionprops](https://scikit-image.org/docs/stable/api/skimage.measure.html#skimage.measure.regionprops) for details.

    Returns
    -------
    pd.DataFrame
        The evaluation results.
    """
    # evaluate the segmentation
    props = regionprops_table(label_image=label_image, properties=properties, spacing=(pixel_size_um, pixel_size_um))
    return pd.DataFrame(props)


def process_folder(image_folder: Path, output_folder: Path, *args, **kwargs):
    """
    Preprocesses the images in the given folder and saves the preprocessed images and labels to the output folder.

    Parameters
    ----------
    image_folder: Path
        The path to the folder containing the original images.
    output_folder: Path
        The path to the folder where the preprocessed images and labels will be saved.

    Returns
    -------
    None
    """
    last_processed = Path("dummy_00.tif")
    output_folder.mkdir(exist_ok=True, parents=True)
    for path_to_image in natsorted(image_folder.glob("*.tif")):
        matching_image_number = calculate_matching_image_number(get_image_number(path_to_image))
        if matching_image_number == get_image_number(last_processed):
            continue
        print(f"Processing {path_to_image}")
        inlens_image, se_image = read_image_pair(path_to_image)
        cropped_inlens_image = crop_away_metadata(inlens_image)
        cropped_se_image = crop_away_metadata(se_image)
        segmented = segment_combined(cropped_se_image, cropped_inlens_image, *args, **kwargs)
        segmented_for_overlay = np.zeros_like(se_image)
        segmented_for_overlay[: segmented.shape[0], : segmented.shape[1]] = segmented
        rgb_overlay = combine_segmentation_with_overlay(se_image, inlens_image, segmented_for_overlay)
        output_name = path_to_image.stem + f"-{matching_image_number:02d}"
        imsave(output_folder / (output_name + "_label.tif"), segmented, check_contrast=False)
        imsave(output_folder / (output_name + "_overlay.bmp"), rgb_overlay, check_contrast=False)
        df = evaluate_segmentation(segmented)
        df.to_csv(output_folder / (output_name + "_table.csv"))
        last_processed = path_to_image


@click.command()
@click.option(
    "-o",
    "--output_folder",
    type=Path,
    default="Evaluation",
    help="The output folder for the evaluation.",
    show_default=True,
)
@click.option(
    "-s",
    "--sigma",
    type=float,
    default="1.0",
    help="The standard deviation of the Gaussian filter used for denoising.",
    show_default=True,
)
@click.option(
    "-r",
    "--radius",
    type=float,
    default="30.0",
    help="The radius of the white tophat background removal operation.",
    show_default=True,
)
@click.option(
    "-m",
    "--minimum_size",
    type=int,
    default="3",
    help="The minimum size of the objects to keep.",
    show_default=True,
)
@click.argument("image_folder", type=Path, default=".")
def process_folder_cli(output_folder, sigma, radius, minimum_size, image_folder):
    """
    Usage:
       carde-process [OPTIONS] <path/to/image_folder>

    Preprocesses the images in the given folder (default the current folder) and saves the processed label images and csv tables to the output folder defined by the -o option (default: ./Evaluation).
    """
    assert image_folder.exists(), "The image folder must exist."
    assert image_folder.is_dir(), "The image folder must be a directory."
    process_folder(Path(image_folder), Path(output_folder), sigma=sigma, radius=radius, minimum_size=minimum_size)


class RobustImageScaler:
    def __init__(self):
        self.scaler = RobustScaler()

    def fit(self, img: np.ndarray, y=None):
        """
        Fit the scaler to the image data.

        Parameters
        ----------
        img : np.ndarray
            Input image. Must be (C, H, W).
            The image data to fit the scaler.
        y : None
            Ignored. This parameter exists only for compatibility with
            sklearn API.

        Returns
        -------
        None
        """

        n_channels, h, w = img.shape
        img_reshaped = img.reshape(n_channels, -1).T  # shape (H*W, C)
        self.scaler.fit(img_reshaped)

        return self

    def transform(self, img: np.ndarray) -> np.ndarray:
        """
        Transform the image data using the fitted scaler.

        Parameters
        ----------
        img : np.ndarray
            Input image. Must be (C, H, W).

        Returns
        -------
        np.ndarray
            Scaled image with the same shape as the input.
        """

        n_channels, h, w = img.shape
        img_reshaped = img.reshape(n_channels, -1).T  # shape (H*W, C)
        img_scaled = self.scaler.transform(img_reshaped)
        # return to original shape
        return img_scaled.T.reshape(n_channels, h, w)

    def fit_transform(self, img: np.ndarray, y=None) -> np.ndarray:
        """
        Fit the scaler to the image data and transform it.

        Parameters
        ----------
        img : np.ndarray
            Input image. Must be (C, H, W).
        y : None
            Ignored. This parameter exists only for compatibility with
            sklearn API.

        Returns
        -------
        np.ndarray
            Scaled image with the same shape as the input.
        """

        return self.fit(img, y).transform(img)


class CompleteImageTiler:
    """
    A transformer for tiling images with proper handling of edge cases.

    This class divides images into tiles and can reconstruct the original image from tiles,
    handling cases where the image dimensions are not perfectly divisible by the stride.
    Follows the scikit-learn preprocessing API pattern.

    Parameters
    ----------
    tile_size : int, default=128
        Size of the square tiles (height and width in pixels).
    stride : int, default=128
        Step size between consecutive tiles.
    scale : bool, default=True
        Whether to apply robust scaling to the image during transformation.

    Attributes
    ----------
    tile_coords_ : list[tuple[int, int]]
        List of (row_start, col_start) coordinates for each tile.
        Set after calling fit().
    original_shape_ : tuple[int, int, int]
        Shape of the fitted image (C, H, W).
        Set after calling fit().
    """

    def __init__(self, tile_size: int = 128, stride: int = 128):
        self.tile_size = tile_size
        self.stride = stride
        self.tile_coords_ = []
        self.original_shape_ = None
        self.original_ndim_ = None

    def _ensure_CWH(self, X: np.ndarray) -> np.ndarray:
        """
        Ensure the input image is in (C, H, W) format.

        Parameters
        ----------
        X : np.ndarray
            Input image. Can be 2D (H, W) or 3D (C, H, W) or (H, W, C).

        Returns
        -------
        np.ndarray
            Image in (C, H, W) format.
        """
        self.original_ndim_ = X.ndim
        # Normalize input shape to (C, H, W)
        if X.ndim == 2:
            X = X[np.newaxis, ...]  # [1, H, W]
        elif X.ndim == 3 and X.shape[0] > 3:
            warn(
                "Size of first dimension is greater than 3. If you have more than 3 channels, everything is fine. Otherwise, make sure the input is in (C, H, W) format."
            )
        return X  # input shape [C, H, W]

    def fit(self, X: np.ndarray, y=None):
        """
        Fit the tiler to the image dimensions.

        Calculates all tile coordinates based on the input image shape.

        Parameters
        ----------
        X : np.ndarray
            Input image. Can be 2D (H, W) or 3D (C, H, W) or (H, W, C).
        y : None
            Ignored. This parameter exists only for compatibility with
            sklearn API.

        Returns
        -------
        self
            Returns the instance itself.
        """
        X = self._ensure_CWH(X)

        self.original_shape_ = X.shape
        c, h, w = X.shape

        # Make sure tile_size is not larger than image dimensions
        if self.tile_size > h or self.tile_size > w:
            raise ValueError(
                f"tile_size {self.tile_size} is larger than image dimensions "
                f"({h}, {w}). Make sure the image is in (C, H, W) format and at least as large as the tile size."
            )

        # Calculate regular grid positions
        row_positions = list(range(0, h - self.tile_size + 1, self.stride))
        col_positions = list(range(0, w - self.tile_size + 1, self.stride))

        # Add edge-aligned positions if needed
        if row_positions[-1] + self.tile_size < h:
            row_positions.append(h - self.tile_size)
        if col_positions[-1] + self.tile_size < w:
            col_positions.append(w - self.tile_size)

        # Generate all coordinate combinations
        self.tile_coords_ = [(r, c) for r in row_positions for c in col_positions]

        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        """
        Transform the image into tiles.

        Parameters
        ----------
        X : np.ndarray
            Input image. Can be 2D (H, W) or 3D (C, H, W) or (H, W, C).
            Must have the same dimensions as the image used in fit().

        Returns
        -------
        np.ndarray
            Array of tiles with shape (N, C, tile_size, tile_size),
            where N is the number of tiles.
        """
        if not self.tile_coords_:
            raise ValueError(
                "This CompleteImageTiler instance is not fitted yet. " "Call 'fit' before using this estimator."
            )

        X = self._ensure_CWH(X)

        if X.shape != self.original_shape_:
            raise ValueError(f"X has shape {X.shape} but this tiler was fitted " f"for shape {self.original_shape_}")

        # Extract tiles using the coordinates
        tiles = []
        for row_start, col_start in self.tile_coords_:
            tile = X[
                :,
                row_start : row_start + self.tile_size,
                col_start : col_start + self.tile_size,
            ]
            tiles.append(tile)

        return np.array(tiles)

    def fit_transform(self, X: np.ndarray, y=None) -> np.ndarray:
        """
        Fit to data, then transform it.

        Parameters
        ----------
        X : np.ndarray
            Input image. Can be 2D (H, W) or 3D (C, H, W) or (H, W, C).
        y : None
            Ignored. This parameter exists only for compatibility with
            sklearn API.

        Returns
        -------
        np.ndarray
            Array of tiles with shape (N, C, tile_size, tile_size).
        """
        return self.fit(X, y).transform(X)

    def inverse_transform(self, X: np.ndarray, handle_overlap: str = "average") -> np.ndarray:
        """
        Reconstruct the original image from tiles.

        Parameters
        ----------
        X : np.ndarray
            Array of tiles with shape (N, C, tile_size, tile_size).
        handle_overlap : str, default='average'
            Method to handle overlapping regions. Options:
            - 'average': Average overlapping pixels
            - 'last': Use the last tile's values in overlapping regions
            - 'first': Use the first tile's values in overlapping regions

        Returns
        -------
        np.ndarray
            Reconstructed image with shape matching the original fitted image.
        """
        if self.original_shape_ is None:
            raise ValueError(
                "This CompleteImageTiler instance is not fitted yet. " "Call 'fit' before using this estimator."
            )

        c, h, w = self.original_shape_
        reconstructed = np.zeros((c, h, w), dtype=X.dtype)
        weight_map = np.zeros((h, w), dtype=np.float32)

        # Process tiles using stored coordinates
        for tile_idx, (row_start, col_start) in enumerate(self.tile_coords_):
            end_row = row_start + self.tile_size
            end_col = col_start + self.tile_size

            if handle_overlap == "average":
                reconstructed[:, row_start:end_row, col_start:end_col] += X[tile_idx]
                weight_map[row_start:end_row, col_start:end_col] += 1
            elif handle_overlap == "last":
                reconstructed[:, row_start:end_row, col_start:end_col] = X[tile_idx]
            elif handle_overlap == "first":
                # Only fill pixels that haven't been filled yet
                mask = weight_map[row_start:end_row, col_start:end_col] == 0
                reconstructed[:, row_start:end_row, col_start:end_col][:, mask] = X[tile_idx][:, mask]
                weight_map[row_start:end_row, col_start:end_col][mask] = 1

        if handle_overlap == "average":
            # Normalize by weight map to get average
            weight_map[weight_map == 0] = 1  # Avoid division by zero
            reconstructed = reconstructed / weight_map[np.newaxis, :, :]

        if self.original_ndim_ == 2:
            reconstructed = reconstructed[0]  # Remove channel dimension

        return reconstructed


def tile_image(img: np.ndarray, tile_size: int = 128, stride: int = 128, scale=True) -> np.ndarray:
    """
    Divides an image into smaller tiles.

    Parameters
    ----------
    img : np.ndarray
        Input image. Can be 2D (H, W) or 3D (C, H, W) or (H, W, C).
    tile_size : int, optional
        Size of the square tiles, by default 128.
    stride : int, optional
        Step size between consecutive tiles, by default 128.
        When stride < tile_size, tiles will overlap.

    Returns
    -------
    np.ndarray
        Array of tiles with shape (N, C, tile_size, tile_size),
        where N is the number of tiles.

    Notes
    -----
    - For 2D images, a channel dimension is added.
    - For 3D images in (H, W, C) format, the function converts to (C, H, W).
    - Uses scikit-image's view_as_windows function for the sliding window operation.
    """
    if img.ndim == 2:
        img = img[np.newaxis, ...]  # [1, H, W]
    elif img.ndim == 3:
        img = img  # input shape [C, H, W]

    # change to (C, H, W) if originally in (H, W, C)
    if img.shape[0] > 3:
        h, w, c = img.shape
        img = img.transpose(2, 0, 1)

    if scale:
        img = RobustImageScaler().fit_transform(img)

    # create tiles using view_as_windows from skimage
    tiles = view_as_windows(img, (img.shape[0], tile_size, tile_size), step=stride)
    tiles = tiles.reshape(-1, img.shape[0], tile_size, tile_size)
    return tiles


def save_paired_tiles(
    image_path: Path = image_path,
    tiled_image_path: Path = tiled_image_path,
    tiled_label_path: Path = tiled_label_path,
    tile_size: int = 128,
    stride: int = 128,
):
    f"""
    Save tiled images and their corresponding labels as PyTorch tensors.

    This function processes pairs of SEM images (SE2 and InLens) and their labels,
    tiles them into smaller patches, and saves them as PyTorch tensor files.
    Only images with odd numbers are processed, because SE2 and InLens images appear in pairs.

    Parameters
    ----------
    image_path : Path, default = {image_path}
        Directory path containing the original .tif image files.
    tiled_image_path : Path, default = {tiled_image_path}
        Directory path where tiled image tensors will be saved
    tiled_label_path : Path, default = {tiled_label_path}
        Directory path where tiled label tensors will be saved
    tile_size : int, default=128
        Size of the square tiles (height and width in pixels)
    stride : int, default=128
        Step size between consecutive tiles (controls overlap)

    Notes
    -----
    - Image pairs are stacked along a new axis [SE2, InLens]
    - Only processes images with odd numbers
    - Saves tiles as PyTorch tensors with sequential IDs
    - Image tensors are saved as float32 type
    - Label tensors are saved as uint8 type
    """
    tile_id = 0

    for image_path in image_path.glob("*.tif"):
        image_number = get_image_number(image_path)
        if image_number % 2 == 0:
            continue
        se2, inlens = read_image_pair(image_path)
        label = read_label_number(get_image_number(image_path))

        # stack SE2 + InLens
        stacked = np.stack([se2, inlens], axis=0)
        label = label[np.newaxis, ...]

        # tile images and labels
        input_tiles = tile_image(stacked, tile_size, stride)
        label_tiles = tile_image(label, tile_size, stride, scale=False)

        assert input_tiles.shape[0] == label_tiles.shape[0], "mismatch in number of tiles"

        for i in range(input_tiles.shape[0]):
            torch.save(
                torch.tensor(input_tiles[i], dtype=torch.float32), tiled_image_path / f"image_{tile_id:05d}.pt"
            )
            torch.save(torch.tensor(label_tiles[i], dtype=torch.uint8), tiled_label_path / f"label_{tile_id:05d}.pt")
            tile_id += 1
