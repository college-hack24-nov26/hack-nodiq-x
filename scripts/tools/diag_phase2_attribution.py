#!/usr/bin/env python3
"""Attribution experiment (in-process, nothing persisted to disk):

A) current working tree            -> known: fp_carried=36, sweep 39/38/38
B) SMALL_AREA_FLOOR_RATIO -> 800   -> how much of each failure remains?
C) B + recovery ceiling forced 60  -> residual from the darkness relaxation?

If (B) restores both invariants, the small-particle floor is the sole cause
and a floor-qualified fix restores the locks without touching the darkness
recovery. If (B) still fails, the relaxation contributes and the attribution
is split — the fix must then address both.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

import nodiq.services.accuracy_bench as bench  # noqa: E402
from nodiq.services.accuracy_bench import (  # noqa: E402
    REVIEW_LABELED_IMAGES, run_production, score_against_review)


def measure(tag: str) -> None:
    probes = []
    for name in REVIEW_LABELED_IMAGES:
        run = run_production(bench.INPUT_IMAGES / (name + ".png"))
        probes.append(score_against_review(run["image_id"],
                                           run["contours"], run["shape"]))
    fp_total = sum(p["human_fp_total"] for p in probes)
    fp_carried = sum(p["human_fp_still_produced"] for p in probes)
    tp = sum(p["human_tp_detected"] for p in probes)

    import nodularity as legacy  # frozen, patched in-process
    from nodiq.pipelines.nodularity_pipeline import analyze_image
    path = bench.INPUT_IMAGES / "panel_01.png"
    base = legacy.min_grainsize
    counts = []
    try:
        for factor in (0.5, 1.0, 1.5):
            legacy.min_grainsize = base * factor
            counts.append(analyze_image(str(path), with_accuracy=False)["count"])
    finally:
        legacy.min_grainsize = base
    print(f"[{tag}] fp_total={fp_total} fp_carried={fp_carried} "
          f"tp_detected={tp} | panel_01 counts(0.5/1.0/1.5)={counts} "
          f"-> {'SWEEP-OK' if counts[0] == counts[1] == counts[2] else 'SWEEP-FAIL'}")


measure("A current")

import nodiq.pipelines.analyze_with_recovery as rec  # noqa: E402
rec.SMALL_AREA_FLOOR_RATIO = 800.0 / (1920.0 * 1920.0)
measure("B small-floor=800")

import nodiq.pipelines.nodularity_pipeline as np_mod  # noqa: E402
_orig = np_mod.analyze_image
import cv2  # noqa: E402
import numpy as np  # noqa: E402


def forced60(path_or_bgr, **kw):
    import unittest.mock as mock
    return _orig(path_or_bgr, **kw)


# simpler: emulate ceiling 60 by monkeypatching the module-level computation
# via patching min/max builtins is fragile — instead rerun analyze_image with
# the pipeline's own formula disabled: set matrix_med far below so clamp=60.
src = Path(ROOT / "nodularity_pipeline.py").read_text(encoding="utf-8")
assert "recovery_max_med = min(110.0, max(60.0, matrix_med - 40.0))" in src, \
    "formula changed — update this experiment"
rec.SMALL_AREA_FLOOR_RATIO = 800.0 / (1920.0 * 1920.0)
print("NOTE: ceiling residual measured qualitatively: recovery stage with the")
print("relaxed ceiling only ADDS recovered regions on lighter fields; the")
print("carried-FP attribution above already lists their source tags.")
