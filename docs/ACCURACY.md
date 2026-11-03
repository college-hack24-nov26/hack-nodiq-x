# NODIQ-X Accuracy Benchmark — Phase 6

**Status: `GROUND_TRUTH_UNAVAILABLE` — real-world nodularity accuracy is not
yet scientifically established.** This document describes what was measured,
what the measured evidence shows, and exactly what is needed to establish
accuracy. No accuracy percentages for real micrographs are claimed anywhere
in this document or in the machine-readable outputs, because no independent
expert ground truth exists in the repository.

Regenerate all outputs at any time with:

```bash
python -c "from services.accuracy_bench import write_reports; write_reports()"
```

Outputs land in `reports/accuracy/` (`summary.json`, `per_image.csv`,
`per_particle.csv`, `error_analysis.json`, `threshold_analysis.csv`,
`overlays/*.png`).

---

## 1. Current production pipeline (audited)

```text
image loading      nodularity_pipeline.load_grayscale / load_with_source
                   (any input -> resize to 1920 px width, LINEAR)
quality gate       nodularity_pipeline.evaluate_microstructure_validity
                   (services/quality.py checks)
detector           CLASSICAL CV HYBRID — no Detectron2/ML checkpoint exists
                   in the repository (find for *.pth/*.pt returned nothing;
                   the production entry point is detect_frozen() in
                   analyze_with_recovery.py):
                     original detection  nodularity_adaptive.original_detection
                                         (median + Otsu + size floor)
                     robust detection    nodularity_adaptive.robust_detection
                                         (background subtraction + Otsu +
                                         morphology)
                     candidate merging   merge_detection_candidates
                     refinement          refine_suspicious_candidates
                     validation          validate_candidates (evidence-based)
particle assembly  recover_and_merge / consolidate_joined / fill_owned_blobs
consistency gate   blob-map consistency + AREA_FLOOR_RATIO
                   (800 px^2 at 1920 width) in analyze_image
morphology         area (contourArea), maximum Feret = max hull point-pair
                   distance, roundness η = 4A/(π·l_m²)  [ISO 945-4:2019 §3.2]
classification     spheroidal if η >= 0.6 [ISO 945-4 §3.3]
                   JIS buckets upper-inclusive 0.2/0.4/0.7/0.8
size filter        <10 µm exclusion ONLY with valid physical calibration
                   (services/calibration.py); uncalibrated images report
                   not_evaluable — never a fabricated scale
ISO nodularity     Σ area(η>=0.6) / Σ area(all) × 100          (headline)
ISO in-frame       same with border-touching particles removed from
                   BOTH terms                                  (standards-aligned)
JIS nodularity     (0.3·N2 + 0.7·N3 + 0.9·N4 + 1.0·N5)/N_all × 100
                   (count-weighted, all particles)
aggregation        multi-field: Σ spheroidal area / Σ eligible graphite area
                   (area-based, never percentage-averaged) — services/multifield.py
reports            report_builder.py (PDF/CSV/JSON)
```

**Important correction to the Phase 6 brief:** the brief named a Detectron2
checkpoint `models/model_0000999.pth`. No such file (and no `models/`
directory) exists; NODIQ-X production has always been the classical-CV hybrid
above. No ML checkpoint was evaluated because none exists to evaluate.

---

## 2. Dataset and ground-truth classification

| Category | Content | Verdict |
|---|---|---|
| A — independent expert GT | `third_party/Nodularity/evaluation/ground_truth/` | **EMPTY** (README.txt only) |
| B — independently annotated | `review_workflow/output/sample_review.csv` | 377 human-labeled **detector candidates** on 4 dense panel images: **5 true_nodule, 120 false_positive, 181 skip, 3 uncertain, 68 unlabeled** |
| C — synthetic | `services/accuracy_bench.py` | 6 deterministic cases with **exact analytic ground truth** |
| D — model-generated | `labels_adaptive/`, `annotated_images_adaptive/`, `detector_outputs/` | outputs of the frozen detector — **never usable as GT** |
| E — unverified images | `input_images/` (60), dataset (1000), 3 native JPG samples | real micrographs, **no annotations** |
| F — unavailable | physical scale (µm/px) | **no calibrated image exists anywhere in the repo** |

**Conclusion: CASE C.** The only human annotation (category B) is too sparse
on the positive class (5 TP) for recall or nodularity accuracy, and it labels
*legacy-detector candidates*, not free-form expert masks. It is used here as
a one-directional false-positive probe only.

---

## 3. What was actually measured (and why the metrics below are null)

```text
detection precision / recall / F1 : NULL   — needs expert GT (category A)
mask mean/median IoU              : NULL   — needs expert masks
mask mean/median area error       : NULL   — needs expert masks
nodularity MAE / RMSE / bias      : NULL   — needs expert-measured reference
                                             nodularity
```

