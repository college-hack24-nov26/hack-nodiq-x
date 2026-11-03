#!/usr/bin/env python3
"""
tools/annotate_ground_truth.py — minimal expert annotation tool (Phase 7D).

Creates/edits evaluation/ground_truth/<image_id>.json documents.  This is a
GROUND-TRUTH tool: annotations are made by a human looking at the raw image
only — it never loads or displays model predictions, so expert geometry can
never be contaminated by production output.

Interactive editor (OpenCV window, no extra dependencies):

    python scripts/tools/annotate_ground_truth.py edit <image_file> [--gt-dir DIR]

    left click            add polygon vertex for the current particle
    n                     finish particle (polygon closed), start a new one
    z                     remove last vertex
    d                     delete last FINISHED particle
    b                     toggle border-touching on the last finished particle
    u                     toggle uncertain on the last finished particle
    s                     save (schema_version 1.0 JSON next to the repo GT dir)
    q                     quit (prompts to save via terminal)

The expert records provenance/expert/scale interactively on first save; all
fields stay editable in the JSON afterwards.

Importer for externally produced annotations (labelImg, CVAT, Roboflow,
Label Studio, COCO export):

    python scripts/tools/annotate_ground_truth.py import-yolo <image_file> <labels.txt> \
        [--expert NAME] [--provenance A] [--umpp 0.123 --scale-source metadata]

    python scripts/tools/annotate_ground_truth.py import-coco <coco.json> [--expert N] ...

    python scripts/tools/annotate_ground_truth.py validate [--gt-dir DIR]

The importer never runs the detector and never copies detector outputs.
"""
import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

from nodiq.services.ground_truth import (GT_DIR, empty_ground_truth,  # noqa: E402
                                   load_ground_truth, validate_ground_truth,
                                   validate_all)

WINDOW = "NODIQ-X ground-truth annotator (L-click vertex | n new | z undo" \
         " | d del | b border | u uncertain | s save | q quit)"


# ---------------------------------------------------------------------------
# interactive polygon editor
# ---------------------------------------------------------------------------
def edit_image(image_file, gt_dir=GT_DIR):
    import cv2
    import numpy as np

    image_file = Path(image_file)
    if not image_file.is_absolute():
        image_file = PROJECT_ROOT / image_file
    img = cv2.imread(str(image_file))
    if img is None:
        print(f"cannot read image: {image_file}")
        return 1
    h, w = img.shape[:2]
    image_id = image_file.stem

    gt_path = Path(gt_dir) / f"{image_id}.json"
    if gt_path.is_file():
        gt = load_ground_truth(gt_path)
        print(f"loaded existing document: {gt_path}")
    else:
        gt = empty_ground_truth(image_id,
                                str(image_file.relative_to(PROJECT_ROOT)),
                                w, h)
        print("new document (expert, provenance and scale are prompted on "
              "save)")

    finished = list(gt.get("particles", []))
    current_pts = []

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            current_pts.append([int(x), int(y)])

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    scale = 1.0
    if w < 500:                     # small panels: upscale for precision
        scale = 2.0
        big = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_NEAREST)
        cv2.setMouseCallback(WINDOW, on_mouse)
        work = big
    else:
        work = img
        cv2.setMouseCallback(WINDOW, on_mouse)

    while True:
        canvas = work.copy()
        for p in finished:
            pts = np.array([(pt["geometry"]["points"]) for pt in [p]],
                           dtype=object)
            poly = np.array(p["geometry"]["points"], np.int32)
            if scale != 1.0:
                poly = poly * 2
            color = (0, 180, 0) if not p.get("uncertain") else (0, 160, 255)
            cv2.polylines(canvas, [poly], True, color, 1)
            if p.get("border_touching"):
                cv2.circle(canvas, tuple(poly[0]), 4, (0, 215, 255), -1)
        if scale != 1.0:
            cur = [[int(x * 2), int(y * 2)] for x, y in current_pts]
        else:
            cur = current_pts
        if cur:
            cv2.polylines(canvas, [np.array(cur, np.int32)], False,
                          (0, 255, 255), 1)
            for pt in cur:
                cv2.circle(canvas, tuple(pt), 2, (0, 255, 255), -1)
        cv2.setWindowTitle(
            WINDOW, f"{image_id}  particles: {len(finished)}  "
                    f"current vertices: {len(current_pts)}")
        cv2.imshow(WINDOW, canvas)
        key = cv2.waitKey(30) & 0xFF
        if key == ord('n'):
            if len(current_pts) >= 3:
                finished.append({
                    "id": f"p{len(finished) + 1}",
                    "geometry": {"type": "polygon",
                                 "points": [[x / (scale if scale != 1.0
                                                   else 1) * (1 if scale == 1.0
                                                              else 0.5)]
                                            for x, y in
                                            [(x * (1 if scale == 1.0 else 0.5),
                                              y * (1 if scale == 1.0 else 0.5))
                                             for x, y in cur]]},
                    "border_touching": False, "uncertain": False})
                current_pts = []
        elif key == ord('z') and current_pts:
            current_pts.pop()
        elif key == ord('d') and finished:
            finished.pop()
        elif key == ord('b') and finished:
            finished[-1]["border_touching"] = \
                not finished[-1]["border_touching"]
        elif key == ord('u') and finished:
            finished[-1]["uncertain"] = not finished[-1]["uncertain"]
        elif key == ord('s'):
            gt["particles"] = _normalize_points(finished)
            _save_interactive(gt, gt_path)
        elif key == ord('q'):
            if current_pts or True:
                gt["particles"] = _normalize_points(finished)
                _save_interactive(gt, gt_path, prompt=True)
            break
    cv2.destroyAllWindows()
    return 0


