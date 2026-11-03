from pathlib import Path
import torch
import torch.nn as nn
import pytorch_lightning as pl
import numpy as np


class DoubleConv(nn.Module):
    """
    A module that implements a sequence of convolutional layers with batch normalization and ReLU activation.

    This module creates a sequential model of convolutional layers where the number of channels
    linearly interpolates from the input channels to the output channels across the specified number of layers.

    Parameters:
    -----------
        input_channels : int
            Number of input channels.
        output_channels : int
            Number of output channels.
        num_layers : int
            Number of convolutional layers in the sequence.

    Returns:
    --------
        torch.nn.Module
            A sequential model containing the specified convolutional layers.

    Example:
        >>> double_conv = DoubleConv(64, 128, 2)
        >>> x = torch.randn(1, 64, 32, 32)
        >>> output = double_conv(x)
        >>> output.shape
        torch.Size([1, 128, 32, 32])
    """

    def __init__(self, input_channels, output_channels, num_layers):
        super().__init__()
        self.conv = nn.Sequential()
        n_channels = np.linspace(input_channels, output_channels, num_layers + 1).astype(int)
        for n in range(num_layers):
            self.conv.add_module(f"conv{n}", nn.Conv2d(n_channels[n], n_channels[n + 1], 3, padding=1))
            self.conv.add_module(f"batch_norm{n}", nn.BatchNorm2d(n_channels[n + 1]))
            self.conv.add_module(f"relu{n}", nn.ReLU(inplace=True))

    def forward(self, x):
        return self.conv(x)


class UNet(nn.Module):
    """
    U-Net architecture for image segmentation tasks.

    This implementation follows the original U-Net architecture with customizable depth and width.
    The network consists of a contracting path (downsampling), a bottleneck, and an expansive path (upsampling)
    with skip connections between the contracting and expansive paths.

    Parameters
    ----------
    input_channels : int, default=2
        Number of input channels.
    output_channels : int, default=1
        Number of output channels.
    layers_per_block : int, default=2
        Number of convolutional layers per block.
    blocks : int, default=4
        Number of downsampling/upsampling blocks.
    hidden_layers_block1 : int, default=64
        Number of features in the first hidden layer.
    pooling_range : int, default=2
        Size of pooling and upsampling operations.

    References
    ----------
    Ronneberger, O., Fischer, P., & Brox, T. (2015). U-Net: Convolutional Networks for Biomedical
    Image Segmentation. In Medical Image Computing and Computer-Assisted Intervention (MICCAI).

    Example
    -------
    >>> model = UNet(input_channels=1, output_channels=2)
    >>> x = torch.randn(1, 1, 128, 128)
    >>> output = model(x)
    >>> output.shape
    torch.Size([1, 2, 128, 128])
    """

    def __init__(
        self,
        input_channels=2,
        output_channels=1,
        layers_per_block=2,
        blocks=4,
        hidden_layers_block1=64,
        pooling_range=2,
    ):
        super().__init__()
        n_blocks = pooling_range ** np.arange(blocks + 1, dtype=int) * hidden_layers_block1
        n_blocks = np.insert(n_blocks, 0, input_channels, axis=0)
        self.down = nn.ModuleList()
        for n in range(blocks):
            self.down.append(DoubleConv(n_blocks[n], n_blocks[n + 1], layers_per_block))

        self.pool = nn.MaxPool2d(pooling_range)

        self.middle = DoubleConv(n_blocks[-2], n_blocks[-1], layers_per_block)

        self.up = nn.ModuleList()
        self.conv = nn.ModuleList()

        for n in range(1, blocks + 1):
            self.up.append(nn.ConvTranspose2d(n_blocks[n + 1], n_blocks[n], pooling_range, stride=pooling_range))
            self.conv.append(DoubleConv(n_blocks[n + 1], n_blocks[n], layers_per_block))

        self.final = nn.Sequential(nn.Conv2d(n_blocks[1], output_channels, 1))

    def forward(self, x):

        down_out = [
            x,
        ]
        for n, down_block in enumerate(self.down):
            if n == 0:
                down_out.append(down_block(down_out[n]))
            else:
                down_out.append(self.pool(down_block(down_out[n])))

        m = self.middle(self.pool(down_out[-1]))

        up_out = [
            m,
        ]
        for n in range(len(self.up)):
            up_out.append(self.up[-(n + 1)](up_out[n]))
            up_out[-1] = torch.cat([up_out[-1], down_out[-(n + 1)]], dim=1)
            up_out[-1] = self.conv[-(n + 1)](up_out[-1])

        out = self.final(up_out[-1])
        return out


