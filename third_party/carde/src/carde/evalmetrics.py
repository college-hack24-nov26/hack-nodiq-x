from typing import Optional
import numpy as np
import torch
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm
import random

from carde.image_processing import segment_combined
from carde.unet import SegmentationModel, dataloader_to_labels

# figure parameters
plt.rcParams["svg.fonttype"] = "none"  # editable text in svg vector formats
plt.rcParams["font.size"] = 8
plt.rcParams["axes.labelsize"] = 8
plt.rcParams["axes.titlesize"] = 10
plt.rcParams["xtick.labelsize"] = 6
plt.rcParams["ytick.labelsize"] = plt.rcParams["xtick.labelsize"]

# figure sizes
textwidth = 7.05  # inches
onecolumn = 3.42  # inches
# set the default figure size to one column width
plt.rcParams["figure.figsize"] = (textwidth, onecolumn)


def plot_loss(event_acc, axs: list[plt.Axes], yscale="linear"):
    """
    Plot training and validation loss and score curves from TensorBoard event data.

    This function extracts loss and score metrics from a TensorBoard EventAccumulator
    and plots them on the provided axes. It displays training loss, validation loss,
    and validation score (Dice-Sørensen coefficient) across training steps.

    Parameters
    ----------
    event_acc : EventAccumulator
        TensorBoard EventAccumulator object containing logged metrics with keys
        "train_loss_epoch", "validation_loss", and "validation_score".
    axs : list[plt.Axes]
        List of matplotlib Axes objects. Must contain at least 2 axes:
        - axs[0]: Used for plotting training and validation loss curves
        - axs[1]: Used for plotting validation score curve
    yscale : str, optional
        Scale for the y-axis of the loss plot. Can be "linear" or "log".
        Default is "linear".

    Returns
    -------
    list[plt.Axes]
        The modified list of axes with plotted data.

    Notes
    -----
    - The function safely handles missing data by checking if arrays are non-empty
      before plotting.
    - The validation score is expected to be the Dice-Sørensen coefficient, with
      values between 0 and 1.
    - Loss curves are plotted on axs[0] with configurable y-axis scale.
    - Validation score is plotted on axs[1] with a fixed y-axis range [0, 1].
    """

    # extract training/validation curves
    train_loss_scalars = event_acc.Scalars("train_loss_epoch")
    val_loss_scalars = event_acc.Scalars("validation_loss")
    val_score_scalars = event_acc.Scalars("validation_score")

    # convert to numpy arrays [step, value]
    train_loss = np.array([[s.step, s.value] for s in train_loss_scalars])
    val_loss = np.array([[s.step, s.value] for s in val_loss_scalars])
    val_score = np.array([[s.step, s.value] for s in val_score_scalars])

    if train_loss.size:
        axs[0].plot(train_loss[:, 0], train_loss[:, 1], label="train loss")
    if val_loss.size:
        axs[0].plot(val_loss[:, 0], val_loss[:, 1], label="validation loss")

    axs[0].set_xlabel("step")
    axs[0].set_ylabel("loss")
    axs[0].set_yscale(yscale)
    axs[0].legend()

    if val_score.size:
        axs[1].plot(val_score[:, 0], val_score[:, 1], label="validation score", color="C1")
        axs[1].set_xlabel("step")
        axs[1].set_ylabel("Dice-Sørensen\ncoefficient")
        axs[1].set_ylim(0, 1)
        # move ylabel to the right
        # axs[1].yaxis.set_label_position("right")
        # axs[1].yaxis.tick_right()
        axs[1].legend()

    return axs


