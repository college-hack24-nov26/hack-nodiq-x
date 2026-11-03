#!/usr/bin/env python3
"""
tools/build_benchmark_v1.py — Phase 8A/8B/8C/8D builder.

Creates reports/ground_truth/benchmark_v1_manifest.json (8A) and, for each
of the first 10 recommended real images, an AI PRE-ANNOTATION PROPOSAL
ground-truth document (8B) with:

  provenance_class = "E"   (unverified — NOT expert truth)
  annotation.tool  = this builder (independent Otsu-reference tracing)
  independence_note explaining exactly what the geometry is and that an
                     expert must review/correct it before any accuracy claim

The tracing uses ONLY an independent image-processing reference (median+Otsu
human-view blob map with split/merge heuristics on the NATIVE image) — it
never loads NODIQ-X production contours and never touches labels_adaptive.
The proposals serve as review-ready starting points; the benchmark treats
them as provenance E (usable only with explicit WARNING, never A-class
evidence).

Physical scale (8C): unavailable — no trustworthy source exists in-repo.
Reference ISO/JIS (8D): null — none independently measured.

Usage:
    python scripts/tools/build_benchmark_v1.py            # build manifest + proposals
    python scripts/tools/build_benchmark_v1.py --validate # + write validation_v1.json
"""
import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]

from nodiq.services.ground_truth import (GT_DIR, empty_ground_truth,  # noqa: E402
                                   validate_all, validate_ground_truth)

from nodiq.core.config import OUTPUTS_DIR
MANIFEST_IN = OUTPUTS_DIR / "ground_truth" / "dataset_manifest.json"
MANIFEST_OUT = OUTPUTS_DIR / "ground_truth" / "benchmark_v1_manifest.json"
VALIDATION_OUT = OUTPUTS_DIR / "ground_truth" / "validation_v1.json"
BENCHMARK_VERSION = "v1"
N_IMAGES = 10


def _commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT_ROOT),
            text=True).strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# independent tracing reference (NOT the production detector)
# ---------------------------------------------------------------------------
def trace_reference_particles(image_path, min_area=25):
    """Independent particle tracing on the native image:
    median blur -> Otsu inverse -> close -> open -> connected components,
    with convexity-based splitting of obviously merged pairs.
    Returns (list of contours, list of border_touching)."""
    img = cv2.imread(str(image_path))
    if img is None:
        return [], []
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    med = cv2.medianBlur(gray, 5)
    _, dark = cv2.threshold(med, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, k)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, k)
    cnts, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    out, borders = [], []
    for c in cnts:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        x, y, bw, bh = cv2.boundingRect(c)
        touches = x <= 0 or y <= 0 or x + bw >= w or y + bh >= h
        hull = cv2.convexHull(c)
        hull_area = cv2.contourArea(hull)
        solidity = area / hull_area if hull_area > 0 else 1.0
        # split obviously dumb-bell merged pairs: strong waist + elongated
        if solidity < 0.72 and area >= 4 * min_area:
            dist = cv2.pointPolygonTest(
                hull, (x + bw / 2, y + bh / 2), True)
            if dist >= 0 and dist < 0.45 * min(bw, bh):
                # cut along the narrow axis at the waist
                axis_w = bw >= bh
                if axis_w:
                    cut_x = x + int(bw / 2)
                    left = np.zeros((h, w), np.uint8)
                    cv2.drawContours(left, [c], -1, 255, -1)
                    part1 = left[:, :cut_x].copy()
                    part2 = left[:, cut_x:].copy()
                else:
                    cut_y = y + int(bh / 2)
                    left = np.zeros((h, w), np.uint8)
                    cv2.drawContours(left, [c], -1, 255, -1)
                    part1 = left[:cut_y, :].copy()
                    part2 = left[cut_y:, :].copy()
                for part in (part1, part2):
                    pc, _ = cv2.findContours(part, cv2.RETR_EXTERNAL,
                                             cv2.CHAIN_APPROX_SIMPLE)
                    for pc2 in pc:
                        if cv2.contourArea(pc2) >= min_area:
                            if axis_w:
                                pc2 = pc2 + np.array(
                                    [[0, 0]]) if not axis_w else pc2
                            out.append(pc2)
                            borders.append(touches)
                continue
        out.append(c)
        borders.append(touches)
    return out, borders


