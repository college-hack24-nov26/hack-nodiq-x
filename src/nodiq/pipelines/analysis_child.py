#!/usr/bin/env python3
"""
analysis_child.py — isolated engine worker for one analysis job.

Spawned by server.py as a real child process (subprocess). On small hosts
(Render free tier: 0.1 CPU / 512 MB) the heavy OpenCV pipeline can exceed the
container memory budget. Run inside the gunicorn web worker, that meant the
OOM killer took down the WHOLE service — crash-loop, 502s, wiped sessions.

With this module the blast radius is one analysis: if the child dies, the
parent marks the analysis failed with an honest message and keeps serving.

Protocol (argv):
    python analysis_child.py <analysis_id> <user_id> <image_path>
                             <filename> <manual_mpp or ""> <scale_cap>

    image_path   — server-side path to the upload (already magic-number
                   validated by the parent; no untrusted bytes are passed on
                   the command line)
    manual_mpp   — "" (none) or a validated positive float (parent-validated)
    scale_cap    — max long-side pixels for the memory guard (int)

Exit codes:
    0 — analysis completed (payload persisted by this child)
    3 — user-facing failure (_JobFailure path: not a microstructure etc.)
    1 — internal child error (stderr carries the traceback for server logs)

On ANY nonzero exit the parent flips the pending record to "failed" —
including the OOM-killed case where this process never gets a chance to
write anything.
"""
import json
import sys
import time
from pathlib import Path

