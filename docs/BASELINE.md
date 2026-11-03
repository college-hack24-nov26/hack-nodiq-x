# NODIQ-X Baseline (verified live, pre-upgrade)

![date](https://img.shields.io/badge/date-2026--09--13-4a76a8?style=flat-square&labelColor=263449)
![checkpoint](https://img.shields.io/badge/checkpoint-46c9e88-6c63a6?style=flat-square&labelColor=263449)
![server](https://img.shields.io/badge/server-127.0.0.1%3A8001-3e8e82?style=flat-square&labelColor=263449)

Date: 2026-09-13 · checkpoint `46c9e88` · server running on `127.0.0.1:8001`

---

## Contents

1. [Validated batch](#1-validated-batch-1000-images-definitive-run--untouched-on-disk)
2. [Live API regression baseline](#2-live-api-regression-baseline-this-machine-this-run)
3. [Regression gate for the upgrade](#3-regression-gate-for-the-upgrade)

---

## 1. Validated batch (1000 images, definitive run — untouched on disk)
![Engine](https://img.shields.io/badge/-Engine-c08a2e?style=flat-square&labelColor=263449)

From `nodularity_1000_fixed/summary_1000_fixed.md`:

| Metric | Value |
|---|---|
| Images analyzed | 1000 (0 errors) |
| Counting accuracy | **100.00% on every image** (mean 100.00, min 100) |
| Precision / Recall / F1 | 100.00% / 100.00% / 100.00 on every image |
| Double counts | 0 |
| Model nodule count | mean 45.42, median 42 (min 5, max 139) |
| ISO nodularity | mean 49.16% |
| ISO nodularity (in-frame) | mean 55.94% |
| JIS nodularity | mean 75.95% |

Detection-source mix across the batch: frozen ≈ 40.2/image, recovered ≈ 4.1, unified (joined/blobfill) ≈ 3.4 — i.e. every image demonstrates explainability.

---

## 2. Live API regression baseline (this machine, this run)
![Gateway](https://img.shields.io/badge/-Gateway-4a76a8?style=flat-square&labelColor=263449)

`GET /api/health` →
```json
{"status":"ok","engine":"Nodularity Engine v4.2.1 (validated 1000/1000)","dataset_images":1000}
```

Fresh analyses through `/api/dataset/analysis/<name>` reproduce the validated batch exactly (count, ISO, F1 to the decimal):

| Image | Count | ISO % | F1 % | Time | vs. batch |
|---|:---:|:---:|:---:|:---:|:---:|
| `micrograph_0004.png` | 35 | 53.06 | 100.00 | 7.2 s | ![CONSISTENT](https://img.shields.io/badge/-CONSISTENT-3e8e82?style=flat-square) |
| `micrograph_0500.png` | 20 | 50.38 | 100.00 | 3.6 s | ![CONSISTENT](https://img.shields.io/badge/-CONSISTENT-3e8e82?style=flat-square) |
| `micrograph_0993.png` | 51 | 50.34 | 100.00 | 10.9 s | ![CONSISTENT](https://img.shields.io/badge/-CONSISTENT-3e8e82?style=flat-square) |

*(First-call times include worker warm-up; steady-state is ~2 s/image as measured in the batch run.)*

---

## 3. Regression gate for the upgrade
![Gate](https://img.shields.io/badge/-Gate-b5495b?style=flat-square&labelColor=263449)

Any change must preserve, through the public API:

| # | Requirement |
|:---:|---|
| 1 | `count`, `iso_pct`, `jis_pct`, per-nodule `rows` and `self_check` identical for a fixed input (deterministic engine — same bytes → same numbers) |
| 2 | The 1000-image validation artifacts (`summary_1000_fixed.{csv,md}`) untouched |
| 3 | All existing endpoints listed in `ARCHITECTURE.md` keep their request/response contracts (additive fields only) |
| 4 | Frontend builds clean (`npm run build`) and all pages render |

> Baseline recorded; upgrade work may now begin.

---

*NODIQ-X — Baseline snapshot, checkpoint `46c9e88`.*