def _normalize_points(finished):
    """Ensure native-resolution integer/float coordinates and stable ids."""
    out = []
    for i, p in enumerate(finished):
        pts = p["geometry"]["points"]
        out.append({
            "id": p.get("id", f"p{i + 1}"),
            "geometry": {"type": "polygon",
                         "points": [[float(round(x, 2)),
                                     float(round(y, 2))] for x, y in pts]},
            "border_touching": bool(p.get("border_touching")),
            "uncertain": bool(p.get("uncertain")),
            "class": p.get("class"),
            "notes": p.get("notes"),
        })
    return out


def _save_interactive(gt, gt_path, prompt=False):
    ann = gt.setdefault("annotation", {})
    if not ann.get("expert"):
        ann["expert"] = input("annotator name/expert: ").strip() or "unknown"
    if not ann.get("provenance_class"):
        ann["provenance_class"] = \
            input("provenance class A/B/E (A independent expert, B "
                  "independently annotated, E unverified): ").strip() or "A"
    ann["tool"] = "tools/annotate_ground_truth.py (OpenCV editor)"
    ann["date"] = date.today().isoformat()
    ann["version"] = int(ann.get("version", 1))
    scale = gt.setdefault("physical_scale", {})
    if scale.get("status") is None or scale.get("status") == "unavailable":
        ans = input("physical scale available? [y/N]: ").strip().lower()
        if ans == "y":
            scale["status"] = input("  source (metadata|scale_bar|expert): "
                                    ).strip() or "expert"
            scale["microns_per_pixel"] = float(input("  um/px: "))
            scale["notes"] = input("  notes: ").strip() or None
    else:
        scale["status"] = scale.get("status") or "unavailable"
    verdict = validate_ground_truth(gt)
    gt_path.parent.mkdir(parents=True, exist_ok=True)
    gt_path.write_text(json.dumps(gt, indent=1), encoding="utf-8")
    print(f"saved {gt_path}  verdict={verdict['verdict']} "
          f"particles={len(gt.get('particles', []))}")
    for e in verdict["errors"]:
        print(f"  ERROR: {e}")
    if prompt:
        print("(document saved; edit later and re-run validate)")


# ---------------------------------------------------------------------------
# importers (YOLO seg/box, COCO) — external expert exports only
# ---------------------------------------------------------------------------
def import_yolo(image_file, labels_file, expert="unknown", provenance="A",
                umpp=None, scale_source=None, gt_dir=GT_DIR):
    """YOLO import: class 0 lines.  Supports both
    'class cx cy w h' (boxes) and 'class x1 y1 ... xn yn' (segmentation,
    n>=6, normalized).  Coordinates are normalized; de-normalized to pixels."""
    import cv2
    image_file = Path(image_file)
    if not image_file.is_absolute():
        image_file = PROJECT_ROOT / image_file
    img = cv2.imread(str(image_file))
    if img is None:
        print(f"cannot read image: {image_file}")
        return 1
    h, w = img.shape[:2]
    image_id = image_file.stem
    gt = empty_ground_truth(image_id,
                            str(image_file.relative_to(PROJECT_ROOT)), w, h)
    particles = []
    for line in Path(labels_file).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if not parts or parts[0] != "0":
            continue
        vals = [float(v) for v in parts[1:]]
        if len(vals) >= 6 and len(vals) % 2 == 0:        # segmentation
            pts = [[vals[i] * w, vals[i + 1] * h]
                   for i in range(0, len(vals), 2)]
            geometry = {"type": "polygon", "points": pts}
        elif len(vals) == 4:                             # box
            cx, cy, bw, bh = vals
            pts = [[(cx - bw / 2) * w, (cy - bh / 2) * h],
                   [(cx + bw / 2) * w, (cy + bh / 2) * h]]
            geometry = {"type": "box", "points": pts}
        else:
            continue
        particles.append({"id": f"p{len(particles) + 1}",
                          "geometry": geometry,
                          "border_touching": False, "uncertain": False})
    gt["particles"] = particles
    gt["annotation"].update({
        "tool": f"import-yolo from {Path(labels_file).name}",
        "expert": expert, "provenance_class": provenance})
    if umpp:
        gt["physical_scale"] = {"status": scale_source or "expert",
                                "microns_per_pixel": float(umpp),
                                "source": scale_source or "expert",
                                "notes": "imported with annotation"}
    gt_path = Path(gt_dir) / f"{image_id}.json"
    gt_path.parent.mkdir(parents=True, exist_ok=True)
    gt_path.write_text(json.dumps(gt, indent=1), encoding="utf-8")
    verdict = validate_ground_truth(gt)
    print(f"imported {len(particles)} particles -> {gt_path} "
          f"verdict={verdict['verdict']}")
    for e in verdict["errors"]:
        print(f"  ERROR: {e}")
    return 0