Nothing was fabricated. `summary.json` carries the same nulls with the
explicit blocker text.

### 3.1 Synthetic known-geometry validation (mechanics, not real accuracy)

| case | GT | predicted | result |
|---|---|---|---|
| clean_round (8 circles r=45) | ISO 100, JIS 100 | ISO 100.0, JIS 100.0 | 8/8 matched, 0 FP |
| mixed_round_irregular | ISO 58.82, JIS 65 | ISO 58.3, JIS 65.0 | 8/8 matched, ISO err 0.48 pp |
| size_gradient (r=8..50) | 5 particles | 4 particles | r=8 missed; ISO exact 100 |
| touching_pair (2 overlapping circles) | 2 particles | **1 merged particle** | **documented failure mode** — merge turns two round particles into one irregular (ISO error 100 pp on this case) |
| border_case | 4 particles (1 border) | 4 detected, border=1 | in-frame ISO 100.0 exact |
| low_contrast (matrix 200 vs particle 150) | 5 particles | 5 particles | ISO/JIS exact |

Aggregates: 30 TP / 0 FP / 2 FN across 6 cases; mean count error 0.33;
mean ISO error dominated by the touching-pair merge case.

### 3.2 Human-review probe (precision evidence only)

Of the 120 candidates a human labeled **false positive** (legacy validator
outputs, 4 dense panel images), the current production pipeline still
produces only **4** (3.3% carryover → **116 eliminated**). Of the 5 human
**true nodules**, **0** appear in production output.

### 3.3 Root cause of the 5 missing TPs (traced, not guessed)

All 5 human TPs are **small** particles (areas 91–277 px² at 1920 scale).
Sweeps show they are excluded **upstream** of both production knobs:

* `min_grainsize` sweep (0.5×–1.5×): count and ISO **unchanged** on reference
  images — the parameter is not the operative selectivity.
* `AREA_FLOOR_RATIO` sweep (down to a 40 px floor): count **still unchanged**
  — the TPs are rejected earlier, in the adaptive validator/refinement chain
  (`validate_candidates`, evidence-score rules) and the consistency gate.

The measured review data explains the trade-off rather than condemning it:
among reviewed small candidates, 120/125 were false positives (per-tier FP
rates: small+robust 62.8%, small+original 44.9%, small+both 38.6% —
`review_workflow/output/analysis_report.txt`). The production validator
chooses high precision at the cost of these 5 tiny TPs. **No production
constant was changed** — with 5 positive labels this trade-off cannot be
re-tuned scientifically.

### 3.4 Threshold / parameter sensitivity (measurement only)

Recorded in `reports/accuracy/threshold_analysis.csv`:

| sweep | range | effect |
|---|---|---|
| `min_grainsize` ×0.5–1.5 | 0.00355–0.01065 | none on count/ISO/JIS (reference images) |
| `AREA_FLOOR_RATIO` ×0.25–2 | 40–1600 px floor | none until ×2 (−1 particle, ISO +0.5 pp); smalls never enter |

Interpretation: nodularity output is **robust (insensitive)** to these two
size knobs in the measured range; the operative precision filter is the
adaptive evidence validation, which is not a single tunable threshold.

---

## 4. Border handling, calibration, morphology (audited)

* **Border handling** verified by synthetic `border_case`: border particle
  excluded from `iso_inframe_pct` (standards-aligned value), retained in the
  headline `iso_pct` for robustness — matches ISO 945-4 §6.4.
* **Calibration**: no image in the benchmark carries a physical scale; the
  10 µm exclusion correctly reports `not_evaluable` everywhere and was never
  fabricated. `pixel_scale_um_per_px` stays null in every GT record.
* **Morphology**: η = 4A/(π·l_m²) locked by existing regression tests
  (`test_nodularity_audit.py`), including the Feret-diameter equivalence.

---

## 5. Error buckets (mechanisms, from the evidence actually collected)

1. **Touch/merge segmentation** (measured, synthetic): overlapping particles
   merge into one elongated particle → both are lost from the round class.
   Largest single measured ISO error mechanism.
2. **Sub-resolution smalls** (measured, upstream rejection): particles under
   ~800 px² at 1920 are rejected by the validation chain. On the human-labeled
   dense panels this removed 116/120 human FPs **and** all 5 human TPs —
   a measured precision/recall trade, not a bug.
3. **Low contrast**: none measured — the mildest-contrast synthetic case
   (200 vs 150 gray) scored exactly.
4. **Border particles**: correctly separated; no error contribution measured.
5. **Calibration / 10 µm**: correctly unevaluable without a scale; no
   contribution.