def evaluate_model(model, dataloader, trainer, show_sample=True, n_samples=3):
    """
    Evaluate a PyTorch Lightning model on a test dataset and optionally visualize predictions.

    This function computes test metrics (Dice loss and score) and can display sample predictions
    alongside their corresponding inputs and ground truth labels.

    Parameters
    ----------
    model : torch.nn.Module
        A PyTorch Lightning model to be evaluated.
    dataloader : torch.utils.data.DataLoader
        DataLoader containing the test dataset. Expected to yield batches of
        (inputs, labels) where inputs have shape (batch_size, 2, H, W) for SE2 and InLens
        channels, and labels have shape (batch_size, 1, H, W).
    trainer : pytorch_lightning.Trainer
        PyTorch Lightning Trainer instance used for testing and prediction.
    show_sample : bool, optional
        Whether to display visualization of sample predictions. Default is True.
    n_samples : int, optional
        Number of random samples to visualize when show_sample is True. Default is 3.

    Returns
    -------
    avg_loss : float
        Average Dice loss across the test dataset.
    avg_score : float
        Average Dice score (1 - Dice loss) across the test dataset.

    Notes
    -----
    - The function expects the model to output probability predictions that are thresholded
      at 0.5 to create binary masks.
    - Visualization displays 4 columns: SE2 input, InLens input, ground truth label, and
      predicted mask.
    - Requires matplotlib to be imported as plt and random module to be available.
    """
    test_result = trainer.test(model, dataloader)
    avg_loss = test_result[0]["test_loss"]
    avg_score = test_result[0]["test_score"]

    print(f"Average Dice Loss: {avg_loss:.4f}")
    print(f"Average 1 - Dice Loss: {avg_score:.4f}")

    if show_sample:
        # random batch for visualization
        batch = next(iter(dataloader))
        inputs, labels = batch

        pred = trainer.predict(model, dataloader)
        pred_probs = pred[0]
        pred_mask = pred_probs > 0.5

        idxs = random.sample(range(inputs.size(0)), n_samples)
        fig, axs = plt.subplots(n_samples, 4, figsize=(20, 4 * n_samples))

        for i, idx in enumerate(idxs):
            axs[i, 0].imshow(inputs[idx, 0].cpu(), cmap="gray")
            axs[i, 0].set_title("SE2")
            axs[i, 0].axis("off")

            axs[i, 1].imshow(inputs[idx, 1].cpu(), cmap="gray")
            axs[i, 1].set_title("InLens")
            axs[i, 1].axis("off")

            axs[i, 2].imshow(labels[idx, 0].cpu(), cmap="gray")
            axs[i, 2].set_title("Label")
            axs[i, 2].axis("off")

            axs[i, 3].imshow(pred_mask[idx, 0].cpu(), cmap="gray")
            axs[i, 3].set_title("Predicted")
            axs[i, 3].axis("off")

        plt.tight_layout()
        plt.show()

    return avg_loss, avg_score


def show_tiles(tiled_image_path, tiled_label_path, tile_id, n_samples=3):
    """
    Visualize random SE2/InLens/Label tiles from the preprocessed dataset.

    Parameters
    ----------
    tiled_image_path : Path
        Path to the folder containing input tiles (.pt files)
    tiled_label_path : Path
        Path to the folder containing label tiles (.pt files)
    tile_id : int
        Total number of tiles in the dataset
    n_samples : int, optional
        Number of random tiles to display (default is 3)
    """
    idxs = random.sample(range(tile_id), n_samples)

    for idx in idxs:
        image = torch.load(tiled_image_path / f"image_{idx:05d}.pt")
        label = torch.load(tiled_label_path / f"label_{idx:05d}.pt")

        se2 = image[0].numpy()
        inlens = image[1].numpy()
        lbl = label[0].numpy()

        fig, axs = plt.subplots(1, 3, figsize=(10, 3))
        axs[0].imshow(se2, cmap="gray")
        axs[0].set_title("SE2")
        axs[1].imshow(inlens, cmap="gray")
        axs[1].set_title("InLens")
        axs[2].imshow(lbl, cmap="gray")
        axs[2].set_title("Label")
        for ax in axs:
            ax.axis("off")
        plt.tight_layout()
        plt.show()