class SegmentationModel(pl.LightningModule):
    """
    A PyTorch Lightning module for training a U-Net segmentation model.

    This module wraps the UNet architecture and provides functionality for training,
    validation, and testing with PyTorch Lightning. It includes loss computation,
    optimization, and learning rate scheduling.

    Parameters
    ----------
    in_channels : int, default=2
        Number of input channels for the model.
    out_channels : int, default=1
        Number of output channels for the model.
    lr : float, default=2e-4
        Initial learning rate for the optimizer.
    lr_scheduler_patience : int, default=4
        Number of epochs with no improvement after which the learning rate will be reduced.
    lr_scheduler_factor : float, default=0.5
        Factor by which the learning rate will be reduced.
    **kwargs
        Additional arguments passed to the UNet constructor.

    Example
    -------
    >>> model = SegmentationModel(in_channels=2, out_channels=1)
    >>> trainer = pl.Trainer(max_epochs=10)
    >>> trainer.fit(model, train_dataloader, val_dataloader)
    """

    def __init__(
        self,
        in_channels=2,
        out_channels=1,
        lr=2e-4,
        lr_scheduler_patience=4,
        lr_scheduler_factor=0.5,
        **kwargs,
    ):
        super().__init__()
        self.model = UNet(input_channels=in_channels, output_channels=out_channels, **kwargs)
        self.lr = lr
        self.lr_scheduler_patience = lr_scheduler_patience
        self.lr_scheduler_factor = lr_scheduler_factor
        self.temperature = 1.0

    def forward(self, x):
        return self.model(x) / self.temperature

    def dice_loss(self, pred, target, smooth=1.0, eps=1e-6):
        intersection = (pred * target).sum(dim=-1).sum(dim=-1)
        loss = 1 - (
            (2.0 * intersection + smooth)
            / (pred.abs().sum(dim=-1).sum(dim=-1) + target.sum(dim=-1).sum(dim=-1) + smooth).clamp_(min=eps)
        )
        return loss

    def mean_dice_loss(self, pred, target, smooth=1.0):
        pred = nn.Sigmoid()(pred)
        pred = pred.contiguous()
        target = target.contiguous()
        loss = self.dice_loss(pred, target, smooth)
        return loss.mean()

    def training_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        loss = self.mean_dice_loss(logits, y)
        self.log("train_loss", loss, on_step=True, on_epoch=True, prog_bar=True)
        return loss

    def validation_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        loss = self.mean_dice_loss(logits, y)
        self.log("validation_loss", loss, on_step=False, on_epoch=True, prog_bar=True)
        score = 1 - loss
        self.log("validation_score", score, on_step=False, on_epoch=True, prog_bar=True)

    def test_step(self, batch, batch_idx):
        x, y = batch
        logits = self(x)
        loss = self.mean_dice_loss(logits, y)
        self.log("test_loss", loss, on_step=False, on_epoch=True, prog_bar=True)
        score = 1 - loss
        self.log("test_score", score, on_step=False, on_epoch=True, prog_bar=True)

    def predict_step(self, batch):
        x, _ = batch
        return self(x)

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=self.lr)
        scheduler = {
            "scheduler": torch.optim.lr_scheduler.ReduceLROnPlateau(
                optimizer=optimizer,
                mode="min",
                patience=self.lr_scheduler_patience,
                factor=self.lr_scheduler_factor,
            ),
            "name": "lr_scheduler",
            "monitor": "validation_loss",
        }
        return [optimizer], [scheduler]

    def predict_probabilities(self, batch):
        x, _ = batch
        logits = self.forward(x)
        probs = torch.sigmoid(logits / self.temperature)
        return probs

    def calibrate_temperature(self, val_loader, starting_temperature=1.0, max_iter=100, learning_rate=1.0):
        device = self.trainer.strategy.root_device
        all_logits = self.trainer.predict(self, val_loader)
        all_masks = [d[1].to(device).float() for d in val_loader]
        log_temperature = nn.Parameter(torch.zeros(1, device=device))
        log_temperature.data = torch.tensor(starting_temperature, device=device).log()  # start from log(T)=0 => T=1
        loss_function = nn.BCEWithLogitsLoss()

        optimizer = torch.optim.LBFGS(
            [log_temperature], lr=learning_rate, max_iter=max_iter, line_search_fn="strong_wolfe"
        )

        temperature_history = []
        loss_history = []

        iteration = [0]  # Mutable container for tracking iterations inside closure

        def closure():
            optimizer.zero_grad()
            total_loss = 0.0
            total_batches = 0

            for logits, masks in zip(all_logits, all_masks):
                # Clone the pre-computed logits and detach to create a fresh tensor for autograd
                logits_for_grad = logits.clone().detach().requires_grad_(True).to(device)

                # Scale the logits with temperature
                scaled_logits = logits_for_grad / log_temperature.exp()

                loss = loss_function(scaled_logits, masks)
                total_loss += loss
                total_batches += 1

            avg_loss = total_loss / total_batches
            avg_loss.backward()

            # Track current T and loss
            current_T = log_temperature.exp().item()
            temperature_history.append(current_T)
            loss_history.append(avg_loss.item())

            iteration[0] += 1

            return avg_loss

        optimizer.step(closure)

        final_temperature = log_temperature.exp().detach()
        self.temperature = final_temperature.item()
        return temperature_history


