#!/usr/bin/env python3
"""
services/ground_truth.py — expert ground-truth schema, parser and validator
(Phase 7).

Scientific contract:

  * Expert annotations are INDEPENDENT of model predictions.  Nothing in
    this module reads production output for annotation purposes, never
    repairs/edits expert geometry, and never invents particles.
  * Physical scale is recorded only when a trustworthy source exists
    (microscope metadata / scale bar / documented acquisition / expert
    measurement).  Anything else stays "unavailable" — never fabricated.
  * Provenance classes follow the Phase 6 scheme:
      A  independent expert GT          B  independently annotated real image
      C  synthetic                      D  model-generated (contaminated
                                           for benchmark use — excluded)
      E  unverified
  * The validator classifies each image VALID / INVALID / WARNING /
    INCOMPLETE and writes machine-readable output; it never silently
    repairs annotations.

On-disk format (one JSON per image):

    evaluation/ground_truth/<image_id>.json

Full schema documentation: docs/GROUND_TRUTH.md
"""
import json
import math
import re
from datetime import date
from pathlib import Path

import cv2
import numpy as np

from nodiq.core.config import REPO_ROOT, THIRD_PARTY_NODULARITY, OUTPUTS_DIR

PROJECT_ROOT = REPO_ROOT
_nod_main = THIRD_PARTY_NODULARITY
GT_DIR = _nod_main / "evaluation" / "ground_truth"
VALIDATION_REPORT = OUTPUTS_DIR / "ground_truth" / "validation.json"

SCHEMA_VERSION = "1.0"
PROVENANCE_CLASSES = ("A", "B", "C", "D", "E")
SCALE_STATUSES = ("unavailable", "metadata", "scale_bar", "expert")

_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


# ---------------------------------------------------------------------------
# schema helpers
# ---------------------------------------------------------------------------
def empty_ground_truth(image_id, image_file, width, height):
    """An empty, schema-conformant GT document for one image."""
    return {
        "schema_version": SCHEMA_VERSION,
        "image_id": image_id,
        "image_file": image_file,
        "image_width": int(width),
        "image_height": int(height),
        "annotation": {
            "tool": None,
            "expert": None,
            "date": date.today().isoformat(),
            "version": 1,
            "provenance_class": None,
            "independence_note": None,
        },
        "physical_scale": {
            "status": "unavailable",
            "microns_per_pixel": None,
            "source": None,
            "notes": None,
        },
        "reference": {
            "iso_nodularity_pct": None,
            "jis_nodularity_pct": None,
            "jis_class_counts": None,
            "source": None,
        },
        "particles": [],
        "notes": None,
    }