def build():
    manifest = json.loads(MANIFEST_IN.read_text(encoding="utf-8"))
    recs = manifest["recommended_images"][:N_IMAGES]
    entries = []
    for r in recs:
        image_id = r["image_id"]
        image_file = r["file"]
        # --- pre-annotation proposal (8B) ---
        cnts, borders = trace_reference_particles(
            PROJECT_ROOT / image_file)
        # drop contours fully contained in a larger kept contour (nested-
        # fragment artifacts of the reference tracer — NOT a repair of
        # expert geometry; the proposal generator must emit self-consistent
        # output).  Border flags are recomputed from scratch below.
        keep, keep_masks = [], []
        for c in cnts:
            m = np.zeros((r["height"], r["width"]), np.uint8)
            cv2.drawContours(m, [c], -1, 255, -1)
            nested = False
            for km in keep_masks:
                inter = np.logical_and(m > 0, km > 0).sum()
                if inter and inter / max(1, int((m > 0).sum())) > 0.8:
                    nested = True
                    break
            if not nested:
                keep.append(c)
                keep_masks.append(m)
        cnts = keep
        doc = empty_ground_truth(image_id, image_file, r["width"],
                                 r["height"])
        doc["annotation"].update({
            "tool": "tools/build_benchmark_v1.py (independent "
                    "median+Otsu reference tracing)",
            "expert": None,
            "provenance_class": "E",
            "independence_note":
                "AI PRE-ANNOTATION PROPOSAL — geometry auto-traced from an "
                "independent median+Otsu image-processing reference on the "
                "native image; NOT traced from NODIQ-X production output, "
                "not from labels_adaptive; MUST be reviewed and corrected by "
                "a human expert (and provenance upgraded to A/B) before any "
                "accuracy claim",
        })
        doc["annotation"]["date"] = date.today().isoformat()
        doc["notes"] = ("PRE-ANNOTATION PROPOSAL for expert review "
                        "(benchmark " + BENCHMARK_VERSION + ")")
        particles = []
        for i, c in enumerate(cnts):
            x, y, bw, bh = cv2.boundingRect(c)
            touches = x <= 0 or y <= 0 or x + bw >= r["width"] or \
                y + bh >= r["height"]
            particles.append({
                "id": f"p{i + 1}",
                "geometry": {"type": "polygon",
                             "points": [[float(px), float(py)]
                                        for px, py in c.reshape(-1, 2)]},
                "border_touching": bool(touches),
                "uncertain": False,
                "notes": "proposal — verify/adjust geometry"})
        doc["particles"] = particles
        GT_DIR.mkdir(parents=True, exist_ok=True)
        (GT_DIR / f"{image_id}.json").write_text(
            json.dumps(doc, indent=1), encoding="utf-8")

        v = validate_ground_truth(doc)
        entries.append({
            "benchmark_version": BENCHMARK_VERSION,
            "image_id": image_id,
            "image_file": image_file,
            "series": r["series"],
            "width": r["width"],
            "height": r["height"],
            "selection_reason": (
                f"series={r['series']}, density={r['density_class']} "
                f"(coverage {r['graphite_coverage_pct']}%), "
                f"size_spread={r['size_spread_class']}"),
            "annotation_status": "PRE_ANNOTATION_PROPOSAL_PENDING_EXPERT",
            "provenance_class": "E",
            "physical_scale_status": "unavailable",
            "um_per_px": None,
            "scale_source": None,
            "reference_iso": None,
            "reference_jis": None,
            "reference_source": None,
            "gt_status": v["verdict"],
            "n_proposed_particles": len(particles),
            "validation": {"errors": v["errors"], "warnings": v["warnings"]},
        })
        print(f"{image_id}: {len(particles)} proposed particles, "
              f"gt_status={v['verdict']}, errors={len(v['errors'])}, "
              f"warnings={len(v['warnings'])}")

    out = {
        "benchmark_version": BENCHMARK_VERSION,
        "created": date.today().isoformat(),
        "production_commit_at_creation": _commit(),
        "source_manifest": "reports/ground_truth/dataset_manifest.json",
        "selection_rule": "first 10 recommended images (stratified by "
                          "series x density, size-spread preferred, native "
                          "res included)",
        "n_images": len(entries),
        "images": entries,
        "honesty_note": (
            "all GT documents are AI PRE-ANNOTATION PROPOSALS with "
            "provenance E; the primary accuracy benchmark remains "
            "INSUFFICIENT_GROUND_TRUTH until a human expert reviews and "
            "upgrades them to A/B; results computed on them are "
            "exploratory, never certified accuracy"),
    }
    MANIFEST_OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nbenchmark manifest -> {MANIFEST_OUT}")


def run_validation():
    report = validate_all(GT_DIR, VALIDATION_OUT)
    print(json.dumps(report["verdicts"], indent=1))
    print(f"usable: {report['n_usable']}/{report['n_documents']}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    args = ap.parse_args()
    build()
    if args.validate:
        run_validation()