class SegmentationModel_mve(SegmentationModel):
    """
    A PyTorch Lightning module for training a U-Net segmentation model with mean variance estimation.

    This module extends the SegmentationModel to include mean variance estimation,
    allowing for uncertainty estimation in segmentation tasks.

    Parameters
    ----------
    in_channels : int, default=2
        Number of input channels for the model.
    out_channels : int, default=2
        Number of output channels for the model.
    lr : float, default=2e-4
        Initial learning rate for the optimizer.
    lr_scheduler_patience : int, default=4
        Number of epochs with no improvement after which the learning rate will be reduced.
    lr_scheduler_factor : float, default=0.5
        Factor by which the learning rate will be reduced.
    regression : bool, default=False
        If True, use regression loss for mean variance estimation; otherwise, use classification loss.
    **kwargs
        Additional arguments passed to the UNet constructor.

    Example
    -------
    >>> model = SegmentationModel_mve(in_channels=2, out_channels=2)
    >>> trainer = pl.Trainer(max_epochs=10)
    >>> trainer.fit(model, train_dataloader, val_dataloader)
    """

    def __init__(
        self,
        in_channels=2,
        out_channels=2,
        lr=2e-4,
        lr_scheduler_patience=4,
        lr_scheduler_factor=0.5,
        regression=False,
        **kwargs,
    ):
        assert out_channels == 2, "For mean variance estimation, out_channels must be 2 (mean and variance)."
        super().__init__(
            in_channels=in_channels,
            out_channels=out_channels,
            lr=lr,
            lr_scheduler_patience=lr_scheduler_patience,
            lr_scheduler_factor=lr_scheduler_factor,
            **kwargs,
        )
        self.regression = regression
        self.var_loss_weight = 0

    def forward(self, x):
        """
        Forward pass that returns only the logits (mean predictions).
        """
        return self.model(x)[:, 0:1, :, :]

    def forward_mean_var(self, x):
        """
        Forward pass that returns both logits (mean predictions) and log variance.
        """
        output = self.model(x)
        logits = output[:, 0:1, :, :]
        log_var = output[:, 1:2, :, :]
        return logits, log_var

    def regression_loss(self, logits, log_var, target):
        """
        Computes the Gaussian negative log-likelihood loss for mean-variance uncertainty estimation in the regression case.

        This method implements the loss function described in equation (8) of Kendall & Gal 2017. This loss function combines both the prediction
        accuracy and the uncertainty estimation by incorporating the learned variance into the loss computation.

        Args:
            pred (torch.Tensor): The predicted mean values from the model.
            log_var (torch.Tensor): The logarithm of the predicted variance values.
            target (torch.Tensor): The ground truth target values.

        Returns:
            torch.Tensor: The computed Gaussian negative log-likelihood loss, reduced by mean.
        """
        nll = 0.5 * log_var + (0.5 * torch.exp(-log_var) * torch.pow(target - nn.Sigmoid()(logits), 2))
        return nll.mean()

    def classification_loss(self, logits, sigma, target, T=40):
        noise = torch.randn(T, *logits.shape, device=logits.device)
        perturbed_logits = logits.unsqueeze(0) + sigma.unsqueeze(0) * noise
        target_exp = target.unsqueeze(0).expand(T, -1, -1, -1, -1)
        loss = self.mean_dice_loss(perturbed_logits, target_exp.float())
        return loss

    def compute_losses(self, batch):
        x, y = batch
        predicted_logits, var = self.forward_mean_var(x)
        if self.var_loss_weight < 1:
            dice = self.mean_dice_loss(predicted_logits, y)
        else:
            dice = torch.tensor(0.0, device=self.device)
        if self.var_loss_weight > 0:
            if self.regression:
                p = nn.Sigmoid()(predicted_logits)
                nll = self.regression_loss(p, var, y)
            else:
                nll = self.classification_loss(predicted_logits, var, y)
        else:
            nll = torch.tensor(0.0, device=self.device)
        loss = (1 - self.var_loss_weight) * dice + self.var_loss_weight * nll
        return dice, nll, loss

    def training_step(self, batch, batch_idx):
        dice, nll, loss = self.compute_losses(batch)

        self.log("train_loss", loss, on_step=True, on_epoch=True, prog_bar=True)
        self.log("train_dice_loss", dice, on_step=True, on_epoch=True, prog_bar=True)
        self.log("train_nll", nll, on_step=True, on_epoch=True, prog_bar=True)
        self.log(
            "var_loss_weight",
            self.var_loss_weight,
            on_epoch=True,
            prog_bar=True,
        )
        return loss

    def predict_step(self, batch):
        x, _ = batch
        return self.forward_mean_var(x)

    def predict_probabilities(self, batch, samples=40):
        x, _ = batch
        logits, sigma = self.forward_mean_var(x)
        noise = torch.randn(samples, *logits.shape, device=logits.device)
        perturbed_logits = logits.unsqueeze(0) + sigma.unsqueeze(0) * noise
        probs = torch.sigmoid(perturbed_logits)
        mean_probs = probs.mean(dim=0)
        return mean_probs


