#!/usr/bin/env python3
"""
ai/reference.py — local reference knowledge layer (Phase 34).

Project-authored content only: NODIQ-X methodology, ISO/JIS classification
concepts as used by this app, and microstructure terminology. No copyrighted
standard text is reproduced. search_reference() powers the Copilot's
'search_reference' tool.
"""
from pathlib import Path

from nodiq.core.config import REPO_ROOT
ROOT = REPO_ROOT

_TOPICS = {
    "nodularity": "Nodularity is the fraction of graphite that is spheroidal "
    "(nodular). NODIQ-X reports ISO nodularity as the AREA fraction of "
    "particles whose roundness (marumi = area / (max_hull_radius^2 * pi)) is "
    "at least 0.6 (ISO classes V/VI). A JIS-style percentage is also computed "
    "from shape classes 1-5 with weights 0.3/0.7/0.9/1.0.",

    "iso": "In NODIQ-X, ISO classification maps each particle to V/VI "
    "(round/nodular) when roundness >= 0.6, otherwise 'irregular' (classes "
    "I-IV). ISO nodularity = round area / total graphite area * 100. An "
    "in-frame variant excludes particles touching the image border.",

    "jis": "The JIS-style shape classification buckets particles by roundness "
    "into classes 1 (<=0.2, flake-like) to 5 (>0.8, compact). The reported "
    "JIS nodularity = (0.3*n2 + 0.7*n3 + 0.9*n4 + 1.0*n5) / total * 100.",

    "self_check": "Every NODIQ-X analysis self-checks: an independent "
    "reference segmentation (median+Otsu opened blob map, one connected "
    "component = one particle) is compared to the detector output, producing "
    "precision, recall, F1 and counting accuracy per image. This validates "
    "the count against a second, methodologically independent measurement.",

    "quality gate": "The quality gate measures resolution, focus (Laplacian "
    "variance), contrast, illumination uniformity and noise before trusting "
    "measurements. Status PASS/WARNING/REJECT guides interpretation; the "
    "engine always runs, but low quality lowers confidence in shape metrics.",

    "calibration": "Calibration converts pixels to physical units. If a "
    "trusted scale-bar length is available (detected bar + declared physical "
    "length, or a user-entered manual calibration), micrometers-per-pixel is "
    "computed and nodule diameters/areas are reported in µm/µm². Without it, "
    "NODIQ-X reports pixels only and states 'Scale unavailable' — it never "
    "invents µm values.",

    "size filter": "ISO 945-4 clause 6.3 excludes graphite particles with a "
    "maximum Feret diameter below 10 µm from the evaluation — but only when "
    "a valid physical calibration (µm per pixel) exists, because particle "
    "sizes are measured in pixels. When calibration is active the filter is "
    "applied and a size-qualified ISO nodularity is reported; without "
    "calibration the rule is reported as 'not evaluable' and is never "
    "silently skipped or faked.",

    "multi-field": "ISO 945-4 asks for at least 5 fields of view and at "
    "least 500 graphite particles when evaluating nodularity. NODIQ-X "
    "multi-field sessions attach completed single-image analyses as fields, "
    "keep every field independently traceable, and aggregate the "
    "UNDERLYING AREAS for ISO (never an average of field percentages) and "
    "the UNDERLYING CLASS COUNTS for JIS. Sampling status reports the "
    "5-field and 500-particle targets explicitly; fields without valid "
    "calibration or with mismatched scales are excluded from the "
    "standards-aligned aggregate and explained. The workflow provides a "
    "standards-aligned sampling framework; formal conformity depends on "
    "specimen preparation, microscope acquisition, calibration traceability "
    "and field selection.",

    "anomaly": "Anomalies are detected by deterministic rules over measured "
    "data: threshold checks (nodularity below acceptance), batch-relative "
    "z-scores, distribution shifts (irregular fraction, size spread, "
    "roundness spread), border-touching fraction and image quality. Every "
    "anomaly carries explicit reasons — the AI explains them, it never "
    "fabricates them.",

    "spc": "Statistical process control uses mean ± 3-sigma control limits "
    "computed from your history (minimum 8 points). Western-Electric-style "
    "rules flag single points beyond 3 sigma, 2-of-3 beyond 2 sigma on one "
    "side, and runs of 8 on one side of the center line.",

    "detection sources": "Each nodule records how it was detected: frozen "
    "(hybrid detector), merged (partial catch + dark remainder unified), "
    "recovered (missed region added), joined/blobfill (dividing nodules on "
    "one physical blob unified as one), salvaged (particle rescued from a "
    "rejected background blob). This makes every detection explainable.",

    "engine": "The measurement engine runs: hybrid detector -> dark-region "
    "recovery -> dividing-nodule unification -> whole-blob fill -> "
    "particle-anchored consistency gate with salvage -> ISO/JIS metrics -> "
    "independent-reference self-check. It is validated at 100% counting "
    "accuracy on 1000 micrographs.",

    "confidence": "Per-nodule confidence is a documented heuristic: shape "
    "certainty (distance of measured roundness from the 0.6 class boundary) "
    "blended with the image-level self-check F1. It expresses classification "
    "certainty, not a detection probability from a learned model.",
}

_KEYWORDS = {
    "nodularity": ["nodularity", "nodular", "spheroid"],
    "iso": ["iso", "v/vi", "class"],
    "jis": ["jis", "bucket", "shape class"],
    "self_check": ["self-check", "self check", "accuracy", "f1", "precision",
                   "recall"],
    "quality gate": ["quality", "blur", "focus", "resolution"],
    "calibration": ["calibration", "scale", "µm", "um", "micrometer",
                    "physical"],
    "size filter": ["10 µm", "10 um", "10um", "size filter", "size rule",
                    "minimum size", "feret", "compliant", "compliance",
                    "excluded", "certified"],
    "anomaly": ["anomaly", "unusual", "outlier"],
    "spc": ["spc", "control limit", "ucl", "lcl", "western"],
    "detection sources": ["source", "frozen", "recovered", "merged",
                          "joined", "blobfill", "salvaged", "explain"],
    "engine": ["engine", "pipeline", "detector", "how does"],
    "confidence": ["confidence", "certain", "probability"],
}


def search_reference(query, limit=3):
    """Keyword-scored search over local topics. Deterministic, offline."""
    low = (query or "").lower()
    scores = []
    for topic, keywords in _KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in low)
        if score:
            scores.append((score, topic))
    scores.sort(reverse=True)
    results = [{"topic": t, "text": _TOPICS[t]}
               for _, t in scores[:limit]]
    if not results:
        # fall back to doc files present in the repo
        for doc in ("docs/ARCHITECTURE.md",
                    "docs/BASELINE.md"):
            p = ROOT / doc
            if p.exists() and low and low in p.read_text(
                    encoding="utf-8", errors="ignore").lower():
                results.append({"topic": doc, "text": f"See {doc}"})
                break
    return {"results": results} if results else {
        "results": [], "note": "no matching reference topic; available "
        "topics: " + ", ".join(sorted(_TOPICS))}
