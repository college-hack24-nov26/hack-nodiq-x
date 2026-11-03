"""ASTM Grain-Size Estimator — Jeffries planimetric reporting tests.

Two kinds of coverage, clearly separated and labeled:

* REAL-execution tests (``test_real_*``) — execute the repository's own
  ``calculate_jeffries()`` unmodified (in the isolated ASTM runtime when the
  app interpreter's pandas is unusable). They assert the documented formula
  ``G = 3.321928*log10(N_A) - 2.954`` and the Jeffries planimetric relation
  ``N_A = (internal + intercepted/2) / circle_area_mm2`` on synthetic grain
  masks whose geometry is constructed to be verifiable.
* MOCKED tests (``test_mocked_*``) — patch ONLY the model boundary
  (``availability`` / instance-segmentation output) because a full
  Cellpose-SAM inference pass is too heavy for a unit test. Inside those
  tests the Jeffries calculation is still executed by the REAL repository
  code via the isolated runtime; ONLY the segmentation is injected.

Regression guard: the Cast Iron Graphite Nodularity product must be
untouched — this file also verifies the nodularity entry points stay
importable and that no fake pandas stub remains in the adapter source.
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from skimage.segmentation import find_boundaries

ROOT = Path(__file__).resolve().parent.parent

import nodiq.services.grain_size.astm_estimator_adapter as astm_adapter

REPO = ROOT / "third_party" / "ASTM-Grain-Size-Estimator"
MASK_SIDE = 240


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _isolated_runtime_python():
    """Path of the isolated ASTM runtime interpreter, or None."""
    try:
        return astm_adapter._venv_python()
    except Exception:
        return None


def _synthetic_grain_label_map():
    """5 disjoint round grain instances -> an instance-label map shaped
    exactly like a real Cellpose-SAM output (0 = background)."""
    labels = np.zeros((MASK_SIDE, MASK_SIDE), dtype=np.int32)
    cc, rr = np.mgrid[0:MASK_SIDE, 0:MASK_SIDE]
    for cx, cy in ((60, 60), (170, 60), (60, 170), (170, 170), (120, 120)):
        dist2 = (cc - cx) ** 2 + (rr - cy) ** 2
        labels[dist2 < 45 ** 2] = int(labels.max()) + 1
    return labels


def _binary_from_labels(labels):
    """The binary_output stage the repository writes: white grain
    interiors, black outer boundaries, black background."""
    boundaries = find_boundaries(labels, mode="outer")
    binary = np.full(labels.shape, 255, dtype=np.uint8)
    binary[boundaries] = 0
    binary[labels == 0] = 0
    return binary


def _mock_rgb():
    """Homogeneous RGB stand-in — the mocked inference ignores it."""
    return np.full((MASK_SIDE, MASK_SIDE, 3), 128, dtype=np.uint8)


def _patch_inference(monkeypatch, labels):
    """Inject `labels` as the model's segmentation output (mock boundary)."""
    monkeypatch.setattr(
        astm_adapter, "_run_inference_subprocess",
        lambda rgb_, ckpt: (np.asarray(labels), False, {}))


def _patch_available(monkeypatch):
    """Short-circuit the (very heavy) availability probe: segmentation is
    mocked below anyway, so no model/weights initialization is needed."""
    monkeypatch.setattr(astm_adapter, "availability", lambda: {
        "available": True,
        "engine": astm_adapter.ENGINE_ID,
        "engine_name": astm_adapter.ENGINE_NAME,
        "missing": [],
        "runtime": "isolated",
        "notes": [],
    })


requires_isolated_runtime = pytest.mark.skipif(
    _isolated_runtime_python() is None,
    reason="no isolated ASTM runtime (.venv-astm / NODIQ_ASTM_PYTHON) in "
           "this environment")


# --------------------------------------------------------------------------- #
# REAL execution — the repository's calculate_jeffries() itself
# --------------------------------------------------------------------------- #