class NLLWarmupCallback(pl.Callback):
    """
    PyTorch Lightning callback to gradually increase the weight of the NLL loss during training.

    This callback modifies the `var_loss_weight` attribute of the model at the end of each epoch,
    allowing for a gradual transition from focusing solely on the Dice loss to incorporating the NLL loss.

    Parameters
    ----------
    warmup_epochs : int, default=10
        Number of epochs over which to linearly increase the NLL loss weight from 0 to 1.
    """

    def __init__(self, warmup_epochs: int = 10):
        super().__init__()
        self.warmup_epochs = warmup_epochs

    def on_train_epoch_end(self, trainer, pl_module):
        if trainer.current_epoch < self.warmup_epochs:
            # Linearly increase the NLL loss weight
            pl_module.var_loss_weight = (trainer.current_epoch + 1) / self.warmup_epochs


def learn_temperature_lbfgs(
    model, val_loader, starting_temperature=1.0, max_iter=100, learning_rate=1.0, device_name="cuda"
):
    """
    Learns and tracks a scalar temperature parameter T using L-BFGS to calibrate
    a binary segmentation model's outputs.

    Parameters:
    -----------
    model : torch.nn.Module
        The trained segmentation model (outputs raw logits).
    val_loader : torch.utils.data.DataLoader
        Validation dataloader with (input, mask) batches.
    starting_temperature : float (default=1.0)
        Initial value for the temperature parameter.
    max_iter : int (default=100)
        Max iterations for L-BFGS.
    learning_rate : float (default=1.0)
        Learning rate for L-BFGS (used as damping factor).
    device_name : str (default="cuda")
        Device to run the optimization on.

    Returns:
    --------
    temperature : torch.Tensor
        Learned scalar temperature T.

    temperature_history : List[float]
        List of T values after each optimizer step (for plotting/debugging).
    """
    device = torch.device(device_name)

    # Pre-compute model outputs to avoid repeated forward passes
    # Store them as regular tensors to later detach and clone
    acc = "gpu" if device_name == "cuda" or device_name == "mps" else "cpu"
    trainer = pl.Trainer(accelerator=acc, enable_progress_bar=False)
    all_logits = trainer.predict(model, val_loader)
    all_masks = []
    for _, masks in val_loader:
        masks = masks.to(device).float()
        if masks.ndim == 3:
            masks = masks.unsqueeze(1)
        all_masks.append(masks)

    log_temperature = nn.Parameter(torch.zeros(1, device=device))
    log_temperature.data = torch.tensor(starting_temperature, device=device).log()  # start from log(T)=0 => T=1
    loss_function = nn.BCEWithLogitsLoss()

    optimizer = torch.optim.LBFGS(
        [log_temperature], lr=learning_rate, max_iter=max_iter, line_search_fn="strong_wolfe"
    )

    temperature_history = []
    loss_history = []

    iteration = [0]  # Mutable container for tracking iterations inside closure

    def closure():
        optimizer.zero_grad()
        total_loss = 0.0
        total_batches = 0

        for logits, masks in zip(all_logits, all_masks):
            # Clone the pre-computed logits and detach to create a fresh tensor for autograd
            logits_for_grad = logits.clone().detach().requires_grad_(True).to(device)

            # Scale the logits with temperature
            scaled_logits = logits_for_grad / log_temperature.exp()

            loss = loss_function(scaled_logits, masks)
            total_loss += loss
            total_batches += 1

        avg_loss = total_loss / total_batches
        avg_loss.backward()

        # Track current T and loss
        current_T = log_temperature.exp().item()
        temperature_history.append(current_T)
        loss_history.append(avg_loss.item())

        print(f"Step {iteration[0]:3d} | T = {current_T:.5f} | Loss = {avg_loss.item():.5f}")
        iteration[0] += 1

        return avg_loss

    optimizer.step(closure)

    final_temperature = log_temperature.exp().detach()
    print(f"\nFinal Optimal Temperature T* = {float(final_temperature):.4f}")
    return final_temperature, temperature_history


