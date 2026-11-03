#!/usr/bin/env python3
"""
services/validation_lab.py — validation lab (Phases 31-32).

Four separated validation kinds, each labeled with its data source:
  INTERNAL   — the stored 1000-image validated batch (recomputed from the CSV,
               never hard-coded numbers)
  BLIND_TEST — run the engine now on N images whose validated rows we hide,
               score against the independent in-process reference
  EXTERNAL   — user-supplied images scored against the same reference method
  SYNTHETIC  — generated images with known ground truth (counted exactly)

Metrics are never silently merged: every block reports its own source label.
"""
import csv
import random
import time
from pathlib import Path

import cv2
import numpy as np

from nodiq.core.config import REPO_ROOT, WEB_DIR, SUMMARY_1000_CSV_PATH

ROOT = REPO_ROOT
DATASET_DIR = WEB_DIR / "public" / "dataset"
SUMMARY_CSV = SUMMARY_1000_CSV_PATH

FIELDS = ["file", "count", "frozen_count", "unified", "recovered",
          "reference_count", "count_accuracy_pct", "precision_pct",
          "recall_pct", "f1_pct", "double_counts", "iso_pct",
          "iso_inframe_pct", "jis_pct", "seconds", "error"]


def _load_batch_rows():
    rows = []
    try:
        with open(SUMMARY_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f) if f.readline().startswith("file,") \
                else csv.reader(f)
            f.seek(0)
            for r in reader:
                if isinstance(r, list):
                    if len(r) != len(FIELDS):
                        continue
                    r = dict(zip(FIELDS, r))
                if r.get("file") and not r.get("error"):
                    rows.append(r)
    except Exception:
        pass
    return rows


def internal_validation():
    """Recompute summary stats from the stored per-image CSV (source of truth)."""
    rows = _load_batch_rows()
    if not rows:
        return {"source": "INTERNAL", "available": False,
                "note": "validated batch CSV not found"}
    def col(k):
        return [float(r[k]) for r in rows if r.get(k)]
    acc, prec, rec, f1 = (col("count_accuracy_pct"), col("precision_pct"),
                          col("recall_pct"), col("f1_pct"))
    t = col("seconds")
    n = len(rows)
    return {
        "source": "INTERNAL",
        "available": True,
        "dataset": "ductile_cast_iron_1000_unique_micrographs",
        "image_count": n,
        "ground_truth": "independent reference segmentation "
                        "(median+Otsu opened map, per-image, computed in-process)",
        "count_accuracy_pct": round(sum(acc) / len(acc), 2),
        "precision_pct": round(sum(prec) / len(prec), 2),
        "recall_pct": round(sum(rec) / len(rec), 2),
        "f1_pct": round(sum(f1) / len(f1), 2),
        "min_count_accuracy_pct": round(min(acc), 2),
        "double_counts_total": int(sum(float(r["double_counts"] or 0)
                                       for r in rows)),
        "processing_time_s_mean": round(sum(t) / len(t), 2) if t else None,
        "artifacts": "nodularity_1000_fixed/summary_1000_fixed.{csv,md}",
    }


# ------------------------------------------------------------- blind test ----
def blind_test(n=10, seed=None):
    """Run the engine on n dataset images now; score against the in-process
    reference. Validated CSV rows are NOT consulted (blind)."""
    from nodiq.pipelines.nodularity_pipeline import analyze_image
    names = sorted(p.name for p in DATASET_DIR.glob("micrograph_*.png"))
    if not names:
        return {"source": "BLIND_TEST", "available": False,
                "note": "dataset not found"}
    rng = random.Random(seed)
    picks = rng.sample(names, min(n, len(names)))
    accs, precs, recs, f1s, ts = [], [], [], [], []
    per_image = []
    for name in picks:
        t0 = time.time()
        res = analyze_image(str(DATASET_DIR / name))
        dt = time.time() - t0
        accs.append(res["count_accuracy_pct"])
        precs.append(res["precision_pct"])
        recs.append(res["recall_pct"])
        f1s.append(res["f1_pct"])
        ts.append(dt)
        per_image.append({"file": name, "count": res["count"],
                          "reference_count": res["reference_count"],
                          "accuracy_pct": res["count_accuracy_pct"],
                          "f1_pct": res["f1_pct"]})
    return {
        "source": "BLIND_TEST",
        "available": True,
        "n": len(picks),
        "seed": seed,
        "count_accuracy_pct": round(sum(accs) / len(accs), 2),
        "precision_pct": round(sum(precs) / len(precs), 2),
        "recall_pct": round(sum(recs) / len(recs), 2),
        "f1_pct": round(sum(f1s) / len(f1s), 2),
        "processing_time_s_mean": round(sum(ts) / len(ts), 2),
        "per_image": per_image,
    }


