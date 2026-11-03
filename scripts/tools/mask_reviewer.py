"""Dedicated Local Browser-Based Mask Reviewer for Gray Cast Iron Metallography.

Provides a full-resolution (2592 x 1944) interactive review and editing workflow:
- Synchronized pan and zoom (5% to 2000%)
- Hardware-accelerated dual-layer canvas with nearest-neighbor crisp pixel display
- Circular brush cursor preview matching exact brush radius in image coordinates
- White Brush (B) paints foreground (255)
- Black Eraser (E) clears background (0)
- Overlay opacity control and instant toggle (M)
- Multi-step Undo (Ctrl+Z) and Redo (Ctrl+Y)
- Strict validation: dimensions must be exactly 2592 x 1944, single-channel, values in {0, 255}
- Safe atomic save to data/gray_cast_iron_raw/masks/sample_1_reviewed.png
- Localhost only (127.0.0.1)
"""
from __future__ import annotations

import argparse
import base64
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse
import webbrowser

import cv2
import numpy as np

from nodiq.core.config import REPO_ROOT, GRAY_CAST_IRON_RAW_DIR
PROJECT_ROOT = REPO_ROOT
DEFAULT_IMAGE_PATH = GRAY_CAST_IRON_RAW_DIR / "images" / "sample_1.bmp"
DEFAULT_DRAFT_MASK_PATH = GRAY_CAST_IRON_RAW_DIR / "masks" / "sample_1_draft_v2.png"
DEFAULT_REVIEWED_MASK_PATH = GRAY_CAST_IRON_RAW_DIR / "masks" / "sample_1_reviewed.png"
ALLOWED_MASKS_DIR = (GRAY_CAST_IRON_RAW_DIR / "masks").resolve()

EXPECTED_SHAPE = (1944, 2592)  # (H, W)

PROTECTED_FILENAMES = {
    f"sample_{i}.bmp" for i in range(1, 21)
} | {
    "sample_1_draft.png",
} | {
    f"sample_{i}_draft_v2.png" for i in range(1, 21)
}


def resolve_sample_paths(sample_key: Any) -> Tuple[Path, Path, Path, str]:
    """Resolve (image_path, mask_path, reviewed_path, sample_name) for a given sample identifier."""
    key_str = str(sample_key or "1").strip().lower()
    num = "".join(filter(str.isdigit, key_str))
    if not num:
        num = "1"
    s_name = f"sample_{num}"
    img = GRAY_CAST_IRON_RAW_DIR / "images" / f"{s_name}.bmp"
    draft = GRAY_CAST_IRON_RAW_DIR / "masks" / f"{s_name}_draft_v2.png"
    reviewed = GRAY_CAST_IRON_RAW_DIR / "masks" / f"{s_name}_reviewed.png"
    return img, draft, reviewed, s_name


def get_dataset_samples_manifest() -> List[Dict[str, Any]]:
    """Scan and list all 20 expected gray cast iron samples with accurate status."""
    samples = []
    for idx in range(1, 21):
        s_name = f"sample_{idx}"
        img_p = GRAY_CAST_IRON_RAW_DIR / "images" / f"{s_name}.bmp"
        draft_p = GRAY_CAST_IRON_RAW_DIR / "masks" / f"{s_name}_draft_v2.png"
        rev_p = GRAY_CAST_IRON_RAW_DIR / "masks" / f"{s_name}_reviewed.png"

        img_exists = img_p.is_file()
        draft_exists = draft_p.is_file()
        rev_exists = rev_p.is_file()

        if rev_exists:
            status = "REVIEWED"
            label = "Reviewed Mask Saved"
        elif not img_exists:
            status = "MISSING_SOURCE"
            label = "Micrograph Missing"
        elif draft_exists:
            status = "AWAITING_REVIEW"
            label = "Draft Ready (Awaiting Review)"
        else:
            status = "FAILED"
            label = "Draft Generation Failed"

        samples.append({
            "id": str(idx),
            "sample_name": s_name,
            "image_file": f"{s_name}.bmp",
            "image_exists": img_exists,
            "draft_file": f"{s_name}_draft_v2.png",
            "draft_exists": draft_exists,
            "reviewed_file": f"{s_name}_reviewed.png",
            "reviewed_exists": rev_exists,
            "status": status,
            "label": label,
        })
    return samples



def screen_to_canvas_coords(
    screen_x: float,
    screen_y: float,
    offset_x: float,
    offset_y: float,
    scale: float,
) -> Tuple[float, float]:
    """Map display/screen coordinates to full-resolution canvas coordinates."""
    if scale <= 0:
        scale = 1.0
    canvas_x = (screen_x - offset_x) / scale
    canvas_y = (screen_y - offset_y) / scale
    return canvas_x, canvas_y


def apply_brush_stroke(
    mask: np.ndarray,
    pt1: Tuple[int, int],
    pt2: Tuple[int, int],
    radius: int,
    value: int = 255,
) -> np.ndarray:
    """Rasterize a continuous brush stroke onto a mask buffer."""
    out = mask.copy()
    thickness = max(1, int(radius * 2))
    cv2.line(out, pt1, pt2, int(value), thickness=thickness, lineType=cv2.LINE_8)
    cv2.circle(out, pt1, int(radius), int(value), thickness=-1)
    cv2.circle(out, pt2, int(radius), int(value), thickness=-1)
    return out