def import_coco(coco_file, expert="unknown", provenance="A", gt_dir=GT_DIR,
                image_filter=None):
    """COCO import: category-0 (or 'graphite') annotations for the images in
    the file.  Segmentation polygons and bbox are both supported."""
    data = json.loads(Path(coco_file).read_text(encoding="utf-8"))
    cat_ids = {c["id"] for c in data.get("categories", [])
               if "graphite" in (c.get("name", "") or "").lower()
               or c.get("id") == 0 or c.get("name") == "nodule"}
    imgs = {im["id"]: im for im in data.get("images", [])}
    anns = {}
    for a in data.get("annotations", []):
        if a.get("category_id") not in cat_ids:
            continue
        anns.setdefault(a["image_id"], []).append(a)
    n_written = 0
    for iid, alist in sorted(anns.items()):
        im = imgs[iid]
        if image_filter and im["file_name"] != image_filter:
            continue
        w, h = im["width"], im["height"]
        image_file = PROJECT_ROOT / im["file_name"]
        if not image_file.is_file():
            print(f"  skip {im['file_name']}: image not found")
            continue
        image_id = Path(im["file_name"]).stem
        gt = empty_ground_truth(image_id, im["file_name"], w, h)
        particles = []
        for a in alist:
            if a.get("segmentation") and \
                    isinstance(a["segmentation"], list) and \
                    isinstance(a["segmentation"][0], list):
                pts = [[a["segmentation"][0][i] * w,
                        a["segmentation"][0][i + 1] * h]
                       for i in range(0, len(a["segmentation"][0]), 2)]
                geometry = {"type": "polygon", "points": pts}
            else:
                x, y, bw, bh = a["bbox"]
                geometry = {"type": "box",
                            "points": [[x, y], [x + bw, y + bh]]}
            particles.append({"id": f"p{len(particles) + 1}",
                              "geometry": geometry,
                              "border_touching": False,
                              "uncertain": False})
        gt["particles"] = particles
        gt["annotation"].update({
            "tool": f"import-coco from {Path(coco_file).name}",
            "expert": expert, "provenance_class": provenance})
        gt_path = Path(gt_dir) / f"{image_id}.json"
        gt_path.write_text(json.dumps(gt, indent=1), encoding="utf-8")
        verdict = validate_ground_truth(gt)
        print(f"{image_id}: {len(particles)} particles "
              f"verdict={verdict['verdict']}")
        n_written += 1
    print(f"coco import complete: {n_written} images")
    return 0


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("edit", help="interactive polygon editor")
    e.add_argument("image_file")
    e.add_argument("--gt-dir", default=str(GT_DIR))

    y = sub.add_parser("import-yolo", help="import YOLO labels (boxes/seg)")
    y.add_argument("image_file")
    y.add_argument("labels_file")
    y.add_argument("--expert", default="unknown")
    y.add_argument("--provenance", default="A", choices=["A", "B", "E"])
    y.add_argument("--umpp", type=float, default=None)
    y.add_argument("--scale-source", default=None,
                   choices=["metadata", "scale_bar", "expert"])

    c = sub.add_parser("import-coco", help="import COCO annotations")
    c.add_argument("coco_file")
    c.add_argument("--expert", default="unknown")
    c.add_argument("--provenance", default="A", choices=["A", "B", "E"])

    v = sub.add_parser("validate", help="validate all GT documents")
    v.add_argument("--gt-dir", default=str(GT_DIR))

    args = ap.parse_args()
    if args.cmd == "edit":
        return edit_image(args.image_file, args.gt_dir)
    if args.cmd == "import-yolo":
        return import_yolo(args.image_file, args.labels_file, args.expert,
                           args.provenance, args.umpp, args.scale_source)
    if args.cmd == "import-coco":
        return import_coco(args.coco_file, args.expert, args.provenance)
    if args.cmd == "validate":
        report = validate_all(args.gt_dir)
        print(json.dumps(report["verdicts"], indent=1))
        print(f"usable: {report['n_usable']}/{report['n_documents']}  "
              f"primary benchmark ready: "
              f"{report['primary_benchmark_ready']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