from nodiq.core.config import REPO_ROOT
ROOT = REPO_ROOT
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Cap OpenCV/BLAS thread pools BEFORE cv2/numpy load their engines:
# default to min(8, max(2, _preos.cpu_count() or 4)) so multi-core systems
# can leverage parallel vector instructions, while keeping thread stack bounds.
import os as _preos
_default_threads = str(min(8, max(2, _preos.cpu_count() or 4)))
for _v in ("OPENCV_NUM_THREADS", "OMP_NUM_THREADS",
           "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    _preos.environ.setdefault(_v, _default_threads)

import cv2
import numpy as np

from nodiq.pipelines.nodularity_pipeline import (analyze_for_frontend_json, analyze_image,
                                 apply_size_filter_and_iso,
                                 evaluate_microstructure_validity,
                                 load_with_source)
import nodiq.pipelines.steel_grain_size_pipeline as steel_pipeline
import nodiq.services.white_cast_iron.pipeline as white_cast_iron_pipeline
import nodiq.services.gray_cast_iron.pipeline as gray_cast_iron_pipeline
from nodiq.services import context as context_svc
from nodiq.services import db as store
from nodiq.services import seclog
# NOTE: services.storage (and its `requests` dependency, ~20MB RSS) is
# imported ONLY when Supabase persistence is actually configured — the
# env test below mirrors storage.BACKEND without importing the module.
# On the sqlite dev backend the child keeps the pre-migration memory
# baseline, which is what fits the 512MB free-tier budget alongside the
# web worker.
from nodiq.services.calibration import (auto_calibrate, make_calibration,
                                  validate_um_per_px)
from nodiq.services.morphology import classify_graphite_forms
from nodiq.services.nodule_data import enrich_rows
from nodiq.services.properties import estimate_properties
from nodiq.services.quality import assess_quality

from nodiq.ai.config import get_config as _ai_cfg

CFG = _ai_cfg()


class _JobFailure(Exception):
    """A user-facing analysis failure (message is safe to show the client)."""


def _set_progress(analysis_id, user_id, progress):
    """Persist progress on the processing record — the poll route reads the
    record (not process memory), so this keeps the live progress bar working
    even though the compute now runs in a separate process."""
    record = store.get_analysis_record(analysis_id, user_id)
    if record and record.get("status") == "processing":
        store.insert_analysis({**record, "progress": progress}, user_id)


def _save_and_upload_artifacts(analysis_id, user_id, image_path, images, pending):
    """Save analysis visual artifacts to disk and persistent storage in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    local_paths = {}

    def _write_one(item):
        k, img_arr = item
        p = context_svc.FULL_DIR / f"{analysis_id}_{k}.png"
        try:
            # PNG compression level 3: ~3-4x faster compression with minimal byte delta
            if cv2.imwrite(str(p), img_arr, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
                return k, p
        except Exception:
            pass
        return k, None

    if images:
        with ThreadPoolExecutor(max_workers=min(len(images), 4) or 1) as pool:
            for k, p in pool.map(_write_one, list(images.items())):
                if p is not None:
                    local_paths[k] = p

    artifact_keys = {}
    import os as _os
    if _os.environ.get("SUPABASE_URL") and _os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        from nodiq.services import storage as storage_svc
        try:
            upload_queue = [("original", Path(image_path).read_bytes())]
            for k, p in local_paths.items():
                upload_queue.append((k, p.read_bytes()))

            def _upload_one(pair):
                k, b = pair
                return k, storage_svc.put_bytes(user_id, analysis_id, k, b)

            # Sequential upload (max_workers=1) dedicates full connection bandwidth
            # to each artifact, preventing socket send buffer contention and write timeouts
            with ThreadPoolExecutor(max_workers=1) as pool:
                for k, ukey in pool.map(_upload_one, upload_queue):
                    artifact_keys[k] = ukey
        except Exception as exc:
            detail_txt = f"{type(exc).__name__}: {str(exc)[:160]}"
            print(f"[analysis_child] persistent storage upload warning for {analysis_id}: {detail_txt}; continuing with local storage", flush=True)
            seclog.log_event("artifact_upload_warning",
                             route="analysis_child", method="POST",
                             status=0,
                             detail=f"{analysis_id}: {str(exc)[:120]}")

    return local_paths, artifact_keys, 0


def run(analysis_id, user_id, image_path, filename, manual_mpp, scale_cap,
        analysis_type="graphite_nodularity", method="gsat"):
    t0 = time.time()
    # Fresh process: open the DB + run migrations before anything touches it
    # (server.py does this at import time; the child cannot rely on that).
    store.init_db()
    pending = store.get_analysis_record(analysis_id, user_id) or {}
    data = Path(image_path).read_bytes()
    try:
        analysis_type = str(analysis_type or "graphite_nodularity").strip() or "graphite_nodularity"
        if analysis_type == "steel_grain_size":
            # Steel Grain-Size Analysis — dispatched to the two real
            # pipelines (GSAT / ASTM estimator). This branch must never
            # touch the nodularity engine below.
            def _steel_progress(p):
                _set_progress(analysis_id, user_id, int(p))

            payload = steel_pipeline.analyze_image(
                data, calibration=manual_mpp, method=method,
                progress_cb=_steel_progress)
            images = payload.pop("images", {}) or {}
            payload["analysis_type"] = "steel_grain_size"
            payload["filename"] = filename
            payload["analysis_id"] = analysis_id
            if payload.get("status") == "failed":
                raise _JobFailure(payload.get("error") or
                                  "Steel grain-size analysis failed on the "
                                  "server.")

            local_paths, artifact_keys, code = _save_and_upload_artifacts(
                analysis_id, user_id, image_path, images, pending)
            if code != 0:
                return code
            if artifact_keys:
                payload["artifact_keys"] = artifact_keys

            record = {
                **pending,
                "id": analysis_id,
                "status": "completed",
                "progress": 100,
                "type": "Steel Grain-Size Analysis",
                "analysis_type": "steel_grain_size",
                "method": payload.get("method", method),
                "method_label": payload.get("method_label"),
                "pipeline_status": {
                    name: p.get("status")
                    for name, p in (payload.get("pipelines") or {}).items()},
                "warnings": payload.get("warnings", []),
                "source_width": payload.get("source_width"),
                "source_height": payload.get("source_height"),
                "calibrated": bool((payload.get("calibration") or {}) 
                                   .get("available")),
                "filename": filename,
            }
            payload["processing_time_s"] = round(time.time() - t0, 2)
            context_svc.save_full_analysis(analysis_id, payload)
            store.insert_analysis(record, user_id)
            seclog.log_event("analysis_completed", route="analysis_child",
                             method="POST", status=0,
                             detail=f"{analysis_id} (steel/"
                                    f"{payload.get('method')}): "
                                    f"{round(time.time() - t0, 1)}s")
            return 0

        elif analysis_type == "white_cast_iron_carbide":
            def _wci_progress(p):
                _set_progress(analysis_id, user_id, int(p))

            payload = white_cast_iron_pipeline.analyze_image(
                data, calibration=manual_mpp, method=method,
                progress_cb=_wci_progress)
            images = payload.pop("images", {}) or {}
            payload["analysis_type"] = "white_cast_iron_carbide"
            payload["filename"] = filename
            payload["analysis_id"] = analysis_id
            if payload.get("status") == "failed":
                raise _JobFailure(payload.get("error") or
                                  "White cast iron carbide analysis failed on the server.")

            local_paths, artifact_keys, code = _save_and_upload_artifacts(
                analysis_id, user_id, image_path, images, pending)
            if code != 0:
                return code
            if artifact_keys:
                payload["artifact_keys"] = artifact_keys

            record = {
                **pending,
                "id": analysis_id,
                "status": "completed",
                "progress": 100,
                "type": "White Cast Iron Carbide Analysis",
                "analysis_type": "white_cast_iron_carbide",
                "method": payload.get("method", method),
                "method_label": payload.get("method_label"),
                "carbide_count": (payload.get("white_cast_iron") or {}).get("carbide_count", 0),
                "warnings": payload.get("warnings", []),
                "source_width": payload.get("source_width"),
                "source_height": payload.get("source_height"),
                "calibrated": bool((payload.get("calibration") or {}).get("available")),
                "filename": filename,
            }
            payload["processing_time_s"] = round(time.time() - t0, 2)
            context_svc.save_full_analysis(analysis_id, payload)
            store.insert_analysis(record, user_id)
            seclog.log_event("analysis_completed", route="analysis_child",
                             method="POST", status=0,
                             detail=f"{analysis_id} (white_cast_iron/{payload.get('method')}): {round(time.time() - t0, 1)}s")
            return 0

        elif analysis_type == "gray_cast_iron_graphite_flake":
            def _gci_progress(p):
                _set_progress(analysis_id, user_id, int(p))

            # Dimension guard: downscale very large photos (>scale_cap px) to preserve memory and speed
            gci_data = data
            gci_mpp = manual_mpp
            try:
                arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if arr is not None:
                    h, w = arr.shape[:2]
                    max_side = max(h, w)
                    if max_side > scale_cap:
                        scale = scale_cap / max_side
                        arr_resized = cv2.resize(arr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
                        ok, enc = cv2.imencode(".png", arr_resized)
                        if ok:
                            gci_data = enc.tobytes()
                            if gci_mpp is not None and gci_mpp > 0:
                                gci_mpp = gci_mpp / scale
            except Exception:
                gci_data = data
                gci_mpp = manual_mpp

            payload = gray_cast_iron_pipeline.analyze_image(
                gci_data, calibration=gci_mpp, method=method,
                progress_cb=_gci_progress)
            images = payload.pop("images", {}) or {}
            payload["analysis_type"] = "gray_cast_iron_graphite_flake"
            payload["filename"] = filename
            payload["analysis_id"] = analysis_id
            if payload.get("status") == "failed":
                raise _JobFailure(payload.get("error") or
                                  "Gray cast iron graphite flake analysis failed on the server.")

            local_paths, artifact_keys, code = _save_and_upload_artifacts(
                analysis_id, user_id, image_path, images, pending)
            if code != 0:
                return code
            if artifact_keys:
                payload["artifact_keys"] = artifact_keys

            sc = payload.get("self_check") or (payload.get("gray_cast_iron") or {}).get("self_check") or {}
            record = {
                **pending,
                "id": analysis_id,
                "status": "completed",
                "progress": 100,
                "type": "Gray Cast Iron Graphite Flake Analysis",
                "analysis_type": "gray_cast_iron_graphite_flake",
                "method": payload.get("method", method),
                "method_label": payload.get("method_label"),
                "flake_count": (payload.get("gray_cast_iron") or {}).get("flake_count", 0),
                "qualified_flake_count": (payload.get("gray_cast_iron") or {}).get("qualified_flake_count", 0),
                "raw_flake_count": (payload.get("gray_cast_iron") or {}).get("raw_flake_count", 0),
                "accuracy_pct": sc.get("count_accuracy_pct", 100.0),
                "warnings": payload.get("warnings", []),
                "source_width": payload.get("source_width"),
                "source_height": payload.get("source_height"),
                "calibrated": bool((payload.get("calibration") or {}).get("available")),
                "filename": filename,
            }
            payload["processing_time_s"] = round(time.time() - t0, 2)
            context_svc.save_full_analysis(analysis_id, payload)
            store.insert_analysis(record, user_id)
            seclog.log_event("analysis_completed", route="analysis_child",
                             method="POST", status=0,
                             detail=f"{analysis_id} (gray_cast_iron/{payload.get('method')}): {round(time.time() - t0, 1)}s")
            return 0

        # Memory guard for small containers: very large photos are downscaled
        # once to <=scale_cap px on the long side before analysis. Nodularity
        # metrics are UNAFFECTED: ISO (area ratio), JIS (count shares),
        # roundness and graphite form are all scale-invariant under uniform
        # rescaling; particle COUNT can only change for sub-resolution
        # specks, which the pipeline already filters by a minimum-area rule.
        arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        h, w = arr.shape[:2]
        scale = 1.0
        max_side = max(h, w)
        if max_side > scale_cap:
            scale = scale_cap / max_side
            arr = cv2.resize(arr, (int(round(w * scale)), int(round(h * scale))),
                             interpolation=cv2.INTER_AREA)
            _, png_buf = cv2.imencode(".png", arr)
            data = png_buf.tobytes()
            seclog.log_event("upload_downscaled", route="analysis_child",
                             method="POST", status=0,
                             detail=f"{w}x{h} -> {arr.shape[1]}x{arr.shape[0]}")
        res = analyze_image(data)
        _set_progress(analysis_id, user_id, 45)
        validation = evaluate_microstructure_validity(data, res)
        if not validation.get("valid"):
            raise _JobFailure("Not a valid microstructure image — "
                              + str(validation.get("reason") or
                                    "the engine could not segment graphite "
                                    "particles from this photo."))
        payload, err = analyze_for_frontend_json(data, res=res)
        if err:
            raise _JobFailure(str(err))
        _set_progress(analysis_id, user_id, 70)

        quality = None
        try:
            color, gray, (src_w, src_h) = load_with_source(data)
            quality = assess_quality(gray, src_w, src_h, bgr=color)
            if CFG.enable_calibration:
                auto_calibrate(gray)
        except Exception:
            quality = None
        if quality:
            payload["quality"] = quality

        cal_dict = payload.get("calibration") or {}
        effective_mpp = manual_mpp or validate_um_per_px(cal_dict.get("um_per_px"))
        if manual_mpp and not cal_dict.get("available"):
            payload["calibration"] = make_calibration(
                manual_mpp, source="manual",
                notes="client-provided microns_per_pixel for this analysis").to_dict()
        elif manual_mpp:
            payload["calibration"]["source"] = "manual"
            payload["calibration"]["notes"] = ("client-provided "
                                               "microns_per_pixel for this "
                                               "analysis")
        try:
            _shim = {"rows": payload.get("nodules") or []}
            apply_size_filter_and_iso(_shim, effective_mpp)
            payload["iso_size_qualified_pct"] = _shim["iso_size_qualified_pct"]
            payload["size_filter"] = _shim["size_filter"]
        except Exception:
            payload.setdefault("size_filter", {
                "available": False, "threshold_um": 10.0, "applied": False,
                "excluded_count": None, "included_count": None,
                "reason": "Physical calibration unavailable"})

        try:
            payload["nodules"] = enrich_rows(res["rows"], res["contours"],
                                             (payload.get("self_check") or {})
                                             .get("f1_pct"))
        except Exception:
            pass

        try:
            payload["graphite_forms"] = classify_graphite_forms(
                payload.get("nodules") or [])
        except Exception:
            pass
        try:
            payload["property_estimates"] = estimate_properties(
                payload.get("iso_nodularity_pct"))
        except Exception:
            pass

        try:
            src_hist = {}
            for r_ in res["rows"]:
                src_hist[r_.get("source", "unknown")] = \
                    src_hist.get(r_.get("source", "unknown"), 0) + 1
            payload["detections"] = {"sources": src_hist}
        except Exception:
            pass

        payload["filename"] = filename
        payload["processing_time_s"] = round(time.time() - t0, 2)
        if scale != 1.0:
            payload["analyzed_at_scale"] = round(scale, 5)
            payload.setdefault("warnings", []).append(
                f"large image downscaled {w}x{h} -> {arr.shape[1]}x{arr.shape[0]} "
                "for analysis; nodularity percentages are unaffected")
            cal = payload.get("calibration")
            if isinstance(cal, dict) and cal.get("available") and cal.get("um_per_px"):
                cal["um_per_px"] = round(cal["um_per_px"] / scale, 6)
        _set_progress(analysis_id, user_id, 90)

        record = {
            **pending,
            "id": analysis_id,
            "status": "completed",
            "progress": 100,
            "nodule_count": payload["nodule_count"],
            "iso_nodularity_pct": payload["iso_nodularity_pct"],
            "jis_nodularity_pct": payload["jis_nodularity_pct"],
            "accuracy_pct": (payload.get("self_check") or {}).get(
                "count_accuracy_pct"),
            "confidence_pct": (payload.get("self_check") or {}).get("f1_pct"),
            "warnings": payload.get("warnings", []),
            "source_width": payload.get("source_width"),
            "source_height": payload.get("source_height"),
            "quality_score": (payload.get("quality") or {}).get("score"),
            "quality_status": (payload.get("quality") or {}).get("status"),
        }
        local_annotated = context_svc.FULL_DIR / f"{analysis_id}_annotated.png"
        local_mask = context_svc.FULL_DIR / f"{analysis_id}_mask.png"
        try:
            cv2.imwrite(str(local_annotated), res["annotated"])
            cv2.imwrite(str(local_mask), res["mask"])
        except Exception:
            pass
        artifact_keys = {}
        import os as _os
        if _os.environ.get("SUPABASE_URL") and \
                _os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
            from nodiq.services import storage as storage_svc
            try:
                original = Path(image_path).read_bytes()
                artifact_keys["original"] = storage_svc.put_bytes(
                    user_id, analysis_id, "original", original)
                artifact_keys["annotated"] = storage_svc.put_bytes(
                    user_id, analysis_id, "annotated",
                    local_annotated.read_bytes())
                artifact_keys["mask"] = storage_svc.put_bytes(
                    user_id, analysis_id, "mask", local_mask.read_bytes())
            except Exception as exc:
                detail_txt = f"{type(exc).__name__}: {str(exc)[:160]}"
                print(f"[analysis_child] persistent storage upload warning for "
                      f"{analysis_id}: {detail_txt}; continuing with local storage", flush=True)
                payload.setdefault("warnings", []).append(
                    f"Remote artifact upload skipped: {detail_txt[:80]}")
                seclog.log_event("artifact_upload_warning",
                                 route="analysis_child", method="POST",
                                 status=0,
                                 detail=f"{analysis_id}: {str(exc)[:120]}")
        payload["analysis_id"] = analysis_id
        if artifact_keys:
            payload["artifact_keys"] = artifact_keys
        context_svc.save_full_analysis(analysis_id, payload)
        store.insert_analysis(record, user_id)

        seclog.log_event("analysis_completed", route="analysis_child",
                         method="POST", status=0,
                         detail=f"{analysis_id}: "
                                f"{round(time.time() - t0, 1)}s")
        return 0
    except _JobFailure as exc:
        _fail(analysis_id, user_id, pending, str(exc))
        return 3
    except MemoryError:
        _fail(analysis_id, user_id, pending,
              "Analysis ran out of memory on the server — please try a "
              "smaller version of this image.")
        return 3
    except Exception:
        _fail(analysis_id, user_id, pending,
              "Analysis failed on the server — please try again. Very "
              "large images can exceed free-tier memory; a smaller "
              "version of the same micrograph works too.")
        return 1


def _fail(analysis_id, user_id, pending, message):
    seclog.log_event("analysis_failed", route="analysis_child",
                     method="POST", status=0,
                     detail=f"{analysis_id}: {message[:80]}")
    store.insert_analysis({**pending, "id": analysis_id,
                           "status": "failed", "progress": 100,
                           "error": message}, user_id)


def main(argv):
    analysis_id, user_id, image_path, filename = argv[0], argv[1], argv[2], argv[3]
    manual_mpp = float(argv[4]) if argv[4] else None
    scale_cap = int(argv[5])
    analysis_type = argv[6] if len(argv) > 6 else "graphite_nodularity"
    method = argv[7] if len(argv) > 7 else "gsat"
    return run(analysis_id, user_id, image_path, filename, manual_mpp,
               scale_cap, analysis_type=analysis_type, method=method)


if __name__ == "__main__":
    if len(sys.argv) not in (7, 9):
        print(json.dumps({"error": "usage: analysis_child.py <id> <user> "
                                   "<image> <filename> <mpp|''> <cap> "
                                   "[<analysis_type> <method>]"}),
              file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