def compute_nll(logits, labels):
    """
    Computes the average Negative Log-Likelihood (BCE with logits)
    for the model on the validation set.

    Parameters:
    -----------
    model : torch.nn.Module
        The segmentation model (should output raw logits).

    val_loader : torch.utils.data.DataLoader
        Dataloader with validation (image, mask) batches.

    temperature : float or None
        If set, logits will be divided by this temperature before loss is computed.

    Returns:
    --------
    avg_nll : float
        Average BCEWithLogitsLoss over the validation set.
    """
    avg_nll = torch.nn.BCEWithLogitsLoss(reduction="mean")(logits, labels).item()
    return avg_nll


def compute_ece(probabilities, labels, n_bins=30):
    """
    Computes Expected Calibration Error (ECE).

    Parameters:
    -----------
    probabilities : torch.Tensor
        Model probabilities.
    labels : torch.Tensor
        True binary labels.
    n_bins : int
        Number of bins for ECE calculation.

    Returns:
    --------
    ece : float
        Expected Calibration Error.
    """
    # Bin boundaries
    bin_boundaries = torch.linspace(0, 1, steps=n_bins + 1).to(probabilities.device)
    ece = torch.zeros(1).to(probabilities.device)
    probabilities = probabilities.flatten()
    labels = labels.flatten()

    for i in range(n_bins):
        lower = bin_boundaries[i]
        upper = bin_boundaries[i + 1]

        # Get indices for the bin
        mask = (probabilities > lower) & (probabilities <= upper)
        bin_size = mask.sum().item()

        if bin_size > 0:
            bin_confidence = probabilities[mask].mean()
            bin_accuracy = labels[mask].mean()
            ece += (bin_size / len(probabilities)) * torch.abs(bin_confidence - bin_accuracy)

    return ece.item()


def compute_reliability_curve(
    probs: torch.Tensor, labels: torch.Tensor, n_bins: int = 15
) -> tuple[torch.Tensor, torch.Tensor]:
    """
    Computes accuracies, and confidences for a reliability diagram.

    Parameters:
    -----------
        probs : torch.Tensor
            Model probabilities.
        labels : torch.Tensor
            True binary labels.
        n_bins : int
            Number of bins for the histogram.

    Returns:
    --------
        accuracies : torch.Tensor
        confidences : torch.Tensor
    """
    bin_edges = torch.linspace(0, 1, n_bins + 1).to(probs.device)
    bin_indices = torch.bucketize(probs, bin_edges, right=True)

    accuracies = torch.zeros(n_bins).to(probs.device)
    confidences = torch.zeros(n_bins).to(probs.device)
    bin_counts = torch.zeros(n_bins).to(probs.device)

    for i in range(1, n_bins + 1):
        mask = bin_indices == i
        bin_count = mask.sum()
        if bin_count > 0:
            bin_conf = probs[mask].mean()
            bin_acc = labels[mask].float().mean()
            confidences[i - 1] = bin_conf
            accuracies[i - 1] = bin_acc
            bin_counts[i - 1] = bin_count

    return accuracies, confidences


def plot_reliability_diagram(
    prob_list: list[torch.Tensor], labels: torch.Tensor, legend_labels: list, ax=None
) -> plt.Axes:
    """
    Plots a reliability diagram for model calibration.

    Parameters
    ----------
        prob_list : list[torch.Tensor]
            List of model probabilities to plot.
        labels : torch.Tensor
            True binary labels.
        legend_labels : list
            List of labels for the legend corresponding to each probability tensor.
        ax : matplotlib.axes.Axes, optional
            The axes on which to draw the reliability diagram. If None, a new figure and axes
            will be created.

    Returns
    -------
        ax : matplotlib.axes.Axes
            The axes containing the reliability diagram.
    """

    if ax is None:
        plt.figure(figsize=(onecolumn, onecolumn))
        ax = plt.gca()

    # Perfect calibration line
    ax.plot([0, 1], [0, 1], linestyle="--", color="gray", label="perfect calibration")

    for n, prob in enumerate(prob_list):
        accuracies, confidences = compute_reliability_curve(prob, labels)
        ax.plot(confidences.cpu(), accuracies.cpu(), label=legend_labels[n])

    ax.set_xlabel("confidence")
    ax.set_ylabel("accuracy")
    ax.set_title("reliability diagram")
    ax.legend()
    ax.grid(True)
    return ax