def dataloader_to_labels(dataloader: torch.utils.data.DataLoader) -> torch.Tensor:
    """
    Extracts and concatenates all labels from a dataloader.

    Parameters:
    -----------
    dataloader : torch.utils.data.DataLoader
        Dataloader containing (images, masks) batches.

    Returns:
    --------
    labels : torch.Tensor
        Concatenated labels tensor.
    """
    labels = []
    for _, l in dataloader:
        labels.append(l)
    labels = torch.cat(labels, dim=0)
    return labels


def get_latest_checkpoint_path(model_path: Path, model_name: str) -> Path:
    """
    Get the path to the latest checkpoint file for a given model.

    Parameters:
    -----------
    model_path : Path
        Directory where model checkpoints are stored.
    model_name : str
        Name of the model to find checkpoints for.

    Returns:
    --------
    Path
        Path to the latest checkpoint file.
    """
    checkpoint_paths = list((model_path / model_name).glob("**/*.ckpt"))
    if checkpoint_paths:
        print(f"Found existing checkpoints: {list(checkpoint_paths)}. Using the latest one for training.")
        checkpoint_path = max(checkpoint_paths, key=lambda p: p.stat().st_mtime)
        print(f"Loading checkpoint from {checkpoint_path}")
    else:
        checkpoint_path = None
        print("No checkpoints found. Starting training from scratch.")
    return checkpoint_path


def load_model(
    checkpoint_path: Path,
    model_class: SegmentationModel = SegmentationModel,
    **model_params,
) -> pl.LightningModule:
    """
    Load a segmentation model from the latest checkpoint.

    Parameters:
    -----------
    model_path : Path
        Directory where model checkpoints are stored.
    model_name : str
        Name of the model to load.

    Returns:
    --------
    pl.LightningModule
        Loaded segmentation model.
    """
    if checkpoint_path is not None:
        model = model_class.load_from_checkpoint(str(checkpoint_path), **model_params)
        print(f"Model loaded from {checkpoint_path}")
    else:
        model = model_class(**model_params)
        print("Initialized new model.")
    return model