@requires_isolated_runtime
def test_real_jeffries_formula_is_exact():
    """REAL calculate_jeffries() via the isolated runtime: the returned G
    MUST equal the documented formula on the returned N_A — bit-exact."""
    binary = _binary_from_labels(_synthetic_grain_label_map())
    pixels_per_um = 0.5
    j = astm_adapter._run_jeffries_in_runtime(
        binary, target=5, pixels_per_um=pixels_per_um)

    assert set(j) == {"r", "internal", "intercepted", "na", "g"}
    assert j["internal"] >= 0 and j["intercepted"] >= 0

    # 1) documented grain-size formula
    g_expected = 3.321928 * math.log10(j["na"]) - 2.954
    assert j["g"] == pytest.approx(g_expected, abs=1e-9)

    # 2) the Jeffries planimetric density relation itself
    circle_area_mm2 = math.pi * (j["r"] ** 2) / (pixels_per_um ** 2) / 1e6
    na_expected = (j["internal"] + j["intercepted"] / 2.0) / circle_area_mm2
    assert j["na"] == pytest.approx(na_expected, abs=1e-6)


@requires_isolated_runtime
def test_real_jeffries_counts_are_physically_consistent():
    """5 synthetic grains: internal + intercepted must account for a sane
    subset of them (never exceed the constructed count, never be zero)."""
    binary = _binary_from_labels(_synthetic_grain_label_map())
    j = astm_adapter._run_jeffries_in_runtime(
        binary, target=5, pixels_per_um=2.0)
    total = j["internal"] + j["intercepted"]
    assert 1 <= total <= 5, (
        f"grain counting out of range for a 5-grain mask: {j}")


@requires_isolated_runtime
def test_real_jeffries_is_monotonic_in_circle_target():
    """A larger `target` cannot shrink the search circle below the smaller
    target's radius — the repository's dynamic circle search guarantees
    internal(target) is non-decreasing."""
    binary = _binary_from_labels(_synthetic_grain_label_map())
    small = astm_adapter._run_jeffries_in_runtime(
        binary, target=1, pixels_per_um=2.0)
    large = astm_adapter._run_jeffries_in_runtime(
        binary, target=5, pixels_per_um=2.0)
    assert large["internal"] >= small["internal"]


def test_real_runner_rejects_unusable_mask():
    """A fully black mask has no grain components: the repository returns
    None and the runner surfaces that as a RuntimeError — it never
    fabricates a grain-size number."""
    black = np.zeros((MASK_SIDE, MASK_SIDE), dtype=np.uint8)
    if _isolated_runtime_python() is None:
        pytest.skip("no isolated runtime")
    with pytest.raises(Exception) as excinfo:
        astm_adapter._run_jeffries_in_runtime(
            black, target=5, pixels_per_um=2.0)
    assert not str(excinfo.value).strip().lower().startswith("g=")


# --------------------------------------------------------------------------- #
# mocked segmentation + REAL Jeffries through the full run_astm_estimator()
# --------------------------------------------------------------------------- #

def test_mocked_no_calibration_keeps_pixels_only(monkeypatch):
    """No calibration -> pixel measurements preserved, physical values and
    the Jeffries grain-size number explicitly unavailable (never 0)."""
    _patch_available(monkeypatch)
    _patch_inference(monkeypatch, _synthetic_grain_label_map())

    res = astm_adapter.run_astm_estimator(_mock_rgb(), um_per_px=None)

    assert res["status"] == "completed"
    m = res["measurements"]
    assert m["grain_count"] == 5
    assert "mean_grain_area_px2" in m
    assert "mean_grain_area_um2" not in m
    assert "mean_equiv_grain_diameter_um" not in m

    j = res["jeffries"]
    assert j["available"] is False
    assert "calibration" in j["reason"].lower()
    assert "astm_grain_size_number" not in j
    assert "na" not in j
    assert any("calibration" in w.lower() for w in res["warnings"])


@pytest.mark.parametrize("bad", [0.0, -2.0, float("nan"), float("inf"),
                                 "2.0", True])
def test_mocked_invalid_calibration_rejected(monkeypatch, bad):
    """NaN / 0 / negative / string / boolean calibrations must NOT produce
    physical values or a Jeffries number."""
    _patch_available(monkeypatch)
    _patch_inference(monkeypatch, _synthetic_grain_label_map())

    res = astm_adapter.run_astm_estimator(_mock_rgb(), um_per_px=bad)

    assert res["status"] == "completed"
    assert res["jeffries"]["available"] is False
    assert "astm_grain_size_number" not in res["jeffries"]
    m = res["measurements"]
    assert "mean_grain_area_um2" not in m
    assert "mean_equiv_grain_diameter_um" not in m


