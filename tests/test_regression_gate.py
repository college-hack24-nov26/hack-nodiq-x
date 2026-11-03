#!/usr/bin/env python3
"""
CI regression gate — protects the validated-engine claim (Advancement).

Runs the real pipeline on a small deterministic slice of the dataset and
FAILS the build if counting accuracy degrades. Skipped automatically when
the dataset/CSV artifacts are absent (e.g. minimal CI checkout).

The engine probe runs in a SUBPROCESS: importing nodularity_pipeline (which
pulls in the legacy nodularity module) hijacks sys.stdin/stdout/stderr with
new TextIOWrappers, which corrupts pytest's output capture. A subprocess
sidesteps that entirely and matches how CI invokes the gate.
"""
import csv
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = ROOT / "apps" / "web" / "public" / "dataset"
from nodiq.core.config import SUMMARY_1000_CSV_PATH

SUMMARY_CSV = SUMMARY_1000_CSV_PATH

# Regression gate: mean count accuracy over the probe slice must stay at or
# above this. Validated batch runs ~100%; 85% leaves headroom for CI noise
# while still catching real engine regressions.
GATE_ACCURACY_PCT = 85.0
PROBE_N = 5

pytestmark = pytest.mark.skipif(
    not (DATASET_DIR.exists() and SUMMARY_CSV.exists()),
    reason="dataset/summary CSV not present (lightweight CI checkout)")

_PROBE_SNIPPET = """
import csv, json, sys
from pathlib import Path
from nodiq.pipelines.nodularity_pipeline import analyze_image
dataset = Path({dataset!r})
ref = {{}}
with open({csv!r}, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row.get("file") and not row.get("error"):
            ref[row["file"]] = row
out = []
for name in sorted(ref)[:{n}]:
    if (dataset / name).exists():
        res = analyze_image(str(dataset / name))
        out.append({{"file": name, "accuracy_pct": res["count_accuracy_pct"]}})
print("GATE_JSON=" + json.dumps(out))
"""


def test_engine_accuracy_gate():
    code = _PROBE_SNIPPET.format(root=str(ROOT), dataset=str(DATASET_DIR),
                                 csv=str(SUMMARY_CSV), n=PROBE_N)
    proc = subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, timeout=240)
    assert proc.returncode == 0, f"engine probe crashed:\n{proc.stderr[-1500:]}"

    line = next((l for l in proc.stdout.splitlines()
                 if l.startswith("GATE_JSON=")), None)
    assert line, f"probe produced no result line\nstdout: {proc.stdout[-500:]}"

    import json
    results = json.loads(line.split("=", 1)[1])
    assert results, "no probe images available for the regression gate"

    accs = [r["accuracy_pct"] for r in results]
    mean_acc = sum(accs) / len(accs)
    assert mean_acc >= GATE_ACCURACY_PCT, (
        f"engine regression: mean count accuracy {mean_acc:.1f}% over "
        f"{len(accs)} probe images is below the {GATE_ACCURACY_PCT}% gate")
