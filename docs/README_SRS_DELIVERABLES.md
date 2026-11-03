# NODIQ-X — SRS & System Architecture Deliverables

Created 2026-10-01 · Version 1.6.0 · Factual source of truth: [`NODIQ-X_PROJECT_INFO.md`](NODIQ-X_PROJECT_INFO.md)

## Files

| File | Purpose | Notes |
|---|---|---|
| [`NODIQ-X_SRS.md`](NODIQ-X_SRS.md) | Software Requirements Specification (markdown master) | 13 sections; FR-001…FR-041, NFR-001…NFR-014, SEC-001…SEC-007, CAM-001…CAM-008, UC-01…UC-13, AC-01…AC-15, FE-01…FE-08; statuses [IMPLEMENTED] / [PARTIALLY IMPLEMENTED] / [PLANNED] |
| [`NODIQ-X_SRS.docx`](NODIQ-X_SRS.docx) | Academic submission version (Word) | Title page, TOC field (right-click → Update Field), 13 numbered sections, 35 tables, architecture figure (Figure 1, §2→§3 boundary), header + "Page X of Y" footer, A4, Calibri |
| [`NODIQ-X_System_Architecture.png`](NODIQ-X_System_Architecture.png) | Architecture diagram (raster) | 3224 × 2502 px (≈300 dpi A4 landscape) — for reports/slides |
| [`NODIQ-X_System_Architecture.svg`](NODIQ-X_System_Architecture.svg) | Architecture diagram (vector) | Scales cleanly to A4/A3 print |
| [`NODIQ-X_System_Architecture.md`](NODIQ-X_System_Architecture.md) | Architecture in text/ASCII + layer tables | Includes the single-funnel flow and layer reference |
| [`NODIQ-X_System_Architecture.drawio`](NODIQ-X_System_Architecture.drawio) | Editable diagram (draw.io / diagrams.net) | Uncompressed mxGraph XML; open and edit freely |

## Key facts encoded in these documents

- **Two image input sources — one pipeline.** Normal upload (file/dataset) and microscope
  camera capture both enter the same `POST /api/analyze → nodularity_pipeline.py` flow; there
  is **no second analysis pipeline**. Capture↔upload byte-identical parity verified (Phase 4
  and Phase 5 runs).
- **Route terminology (verified):** 68 Flask route decorators (41 GET / 23 POST / 4 DELETE) →
  61 unique URL paths = **58 REST API endpoint paths** + 3 non-API paths (SPA root, SPA
  fallback, `/dataset/<file>`); 27 React Router routes; 3 camera-agent endpoints
  (`/status`, `/preview`, `/capture`). The older "49 endpoints" figure in
  `docs/ARCHITECTURE.md` reflects endpoint groups at that document's writing time.
- **Camera:** MATRIX VISION mvBlueFOX-ML/IGC205C, S/N 29605128; agent 127.0.0.1:8765; capture
  2592×1944 PNG; preview ≈1024×768 JPEG at ≈1 Hz; 15 s idle-close; typed errors
  (`409 camera_busy`, `503 camera_not_found`/`sdk_unavailable`, `504 capture_failed`).
- **Accuracy honesty:** accuracy/confidence values are the **engine self-check (consistency)**;
  **no independent metallurgical ground truth has been established** — no certified accuracy is
  claimed.
- **Validation baseline:** 298/298 pytest (56 pinning + 5 camera-state), oxlint 0 errors,
  `npm run build` PASS.

## Regenerating

```bash
# diagram (SVG + PNG + drawio from one shared layout)
python .freebuff/srs_build/gen_diagram.py

# DOCX from the markdown master (uses python-docx installed at .freebuff/pylibs)
python .freebuff/srs_build/gen_docx.py
```

Edit `docs/NODIQ-X_SRS.md` (the master) and re-run the DOCX generator; edit the layout in
`gen_diagram.py` and re-run for all three diagram formats. The preview wrapper
(`.freebuff/srs_build/preview.html`) embeds the PNG for in-app preview only and is not a
deliverable.