def load_ground_truth(path):
    """Parse one GT JSON file.  Raises ValueError on unreadable/invalid
    JSON structure (the validator turns this into an INVALID verdict)."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("GT document must be a JSON object")
    if "image_id" not in data or "particles" not in data:
        raise ValueError("GT document missing required keys "
                         "(image_id, particles)")
    return data


def load_all_ground_truth(gt_dir=GT_DIR):
    """Load every <image_id>.json in the GT directory (README ignored)."""
    gt_dir = Path(gt_dir)
    out = {}
    if not gt_dir.is_dir():
        return out
    for p in sorted(gt_dir.glob("*.json")):
        try:
            out[p.stem] = load_ground_truth(p)
        except (ValueError, json.JSONDecodeError):
            out[p.stem] = None          # parse failure surfaced by validator
    return out


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------
def particle_mask(particle, shape):
    """Rasterize one particle annotation to a mask at the given shape.
    Supports polygon (>=3 points) and box geometry.  Returns None for
    unusable geometry (caller counts this as an error, never repairs)."""
    geo = particle.get("geometry") or {}
    gtype = geo.get("type")
    pts = geo.get("points")
    if gtype not in ("polygon", "box") or not isinstance(pts, list) or \
            len(pts) < 2:
        return None
    if gtype == "polygon" and len(pts) < 3:
        return None
    arr = np.asarray(pts, dtype=np.float64)
    if arr.shape[1] != 2 or not np.isfinite(arr).all():
        return None
    m = np.zeros(shape[:2], np.uint8)
    if gtype == "polygon":
        cv2.fillPoly(m, [np.round(arr).astype(np.int32)], 255)
    else:
        x0, y0 = arr.min(axis=0)
        x1, y1 = arr.max(axis=0)
        cv2.rectangle(m, (int(round(x0)), int(round(y0))),
                      (int(round(x1)), int(round(y1))), 255, -1)
    return m if m.any() else None


def gt_particles_to_masks(gt, shape, scale=1.0):
    """Rasterize all particles of a GT document; rescaling coordinates by
    `scale` (e.g. 1920/src_width to compare with production contours)."""
    items = []
    for p in gt.get("particles", []):
        pts = (p.get("geometry") or {}).get("points")
        if pts is not None:
            scaled = [[x * scale, y * scale] for x, y in pts]
            p2 = {"geometry": {"type": p["geometry"]["type"],
                               "points": scaled}}
        else:
            p2 = p
        m = particle_mask(p2, shape)
        if m is not None:
            items.append({"mask": m, "particle": p})
    return items


def gt_nodularity_from_geometry(gt, roundness_threshold=0.6):
    """Derive reference ISO/JIS from the expert polygons themselves, using
    the same verified definitions as the engine (η = 4A/(π·l_m²),
    area-weighted ISO; count-weighted JIS buckets).  Returns None if no
    usable particle geometry exists."""
    from nodiq.pipelines.analyze_with_recovery import jis_bucket
    rows = []
    h = gt.get("image_height")
    w = gt.get("image_width")
    if not h or not w:
        return None
    for p in gt.get("particles", []):
        m = particle_mask(p, (h, w))
        if m is None:
            continue
        area = float((m > 0).sum())
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        cnt = max(cnts, key=cv2.contourArea)
        hull = cv2.convexHull(cnt)
        # maximum Feret = max point-pair distance on the hull (same as the
        # engine's legacy.get_graphite_length semantics)
        pts = hull.reshape(-1, 2).astype(np.float64)
        if len(pts) >= 2:
            d2 = ((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)
            l_m = float(np.sqrt(d2.max()))
        else:
            l_m = math.sqrt(4 * area / math.pi)
        eta = 4 * area / (math.pi * l_m ** 2) if l_m > 0 else 0.0
        per = cv2.arcLength(cnt, True)
        circ = (4 * math.pi * area / (per ** 2)) if per > 0 else 0.0
        hull_area = cv2.contourArea(hull)
        sol = min(1.0, area / hull_area) if hull_area > 0 else 0.0
        rows.append({"area": area, "roundness": eta, "circularity": circ,
                     "solidity": sol,
                     "touches_border": bool(p.get("border_touching"))})
    if not rows:
        return None
    area_total = sum(r["area"] for r in rows)
    area_round = sum(r["area"] for r in rows
                     if r["roundness"] >= roundness_threshold)
    iso = area_round / area_total * 100 if area_total else None
    counts = [0, 0, 0, 0, 0]
    for r in rows:
        counts[jis_bucket(r["roundness"]) - 1] += 1
    n = len(rows)
    jis = ((0.3 * counts[1] + 0.7 * counts[2] + 0.9 * counts[3] +
            counts[4]) / n * 100) if n else None
    return {"n_particles": n, "iso_pct": iso, "jis_pct": jis,
            "jis_class_counts": counts,
            "border_count": sum(1 for r in rows if r["touches_border"]),
            "mean_roundness": (sum(r["roundness"] for r in rows) / n),
            "mean_circularity": (sum(r["circularity"] for r in rows) / n),
            "mean_solidity": (sum(r["solidity"] for r in rows) / n)}


# ---------------------------------------------------------------------------
# validation (Phase 7C) — never repairs, only classifies
# ---------------------------------------------------------------------------
def validate_ground_truth(gt, gt_dir=GT_DIR):
    """Deterministic validation of one GT document.

    Returns {"image_id", "verdict": VALID|INVALID|WARNING|INCOMPLETE,
    "errors": [...], "warnings": [...], "info": {...}}."""
    image_id = gt.get("image_id") if isinstance(gt, dict) else Path(str(gt_dir)).stem
    errors, warnings = [], []

    if gt is None:
        return {"image_id": None, "verdict": "INVALID",
                "errors": ["unparseable or missing JSON document"],
                "warnings": [], "info": {}}

    image_id = gt.get("image_id")
    if not image_id or not isinstance(image_id, str) or not _ID_RE.match(image_id):
        errors.append("image_id missing or contains invalid characters")

    # image exists + dimensions match
    img_file = gt.get("image_file")
    img = cv2.imread(str(PROJECT_ROOT / img_file)) if img_file else None
    if img is None:
        errors.append(f"image file missing or unreadable: {img_file}")
        shape = None
    else:
        shape = img.shape[:2]
        if gt.get("image_width") != shape[1] or \
                gt.get("image_height") != shape[0]:
            errors.append(
                f"dimension mismatch: document says "
                f"{gt.get('image_width')}x{gt.get('image_height')}, file is "
                f"{shape[1]}x{shape[0]}")

    # provenance (missing provenance -> INCOMPLETE, wrong provenance ->
    # INVALID: model-generated/synthetic contamination must never benchmark)
    prov = (gt.get("annotation") or {}).get("provenance_class")
    incomplete = False
    if prov not in PROVENANCE_CLASSES:
        warnings.append(f"provenance_class not recorded (must be one of "
                        f"{list(PROVENANCE_CLASSES)})")
        incomplete = True
    elif prov in ("C", "D"):
        errors.append(
            f"provenance class {prov} is not allowed in the primary "
            f"benchmark (synthetic or model-generated = contaminated)")
    elif prov == "E":
        warnings.append("provenance class E (unverified) — excluded from "
                        "primary accuracy claims")
    if not (gt.get("annotation") or {}).get("expert"):
        warnings.append("annotation.expert not recorded")
        incomplete = True
    elif "pending" in str((gt.get("annotation") or {}).get("expert")).lower():
        warnings.append("annotation.expert is a pending pre-annotation "
                        "placeholder — NOT yet reviewed by a human expert")

    # physical scale
    scale = gt.get("physical_scale") or {}
    status = scale.get("status", "unavailable")
    umpp = scale.get("microns_per_pixel")
    if status not in SCALE_STATUSES:
        errors.append(f"physical_scale.status invalid: {status!r}")
    if status != "unavailable":
        if not isinstance(umpp, (int, float)) or \
                not math.isfinite(umpp) or umpp <= 0:
            errors.append(
                "physical_scale.microns_per_pixel must be finite and > 0 "
                "when status is not 'unavailable'")
        elif not scale.get("source"):
            warnings.append("scale provided without a recorded source")

    # particles
    particles = gt.get("particles", [])
    if not particles:
        warnings.append("no particles annotated (incomplete for benchmark)")
    ids = set()
    masks = []
    for i, p in enumerate(particles):
        pid = p.get("id")
        if pid is None:
            errors.append(f"particle #{i}: missing id")
        elif pid in ids:
            errors.append(f"duplicate particle id: {pid}")
        ids.add(pid)
        m = particle_mask(p, shape) if shape else None
        if m is None:
            errors.append(
                f"particle #{i}: invalid or empty geometry "
                f"(needs polygon>=3 pts or box, finite in-bounds coords)")
            masks.append(None)
            continue
        masks.append(m)
        ys, xs = np.nonzero(m > 0)
        if shape and (xs.min() < 0 or ys.min() < 0 or
                      xs.max() >= shape[1] or ys.max() >= shape[0]):
            errors.append(f"particle #{i}: coordinates outside image bounds")

    # overlapping annotations (pairwise IoU on usable masks)
    if shape:
        for i in range(len(masks)):
            if masks[i] is None:
                continue
            for j in range(i + 1, len(masks)):
                if masks[j] is None:
                    continue
                inter = np.logical_and(masks[i] > 0, masks[j] > 0).sum()
                if inter == 0:
                    continue
                union = np.logical_or(masks[i] > 0, masks[j] > 0).sum()
                iou = inter / union
                if iou > 0.5:
                    errors.append(
                        f"particles {ids_list(particles)[i]} and "
                        f"{ids_list(particles)[j]} overlap heavily "
                        f"(IoU {iou:.2f}) — impossible geometry")
                elif iou > 0.1:
                    warnings.append(
                        f"particles {ids_list(particles)[i]} and "
                        f"{ids_list(particles)[j]} overlap (IoU {iou:.2f}) — "
                        f"touching/clustered case")

    # optional reference values
    ref = gt.get("reference") or {}
    for key in ("iso_nodularity_pct", "jis_nodularity_pct"):
        v = ref.get(key)
        if v is not None and (not isinstance(v, (int, float)) or
                              not math.isfinite(v) or not 0 <= v <= 100):
            errors.append(f"reference.{key} must be a percentage in [0,100]")

    verdict = "INVALID" if errors else (
        "INCOMPLETE" if incomplete or not particles
        else ("WARNING" if warnings else "VALID"))
    border = sum(1 for p in particles if p.get("border_touching"))
    uncertain = sum(1 for p in particles if p.get("uncertain"))
    return {
        "image_id": image_id,
        "verdict": verdict,
        "errors": errors,
        "warnings": warnings,
        "info": {
            "n_particles": len(particles),
            "border_touching": border,
            "uncertain": uncertain,
            "provenance_class": prov,
            "physical_scale_status": status,
            "microns_per_pixel": umpp if status != "unavailable" else None,
            "shape": list(shape) if shape else None,
        },
    }


def ids_list(particles):
    return [str(p.get("id", f"#{i}")) for i, p in enumerate(particles)]


def validate_all(gt_dir=GT_DIR, out_path=VALIDATION_REPORT):
    """Validate every GT document; write reports/ground_truth/validation.json."""
    gt_dir = Path(gt_dir)
    per_image = {}
    if gt_dir.is_dir():
        for p in sorted(gt_dir.glob("*.json")):
            try:
                gt = load_ground_truth(p)
            except (ValueError, json.JSONDecodeError) as exc:
                gt = None
                per_image[p.stem] = {
                    "image_id": p.stem, "verdict": "INVALID",
                    "errors": [f"parse error: {exc}"], "warnings": [],
                    "info": {}}
                continue
            per_image[p.stem] = validate_ground_truth(gt, gt_dir)
    n_valid = sum(1 for v in per_image.values() if v["verdict"] == "VALID")
    n_usable = sum(1 for v in per_image.values()
                   if v["verdict"] in ("VALID", "WARNING"))
    report = {
        "schema_version": SCHEMA_VERSION,
        "gt_directory": str(gt_dir),
        "n_documents": len(per_image),
        "n_valid": n_valid,
        "n_usable": n_usable,
        "primary_benchmark_ready": n_usable >= 10,
        "verdicts": {k: v["verdict"] for k, v in per_image.items()},
        "per_image": per_image,
        "note": ("validator never repairs expert annotations; INVALID "
                 "documents must be fixed by the expert"),
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
