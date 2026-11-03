# NODIQ-X API Reference

![version](https://img.shields.io/badge/version-2.0-4a76a8?style=flat-square&labelColor=263449)
![base](https://img.shields.io/badge/base-127.0.0.1%3A8001-3e8e82?style=flat-square&labelColor=263449)
![format](https://img.shields.io/badge/format-JSON-6c63a6?style=flat-square&labelColor=263449)

Base: `http://127.0.0.1:8001` · All bodies JSON unless noted.

**Methods** ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) ![POST](https://img.shields.io/badge/POST-4a76a8?style=flat-square) ![DELETE](https://img.shields.io/badge/DELETE-b5495b?style=flat-square)

---

## Contents

1. [Legacy endpoints](#1-legacy-endpoints-unchanged-contracts-additive-fields-only)
2. [AI](#2-new-ai)
3. [Analysis detail & explainability](#3-new-analysis-detail--explainability)
4. [Quality & calibration](#4-new-quality--calibration)
5. [Multi-field sampling sessions](#5-new-multi-field-sampling-sessions-iso-945-4-framework)
6. [Comparison / batch / SPC / anomalies / decision support](#6-new-comparison--batch--spc--anomalies--decision-support)
7. [Validation lab](#7-new-validation-lab)
8. [Advanced reports](#8-new-advanced-reports)
9. [Feature flags](#9-feature-flags-env)
10. [Security notes](#10-security-notes)

---

## 1. Legacy endpoints (unchanged contracts, additive fields only)
![Legacy](https://img.shields.io/badge/-Legacy-4a76a8?style=flat-square&labelColor=263449)

| Method | Endpoint | Notes |
|---|---|---|
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/health` | + `platform`, `offline_mode` fields |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/dataset` | unchanged (1000 images + batch metrics) |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/dataset/sample` / `file/<name>` | unchanged |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/dataset/analysis/<name>` | unchanged |
| ![POST](https://img.shields.io/badge/POST-4a76a8?style=flat-square) | `/api/analyze` | + `quality`, `calibration`, enriched `nodules[]`, `detections.sources`; still returns both base64 masks; stores full payload for services |
| ![GET/POST/DEL](https://img.shields.io/badge/GET%2FPOST%2FDEL-6c63a6?style=flat-square) | `/api/analyses`, `/api/analyses/<id>` | records now include `quality_score`, `quality_status` |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/analyses/stats` | unchanged |
| ![GET/DEL](https://img.shields.io/badge/GET%2FDEL-6c63a6?style=flat-square) | `/api/reports`, `/api/reports/<id>` | reports now embed `full_report` + `downloads` |
| ![POST](https://img.shields.io/badge/POST-4a76a8?style=flat-square) | `/api/copilot` | same single-message contract works; + optional `session_id`, `history`, `context` |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/dataset/<f>`, SPA serving | unchanged |

---

## 2. New: AI
![AI](https://img.shields.io/badge/-AI-4a76a8?style=flat-square&labelColor=263449)

| Method | Endpoint | Purpose |
|---|---|---|
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/ai/status` | Active provider, chain availability, offline mode |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/copilot/capabilities` | Capability registry + tool names |
| ![POST](https://img.shields.io/badge/POST-4a76a8?style=flat-square) | `/api/copilot` | Multi-turn: `{message, session_id?, history?, context?: {current_analysis_id, current_page}}` → `{reply, provider, session_id, analysis_id, ui_actions[], tool_trace}` |

---

## 3. New: analysis detail & explainability
![Engine](https://img.shields.io/badge/-Engine-c08a2e?style=flat-square&labelColor=263449)

| Method | Endpoint | Purpose |
|---|---|---|
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/analyses/<id>` | History record + full payload |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/analyses/<id>/nodules` | All enriched nodules + source histogram |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/analyses/<id>/nodules/<n>` | Single nodule: geometry, source, confidence, µm when calibrated |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/analyses/<id>/context` | Cached scientific contract |

---

## 4. New: quality & calibration
![Engine](https://img.shields.io/badge/-Engine-c08a2e?style=flat-square&labelColor=263449)

| Method | Endpoint | Purpose |
|---|---|---|
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/quality/<id>` | Stored quality report |
| ![POST](https://img.shields.io/badge/POST-4a76a8?style=flat-square) | `/api/calibration` | `{microns_per_pixel}` direct (validated), `{bar_length_px, bar_length_um}` manual, or `{analysis_id}` auto-detect |

### Calibration & the ISO 945-4 10 µm size rule

Pixels convert to physical units with one canonical direction: `microns = pixels * microns_per_pixel`. A calibration is valid only when `microns_per_pixel` is finite, > 0 (NaN/Infinity/0/negative are rejected — an invalid value means "no calibration", never a guessed scale).

Analysis payloads (`POST /api/analyze`, optional additive body field `microns_per_pixel`) expose per particle:

| Field | Meaning |
|---|---|
| `feret_diameter_px` | The same maximum Feret diameter that feeds the roundness formula (η = 4A/(π·l_m²)), never a second size metric |
| `feret_diameter_um` | px × microns_per_pixel when calibrated, else `null` |
| `size_filter_status` | `included` (feret_um ≥ 10 µm) / `excluded_below_10um` (feret_um < 10 µm) / `not_evaluable` (uncalibrated) |

Plus analysis-level `size_filter` metadata (`available/threshold_um=10/applied/excluded_count/included_count/reason`) and, when calibrated, `iso_size_qualified_pct` — the ISO area ratio over size-qualified, non-border particles (ISO 945-4 clauses 6.3 + 6.4).

**Without calibration nothing is fabricated:** legacy values (`iso_nodularity_pct`, `iso_nodularity_inframe_pct`, `jis_nodularity_pct`) are unchanged, `feret_diameter_um` is `null`, the filter is reported as `not evaluable` with reason `Physical calibration unavailable`, and reports state that the ISO minimum-size criterion could not be evaluated. Results are ISO 945-4-based, not certified.

| Status | Clause | Coverage |
|---|---|---|
| ✅ Verified | §3.2, §3.3, §6.4 | Roundness definition, η ≥ 0.6 spheroidal threshold, area-weighted method, border exclusion (in-frame value) |
| ◐ Conditional | §6.3 | 10 µm minimum Feret diameter rule — applied only with a valid physical calibration |
| — Out of software scope | §6.3 / §6.5 | Specimen preparation, microscope acquisition, calibration traceability, field selection, complete standard text (paywalled) |

---

## 5. New: multi-field sampling sessions (ISO 945-4 framework)
![Engine](https://img.shields.io/badge/-Engine-c08a2e?style=flat-square&labelColor=263449)

ISO 945-4 asks for **≥5 fields of view** and **≥500 graphite particles**. Multi-field sessions keep every field independently stored and traceable, and aggregate the underlying measurements — never averages of per-field percentages.

| Method | Endpoint | Purpose |
|---|---|---|
| ![POST](https://img.shields.io/badge/POST-4a76a8?style=flat-square) | `/api/multifield` | `{label?}` → create session (201, aggregate body) |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/multifield` | List the user's sessions |
| ![POST](https://img.shields.io/badge/POST-4a76a8?style=flat-square) | `/api/multifield/<sid>/fields` | `{analysis_id}` → attach a completed analysis |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/multifield/<sid>` | Full aggregate state + per-field traceability |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/multifield/<sid>/statistics` | Sampling/calibration/ISO/JIS summary |
| ![DELETE](https://img.shields.io/badge/DELETE-b5495b?style=flat-square) | `/api/multifield/<sid>` | Delete session (fields' analyses untouched) |

**Aggregation methodology**

- **ISO (area-based):** `Σ spheroidal_area / Σ eligible_graphite_area × 100` over eligible fields. Each field's areas come from its stored particle rows, in-frame (border-excluded) and size-qualified (its own `<10 µm` filter). The aggregate is exactly reproducible from the exposed `aggregate_spheroidal_area` / `aggregate_graphite_area`.
- **JIS (count-based):** class counts (`jis_bucket` 1–5) are pooled across eligible fields, then weighted once: `(0.3·N₂+0.7·N₃+0.9·N₄+1.0·N₅)/N_all × 100`.
- **Never** an average of per-field percentages (locked by tests).

**Sampling status:** `no_fields` / `below_field_target` (<5 fields) / `below_particle_target` (<500 classified particles) / `meets_field_and_particle_target`. Targets: `FIELD_TARGET = 5`, `PARTICLE_TARGET = 500`. `standards_aligned` is `true` only when both targets are met **and** every field is calibrated **and** the aggregate ISO exists.

**Calibration handling:** each field records the `microns_per_pixel`, source and status of the calibration its own analysis used. Fields without valid calibration are excluded from the standards-aligned aggregate with an explicit reason (the 10 µm rule is not evaluable for them — never faked). Fields with different valid scales are flagged (`consistent_scales: false`); only the largest single-scale group aggregates, because area ratios are not meaningful across scales.

**Traceability:** every aggregate exposes per-field rows: `analysis_id`, `image_name`, `particle_count`, `border_count`, calibrated scale, `size_excluded_count`, `spheroidal_area`, `graphite_area`, per-field `iso_pct`/`jis_pct`, and `eligible` + `exclusion_reason`. Analyses attached to a session surface the session in their Copilot contract (`multifield` key) and in generated reports (`multifield_sampling` section; PDF §8a/8b/8c, CSV rows).

> **Scope statement:** the multi-field workflow provides a standards-aligned sampling framework; formal conformity depends on specimen preparation, microscope acquisition, calibration, field selection, and the complete applicable standard requirements. This is not a certification.

---

## 6. New: comparison / batch / SPC / anomalies / decision support
![Services](https://img.shields.io/badge/-Services-3e8e82?style=flat-square&labelColor=263449)

| Method | Endpoint | Purpose |
|---|---|---|
| ![POST](https://img.shields.io/badge/POST-4a76a8?style=flat-square) | `/api/compare` | `{analysis_a, analysis_b?}` → measured deltas + summary |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/batch/stats` | Mean/median/std, pass-fail rates, distributions |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/batch/distributions` | Nodularity + count histograms |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/spc?metric=nodularity\|count` | Control limits, WE-rule violations, trend |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/batch/<id>/spc` | Compatibility alias for current-user history SPC; `<id>` is retained for API compatibility and is not a batch key |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/anomalies` | History scan, sorted by score, each with `reasons[]` |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/anomalies/<id>` | One analysis anomaly card |
| ![POST](https://img.shields.io/badge/POST-4a76a8?style=flat-square) | `/api/decision-support` | `{analysis_id}` → MEASURED/OBSERVED/INTERPRETATION/RECOMMENDATION |

---

## 7. New: validation lab
![Engine](https://img.shields.io/badge/-Engine-c08a2e?style=flat-square&labelColor=263449)

| Method | Endpoint | Purpose |
|---|---|---|
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/validation` | Internal (1000-image) summary recomputed from CSV |
| ![POST](https://img.shields.io/badge/POST-4a76a8?style=flat-square) | `/api/validation/run` | `{kind: blind\|synthetic\|internal, n?, seed?}` — sources never merged |

---

## 8. New: advanced reports
![Services](https://img.shields.io/badge/-Services-3e8e82?style=flat-square&labelColor=263449)

| Method | Endpoint | Purpose |
|---|---|---|
| ![POST](https://img.shields.io/badge/POST-4a76a8?style=flat-square) | `/api/reports/generate` | Full engineering report (14 sections) + `downloads` map |
| ![POST](https://img.shields.io/badge/POST-4a76a8?style=flat-square) | `/api/reports/ai-summary` | `{analysis_id}` → AI interpretation only |
| ![GET](https://img.shields.io/badge/GET-3e8e82?style=flat-square) | `/api/reports/<id>/download?format=pdf\|csv\|json` | File download |

---

## 9. Feature flags (env)
![Services](https://img.shields.io/badge/-Services-3e8e82?style=flat-square&labelColor=263449)

`ENABLE_COPILOT`, `ENABLE_QUALITY_GATE`, `ENABLE_CALIBRATION`, `ENABLE_BATCH_ANALYTICS`, `ENABLE_SPC`, `ENABLE_ANOMALY_DETECTION`, `ENABLE_AI_REPORTS`, `OFFLINE_MODE` — all default on; disabled features return HTTP 503 with a clear message.

---

## 10. Security notes
![Security](https://img.shields.io/badge/-Security-b5495b?style=flat-square&labelColor=263449)

- Upload cap 25 MB; dataset filenames regex-validated
- Tool args allowlisted and sanitized
- No shell/SQL/arbitrary execution anywhere in the AI stack
- API keys read from env/.env only (never logged, never hard-coded)

---

*NODIQ-X — API Reference, v2.0.*