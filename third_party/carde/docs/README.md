# Notebooks

## Main notebooks

- [notebooks/run_unet_experiments.ipynb](notebooks/run_unet_experiments.ipynb) Generates segmentation results and plots the figures shown in the manuscript.
- [notebooks/uncertainty_estimation.ipynb](notebooks/uncertainty_estimation.ipynb) Reproduces unertainty estimation via temperature scaing.
- [notebooks/hyperparameter_optimization.ipynb](notebooks/hyperparameter_optimization.ipynb) Reproduces hyperparameter optimization experiments.

## Data preprocessing

- [notebooks/preprocess_images.ipynb](notebooks/preprocess_images.ipynb) Used for image preprocessing (removing metadata bar)
- [notebooks/tile_images.ipynb](notebooks/tile_images.ipynb) Normalize preprocessed images and tile them into 128x128 px tiles.

## Classical image analysis pipeline

- [notebooks/classic_ml_segmentation.ipynb](notebooks/classic_ml_segmentation.ipynb) Explains the classical image analysis pipeline
- [notebooks/process_image_folder.ipynb](notebooks/process_image_folder.ipynb) Process a whole folder of images with the classical analysis pipeline.