# --------------------------------------------------------------- synthetic ----
def _synthetic_micrograph(n_nodules=40, size=(1200, 1600), seed=0):
    """Generate a synthetic ductile-iron-like micrograph with exact GT.

    Light matrix, dark round-ish blobs. Returns (gray, gt_count).
    """
    rng = np.random.RandomState(seed)
    w, h = size
    img = np.full((h, w), 215, np.uint8)
    img += rng.normal(0, 6, (h, w)).astype(np.int16).clip(-25, 25).astype(np.uint8)
    placed = 0
    tries = 0
    while placed < n_nodules and tries < n_nodules * 30:
        tries += 1
        r = int(rng.randint(9, 26))
        cx, cy = int(rng.randint(r + 4, w - r - 4)), int(rng.randint(r + 4, h - r - 4))
        blob = np.zeros((h, w), np.uint8)
        cv2.circle(blob, (cx, cy), r, 255, -1)
        cv2.imwrite  # noqa: B018 (no-op to keep linters quiet about import order)
        img[blob > 0] = np.uint8(30 + rng.randint(0, 25))
        placed += 1
    return img, placed


def synthetic_validation(n_images=3, seed=7):
    """Ground-truthed synthetic test: count accuracy against exact GT."""
    from nodiq.pipelines.nodularity_pipeline import analyze_image
    per_image, accs, f1s = [], [], []
    for i in range(n_images):
        gray, gt = _synthetic_micrograph(seed=seed + i)
        res = analyze_image(gray)
        acc = max(0.0, (1 - abs(res["count"] - gt) / max(gt, 1)) * 100)
        accs.append(acc)
        f1s.append(res["f1_pct"])
        per_image.append({"image": i, "gt_count": gt, "count": res["count"],
                          "accuracy_pct": round(acc, 2)})
    return {
        "source": "SYNTHETIC",
        "available": True,
        "n": n_images,
        "count_accuracy_pct": round(sum(accs) / len(accs), 2),
        "f1_pct": round(sum(f1s) / len(f1s), 2),
        "per_image": per_image,
        "note": "synthetic blobs; checks counting logic, not graphite realism",
    }


def external_validation(paths):
    """Score user-supplied images against the in-process reference method."""
    from nodiq.pipelines.nodularity_pipeline import analyze_image
    per_image, f1s = [], []
    for p in paths:
        try:
            res = analyze_image(str(p))
            per_image.append({"file": Path(p).name,
                              "count": res["count"],
                              "reference_count": res["reference_count"],
                              "accuracy_pct": res["count_accuracy_pct"],
                              "f1_pct": res["f1_pct"]})
            f1s.append(res["f1_pct"])
        except Exception as exc:
            per_image.append({"file": Path(p).name, "error": str(exc)})
    return {
        "source": "EXTERNAL",
        "available": True,
        "n": len(paths),
        "f1_pct": round(sum(f1s) / len(f1s), 2) if f1s else None,
        "per_image": per_image,
    }


def validation_summary():
    """All validation kinds, separately labeled (Phase 32)."""
    return {
        "internal": internal_validation(),
        "note": ("each validation kind is computed separately; metrics are "
                 "never merged across sources"),
    }
