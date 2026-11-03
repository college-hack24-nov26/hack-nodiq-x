from pathlib import Path
from skimage.io import imread, imsave

data_path = Path("../../data")
local_data_path = data_path / "cloud/"
preprocessed_image_path = local_data_path / "preprocessed"
image_path = preprocessed_image_path / "images"
label_path = preprocessed_image_path / "labels"

# output paths
tile_path = Path("../../data/cloud/processed_tiles")
tiled_image_path = tile_path / "images"
tiled_label_path = tile_path / "labels"
tiled_image_path.mkdir(parents=True, exist_ok=True)
tiled_label_path.mkdir(parents=True, exist_ok=True)


def read_credentials() -> tuple[str, str]:
    """
    Reads the username and password from the 'nextcloud_key.secret' file.

    Returns
    -------
    tuple[str, str]
        A tuple of strings containing the username and password.
    """
    with open(data_path / "nextcloud_key.secret", "r") as f:
        username = f.readline().strip()
        password = f.readline().strip()
    return (username, password)


def load_data_from_cloud(target_path: Path):
    from nc_py_api import Nextcloud

    username, password = read_credentials()
    nc = Nextcloud(nextcloud_url="https://cloud.hzdr.de", nc_auth_user=username, nc_auth_pass=password)

    # download all files from the cloud
    files = nc.files.find(["like", "name", target_path.name])
    # make sure that the parent directory exists and create it if it does not
    target_path.parent.mkdir(parents=True, exist_ok=True)
    nc.files.download2stream(files[0], target_path)


def ensure_local(file_path: Path) -> Path:
    """
    Ensures that the file at the given file path exists locally.
    If the file does not exist, it is loaded from the cloud.

    Parameters
    ----------
    file_path: pathlib.Path
        The path to the file.

    Returns
    -------
    pathlib.Path
        The path to the local file.

    Raises
    ------
    AssertionError
        If the file could not be obtained from the cloud.
    """
    if not file_path.exists():
        load_data_from_cloud(file_path)
    assert file_path.exists(), f"Could not get {file_path} from cloud."
    return file_path


def read_image_number(image_number: int) -> "numpy.ndarray":  # type: ignore
    """
    Reads an image file based on the provided image number and returns it as a numpy array.

    Parameters
    ----------
    image_number: int
        The image number.

    Returns
    -------
    numpy.ndarray
        The image as a numpy array.

    Raises
    ------
    StopIteration
        If no image file with the given image number exists.

    Notes
    -----
    The function expects the image files to be in the TIFF format and named with the image number at the end of the file name.
    """
    im_path = image_path.glob(f"*{image_number:02d}.tif").__next__()
    return imread(im_path)


def read_label_number(image_number: int) -> "numpy.ndarray":  # type: ignore
    """
    Reads a label image corresponding to the given image number.

    Parameters
    ----------
    image_number: int
        The image number.

    Returns
    -------
    numpy.ndarray
        The image as a numpy array.

    Raises
    ------
    StopIteration
        If no image file with the given image number exists.

    Notes
    -----
    The function expects the image files to be in the TIFF format and named with the image number at the end of the file name.
    """
    lbl_path = label_path.glob(f"*{image_number:02d}_label.png").__next__()
    return imread(lbl_path)


def calculate_matching_image_number(image_number: int) -> int:
    """
    Calculate the matching image number based on the given image number.

    The function adjusts the image number by converting an even image number
    to the previous odd number and an odd image number to the next even number.

    Parameters
    ----------
    image_number: int
        The image number.

    Returns
    -------
    int
        The matching image number.
    """
    return image_number - 1 + (2 * (image_number % 2))


def read_matching_images(image_number: int) -> dict["numpy.ndarray"]:  # type: ignore
    image_numbers = [image_number, calculate_matching_image_number(image_number)]
    image_numbers.sort()
    image1 = read_image_number(image_numbers[0])
    image2 = read_image_number(image_numbers[1])
    label = read_label_number(image_numbers[0])
    return {"Image1": image1, "Image2": image2, "label": label}


def get_image_number(image_path: Path) -> int:
    """
    Extracts and returns the image number from the given image file path.

    The image number is expected to be the last part of the file name,
    separated by an underscore and without the file extension.

    Parameters
    ----------
    image_path: pathlib.Path
        The path to the image file.

    Returns
    -------
    int
        The image number.
    """
    return int(image_path.stem.split("_")[-1])


def read_image_pair(image_path: Path) -> tuple["numpy.ndarray"]:  # type: ignore
    """
    Reads a pair of images based on the given image path. The function assumes that the image
    filenames contain an image number at the end, separated by an underscore. It calculates the
    matching image number and reads both images, returning them as a tuple.

    Parameters
    ----------
        image_path: pathlib.Path
            The path to the image file

    Returns
    -------
        tuple["numpy.ndarray"]
            A tuple containing the InLens and SE2 images
    """
    name_parts = image_path.stem.split("_")
    image_number = get_image_number(image_path)
    matching_image_number = calculate_matching_image_number(image_number)
    name_parts[-1] = str(matching_image_number).zfill(len(name_parts[-1]))
    matching_image_path = image_path.parent / ("_".join(name_parts) + image_path.suffix)
    if image_number < matching_image_number:
        image1 = imread(matching_image_path)
        image2 = imread(image_path)
    else:
        image1 = imread(image_path)
        image2 = imread(matching_image_path)
    return image1, image2
