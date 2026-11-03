# NODIQ-X Ground-Truth Format — Phase 7

![schema](https://img.shields.io/badge/schema-v1.0-4a76a8?style=flat-square&labelColor=263449)
![phase](https://img.shields.io/badge/phase-7-6c63a6?style=flat-square&labelColor=263449)
![rule](https://img.shields.io/badge/model%20contamination-rejected-b5495b?style=flat-square&labelColor=263449)

This document specifies the **expert ground-truth format** used to benchmark real-world nodularity accuracy.

> Ground truth is produced by a human expert looking at the image only. Model predictions are never used to create, complete, or "correct" ground truth. Documents whose provenance is synthetic (C) or model-generated (D) are rejected by the validator and can never enter the primary benchmark.

---

## Contents

1. [Location](#1-location)
2. [Schema (version 1.0)](#2-schema-version-10)
3. [Provenance classes](#3-provenance-classes-phase-7f)
4. [Physical scale](#4-physical-scale-phase-7g)
5. [Reference nodularity](#5-reference-nodularity-phase-7k)
6. [Validation](#6-validation-phase-7c)
7. [Annotation workflow](#7-annotation-workflow-phase-7d)
8. [Benchmark selection](#8-benchmark-selection-phase-7e)
9. [What happens when GT exists](#9-what-happens-when-gt-exists)
10. [Pre-annotation proposals](#10-pre-annotation-proposals-phase-8)

---

## 1. Location
![Engine](https://img.shields.io/badge/-Engine-c08a2e?style=flat-square&labelColor=263449)

One JSON document per image:

```text
third_party/Nodularity/evaluation/ground_truth/<image_id>.json
```

`image_id` is the image file stem (e.g. `panel_01`, `sample2(min_grainsize=0.007)`).

---

## 2. Schema (version 1.0)
![Engine](https://img.shields.io/badge/-Engine-c08a2e?style=flat-square&labelColor=263449)

```jsonc
{
  "schema_version": "1.0",
  "image_id": "panel_01",                    // [A-Za-z0-9_-]+
  "image_file": "third_party/Nodularity/input_images/panel_01.png",  // repo-relative
  "image_width": 277,                        // must match the actual file
  "image_height": 277,

  "annotation": {
    "tool": "tools/annotate_ground_truth.py (OpenCV editor)",
    "expert": "J. Doe (metallographer)",     // required for VALID verdict
    "date": "2026-09-17",
    "version": 1,                            // incremented on each revision
    "provenance_class": "A",                 // A|B|C|D|E — see below
    "independence_note": null                // describe any prior model contact
  },

  "physical_scale": {
    "status": "unavailable",                 // unavailable|metadata|scale_bar|expert
    "microns_per_pixel": null,               // required finite >0 when status != unavailable
    "source": null,                          // microscope model / scale bar / expert measurement
    "notes": null
  },

  "reference": {                             // all optional, never estimated
    "iso_nodularity_pct": null,              // expert-measured reference, if any
    "jis_nodularity_pct": null,
    "jis_class_counts": null,                // e.g. {"2": 3, "3": 10, "4": 5, "5": 12}
    "source": null                           // e.g. "lab report 2026-09-01"
  },

  "particles": [
    {
      "id": "p1",                            // unique within the document
      "geometry": {
        "type": "polygon",                   // polygon | box
        "points": [[x, y], ...]              // NATIVE image pixels; polygon >= 3 points
      },
      "border_touching": false,              // particle intersects the frame edge
      "uncertain": false,                    // expert could not decide (kept, flagged)
      "class": "V",                          // optional ISO form I..VI if the expert knows it
      "notes": null                          // free text / uncertainty
    }
  ],

  "notes": null                              // document-level notes
}
```

---

## 3. Provenance classes (Phase 7F)
![Gate](https://img.shields.io/badge/-Gate-b5495b?style=flat-square&labelColor=263449)

| Class | Meaning | Primary benchmark |
|:---:|---|:---:|
| A | Independent expert GT | ![allowed](https://img.shields.io/badge/-allowed-3e8e82?style=flat-square) |
| B | Independently annotated real image | ![allowed](https://img.shields.io/badge/-allowed-3e8e82?style=flat-square) |
| C | Synthetic | ![rejected](https://img.shields.io/badge/-rejected-b5495b?style=flat-square) validator error |
| D | Model-generated | ![rejected](https://img.shields.io/badge/-rejected-b5495b?style=flat-square) contaminated, validator error |
| E | Unverified | ![warning](https://img.shields.io/badge/-warning-c08a2e?style=flat-square) excluded from primary accuracy claims |

---

## 4. Physical scale (Phase 7G)
![Engine](https://img.shields.io/badge/-Engine-c08a2e?style=flat-square&labelColor=263449)

`microns_per_pixel` is accepted **only** with `status` in `metadata | scale_bar | expert` plus a recorded `source`. When no trustworthy scale exists the status stays `unavailable` and the image is excluded from the ISO 945-4 §6.3 10 µm qualification benchmark. Scales are never invented and the Phase 6 synthetic test calibrations are never reused.

---

## 5. Reference nodularity (Phase 7K)
![Engine](https://img.shields.io/badge/-Engine-c08a2e?style=flat-square&labelColor=263449)

If the expert (or a lab measurement) provides `reference.iso_nodularity_pct` / `jis_nodularity_pct`, those override the geometry-derived values in the comparison. When absent, the benchmark **derives** reference ISO/JIS from the expert polygons using the same verified formulas as the engine (η = 4A/(π·l_m²), η ≥ 0.6, area-weighted ISO; upper-inclusive JIS buckets with 0.3/0.7/0.9/1.0 weights) — this measures segmentation/morphology fidelity against expert geometry rather than agreement with a possibly different expert counting convention.

---

## 6. Validation (Phase 7C)
![Gate](https://img.shields.io/badge/-Gate-b5495b?style=flat-square&labelColor=263449)

```bash
python scripts/tools/annotate_ground_truth.py validate
# or
python -c "from nodiq.services.ground_truth import validate_all; validate_all()"
```

Writes `reports/ground_truth/validation.json`. Verdicts:

| Verdict | Meaning |
|---|---|
| ![VALID](https://img.shields.io/badge/VALID-3e8e82?style=flat-square) | No errors, no warnings, ≥1 particle, provenance + expert recorded |
| ![WARNING](https://img.shields.io/badge/WARNING-c08a2e?style=flat-square) | Usable, with recorded warnings (e.g. overlapping particles = touching/clustered case, provenance E) |
| ![INCOMPLETE](https://img.shields.io/badge/INCOMPLETE-4a76a8?style=flat-square) | Work in progress (missing provenance/expert or no particles) |
| ![INVALID](https://img.shields.io/badge/INVALID-b5495b?style=flat-square) | Unusable (bad geometry, dimension mismatch, duplicate ids, impossible overlap IoU>0.5, bad scale, contaminated provenance, parse error) |

The validator **never repairs** expert annotations — INVALID documents must be fixed by the annotator.

---

## 7. Annotation workflow (Phase 7D)
![Services](https://img.shields.io/badge/-Services-3e8e82?style=flat-square&labelColor=263449)

Interactive editor (OpenCV window, no extra dependencies, native-resolution polygons, small panels auto-upscaled 2× for precision):

```bash
python scripts/tools/annotate_ground_truth.py edit third_party/Nodularity/input_images/panel_01.png
```

**Controls:** left-click adds a vertex · `n` finishes a particle · `z` undoes a vertex · `d` deletes the last particle · `b` toggles border-touching · `u` toggles uncertain · `s` saves · `q` quits. Expert name, provenance class and physical scale are prompted on first save.

**Imports** (externally produced expert annotations only — labelImg, CVAT, Roboflow, Label Studio):

```bash
python scripts/tools/annotate_ground_truth.py import-yolo <image> <labels.txt> --expert NAME
python scripts/tools/annotate_ground_truth.py import-coco <coco.json> --expert NAME
```

> **Independence rule:** the annotation tool never loads or displays model predictions. Importing detector outputs (e.g. `labels_adaptive/`) is only legitimate with provenance D — which the validator rejects for benchmarking. This was verified by an actual import drill during Phase 7.

---

## 8. Benchmark selection (Phase 7E)
![Services](https://img.shields.io/badge/-Services-3e8e82?style=flat-square&labelColor=263449)

The benchmark must span measured variation, not convenience. `selection` guidance and coverage are recorded per image in `reports/ground_truth/dataset_manifest.json` (written by `services/gt_benchmark.py`). Minimum 10 real images (target 20–30) across:

low/high nodularity · sparse/dense graphite · small/large particles · touching/clustered · round/irregular/elongated · contrast/brightness variation · magnification variation · border particles.

---

## 9. What happens when GT exists
![Services](https://img.shields.io/badge/-Services-3e8e82?style=flat-square&labelColor=263449)

`services/gt_benchmark.py` (run via `python -c "from services.gt_benchmark import run_production_benchmark; run_production_benchmark(suffix=\"_v1\")"`) runs the **unchanged** production pipeline on every usable image and writes `reports/ground_truth/`: `summary<suffix>.json`, `per_image<suffix>.csv`, `per_particle<suffix>.csv`, `validation<suffix>.json`, `overlays/<image_id>.png`.

`summary.real_world_accuracy_status` is gated on **provenance**, not just count (Phase 8):

| Status | Condition |
|---|---|
| ![VERIFIED](https://img.shields.io/badge/VERIFIED-3e8e82?style=flat-square) | ≥10 usable images **and** ≥10 with provenance A/B (independent expert truth) |
| ![PARTIALLY VERIFIED](https://img.shields.io/badge/PARTIALLY%20VERIFIED-c08a2e?style=flat-square) | Usable images exist but fewer than 10 carry A/B provenance (exploratory results only; never cited as certified accuracy) |
| ![INSUFFICIENT](https://img.shields.io/badge/INSUFFICIENT_GROUND_TRUTH-b5495b?style=flat-square) | No usable GT documents |

---

## 10. Pre-annotation proposals (Phase 8)
![Gate](https://img.shields.io/badge/-Gate-b5495b?style=flat-square&labelColor=263449)

`tools/build_benchmark_v1.py` builds `reports/ground_truth/benchmark_v1_manifest.json` plus AI **pre-annotation proposals** for the first 10 recommended images. Each proposal is traced by an **independent** median+Otsu reference (never from production output or `labels_adaptive/`), saved as a normal GT document with `provenance_class: "E"`, `expert: "pending-expert-review"`, and a pre-annotation proposal note.

The honesty gate is enforced in code: with 0 expert-reviewed documents the benchmark reports `PARTIALLY VERIFIED` at best, and every E-provenance image is excluded from primary accuracy claims. Proposals become real ground truth only when a human expert opens them in the editor, corrects the ground truth, and upgrades provenance to A/B.

---

*NODIQ-X — Ground-Truth Format, Phase 7.*