def validate_mask_array(
    mask: np.ndarray,
    expected_shape: Tuple[int, int] = EXPECTED_SHAPE,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Strictly validate that a mask matches dimensions, single channel, and binary values."""
    if mask is None or not isinstance(mask, np.ndarray):
        return False, "Mask is null or not a valid numpy array.", {}

    if mask.ndim != 2:
        return False, f"Mask must be single-channel 2D array, got {mask.ndim} dimensions (shape: {mask.shape}).", {}

    h, w = mask.shape
    if (h, w) != expected_shape:
        return False, f"Dimension mismatch: expected {expected_shape[1]}x{expected_shape[0]}, got {w}x{h}.", {}

    if mask.dtype != np.uint8:
        return False, f"Mask dtype must be uint8, got {mask.dtype}.", {}

    unique_vals = set(np.unique(mask).tolist())
    if not unique_vals.issubset({0, 255}):
        return False, f"Mask contains non-binary pixel values: {sorted(list(unique_vals))}. Only 0 and 255 are permitted.", {}

    total_pixels = h * w
    fg_pixels = int(np.count_nonzero(mask == 255))
    area_fraction_pct = round((fg_pixels / total_pixels) * 100.0, 2)

    meta = {
        "width": w,
        "height": h,
        "total_pixels": total_pixels,
        "graphite_pixels": fg_pixels,
        "area_fraction_pct": area_fraction_pct,
        "unique_values": sorted(list(unique_vals)),
    }
    return True, "Valid binary mask.", meta


def validate_mask_file(
    file_path: Path,
    expected_shape: Tuple[int, int] = EXPECTED_SHAPE,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate a mask file on disk for shape (1944, 2592), uint8, single-channel, and {0, 255} binary values."""
    path = Path(file_path).resolve()
    if not path.is_file():
        return False, f"Mask file does not exist: {path}", {}
    mask = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if mask is None:
        return False, f"Failed to read image at {path}", {}
    return validate_mask_array(mask, expected_shape=expected_shape)


def save_reviewed_mask_atomically(
    mask: np.ndarray,
    out_path: Path,
    overwrite: bool = False,
    expected_shape: Tuple[int, int] = EXPECTED_SHAPE,
    current_sample: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Atomically save reviewed mask with strict path and value validation."""
    out_path = Path(out_path).resolve()

    # Security check: path must stay within ALLOWED_MASKS_DIR
    try:
        out_path.relative_to(ALLOWED_MASKS_DIR)
    except ValueError:
        return False, f"Security violation: Target path {out_path} is outside allowed directory {ALLOWED_MASKS_DIR}.", {}

    # Never overwrite original image or draft masks
    if (
        out_path.name in PROTECTED_FILENAMES
        or out_path.name.endswith(".bmp")
        or "_draft" in out_path.name
    ):
        return False, f"Protected file: Cannot overwrite raw image or existing draft {out_path.name}.", {}

    # Cross-sample protection: sample N can never overwrite any other sample's reviewed mask
    if current_sample:
        cur_num = "".join(filter(str.isdigit, str(current_sample)))
        for other_num in range(1, 21):
            if str(other_num) != cur_num and out_path.name == f"sample_{other_num}_reviewed.png":
                return False, f"Protected file: Cannot overwrite sample {other_num} reviewed mask while working on sample {cur_num}.", {}

    if out_path.exists() and not overwrite:
        return False, f"File {out_path.name} already exists. Confirmation required before overwriting.", {"requires_confirmation": True}

    is_valid, msg, meta = validate_mask_array(mask, expected_shape=expected_shape)
    if not is_valid:
        return False, f"Validation failure: {msg}", meta

    # Atomic write via temporary file
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_name(f"{out_path.stem}.tmp_{os.getpid()}_{int(time.time()*1000)}.png")

    try:
        success = cv2.imwrite(str(temp_path), mask)
        if not success or not temp_path.exists():
            return False, "Failed to encode or write temporary mask file.", {}

        # Atomic replace
        os.replace(temp_path, out_path)
    except Exception as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        return False, f"Filesystem write error: {e}", {}

    meta["saved_path"] = str(out_path)
    return True, f"Successfully saved reviewed mask to {out_path.name}.", meta


def check_staging_prerequisites(
    img_path: Path,
    mask_path: Path,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Verify presence and dimensional compatibility of input files."""
    img_path = Path(img_path)
    mask_path = Path(mask_path)

    status: Dict[str, Any] = {
        "image_path": str(img_path),
        "image_exists": img_path.is_file(),
        "mask_path": str(mask_path),
        "mask_exists": mask_path.is_file(),
        "image_dims": None,
        "mask_dims": None,
        "dimensions_match": False,
    }

    if not img_path.is_file():
        return False, f"Source micrograph not found at {img_path}.", status

    if not mask_path.is_file():
        return False, f"Draft mask not found at {mask_path}.", status

    img = cv2.imread(str(img_path))
    if img is None:
        return False, f"Cannot decode image at {img_path}.", status
    h_img, w_img = img.shape[:2]
    status["image_dims"] = [w_img, h_img]

    mask = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
    if mask is None:
        return False, f"Cannot decode mask at {mask_path}.", status
    if mask.ndim == 2:
        h_mask, w_mask = mask.shape
    else:
        h_mask, w_mask = mask.shape[:2]
    status["mask_dims"] = [w_mask, h_mask]

    if (w_img, h_img) != (w_mask, h_mask):
        return False, f"Dimension mismatch: image is {w_img}x{h_img}, but mask is {w_mask}x{h_mask}.", status

    status["dimensions_match"] = True
    return True, "Prerequisites verified.", status


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gray Cast Iron — Mask Reviewer (Full-Resolution 2592x1944)</title>
<style>
  :root {
    --bg-dark: #0a0d14;
    --panel-bg: #141923;
    --border-color: #263042;
    --accent-cyan: #06b6d4;
    --accent-emerald: #10b981;
    --accent-amber: #f59e0b;
    --accent-rose: #f43f5e;
    --text-main: #f8fafc;
    --text-muted: #94a3b8;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; user-select: none; }
  body {
    background: var(--bg-dark);
    color: var(--text-main);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  }
  header {
    background: var(--panel-bg);
    border-bottom: 1px solid var(--border-color);
    padding: 10px 18px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    z-index: 20;
    pointer-events: auto;
  }
  .title-group h1 {
    font-size: 15px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .badge {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 4px;
    background: #1e293b;
    color: var(--accent-cyan);
    font-weight: 500;
    border: 1px solid #334155;
  }
  .badge-dim { color: #cbd5e1; }
  .controls-bar {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .btn-group {
    display: flex;
    background: #090d14;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    overflow: hidden;
  }
  button.tool-btn {
    background: transparent;
    border: none;
    color: var(--text-muted);
    padding: 7px 13px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 6px;
    transition: all 0.15s ease;
  }
  button.tool-btn:hover { background: #1e293b; color: var(--text-main); }
  button.tool-btn.active {
    background: var(--accent-cyan);
    color: #090d14;
    font-weight: 600;
  }
  button.tool-btn.active.eraser {
    background: var(--accent-rose);
    color: #ffffff;
  }
  .slider-group {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    color: var(--text-muted);
  }
  input[type="range"] {
    accent-color: var(--accent-cyan);
    cursor: pointer;
  }
  .save-btn {
    background: linear-gradient(135deg, #0ea5e9, #06b6d4);
    color: #fff;
    border: none;
    padding: 7px 16px;
    border-radius: 6px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(6, 182, 212, 0.25);
    transition: all 0.15s;
  }
  .save-btn:hover { filter: brightness(1.1); }
  .save-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  #main-viewport {
    flex: 1;
    position: relative;
    overflow: hidden;
    background: #040608;
    cursor: crosshair;
    touch-action: none;
  }
  #view-canvas {
    position: absolute;
    top: 0;
    left: 0;
    image-rendering: pixelated;
    image-rendering: crisp-edges;
    pointer-events: auto;
  }
  .status-bar {
    background: var(--panel-bg);
    border-top: 1px solid var(--border-color);
    padding: 6px 18px;
    font-size: 12px;
    color: var(--text-muted);
    display: flex;
    justify-content: space-between;
    align-items: center;
    z-index: 20;
  }
  .status-left { display: flex; gap: 16px; align-items: center; }
  .hud-badge { color: #f8fafc; font-weight: 600; }
  .banner-err {
    position: absolute;
    top: 20px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(244, 63, 94, 0.95);
    color: #fff;
    padding: 10px 20px;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
    box-shadow: 0 4px 16px rgba(0,0,0,0.5);
    z-index: 100;
    display: none;
    pointer-events: none;
  }
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.75);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 200;
  }
  .modal-card {
    background: var(--panel-bg);
    border: 1px solid var(--border-color);
    padding: 24px;
    border-radius: 10px;
    width: 440px;
    color: var(--text-main);
  }
  .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    margin-top: 20px;
  }
  .btn-sec { background: #334155; color: #fff; border: none; padding: 7px 15px; border-radius: 6px; cursor: pointer; }
  .btn-prim { background: var(--accent-rose); color: #fff; border: none; padding: 7px 15px; border-radius: 6px; cursor: pointer; font-weight: 600; }
</style>
</head>
<body>

<header>
  <div class="title-group" style="display:flex; align-items:center; gap:12px;">
    <h1>Gray Cast Iron Flake Reviewer <span id="badge-sample-file" class="badge">sample_1.bmp</span> <span class="badge badge-dim">2592 × 1944 px</span></h1>

    <!-- Multi-Sample Navigator with Status Distinction -->
    <div class="sample-nav" style="display:flex; align-items:center; gap:6px;">
      <button id="btn-prev-sample" class="tool-btn" title="Previous Available Sample (Shortcut: <)">&lt; Prev</button>
      <select id="sample-select" style="background:#090d14; color:#f8fafc; border:1px solid #334155; padding:6px 10px; border-radius:6px; font-size:12px; font-weight:600; cursor:pointer;" title="Select any Gray Cast Iron Sample (1-20)">
        <!-- Options populated dynamically via /api/samples -->
      </select>
      <button id="btn-next-sample" class="tool-btn" title="Next Available Sample (Shortcut: >)">Next &gt;</button>
      <span id="badge-status-pill" class="badge" style="font-size:11px; padding:3px 9px; font-weight:600;">Loading...</span>
    </div>
  </div>

  <div class="controls-bar">
    <div class="btn-group">
      <button id="btn-brush" class="tool-btn active" title="Shortcut: B (Draw White Foreground)">🖌️ Brush (White)</button>
      <button id="btn-eraser" class="tool-btn" title="Shortcut: E (Erase to Black Background)">🧹 Eraser (Black)</button>
      <button id="btn-pan" class="tool-btn" title="Shortcut: Space + Drag">✋ Pan</button>
    </div>

    <div class="slider-group">
      <span>Radius:</span>
      <input type="range" id="brush-size" min="1" max="120" value="12">
      <span id="brush-size-val">12 px</span>
    </div>

    <div class="slider-group">
      <span>Overlay Opacity:</span>
      <input type="range" id="overlay-alpha" min="0" max="100" value="45">
      <span id="overlay-alpha-val">45%</span>
    </div>

    <button id="btn-toggle-mask" class="tool-btn active" title="Shortcut: M">👁️ Overlay (M)</button>

    <div class="btn-group">
      <button id="btn-undo" class="tool-btn" title="Shortcut: Ctrl+Z">↶ Undo</button>
      <button id="btn-redo" class="tool-btn" title="Shortcut: Ctrl+Y">↷ Redo</button>
    </div>

    <button id="btn-save" class="save-btn">💾 Save Reviewed Mask</button>
  </div>
</header>

<div id="main-viewport">
  <canvas id="view-canvas"></canvas>
  <div id="banner-error" class="banner-err"></div>
</div>

<div class="status-bar">
  <div class="status-left">
    <span>Zoom: <span id="hud-zoom" class="hud-badge">100%</span></span>
    <span>Cursor: <span id="hud-coord" class="hud-badge">X: 0, Y: 0</span></span>
    <span>Graphite Area Fraction: <span id="hud-af" class="hud-badge">14.81%</span></span>
    <span>Active Tool: <span id="hud-tool" class="hud-badge">White Brush (Graphite Foreground = 255)</span></span>
  </div>
  <div>
    <span>Status: <span id="hud-status" style="color: var(--accent-emerald);">Ready</span></span>
  </div>
</div>

<!-- Overwrite confirmation modal -->
<div id="modal-confirm" class="modal-overlay">
  <div class="modal-card">
    <h3 style="margin-bottom: 8px;">Overwrite Reviewed Mask?</h3>
    <p style="font-size: 13px; color: var(--text-muted); line-height: 1.5;">
      A previously reviewed mask <code id="modal-filename" style="color:var(--accent-cyan);">sample_1_reviewed.png</code> already exists.
      Are you sure you want to overwrite it with your current manual edits?
    </p>
    <div class="modal-actions">
      <button id="modal-cancel" class="btn-sec">Cancel</button>
      <button id="modal-proceed" class="btn-prim">Yes, Overwrite</button>
    </div>
  </div>
</div>

<script>
(function() {
  const FULL_W = 2592;
  const FULL_H = 1944;

  // Offscreen full-resolution buffers (2592 x 1944)
  const imgCanvas = document.createElement("canvas");
  imgCanvas.width = FULL_W;
  imgCanvas.height = FULL_H;
  const imgCtx = imgCanvas.getContext("2d");

  // Mask layer: Foreground flakes are Cyan (#00e5ff, Alpha 255), Background is Transparent (Alpha 0)
  const maskCanvas = document.createElement("canvas");
  maskCanvas.width = FULL_W;
  maskCanvas.height = FULL_H;
  const maskCtx = maskCanvas.getContext("2d");
  maskCtx.imageSmoothingEnabled = false;

  // Viewport elements
  const viewport = document.getElementById("main-viewport");
  const viewCanvas = document.getElementById("view-canvas");
  const viewCtx = viewCanvas.getContext("2d");
  viewCtx.imageSmoothingEnabled = false;

  // State
  let scale = 1.0;
  let offsetX = 0;
  let offsetY = 0;
  let activeTool = "brush"; // "brush", "eraser", "pan"
  let brushRadius = 12;
  let overlayAlpha = 0.45;
  let showMask = true;
  let isPointerDown = false;
  let isDrawing = false;
  let isPanning = false;
  let lastCanvasX = 0, lastCanvasY = 0;
  let panStartX = 0, panStartY = 0;
  let isSpacePressed = false;
  let cursorCanvasX = -999, cursorCanvasY = -999;
  let isCursorInside = false;

  // History stack for undo/redo (max 15 full-resolution states)
  const undoStack = [];
  const redoStack = [];
  const MAX_HISTORY = 15;

  function pushHistory() {
    if (undoStack.length >= MAX_HISTORY) undoStack.shift();
    undoStack.push(maskCtx.getImageData(0, 0, FULL_W, FULL_H));
    redoStack.length = 0;
  }

  function resizeViewport() {
    viewCanvas.width = viewport.clientWidth;
    viewCanvas.height = viewport.clientHeight;
    render();
  }
  window.addEventListener("resize", resizeViewport);

  // Multi-sample navigation & state management
  const urlParams = new URLSearchParams(window.location.search);
  const sampleParam = urlParams.get("sample") || "1";
  let activeSample = "".concat(sampleParam).replace(/\D/g, "") || "1";

  const sampleName = "sample_" + activeSample;
  const imgFilename = sampleName + ".bmp";
  const reviewedFilename = sampleName + "_reviewed.png";

  const badgeSample = document.getElementById("badge-sample-file");
  if (badgeSample) badgeSample.innerText = imgFilename;
  const modalFilename = document.getElementById("modal-filename");
  if (modalFilename) modalFilename.innerText = reviewedFilename;

  let samplesList = [];

  async function loadSamplesList() {
    try {
      const res = await fetch("/api/samples");
      const data = await res.json();
      if (data.ok && Array.isArray(data.samples)) {
        samplesList = data.samples;
        renderSampleDropdown();
      }
    } catch (e) {
      console.error("Failed to fetch /api/samples", e);
    }
  }

  function renderSampleDropdown() {
    const sel = document.getElementById("sample-select");
    if (!sel) return;
    sel.innerHTML = "";
    samplesList.forEach(s => {
      const opt = document.createElement("option");
      opt.value = s.id;
      let symbol = "⏳";
      if (s.status === "REVIEWED") symbol = "✓";
      else if (s.status === "MISSING_SOURCE") symbol = "⚠️";
      else if (s.status === "FAILED") symbol = "❌";

      opt.text = `${s.sample_name}.bmp [${symbol} ${s.label}]`;
      if (s.id === activeSample) opt.selected = true;
      if (s.status === "MISSING_SOURCE") opt.disabled = true;
      sel.appendChild(opt);
    });
    updateStatusPill();
  }

  function updateStatusPill() {
    const pill = document.getElementById("badge-status-pill");
    if (!pill) return;
    const cur = samplesList.find(s => s.id === activeSample);
    if (!cur) return;
    if (cur.status === "REVIEWED") {
      pill.innerText = "✓ Reviewed Mask Saved";
      pill.style.color = "var(--accent-emerald)";
      pill.style.borderColor = "var(--accent-emerald)";
      pill.style.background = "rgba(16, 185, 129, 0.12)";
    } else if (cur.status === "AWAITING_REVIEW") {
      pill.innerText = "⏳ Draft Ready (Awaiting Review)";
      pill.style.color = "var(--accent-amber)";
      pill.style.borderColor = "var(--accent-amber)";
      pill.style.background = "rgba(245, 158, 11, 0.12)";
    } else if (cur.status === "MISSING_SOURCE") {
      pill.innerText = "⚠️ Micrograph Missing";
      pill.style.color = "var(--accent-rose)";
      pill.style.borderColor = "var(--accent-rose)";
      pill.style.background = "rgba(244, 63, 94, 0.12)";
    } else {
      pill.innerText = "❌ Draft Missing";
      pill.style.color = "var(--accent-rose)";
      pill.style.borderColor = "var(--accent-rose)";
      pill.style.background = "rgba(244, 63, 94, 0.12)";
    }
  }

  function navigateToSample(targetId) {
    if (targetId === activeSample) return;
    window.location.href = "/?sample=" + encodeURIComponent(targetId);
  }

  const selDropdown = document.getElementById("sample-select");
  if (selDropdown) {
    selDropdown.onchange = (e) => navigateToSample(e.target.value);
  }

  const prevBtn = document.getElementById("btn-prev-sample");
  if (prevBtn) {
    prevBtn.onclick = () => {
      const valid = samplesList.filter(s => s.status !== "MISSING_SOURCE");
      const idx = valid.findIndex(s => s.id === activeSample);
      if (idx > 0) navigateToSample(valid[idx - 1].id);
    };
  }

  const nextBtn = document.getElementById("btn-next-sample");
  if (nextBtn) {
    nextBtn.onclick = () => {
      const valid = samplesList.filter(s => s.status !== "MISSING_SOURCE");
      const idx = valid.findIndex(s => s.id === activeSample);
      if (idx >= 0 && idx < valid.length - 1) navigateToSample(valid[idx + 1].id);
    };
  }

  loadSamplesList();

  // Load Micrograph and Mask
  const rawImg = new Image();
  const rawMask = new Image();
  let imgLoaded = false;
  let maskLoaded = false;

  rawImg.onload = () => {
    imgCtx.drawImage(rawImg, 0, 0, FULL_W, FULL_H);
    imgLoaded = true;
    checkInit();
  };

  rawMask.onload = () => {
    // Convert 8-bit binary mask (black=0, white=255) to transparent/cyan offscreen mask:
    const tempCan = document.createElement("canvas");
    tempCan.width = FULL_W;
    tempCan.height = FULL_H;
    const tempCtx = tempCan.getContext("2d");
    tempCtx.drawImage(rawMask, 0, 0);

    const imgData = tempCtx.getImageData(0, 0, FULL_W, FULL_H);
    const d = imgData.data;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i] > 127) {
        // Foreground flake: Cyan (#00e5ff) with Alpha 255
        d[i] = 0;
        d[i + 1] = 229;
        d[i + 2] = 255;
        d[i + 3] = 255;
      } else {
        // Background matrix: Fully Transparent
        d[i] = 0;
        d[i + 1] = 0;
        d[i + 2] = 0;
        d[i + 3] = 0;
      }
    }
    maskCtx.putImageData(imgData, 0, 0);
    maskLoaded = true;
    pushHistory();
    updateAreaFraction();
    checkInit();
  };

  rawImg.src = "/api/image?sample=" + encodeURIComponent(activeSample);
  rawMask.src = "/api/mask?sample=" + encodeURIComponent(activeSample);

  function checkInit() {
    if (imgLoaded && maskLoaded) {
      const fitScale = Math.min(viewport.clientWidth / FULL_W, viewport.clientHeight / FULL_H) * 0.95;
      scale = fitScale;
      offsetX = (viewport.clientWidth - FULL_W * scale) / 2;
      offsetY = (viewport.clientHeight - FULL_H * scale) / 2;
      render();
      document.getElementById("hud-status").innerText = `Ready • ${imgFilename} Full-Res 2592x1944 Loaded`;
    }
  }

  // Render composite to viewCanvas
  function render() {
    viewCtx.clearRect(0, 0, viewCanvas.width, viewCanvas.height);
    viewCtx.save();
    viewCtx.imageSmoothingEnabled = false;
    viewCtx.translate(offsetX, offsetY);
    viewCtx.scale(scale, scale);

    // 1. Draw original micrograph
    if (imgLoaded) {
      viewCtx.drawImage(imgCanvas, 0, 0);
    }

    // 2. Draw mask overlay with crisp nearest-neighbor rendering
    if (maskLoaded && showMask && overlayAlpha > 0) {
      viewCtx.save();
      viewCtx.globalAlpha = overlayAlpha;
      viewCtx.drawImage(maskCanvas, 0, 0);
      viewCtx.restore();
    }

    // 3. Draw circular brush cursor preview at cursor location
    if (isCursorInside && activeTool !== "pan" && !isSpacePressed) {
      viewCtx.save();
      viewCtx.beginPath();
      viewCtx.arc(cursorCanvasX, cursorCanvasY, brushRadius, 0, Math.PI * 2);
      viewCtx.strokeStyle = activeTool === "eraser" ? "#f43f5e" : "#00e5ff";
      viewCtx.lineWidth = Math.max(1.5 / scale, 1.0);
      viewCtx.setLineDash([4 / scale, 4 / scale]);
      viewCtx.stroke();
      viewCtx.restore();
    }

    viewCtx.restore();
    document.getElementById("hud-zoom").innerText = Math.round(scale * 100) + "%";
  }

  // Coordinate transforms
  function screenToCanvas(sx, sy) {
    const cx = (sx - offsetX) / scale;
    const cy = (sy - offsetY) / scale;
    return { x: cx, y: cy };
  }

  // Painting on full-resolution mask canvas
  function paintPoint(cx, cy, erase = false) {
    maskCtx.save();
    maskCtx.imageSmoothingEnabled = false;
    if (erase) {
      maskCtx.globalCompositeOperation = "destination-out";
      maskCtx.beginPath();
      maskCtx.arc(cx, cy, brushRadius, 0, Math.PI * 2);
      maskCtx.fill();
    } else {
      maskCtx.globalCompositeOperation = "source-over";
      maskCtx.fillStyle = "#00e5ff"; // Cyan foreground
      maskCtx.beginPath();
      maskCtx.arc(cx, cy, brushRadius, 0, Math.PI * 2);
      maskCtx.fill();
    }
    maskCtx.restore();
  }

  function paintSegment(x0, y0, x1, y1, erase = false) {
    maskCtx.save();
    maskCtx.imageSmoothingEnabled = false;
    if (erase) {
      maskCtx.globalCompositeOperation = "destination-out";
      maskCtx.lineWidth = brushRadius * 2;
      maskCtx.lineCap = "round";
      maskCtx.lineJoin = "round";
      maskCtx.beginPath();
      maskCtx.moveTo(x0, y0);
      maskCtx.lineTo(x1, y1);
      maskCtx.stroke();
    } else {
      maskCtx.globalCompositeOperation = "source-over";
      maskCtx.strokeStyle = "#00e5ff";
      maskCtx.lineWidth = brushRadius * 2;
      maskCtx.lineCap = "round";
      maskCtx.lineJoin = "round";
      maskCtx.beginPath();
      maskCtx.moveTo(x0, y0);
      maskCtx.lineTo(x1, y1);
      maskCtx.stroke();
    }
    maskCtx.restore();
  }

  function updateAreaFraction() {
    const id = maskCtx.getImageData(0, 0, FULL_W, FULL_H);
    let count = 0;
    const d = id.data;
    for (let i = 3; i < d.length; i += 4) {
      if (d[i] > 127) count++;
    }
    const af = ((count / (FULL_W * FULL_H)) * 100).toFixed(2);
    document.getElementById("hud-af").innerText = af + "%";
  }

  // Pointer event handling with pointer-capture for smooth drawing
  viewCanvas.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    viewCanvas.setPointerCapture(e.pointerId);

    const rect = viewCanvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const { x, y } = screenToCanvas(sx, sy);

    isPointerDown = true;

    // Pan mode (Middle click, spacebar held, or pan tool active)
    if (e.button === 1 || isSpacePressed || activeTool === "pan") {
      isPanning = true;
      panStartX = e.clientX - offsetX;
      panStartY = e.clientY - offsetY;
      viewport.style.cursor = "grabbing";
      return;
    }

    // Brush or Eraser mode
    if (e.button === 0) {
      pushHistory();
      isDrawing = true;
      lastCanvasX = x;
      lastCanvasY = y;
      paintPoint(x, y, activeTool === "eraser");
      render();
    }
  });

  viewCanvas.addEventListener("pointermove", (e) => {
    const rect = viewCanvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const { x, y } = screenToCanvas(sx, sy);

    cursorCanvasX = x;
    cursorCanvasY = y;
    isCursorInside = (x >= 0 && x < FULL_W && y >= 0 && y < FULL_H);

    if (isCursorInside) {
      document.getElementById("hud-coord").innerText = `X: ${Math.round(x)}, Y: ${Math.round(y)}`;
    }

    if (isPanning) {
      offsetX = e.clientX - panStartX;
      offsetY = e.clientY - panStartY;
      render();
      return;
    }

    if (isDrawing) {
      paintSegment(lastCanvasX, lastCanvasY, x, y, activeTool === "eraser");
      lastCanvasX = x;
      lastCanvasY = y;
      render();
      return;
    }

    // Re-render cursor ring
    render();
  });

  function stopPointer(e) {
    if (isPointerDown) {
      try { viewCanvas.releasePointerCapture(e.pointerId); } catch(err) {}
      isPointerDown = false;
    }
    if (isDrawing) {
      isDrawing = false;
      updateAreaFraction();
    }
    if (isPanning) {
      isPanning = false;
      viewport.style.cursor = (activeTool === "pan" || isSpacePressed) ? "grab" : "crosshair";
    }
    render();
  }

  viewCanvas.addEventListener("pointerup", stopPointer);
  viewCanvas.addEventListener("pointercancel", stopPointer);

  viewCanvas.addEventListener("pointerleave", () => {
    isCursorInside = false;
    render();
  });
  viewCanvas.addEventListener("pointerenter", () => {
    isCursorInside = true;
    render();
  });

  // Wheel zoom centered on pointer
  viewCanvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = viewCanvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
    const newScale = Math.min(Math.max(scale * zoomFactor, 0.05), 20.0);

    offsetX = mouseX - (mouseX - offsetX) * (newScale / scale);
    offsetY = mouseY - (mouseY - offsetY) * (newScale / scale);
    scale = newScale;
    render();
  }, { passive: false });

  // Tool buttons
  const btnBrush = document.getElementById("btn-brush");
  const btnEraser = document.getElementById("btn-eraser");
  const btnPan = document.getElementById("btn-pan");

  function setTool(tool) {
    activeTool = tool;
    btnBrush.classList.toggle("active", tool === "brush");
    btnEraser.classList.toggle("active", tool === "eraser");
    btnEraser.classList.toggle("eraser", tool === "eraser");
    btnPan.classList.toggle("active", tool === "pan");

    viewport.style.cursor = tool === "pan" ? "grab" : "crosshair";

    document.getElementById("hud-tool").innerText =
      tool === "brush" ? "White Brush (Graphite Foreground = 255)" :
      tool === "eraser" ? "Black Eraser (Matrix Background = 0)" : "Pan Viewport";
    render();
  }

  btnBrush.onclick = () => setTool("brush");
  btnEraser.onclick = () => setTool("eraser");
  btnPan.onclick = () => setTool("pan");

  const brushSlider = document.getElementById("brush-size");
  brushSlider.oninput = () => {
    brushRadius = parseInt(brushSlider.value);
    document.getElementById("brush-size-val").innerText = brushRadius + " px";
    render();
  };

  const alphaSlider = document.getElementById("overlay-alpha");
  alphaSlider.oninput = () => {
    overlayAlpha = parseInt(alphaSlider.value) / 100;
    document.getElementById("overlay-alpha-val").innerText = Math.round(overlayAlpha * 100) + "%";
    render();
  };

  const toggleBtn = document.getElementById("btn-toggle-mask");
  toggleBtn.onclick = () => {
    showMask = !showMask;
    toggleBtn.classList.toggle("active", showMask);
    render();
  };

  // Undo / Redo
  document.getElementById("btn-undo").onclick = () => {
    if (undoStack.length > 0) {
      redoStack.push(maskCtx.getImageData(0, 0, FULL_W, FULL_H));
      const prev = undoStack.pop();
      maskCtx.putImageData(prev, 0, 0);
      updateAreaFraction();
      render();
    }
  };
  document.getElementById("btn-redo").onclick = () => {
    if (redoStack.length > 0) {
      undoStack.push(maskCtx.getImageData(0, 0, FULL_W, FULL_H));
      const next = redoStack.pop();
      maskCtx.putImageData(next, 0, 0);
      updateAreaFraction();
      render();
    }
  };

  // Keyboard hotkeys
  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    const k = e.key.toLowerCase();
    if (k === "b") setTool("brush");
    else if (k === "e") setTool("eraser");
    else if (k === "m") toggleBtn.click();
    else if (e.code === "Space") {
      isSpacePressed = true;
      viewport.style.cursor = "grab";
    } else if (k === "[") {
      brushRadius = Math.max(1, brushRadius - 3);
      brushSlider.value = brushRadius;
      brushSlider.oninput();
    } else if (k === "]") {
      brushRadius = Math.min(120, brushRadius + 3);
      brushSlider.value = brushRadius;
      brushSlider.oninput();
    } else if (k === "<" || k === ",") {
      const p = document.getElementById("btn-prev-sample");
      if (p) p.click();
    } else if (k === ">" || k === ".") {
      const n = document.getElementById("btn-next-sample");
      if (n) n.click();
    } else if (k === "0") {
      checkInit(); // Reset zoom
    } else if (e.ctrlKey && k === "z") {
      e.preventDefault();
      document.getElementById("btn-undo").click();
    } else if (e.ctrlKey && k === "y") {
      e.preventDefault();
      document.getElementById("btn-redo").click();
    }
  });

  window.addEventListener("keyup", (e) => {
    if (e.code === "Space") {
      isSpacePressed = false;
      viewport.style.cursor = activeTool === "pan" ? "grab" : "crosshair";
    }
  });

  // Export full-resolution binary mask (2592 x 1944)
  function createBinaryMaskDataUrl() {
    const exportCan = document.createElement("canvas");
    exportCan.width = FULL_W;
    exportCan.height = FULL_H;
    const expCtx = exportCan.getContext("2d");

    const id = maskCtx.getImageData(0, 0, FULL_W, FULL_H);
    const d = id.data;
    const outImgData = expCtx.createImageData(FULL_W, FULL_H);
    const outD = outImgData.data;

    for (let i = 0; i < d.length; i += 4) {
      // Foreground: Alpha > 127
      if (d[i + 3] > 127) {
        outD[i] = 255;
        outD[i + 1] = 255;
        outD[i + 2] = 255;
        outD[i + 3] = 255; // White
      } else {
        outD[i] = 0;
        outD[i + 1] = 0;
        outD[i + 2] = 0;
        outD[i + 3] = 255; // Black
      }
    }
    expCtx.putImageData(outImgData, 0, 0);
    return exportCan.toDataURL("image/png");
  }

  // Save reviewed mask
  const saveBtn = document.getElementById("btn-save");
  const modalConfirm = document.getElementById("modal-confirm");
  const modalProceed = document.getElementById("modal-proceed");
  const modalCancel = document.getElementById("modal-cancel");

  async function executeSave(overwrite = false) {
    saveBtn.disabled = true;
    saveBtn.innerText = "Saving...";
    document.getElementById("hud-status").innerText = "Saving & Validating...";

    const dataUrl = createBinaryMaskDataUrl();

    try {
      const res = await fetch("/api/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_data: dataUrl,
          overwrite: overwrite,
          sample: activeSample,
        }),
      });

      const body = await res.json();
      if (res.status === 409 && body.requires_confirmation) {
        modalConfirm.style.display = "flex";
        saveBtn.disabled = false;
        saveBtn.innerText = "💾 Save Reviewed Mask";
        return;
      }

      if (!res.ok || !body.ok) {
        throw new Error(body.error || "Save failed.");
      }

      document.getElementById("hud-status").style.color = "var(--accent-emerald)";
      document.getElementById("hud-status").innerText = `Saved Successfully • Area Fraction: ${body.area_fraction_pct}%`;
      saveBtn.disabled = false;
      saveBtn.innerText = "✅ Saved!";
      setTimeout(() => { saveBtn.innerText = "💾 Save Reviewed Mask"; }, 2500);
      loadSamplesList();
    } catch (err) {
      document.getElementById("hud-status").style.color = "var(--accent-rose)";
      document.getElementById("hud-status").innerText = "Save Error: " + err.message;
      alert("Save Failed:\n" + err.message);
      saveBtn.disabled = false;
      saveBtn.innerText = "💾 Save Reviewed Mask";
    }
  }

  saveBtn.onclick = () => executeSave(false);
  modalProceed.onclick = () => {
    modalConfirm.style.display = "none";
    executeSave(true);
  };
  modalCancel.onclick = () => {
    modalConfirm.style.display = "none";
  };

  // Check prerequisites on load
  fetch("/api/status?sample=" + encodeURIComponent(activeSample)).then(r => r.json()).then(data => {
    if (!data.ok) {
      const b = document.getElementById("banner-error");
      b.style.display = "block";
      b.innerText = "Prerequisite Error: " + data.message;
    }
  });

  resizeViewport();
})();
</script>
</body>
</html>
"""


class MaskReviewerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Mask Reviewer bound strictly to localhost."""

    image_path: Path = DEFAULT_IMAGE_PATH
    mask_path: Path = DEFAULT_DRAFT_MASK_PATH
    reviewed_path: Path = DEFAULT_REVIEWED_MASK_PATH
    sample_name: str = "sample_1"

    def log_message(self, format: str, *args: Any) -> None:
        """Quiet log output for clean console."""
        pass

    def _resolve_target_paths(self, query: Dict[str, list], body_data: Optional[Dict[str, Any]] = None) -> Tuple[Path, Path, Path, str]:
        sample_val = None
        if "sample" in query and query["sample"]:
            sample_val = query["sample"][0]
        elif body_data and "sample" in body_data and body_data["sample"]:
            sample_val = body_data["sample"]

        if sample_val is not None:
            resolved_img, resolved_draft, resolved_rev, s_name = resolve_sample_paths(sample_val)
            if s_name == self.sample_name:
                return self.image_path, self.mask_path, self.reviewed_path, self.sample_name
            return resolved_img, resolved_draft, resolved_rev, s_name
        return self.image_path, self.mask_path, self.reviewed_path, self.sample_name

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
            return

        if path == "/api/samples":
            manifest = get_dataset_samples_manifest()
            self._send_json({"ok": True, "total_samples": len(manifest), "samples": manifest})
            return

        if path == "/api/status":
            img_path, mask_path, rev_path, s_name = self._resolve_target_paths(query)
            ok, msg, status = check_staging_prerequisites(img_path, mask_path)
            res = {
                "ok": ok,
                "message": msg,
                "sample": s_name,
                **status,
                "reviewed_path": str(rev_path),
                "reviewed_exists": rev_path.is_file(),
            }
            self._send_json(res)
            return

        if path == "/api/image":
            img_path, _, _, _ = self._resolve_target_paths(query)
            if not img_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, f"Image not found at {img_path}.")
                return
            img = cv2.imread(str(img_path))
            if img is None:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to decode image.")
                return
            ok, buf = cv2.imencode(".png", img)
            if not ok:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to encode PNG.")
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(buf)))
            self.end_headers()
            self.wfile.write(buf.tobytes())
            return

        if path == "/api/mask":
            _, mask_path, rev_path, _ = self._resolve_target_paths(query)
            target = mask_path
            if rev_path.is_file() and query.get("use_draft") != ["true"]:
                target = rev_path
            elif query.get("use_reviewed") == ["true"] and rev_path.is_file():
                target = rev_path

            if not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, f"Mask not found at {target}.")
                return
            mask_bytes = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(mask_bytes)))
            self.end_headers()
            self.wfile.write(mask_bytes)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Path not found.")

    def do_POST(self) -> None:
        if self.path == "/api/save":
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len == 0 or content_len > 60_000_000:
                self._send_json({"ok": False, "error": "Invalid request body size."}, status=HTTPStatus.BAD_REQUEST)
                return

            body = self.rfile.read(content_len)
            try:
                data = json.loads(body.decode("utf-8"))
            except Exception as e:
                self._send_json({"ok": False, "error": f"Invalid JSON: {e}"}, status=HTTPStatus.BAD_REQUEST)
                return

            data_url = data.get("image_data", "")
            overwrite = bool(data.get("overwrite", False))

            if not data_url.startswith("data:image/png;base64,"):
                self._send_json({"ok": False, "error": "Expected base64 PNG data URL."}, status=HTTPStatus.BAD_REQUEST)
                return

            b64_str = data_url.split(",", 1)[1]
            try:
                png_bytes = base64.b64decode(b64_str)
                nparr = np.frombuffer(png_bytes, np.uint8)
                mask = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
            except Exception as e:
                self._send_json({"ok": False, "error": f"Failed to decode base64 PNG: {e}"}, status=HTTPStatus.BAD_REQUEST)
                return

            if mask is None:
                self._send_json({"ok": False, "error": "Decoded mask is null."}, status=HTTPStatus.BAD_REQUEST)
                return

            # Convert to single-channel if RGBA or RGB was generated by canvas
            if mask.ndim == 3:
                # If 4 channels (RGBA): check red or alpha
                gray = mask[:, :, 0]
                mask = (gray > 127).astype(np.uint8) * 255
            else:
                mask = (mask > 127).astype(np.uint8) * 255

            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            _, _, target_reviewed_path, current_s_name = self._resolve_target_paths(query, body_data=data)

            success, msg, meta = save_reviewed_mask_atomically(
                mask,
                target_reviewed_path,
                overwrite=overwrite,
                expected_shape=EXPECTED_SHAPE,
                current_sample=current_s_name,
            )

            if not success:
                status_code = HTTPStatus.CONFLICT if meta.get("requires_confirmation") else HTTPStatus.BAD_REQUEST
                self._send_json({"ok": False, "error": msg, **meta}, status=status_code)
                return

            self._send_json({"ok": True, "message": msg, **meta})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found.")

    def _send_json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def run_reviewer_server(
    host: str = "127.0.0.1",
    port: int = 5055,
    open_browser: bool = True,
    image_path: Optional[Path] = None,
    mask_path: Optional[Path] = None,
    reviewed_path: Optional[Path] = None,
    sample: Optional[str] = "1",
) -> ThreadingHTTPServer:
    """Launch local reviewer server bound strictly to localhost."""
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError(f"Security policy: Reviewer must bind to 127.0.0.1 only. Disallowed: {host}")

    def_img, def_draft, def_rev, s_name = resolve_sample_paths(sample)
    final_image_path = Path(image_path) if image_path else def_img
    final_mask_path = Path(mask_path) if mask_path else def_draft
    final_reviewed_path = Path(reviewed_path) if reviewed_path else def_rev

    MaskReviewerHandler.image_path = final_image_path
    MaskReviewerHandler.mask_path = final_mask_path
    MaskReviewerHandler.reviewed_path = final_reviewed_path
    MaskReviewerHandler.sample_name = s_name

    server = ThreadingHTTPServer((host, port), MaskReviewerHandler)
    url = f"http://{host}:{port}/" + (f"?sample={sample}" if str(sample) not in ("1", "sample_1") else "")
    print("=" * 72)
    print("  GRAY CAST IRON — LOCAL MASK REVIEWER")
    print("=" * 72)
    print(f"Active Sample    : {s_name}")
    print(f"Server URL       : {url}")
    print(f"Bound Address    : {host}:{port} (Localhost Only)")
    print(f"Source Image     : {final_image_path}")
    print(f"Input Draft Mask : {final_mask_path}")
    print(f"Target Output    : {final_reviewed_path}")
    print("-" * 72)
    print("Press Ctrl+C to stop the server.")
    print("=" * 72)

    if open_browser:
        threading.Thread(target=lambda: (time.sleep(0.5), webbrowser.open(url)), daemon=True).start()

    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Launch local browser-based gray cast iron mask reviewer.")
    parser.add_argument("--sample", type=str, default="1", help="Sample to review (1 or 2, default: 1)")
    parser.add_argument("--port", type=int, default=5055, help="Port to bind (default: 5055)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser")
    parser.add_argument("--image", type=str, default=None, help="Custom source micrograph path (overrides sample)")
    parser.add_argument("--mask", type=str, default=None, help="Custom draft mask path (overrides sample)")
    parser.add_argument("--out", type=str, default=None, help="Custom reviewed mask path (overrides sample)")
    args = parser.parse_args()

    srv = run_reviewer_server(
        host="127.0.0.1",
        port=args.port,
        open_browser=not args.no_browser,
        image_path=Path(args.image) if args.image else None,
        mask_path=Path(args.mask) if args.mask else None,
        reviewed_path=Path(args.out) if args.out else None,
        sample=args.sample,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Mask Reviewer server...")
        srv.server_close()
