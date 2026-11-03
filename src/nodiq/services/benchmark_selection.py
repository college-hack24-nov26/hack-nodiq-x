#!/usr/bin/env python3
"""
services/benchmark_selection.py — benchmark image selection helper (Phase 7E).

Chooses WHICH real images experts should annotate first, so the benchmark
spans measured variation instead of convenience.  Selection is based only on
measured image/analysis properties (detector-independent where possible):

  * graphite coverage (human-view Otsu dark fraction)  -> sparse/dense
  * native resolution / series                          -> magnification variation
  * particle size spread (from the frozen detector's OWN candidate geometry
    on the working scale is NOT used for selection — selection is
    detector-independent; size spread comes from the human-view blob map)
  * series identity (1000270578 / panel / rosenberger / samples) -> provenance

This module never writes ground truth and never runs accuracy scoring.
"""

import json
from pathlib import Path

import cv2
import numpy as np

from nodiq.core.config import REPO_ROOT, THIRD_PARTY_NODULARITY, OUTPUTS_DIR

PROJECT_ROOT = REPO_ROOT
_nod_main = THIRD_PARTY_NODULARITY
INPUT_IMAGES = _nod_main / "input_images"
SAMPLES = _nod_main
MANIFEST_OUT = OUTPUTS_DIR / "ground_truth" / "dataset_manifest.json"


def _series_of(name):
    if name.startswith("1000270578"):
        return "1000270578"
    if name.startswith("rosenberger"):
        return "rosenberger"
    if name.startswith("panel"):
        return "panel"
    return "sample"


def measure_image(path):
    """Detector-independent image properties for selection."""
    img = cv2.imread(str(path))
    if img is None:
        return None
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    med = cv2.medianBlur(gray, 5)
    _, dark = cv2.threshold(med, 0, 255,
                            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    coverage = float((dark > 0).mean())
    n_blobs = 0
    size_spread = None
    n, lab, stats, _ = cv2.connectedComponentsWithStats(dark)
    areas = [stats[i, cv2.CC_STAT_AREA] for i in range(1, n)
             if stats[i, cv2.CC_STAT_AREA] >= 8]
    n_blobs = len(areas)
    if areas:
        size_spread = float(np.percentile(areas, 90) /
                            max(1, np.percentile(areas, 10)))
    return {
        "file": str(path.relative_to(PROJECT_ROOT)),
        "image_id": path.stem,
        "series": _series_of(path.stem),
        "width": w, "height": h,
        "graphite_coverage_pct": round(coverage * 100, 2),
        "human_view_blob_count": n_blobs,
        "blob_size_p90_over_p10": size_spread,
        "contrast_std": float(round(gray.std(), 1)),
        "mean_brightness": float(round(gray.mean(), 1)),
    }


def build_selection_manifest(top_n=20, out_path=MANIFEST_OUT):
    """Score every real repo image and record a recommended annotation set
    covering the variation matrix.  Writes dataset_manifest.json."""
    cands = []
    for p in sorted(INPUT_IMAGES.glob("*.png")):
        m = measure_image(p)
        if m:
            cands.append(m)
    for i in (1, 2, 3):
        p = SAMPLES / f"sample{i}(min_grainsize=0.007).jpg"
        if p.is_file():
            m = measure_image(p)
            if m:
                m["native_highres"] = True
                cands.append(m)

    # coverage buckets from measured properties
    for m in cands:
        cov = m["graphite_coverage_pct"]
        m["density_class"] = ("sparse" if cov < 3 else
                              "medium" if cov < 10 else "dense")
        m["size_spread_class"] = (
            "low" if m["blob_size_p90_over_p10"] is None else
            "low" if m["blob_size_p90_over_p10"] < 8 else
            "medium" if m["blob_size_p90_over_p10"] < 20 else "high")

    # stratified pick: every series, every density class, prefer native res
    picks = []
    seen = set()
    def take(pred, n):
        for m in cands:
            if len([p for p in picks]) >= len(picks) + n and False:
                break
            if m["image_id"] in seen or not pred(m):
                continue
            picks.append(m["image_id"])
            seen.add(m["image_id"])
            if sum(1 for p in picks) and m["image_id"] not in picks:
                break
    for series in ("1000270578", "panel", "rosenberger", "sample"):
        for dens in ("sparse", "medium", "dense"):
            pool = [m for m in cands if m["series"] == series
                    and m["density_class"] == dens
                    and m["image_id"] not in seen]
            pool.sort(key=lambda m: -(m["blob_size_p90_over_p10"] or 0))
            for m in pool[:2]:
                if m["image_id"] not in seen:
                    picks.append(m["image_id"])
                    seen.add(m["image_id"])
    for m in cands:                      # native high-res always included
        if m.get("native_highres") and m["image_id"] not in seen:
            picks.append(m["image_id"])
            seen.add(m["image_id"])
    picks = picks[:top_n]

    manifest = {
        "purpose": ("Phase 7E annotation selection — recommended real-image "
                    "benchmark covering measured variation; NOT ground truth "
                    "itself"),
        "n_real_images_available": len(cands),
        "n_recommended_for_annotation": len(picks),
        "minimum_for_primary_benchmark": 10,
        "coverage_matrix": _coverage_matrix(cands, picks),
        "recommended_images": [next(m for m in cands
                                    if m["image_id"] == pid)
                               for pid in picks],
        "all_measured_images": cands,
        "provenance_note": ("all input_images/ and sample*.jpg are REAL "
                            "micrographs (category E until expert-annotated, "
                            "then A/B); labels_adaptive/ is model output and "
                            "is never eligible"),
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _coverage_matrix(cands, picks):
    matrix = {}
    for m in cands:
        key = (m["series"], m["density_class"])
        matrix.setdefault(key, {"available": 0, "recommended": 0})
        matrix[key]["available"] += 1
        if m["image_id"] in picks:
            matrix[key]["recommended"] += 1
    return {f"{s}/{d}": v for (s, d), v in sorted(matrix.items())}


if __name__ == "__main__":
    m = build_selection_manifest()
    print(json.dumps({"recommended": m["n_recommended_for_annotation"],
                      "coverage": m["coverage_matrix"]}, indent=1))