@requires_isolated_runtime
def test_mocked_valid_calibration_computes_real_jeffries(monkeypatch):
    """Valid calibration -> a REAL Jeffries number from the REAL repository
    function (only segmentation is mocked)."""
    _patch_available(monkeypatch)
    _patch_inference(monkeypatch, _synthetic_grain_label_map())

    res = astm_adapter.run_astm_estimator(_mock_rgb(), um_per_px=2.0)

    assert res["status"] == "completed"
    j = res["jeffries"]
    assert j["available"] is True
    assert j["na"] > 0
    assert j["astm_grain_size_number"] > 0

    # formula cross-check against the computed density
    g_expected = 3.321928 * math.log10(j["na"]) - 2.954
    assert j["astm_grain_size_number"] == pytest.approx(
        round(g_expected, 2), abs=0.02)

    # inside/intercepted relayed from the repository result
    assert set(j) >= {"na", "astm_grain_size_number",
                      "grains_inside_circle",
                      "grains_intercepted_by_circle",
                      "test_circle_radius_px"}
    assert j["grains_inside_circle"] >= 0
    assert j["grains_intercepted_by_circle"] >= 0

    # pixel AND calibrated measurements reported separately
    m = res["measurements"]
    assert "mean_grain_area_px2" in m
    assert "mean_grain_area_um2" in m
    assert "mean_equiv_grain_diameter_um" in m

    assert j["runtime"] == "isolated"


@requires_isolated_runtime
def test_mocked_jeffries_failure_preserves_segmentation(monkeypatch):
    """When the Jeffries runner raises, segmentation measurements survive
    and the Jeffries block reports a reason — never silently dropped."""
    _patch_available(monkeypatch)
    _patch_inference(monkeypatch, _synthetic_grain_label_map())

    def boom(binary_output, target, pixels_per_um):
        raise RuntimeError("boom — isolated runtime failure")

    monkeypatch.setattr(astm_adapter, "_run_jeffries_in_runtime", boom)

    res = astm_adapter.run_astm_estimator(_mock_rgb(), um_per_px=2.0)

    assert res["status"] == "completed"
    assert res["measurements"]["grain_count"] == 5
    assert res["measurements"]["mean_grain_area_px2"] > 0
    j = res["jeffries"]
    assert j["available"] is False
    assert "failed" in j["reason"].lower()
    assert "astm_grain_size_number" not in j
    assert any("jeffries" in w.lower() for w in res["warnings"])


@requires_isolated_runtime
def test_mocked_jeffries_none_result_reported_not_hidden(monkeypatch):
    """calculate_jeffries() returning no result must surface as
    available=False with a reason — a completed segmentation survives."""
    _patch_available(monkeypatch)
    _patch_inference(monkeypatch, _synthetic_grain_label_map())
    monkeypatch.setattr(astm_adapter, "_run_jeffries_in_runtime",
                        lambda binary, target, pixels_per_um: None)

    res = astm_adapter.run_astm_estimator(_mock_rgb(), um_per_px=2.0)

    assert res["status"] == "completed"
    assert res["measurements"]["grain_count"] == 5
    j = res["jeffries"]
    assert j["available"] is False
    assert "no result" in j["reason"].lower()


def test_mocked_empty_segmentation_fails_honestly(monkeypatch):
    """No grain instances -> failed status, empty measurements and images,
    and no fabricated Jeffries number."""
    _patch_available(monkeypatch)
    _patch_inference(monkeypatch, np.zeros((MASK_SIDE, MASK_SIDE),
                                           dtype=np.int32))

    res = astm_adapter.run_astm_estimator(_mock_rgb(), um_per_px=2.0)

    assert res["status"] == "failed"
    assert res["measurements"] == {}
    assert res["images"] == {}
    assert "no grain instances" in res["error"].lower()


def test_mocked_inference_failure_propagates_as_failed(monkeypatch):
    """A failing segmentation backend must surface as status=failed with
    the captured error — never an empty-but-completed run."""
    _patch_available(monkeypatch)

    def broken_inference(rgb_, ckpt):
        raise RuntimeError("runner died")

    monkeypatch.setattr(astm_adapter, "_run_inference_subprocess",
                        broken_inference)

    res = astm_adapter.run_astm_estimator(_mock_rgb(), um_per_px=None)

    assert res["status"] == "failed"
    assert "runner died" in res["error"]
    assert res["measurements"] == {}


# --------------------------------------------------------------------------- #
# calibration validation (REAL adapter validation logic)
# --------------------------------------------------------------------------- #

