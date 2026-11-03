#!/usr/bin/env python3
"""
run_1000_fixed.py — batch: fixed pipeline + accuracy on all 1000 micrographs.

* Parallel (8 workers), resume-safe: skips images already present in summary.
* Writes per-image outputs only when WITH_FILES=1 (default 0 — summary first).
* Produces:
    nodularity_1000_fixed/summary_1000_fixed.csv   per-image table
    nodularity_1000_fixed/summary_1000_fixed.md    human-readable summary
"""
import csv
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

WORKER_VERBOSE = False


def one_image(args):
    img_path, out_dir, with_files = args
    import cv2  # noqa: F401  (worker import cost)
    from nodiq.pipelines.nodularity_pipeline import analyze_file
    try:
        t0 = time.time()
        outd = Path(out_dir) if with_files else None
        r = analyze_file(img_path, outd)
        dt = time.time() - t0
        return {
            "file": Path(img_path).name,
            "count": r["count"],
            "frozen_count": r["frozen_count"],
            "unified": r["n_unified"],
            "recovered": r["n_recovered"],
            "reference_count": r["reference_count"],
            "count_accuracy_pct": r["count_accuracy_pct"],
            "precision_pct": r["precision_pct"],
            "recall_pct": r["recall_pct"],
            "f1_pct": r["f1_pct"],
            "double_counts": r["double_counts"],
            "iso_pct": r["iso_pct"],
            "iso_inframe_pct": r["iso_inframe_pct"],
            "jis_pct": r["jis_pct"],
            "seconds": round(dt, 2),
            "error": "",
        }
    except Exception as e:  # crash-safe: record and continue
        return {"file": Path(img_path).name, "error": f"{type(e).__name__}: {e}"}


def main():
    data_dir = Path(r"C:/Users/Atharv/Downloads/ductile_cast_iron_1000_unique_micrographs")
    from nodiq.core.config import DATA_RAW_DIR
    out_root = DATA_RAW_DIR / "nodularity_1000_fixed"
    out_root.mkdir(exist_ok=True)
    files = sorted(data_dir.glob("micrograph_*.png"))
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        files = files[:int(sys.argv[1])]
        out_root = Path("nodularity_1000_fixed_trial")
        out_root.mkdir(exist_ok=True)
    summary_path = out_root / "summary_1000_fixed.csv"

    fields = ["file", "count", "frozen_count", "unified", "recovered",
              "reference_count", "count_accuracy_pct", "precision_pct",
              "recall_pct", "f1_pct", "double_counts", "iso_pct",
              "iso_inframe_pct", "jis_pct", "seconds", "error"]
    done = {}
    raw_rows = 0
    need_header = True
    if summary_path.exists():
        with open(summary_path, newline="", encoding="utf-8") as f:
            first = f.readline()
            need_header = not first.startswith("file,")
            f.seek(0)
            reader = (csv.reader(f) if need_header else None)
            if need_header:
                # headerless (legacy) file: rows are already in field order;
                # keep ALL 16 parts (error field may be the empty trailing one)
                for parts in reader:
                    if len(parts) != len(fields):
                        continue  # truncated/corrupt line
                    row = dict(zip(fields, parts))
                    raw_rows += 1
                    if row["file"] and not row["error"]:
                        done[row["file"]] = row
            else:
                f.seek(0)
                for row in csv.DictReader(f):
                    raw_rows += 1
                    fname = row.get("file")
                    if fname and not row.get("error"):
                        done[fname] = row
        if raw_rows > len(done):
            # self-heal after an interrupted run: rewrite one row per file
            with open(summary_path, "w", newline="", encoding="utf-8") as f2:
                w = csv.DictWriter(f2, fieldnames=fields)
                w.writeheader()
                w.writerows(done.values())
            print(f"deduped summary: {raw_rows} rows -> {len(done)} files")
    todo = [(str(p), str(out_root), os.environ.get("WITH_FILES", "0") == "1")
            for p in files if p.name not in done]
    print(f"{len(files)} images, {len(done)} already done, {len(todo)} to run")

    t0 = time.time()
    new = 0
    workers = min(8, os.cpu_count() or 4)
    write_header = not summary_path.exists()
    with open(summary_path, "a", newline="", encoding="utf-8") as fout:
        writer = csv.DictWriter(fout, fieldnames=fields)
        if write_header:
            writer.writeheader()
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(one_image, a): a[0] for a in todo}
            for n, fut in enumerate(as_completed(futs), 1):
                row = fut.result()
                if not row.get("error"):
                    done[row["file"]] = row
                    writer.writerow(row)
                    fout.flush()
                    new += 1
                else:
                    print(f"ERROR {row['file']}: {row['error']}")
                if n % 50 == 0 or n == len(todo):
                    el = time.time() - t0
                    print(f"  {n}/{len(todo)} done in {el:.0f}s "
                          f"(~{el / max(n, 1):.2f}s/img)")

    # ---------- aggregate ----------
    rows = list(done.values())
    if not rows:
        print("nothing to summarize")
        return
    nums = {k: [float(r[k]) for r in rows] for k in
            ["count", "frozen_count", "unified", "recovered",
             "reference_count", "count_accuracy_pct", "precision_pct",
             "recall_pct", "f1_pct", "double_counts", "iso_pct",
             "iso_inframe_pct", "jis_pct"]}

    def stat(k):
        v = sorted(nums[k])
        n = len(v)
        return (sum(v) / n, v[n // 2], v[0], v[-1])

    lines = ["# Fixed-pipeline batch summary", "",
             f"Images analyzed: **{len(rows)}** "
             f"({sum(1 for r in rows if r.get('error'))} errors)", "",
             "| metric | mean | median | min | max |", "|---|---|---|---|---|"]
    for k, label in [("count", "Model nodule count"),
                     ("frozen_count", "Frozen detector count (before fix)"),
                     ("unified", "Dividing nodules unified"),
                     ("recovered", "Missed nodules recovered"),
                     ("reference_count", "Independent reference count"),
                     ("count_accuracy_pct", "Counting accuracy %"),
                     ("precision_pct", "Precision %"),
                     ("recall_pct", "Recall %"),
                     ("f1_pct", "F1 %"),
                     ("double_counts", "Double counts (should be ~0)"),
                     ("iso_pct", "ISO nodularity %"),
                     ("iso_inframe_pct", "ISO nodularity (in-frame) %"),
                     ("jis_pct", "JIS nodularity %")]:
        m, md, lo, hi = stat(k)
        lines.append(f"| {label} | {m:.2f} | {md:.1f} | {lo:.1f} | {hi:.1f} |")

    acc = nums["count_accuracy_pct"]
    bands = [("<70%", 0, 70), ("70-85%", 70, 85), ("85-95%", 85, 95),
             ("95-100%", 95, 100.01)]
    lines += ["", "## Counting accuracy distribution", "",
              "| band | images | share |", "|---|---|---|"]
    for label, lo, hi in bands:
        c = sum(1 for v in acc if lo <= v < hi)
        lines.append(f"| {label} | {c} | {c / len(acc) * 100:.1f}% |")
    f1 = nums["f1_pct"]
    lines += ["", "## F1 distribution", "", "| band | images | share |",
              "|---|---|---|"]
    for label, lo, hi in bands:
        c = sum(1 for v in f1 if lo <= v < hi)
        lines.append(f"| {label} | {c} | {c / len(f1) * 100:.1f}% |")

    (out_root / "summary_1000_fixed.md").write_text("\n".join(lines),
                                                    encoding="utf-8")
    print("\n".join(lines))
    print(f"\nCSV: {summary_path}")


if __name__ == "__main__":
    main()