def classical_segmentation(inputs: torch.Tensor) -> np.ndarray:
    """
    Perform classical segmentation on SE2 and InLens images.

    This function combines SE2 and InLens images using a simple thresholding
    technique to segment carbide regions.

    Parameters:
    -----------
        inputs : torch.Tensor
            Tensor of shape (2, H, W) containing SE2 and InLens images.

    Returns:
    --------
        segmented : np.ndarray
            Binary numpy array of shape (H, W) with segmented carbide regions.
    """
    se2_image = inputs[0].cpu().numpy()
    inlens_image = inputs[1].cpu().numpy()

    segmented = segment_combined(se2_image, inlens_image)

    return torch.tensor(segmented > 0, dtype=torch.float32)


def probs_to_confidence_map(probs: torch.Tensor) -> torch.Tensor:
    """
    Convert probability values to a confidence map with discrete levels.

    This function transforms continuous probability values into a discrete confidence map
    with four levels (0-3) based on predefined probability thresholds.

    Args:
        probs (torch.Tensor): Input tensor containing probability values, typically in the range [0, 1].

    Returns:
        torch.Tensor: A tensor of the same shape as `probs` with dtype uint8, where:
            - 0: probability <= 0.025 (very low confidence)
            - 1: 0.025 < probability <= 0.5 (low confidence)
            - 2: 0.5 < probability <= 0.975 (high confidence)
            - 3: probability > 0.975 (very high confidence)

    Note:
        The thresholds are applied sequentially, so higher probability values override
        lower confidence levels in the output tensor.
    """
    # Create the multi-level output array
    output = torch.zeros_like(probs, dtype=torch.uint8)
    output[probs > 0.025] = 1
    output[probs > 0.5] = 2
    output[probs > 0.975] = 3
    return output


def plot_confidence_map(map, ax, fig, color_bar=True):
    """
    Plots a confidence map with 4 discrete bins using a viridis colormap.

    The confidence levels are represented as:
    - 0: Less than 2.5%
    - 1: Greater than 2.5%
    - 2: Greater than 50%
    - 3: Greater than 97.5%

    Parameters
    ----------
    map : numpy.ndarray
        2D array containing confidence values (0, 1, 2, or 3)
    ax : matplotlib.axes.Axes
        The axes on which to draw the confidence map
    fig : matplotlib.figure.Figure
        The figure object containing the axes
    color_bar : bool, optional
        Whether to draw a color bar, by default True

    Returns
    -------
    None
        The function modifies the provided axes in-place
    """
    # discrete colormap for 4 bins: 0,1,2,3
    cmap = plt.get_cmap("viridis", 4)
    norm = BoundaryNorm(boundaries=[-0.5, 0.5, 1.5, 2.5, 3.5], ncolors=4)
    im = ax.imshow(map, cmap=cmap, norm=norm, interpolation="nearest")
    ax.set_title("confidence map")
    ax.axis("off")
    if color_bar:
        cbar = fig.colorbar(
            im,
            ax=ax,
            ticks=[0, 1, 2, 3],
            location="right",
            fraction=0.03,
            pad=0.02,
        )
        cbar.ax.set_yticklabels(["< 2.5%", "> 2.5%", "> 50%", "> 97.5%"])


