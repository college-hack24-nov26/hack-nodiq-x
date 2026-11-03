import pytest
from pathlib import Path
from skimage.io import imread
from unittest.mock import patch, MagicMock
from carde import io


@pytest.fixture
def mock_path():
    with patch("pathlib.Path.glob") as mock_glob:
        yield mock_glob


@pytest.fixture
def mock_imread():
    with patch("carde.io.imread") as mock_imread:
        yield mock_imread


def read_number_success(mock_label_path, mock_imread, read_function, pattern):
    # Arrange
    image_number = 1
    mock_file_path = MagicMock(spec=Path)
    mock_label_path.return_value.__next__.return_value = mock_file_path
    mock_image_array = MagicMock()
    mock_imread.return_value = mock_image_array

    # Act
    result = read_function(image_number)

    # Assert
    mock_label_path.assert_called_once_with(pattern.format(image_number=image_number))
    mock_imread.assert_called_once_with(mock_file_path)
    assert result == mock_image_array


def read_number_no_file(mock_label_path, read_function):
    # Arrange
    image_number = 1
    mock_label_path.return_value.__next__.side_effect = StopIteration

    # Act & Assert
    with pytest.raises(StopIteration):
        read_function(image_number)


def test_read_label_number_success(mock_path, mock_imread):
    read_number_success(mock_path, mock_imread, io.read_label_number, "*{image_number:02d}_label.png")


def test_read_label_number_no_file(mock_path):
    read_number_no_file(mock_path, io.read_label_number)


def test_read_image_number_success(mock_path, mock_imread):
    read_number_success(mock_path, mock_imread, io.read_image_number, "*{image_number:02d}.tif")


def test_read_image_number_no_file(mock_path):
    read_number_no_file(mock_path, io.read_image_number)


def test_calculate_matching_image_number():
    assert io.calculate_matching_image_number(1) == 2
    assert io.calculate_matching_image_number(2) == 1
    assert io.calculate_matching_image_number(3) == 4
    assert io.calculate_matching_image_number(4) == 3
    assert io.calculate_matching_image_number(15) == 16
    assert io.calculate_matching_image_number(16) == 15


def test_read_matching_images_success(mock_path, mock_imread):
    # Arrange
    image_number = 2
    matching_image_number = 1

    mock_image_array1 = MagicMock()
    mock_image_array2 = MagicMock()
    mock_label_array = MagicMock()
    mock_imread.side_effect = [mock_image_array1, mock_image_array2, mock_label_array]

    # Act
    result = io.read_matching_images(image_number)

    # Assert
    mock_path.assert_any_call(f"*{matching_image_number:02d}.tif")
    mock_path.assert_any_call(f"*{image_number:02d}.tif")
    mock_path.assert_any_call(f"*{matching_image_number:02d}_label.png")
    assert mock_imread.call_count == 3
    assert result == {"Image1": mock_image_array1, "Image2": mock_image_array2, "label": mock_label_array}


def test_read_matching_images_no_file(mock_path):
    # Arrange
    image_number = 1
    mock_path.return_value.__next__.side_effect = StopIteration

    # Act & Assert
    with pytest.raises(StopIteration):
        io.read_matching_images(image_number)


def test_get_image_number():
    assert io.get_image_number(Path("some_directory/image_01.tif")) == 1
    assert io.get_image_number(Path("some_directory/image_02.tif")) == 2


def test_get_image_number_no_underscore():
    with pytest.raises(ValueError):
        io.get_image_number(Path("some_directory/image01.tif"))


def test_get_image_number_non_numeric():
    with pytest.raises(ValueError):
        io.get_image_number(Path("some_directory/image_one.tif"))


def read_image_pair_success(mock_imread, image_path, matching_image_path):
    # Arrange
    mock_image_array1 = MagicMock()
    mock_image_array2 = MagicMock()
    mock_imread.side_effect = [mock_image_array1, mock_image_array2]

    # Act
    result = io.read_image_pair(image_path)

    # Assert
    mock_imread.assert_any_call(image_path)
    mock_imread.assert_any_call(matching_image_path)
    assert result == (mock_image_array1, mock_image_array2)


def test_read_image_pair_success(mock_imread):
    read_image_pair_success(mock_imread, Path("some_directory/image_01.tif"), Path("some_directory/image_02.tif"))


def test_read_image_pair_reverse_success(mock_imread):
    read_image_pair_success(mock_imread, Path("some_directory/image_02.tif"), Path("some_directory/image_01.tif"))


def test_read_image_pair_no_file(mock_imread):
    # Arrange
    image_path = Path("some_directory/image_01.tif")
    mock_imread.side_effect = FileNotFoundError

    # Act & Assert
    with pytest.raises(FileNotFoundError):
        io.read_image_pair(image_path)