def test_calibration_validator_rejects_invalid_values():
    """NaN, inf, strings, booleans, 0 and negatives are all unusable — a
    NaN would silently poison every physical conversion."""
    assert not astm_adapter._valid_um_per_px(None)
    assert not astm_adapter._valid_um_per_px(0)
    assert not astm_adapter._valid_um_per_px(-1.5)
    assert not astm_adapter._valid_um_per_px("2.0")
    assert not astm_adapter._valid_um_per_px(float("nan"))
    assert not astm_adapter._valid_um_per_px(float("inf"))
    assert not astm_adapter._valid_um_per_px(True)   # bool, not a length
    assert not astm_adapter._valid_um_per_px([2.0])
    assert astm_adapter._valid_um_per_px(2.0)
    assert astm_adapter._valid_um_per_px(0.123)
    assert astm_adapter._valid_um_per_px(1e-3)


# --------------------------------------------------------------------------- #
# pandas handling
# --------------------------------------------------------------------------- #

def test_pandas_broken_in_app_interpreter_routes_to_isolated_runtime():
    """The app interpreter's pandas import must be probed (and cached) so
    the Jeffries calculation routes to the isolated runtime instead of a
    stub. In this environment the probe is expected to FAIL."""
    astm_adapter._PANDAS_RUNTIME_CACHE.clear()
    result = astm_adapter._runtime_imports_pandas(None)
    if result:
        pytest.skip("app interpreter pandas works here; routing check is "
                    "environment-conditional")
    assert astm_adapter._PANDAS_RUNTIME_CACHE.get("in_process") is False
    # cache actually prevents repeated probing
    assert astm_adapter._runtime_imports_pandas(None) is False


def test_pandas_probe_cache_is_per_interpreter():
    """The cache key is the interpreter path, not a global flag."""
    astm_adapter._PANDAS_RUNTIME_CACHE.clear()
    key = "definitely-not-a-real-python"
    astm_adapter._PANDAS_RUNTIME_CACHE[key] = True
    assert astm_adapter._runtime_imports_pandas(key) is True
    astm_adapter._PANDAS_RUNTIME_CACHE.pop(key)


# --------------------------------------------------------------------------- #
# regression — the fake pandas stub must stay gone; nodularity untouched
# --------------------------------------------------------------------------- #

def test_regression_no_fake_pandas_stub_in_adapter_source():
    adapter_path = ROOT / "src" / "nodiq" / "services" / "grain_size" / "astm_estimator_adapter.py"
    src = adapter_path.read_text(encoding="utf-8")
    assert "types.ModuleType(\"pandas\")" not in src
    assert "stub module is injected" not in src
    assert "from .jeffries import load_repository_jeffries_module" in src


def test_regression_jeffries_loader_never_injects_stub(monkeypatch):
    from nodiq.services.grain_size.jeffries import load_repository_jeffries_module

    jeff_path = ROOT / "src" / "nodiq" / "services" / "grain_size" / "jeffries.py"
    src = jeff_path.read_text(encoding="utf-8")
    assert "ModuleType" not in src.replace(
        "isinstance(existing, types.ModuleType)", "")

    # When pandas is broken or missing, in-process loader raises on broken pandas rather than faking it:
    orig_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "pandas":
            raise ImportError("Simulated missing pandas")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    monkeypatch.delitem(sys.modules, "pandas", raising=False)
    with pytest.raises(ImportError):
        load_repository_jeffries_module(REPO)


def test_regression_nodularity_pipeline_importable():
    """Cast iron nodularity entry points must remain importable (and, by
    convention, untouched by the ASTM work)."""
    import nodiq.pipelines.nodularity_pipeline as nodularity_pipeline

    assert callable(nodularity_pipeline.analyze_image)
    assert callable(nodularity_pipeline.analyze_file)


def test_regression_estimation_result_images_shapes():
    """The images payload the dashboard consumes keeps its three entries
    (mask / overlay / labels) for a mocked completed run."""
    _patch_available(monkeypatch := pytest.MonkeyPatch())
    _patch_inference(monkeypatch, _synthetic_grain_label_map())
    try:
        res = astm_adapter.run_astm_estimator(_mock_rgb(), um_per_px=None)
    finally:
        monkeypatch.undo()

    assert res["status"] == "completed"
    images = res["images"]
    assert set(images) == {"mask", "overlay", "labels"}
    assert images["mask"].shape == (MASK_SIDE, MASK_SIDE)
    assert images["overlay"].shape == (MASK_SIDE, MASK_SIDE, 3)
    assert images["labels"].dtype == np.uint16