def baseline_and_model_scores(
    test_data_loader: torch.utils.data.DataLoader, model: SegmentationModel, device_name="cuda"
) -> tuple[float, float]:
    """
    Computes baseline Dice loss and score by predicting all zeros.

    Parameters:
    -----------
        test_data_loader : torch.utils.data.DataLoader
            Dataloader for the test dataset.
        model : SegmentationModel
            Trained segmentation model.
        device_name : str
            Device to run the computations on.
    Returns:
    --------
        baseline_scores : list[float]
    """
    model.to(device_name)
    baseline_scores = []
    model_scores = []
    for inputs, labels in test_data_loader:
        baseline_pred = []
        for i in range(inputs.size(0)):
            pred = classical_segmentation(inputs[i])
            # add batch dimension and channel dimension
            baseline_pred.append(pred.unsqueeze(0).unsqueeze(0))
        baseline_pred = torch.cat(baseline_pred, dim=0)
        baseline_score_tensor = 1 - model.dice_loss(baseline_pred, labels)

        baseline_scores += [float(item) for item in baseline_score_tensor.ravel()]

        inputs = inputs.to(model.device)
        labels = labels.to(model.device)
        with torch.no_grad():
            logits = model(inputs)
            probs = torch.sigmoid(logits)
            model_pred = (probs > 0.5).float()
            model_score_tensor = 1 - model.dice_loss(model_pred, labels)
            model_scores += [float(item) for item in model_score_tensor.ravel()]

    return baseline_scores, model_scores


## Temperature Scaling Related Functions


def logits_to_probs(logits: torch.Tensor, temperature: float = 1.0) -> torch.Tensor:
    """
    Converts logits to probabilities using sigmoid activation,
    optionally applying temperature scaling.

    Parameters:
    -----------
        logits : torch.Tensor
            Model logits.
        temperature : float
            Temperature for scaling logits. Default is no scaling (temperature = 1.0).

    Returns:
    --------
        probs : torch.Tensor
            Sigmoid probabilities.
    """
    if temperature is not None:
        logits /= temperature
    probs = torch.sigmoid(logits)
    return probs


## MVE Related Functions


def predict_logits_mean_sigma(model, dataloader) -> torch.Tensor:
    output = model.trainer.predict(model, dataloader)
    logits_list = []
    sigma_list = []
    for logits, sigma in output:
        logits_list.append(logits)
        sigma_list.append(sigma)
    logits = torch.cat(logits_list, dim=0)
    sigma = torch.cat(sigma_list, dim=0)
    return logits, sigma


def logits_mean_sigma_to_probabilities(logits: torch.Tensor, sigma: torch.Tensor, samples=40) -> torch.Tensor:
    """Convert mean and sigma tensors to a confidence map.

    Parameters
    ----------
        logits : torch.Tensor
            Tensor of shape (B, C, H, W) representing the logits predictions.
        sigma : torch.Tensor
            Tensor of shape (B, C, H, W) representing the sigma predictions.
        samples : int
            Number of samples to draw for Monte Carlo estimation.

    Returns
    -------
        mean probabilities: torch.Tensor
            Tensor of shape (B, C, H, W) representing the mean probabilities.
    """
    noise = torch.randn(samples, *logits.shape, device=logits.device)
    perturbed_logits = logits.unsqueeze(0) + sigma.unsqueeze(0) * noise
    probs = torch.sigmoid(perturbed_logits)
    return probs.mean(dim=0)


def mve_confidence_map(model, dataloader, samples=40) -> torch.Tensor:
    """Convert mean and variance predictions from the model to a confidence map.

    Parameters
    ----------
        model : torch.nn.Module
            The trained model to use for prediction.
        dataloader : torch.utils.data.DataLoader
            The dataloader containing the input data.
        samples : int
            The number of samples to draw for Monte Carlo estimation.

    Returns
    -------
        torch.Tensor
            The confidence map.
    """
    logits, sigma = predict_logits_mean_sigma(model, dataloader)
    mean_probs = logits_mean_sigma_to_probabilities(logits, sigma, samples=samples)
    return probs_to_confidence_map(mean_probs)