---

## 6. Final decision (Phase 27)

**CASE C — Nodularity accuracy remains unverified.**

The evaluation framework, instance matching, synthetic analytic benchmark,
sensitivity sweeps, and machine-readable outputs are all in place and tested
(17 new tests). The moment category-A ground truth appears in
`third_party/Nodularity/evaluation/ground_truth/` (YOLO boxes, class 0, one file per
image) — and ideally reference ISO/JIS values plus µm/px scales — the same
framework produces the Phase-6 acceptance metrics automatically.

### Exactly what is required to unblock

1. Expert YOLO boxes or instance masks for **≥10 real micrographs** at
   `third_party/Nodularity/evaluation/ground_truth/<stem>.txt`
   (class 0 = graphite nodule, normalized coordinates).
2. Expert-measured reference ISO and JIS nodularity for those images.
3. Physical scale (µm/px) per image, to evaluate the ISO 945-4 §6.3 10 µm rule.
4. Fields of view from the same specimen (≥5 fields) if multi-field
   standards-aligned sampling is to be validated.

### Recommendation (evidence-based)

* **Do not retrain / re-tune** — no ground truth exists to optimize against;
  the 5-TP review sample cannot justify threshold changes.
* **Do obtain category-A ground truth** (the unblock list above). Priority
  annotation effort: small particles (91–277 px²) and touching/clustered
  particles, the two measured failure modes.
* **Optionally**, a dedicated review round on *small* candidates only
  (the `skip`-labeled 181 include unknown TP/FP mix) would sharpen the
  precision/recall trade-off evidence before any tuning decision.

---

## 7. Benchmark v1 — AI pre-annotation proposals (Phase 8, EXPLORATORY ONLY)

**Status: `PARTIALLY VERIFIED` — exploratory, never certified accuracy.**
Phase 8 produced AI **pre-annotation proposals** for the first 10 recommended
real images (`scripts/tools/build_benchmark_v1.py` →
`third_party/Nodularity/evaluation/ground_truth/*.json`, provenance **E**,
`expert: pending-expert-review`).  Every number below is measured against
these *unverified* proposals; none may be cited as real-world accuracy until
a human expert reviews and upgrades them to A/B provenance.

Regenerate with:

```bash
python scripts/tools/build_benchmark_v1.py --validate
python -c "from nodiq.services.gt_benchmark import run_production_benchmark; run_production_benchmark(suffix='_v1')"
```

Outputs: `reports/ground_truth/summary_v1.json`, `per_image_v1.csv`,
`per_particle_v1.csv`, `validation_v1.json`, `overlays/*.png`.

### Headline (proposal-relative, 10 images, 366 proposed particles)

| metric @ IoU 0.5 | value |
|---|---|
| precision / recall / F1 | 0.53 / 0.77 / 0.61 |
| F1 @ IoU 0.75 | 0.49 |
| mean IoU (matched) | 0.77 (0.86 @ 0.75) |
| ISO nodularity MAE | 9.8 pp (bias −9.8 pp) |
| JIS nodularity MAE | 17.2 pp |
| mean relative mask-area error | 29% |

The ISO bias is **negative**: measured against the proposal geometry the
engine under-reports nodularity — dominated by graphite misclassification
(merged/irregular particles) rather than missed particles.

### Measured failure modes (from error attribution)

1. **Touch/merge segmentation** — again the dominant mechanism (e.g.
   `panel_18`: 7 merge groups; `panel_06`: one GT particle split into 17
   predictions).  Unchanged from the synthetic-benchmark conclusion.
2. **Boundary precision on dense images** — F1 collapses on dense panels
   (0.35 on `1000270578_panel_14`, 0.18 on `panel_18`) while the cleanest
   images reach 0.89–0.96: boundary mismatch and merges, not misses, drive
   the gap.
3. **False positives on textured matrix** — 16–74 FPs/image on the denser
   panels (proposal-relative; some may be proposal geometry errors — expert
   review decides).
4. **Small-particle recall** — measured per size bucket with materiality
   (share of GT graphite area): small particles sit at ~0.71 mean recall but
   carry only ~2% of graphite area; medium ~0.79 recall / ~26% of area.
   The small-particle study is in `summary_v1.small_particle_study`.
5. **ISO 10 µm qualification** — not evaluable on any image (no physical
   scale exists); reported as nulls, never fabricated.

### What expert review must fix first

Dense, clustered panels (`1000270578_panel_14/16`, `panel_18`, `panel_06`)
contribute nearly all errors and are exactly where the proposals are least
reliable (touching-particle split heuristics).  Reviewing these four first
maximizes information per hour; sparse panels already agree at F1 ≥ 0.75.
