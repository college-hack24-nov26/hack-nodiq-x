#!/usr/bin/env python3
"""
ai/fallback_provider.py — the NODIQ-X intelligent fallback (Phases 15, 36).

A deterministic answer engine over the structured context. It is NOT an LLM
and never pretends to be one (Phase 36: "Never pretend a deterministic
fallback is an LLM"). It answers the common metallurgical questions from real
measured data and states clearly when something isn't available.

Always available — this is the bottom of the chain that guarantees the
Copilot never dead-ends, online or offline.
"""
from nodiq.ai.provider import AIProvider


def get_provider():
    return FallbackProvider()


def _ctx_val(context, *path):
    node = context or {}
    for p in path:
        if not isinstance(node, dict):
            return None
        node = node.get(p)
    return node


def _fmt(v, nd=1, suffix=""):
    if isinstance(v, (int, float)):
        return f"{v:.{nd}f}{suffix}"
    return str(v) if v is not None else "not available"


class FallbackProvider(AIProvider):
    name = "fallback"

    def available(self):
        return True

    def chat(self, messages, context=None, stream=False):
        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = (m.get("content") or "").lower()
                break
        content = self._answer(user_text, context)
        return {"content": content, "provider": "fallback",
                "model": "nodiq-rules"}

    # ------------------------------------------------------------------
    def _answer(self, q, context):
        iso = _ctx_val(context, "iso945", "nodularity_pct")
        jis = _ctx_val(context, "jis", "nodularity_pct")
        count = _ctx_val(context, "detections", "count")
        f1 = _ctx_val(context, "self_check", "f1_pct")
        quality = _ctx_val(context, "quality", "score")
        quality_status = _ctx_val(context, "quality", "status")
        cal = _ctx_val(context, "calibration") or {}
        filename = _ctx_val(context, "sample", "filename")

        def has(*words):
            return any(w in q for w in words)

        if has("what can you do", "what else", "capabilities", "features",
               "help me"):
            from nodiq.services.capabilities import capabilities_digest
            return ("I can help you with:\n\n"
                    + capabilities_digest()
                    + "\n\nYou can also ask questions about the current "
                      "analysis — I answer from measured data only.")

        if has("quality", "blur", "focus", "resolution okay", "image ok"):
            if quality is None:
                return ("That information isn't available for the current "
                        "analysis — no quality assessment was recorded.")
            return (f"Measured image quality is {quality}/100 "
                    f"({quality_status}). "
                    f"Checks: {', '.join(f'{k}={v}' for k, v in (_ctx_val(context, 'quality', 'metrics') or {}).items())}. "
                    "The analysis engine ran regardless; quality affects how "
                    "much the measurements can be trusted.")

        if has("10 µm", "10 um", "10um", "size filter", "size rule",
               "minimum size", "feret") or ("excluded" in q
                                            and "size" in q):
            sf = _ctx_val(context, "iso945", "size_filter") or {}
            sq = _ctx_val(context, "iso945", "nodularity_size_qualified_pct")
            if sf.get("applied"):
                return (f"Yes — the ISO 945-4 10 µm minimum Feret diameter "
                        f"exclusion WAS applied (physical calibration is "
                        f"active): {sf.get('excluded_count')} of "
                        f"{(sf.get('excluded_count') or 0) + (sf.get('included_count') or 0)} "
                        f"particles were excluded below 10 µm and "
                        f"{sf.get('included_count')} remain. "
                        + (f"The size-qualified ISO nodularity is {sq}%. "
                           if isinstance(sq, (int, float)) else "")
                        + "Excluded particles are marked "
                          "size_filter_status='excluded_below_10um' in the "
                          "per-particle data.")
            return ("No — the 10 µm ISO 945-4 minimum-size rule was NOT "
                    "applied to this analysis: physical scale calibration "
                    "is unavailable, so particle sizes cannot be converted "
                    "to µm and the criterion is not evaluable. No µm values "
                    "were invented. With a trusted calibration (manual bar "
                    "length or declared scale bar) the filter is applied "
                    "and a size-qualified ISO value is reported.")

        if has("multi-field", "multi field", "multifield", "fields of view",
               "how many fields", "field target", "500 particles",
               "sampling status", "aggregate"):
            mf = _ctx_val(context, "multifield")
            if not isinstance(mf, dict):
                return ("This analysis is not part of a multi-field "
                        "session, so there is no aggregate to report. "
                        "Create one via POST /api/multifield, attach "
                        "completed analyses as fields, and the session "
                        "tracks the ISO 945-4 sampling targets (5 fields, "
                        "500 particles).")
            sampling = mf.get("sampling_status", "unknown")
            parts = [
                f"Multi-field session {mf.get('session_id')}: "
                f"{mf.get('field_count')} field(s) attached, "
                f"{mf.get('eligible_field_count')} eligible, "
                f"{mf.get('total_particle_count')} total particles "
                f"({mf.get('total_qualified_particle_count') or 0} "
                f"qualified). Sampling status: {sampling}."
            ]
            if mf.get("aggregate_iso_nodularity_pct") is not None:
                parts.append(
                    f"Aggregate ISO nodularity (area-based, not an average "
                    f"of field percentages): "
                    f"{mf['aggregate_iso_nodularity_pct']}% from "
                    f"{mf.get('aggregate_spheroidal_area')} / "
                    f"{mf.get('aggregate_graphite_area')} um2 of eligible "
                    f"graphite.")
            if mf.get("aggregate_jis_nodularity_pct") is not None:
                parts.append(
                    f"Aggregate JIS (count-based): "
                    f"{mf['aggregate_jis_nodularity_pct']}%.")
            cal = mf.get("calibration") or {}
            cal_text = (
                f"Calibration: {cal.get('fields_calibrated', 0)}/"
                f"{cal.get('fields_total', 0)} fields calibrated")
            if not cal.get("complete"):
                cal_text += (" — the 10 um rule is not evaluable for "
                             "uncalibrated fields")
            parts.append(cal_text + ".")
            for n in mf.get("notes") or []:
                parts.append(n)
            if mf.get("this_field"):
                tf = mf["this_field"]
                parts.append(
                    f"This field: {tf.get('particle_count')} particles, "
                    f"{tf.get('border_count')} border-touching, "
                    f"{'eligible' if tf.get('eligible') else 'excluded: ' + str(tf.get('exclusion_reason'))}.")
            return " ".join(parts)

        if has("compliant", "compliance", "certified", "iso 945-4"):
            sf = _ctx_val(context, "iso945", "size_filter") or {}
            if sf.get("applied"):
                return ("The calculation follows the verified ISO 945-4 "
                        "roundness definition, the 0.6 spheroidal "
                        "threshold, the area-weighted method and the "
                        "border exclusion, and the 10 µm minimum-size "
                        "criterion was evaluable with the active "
                        "calibration. This is an ISO 945-4-based "
                        "calculation, not a formal certification — full "
                        "compliance would also require the standard's "
                        "sampling rules (multiple fields, calibrated "
                        "optics).")
            return ("The calculation follows the verified ISO 945-4 "
                    "roundness and area methodology, but the 10 µm "
                    "minimum-size criterion was not evaluable without "
                    "physical calibration — so this is an ISO 945-4-based "
                    "result, not a fully standards-complete measurement.")

        if has("scale", "calibration", "µm", "um ", "micrometer", "physical"):
            if cal.get("available"):
                return (f"Calibration is active ({cal.get('source')}): "
                        f"{cal.get('um_per_px', 0):.4f} µm/pixel"
                        + (f" (bar {cal.get('bar_length_um')} µm = "
                           f"{cal.get('bar_length_px')} px)"
                           if cal.get("bar_length_px") else "")
                        + ". Nodule sizes are reported in µm alongside px.")
            return ("Scale unavailable. No trusted scale-bar calibration "
                    "exists for this image, so sizes are reported in pixels "
                    "only — I will not invent µm values. You can supply a "
                    "manual calibration (bar length in px and µm).")

        if has("batch", "statistics", "stats", "pass rate", "spc",
               "control limit", "history"):
            batch = _ctx_val(context, "batch_summary")
            if isinstance(batch, dict) and batch.get("samples"):
                nod = batch.get("mean_nodularity")
                lines = [
                    f"Batch statistics over {batch.get('samples')} stored "
                    f"analyses: pass rate {batch.get('pass_rate_pct')}% "
                    f"(ISO >= 80% gate), mean nodularity "
                    f"{_fmt(nod)}%" +
                    (f" (std {batch.get('std_nodularity')})"
                     if batch.get('std_nodularity') is not None else "")
                    + "."]
                spc = _ctx_val(context, "spc")
                if isinstance(spc, dict):
                    if spc.get("sufficient_data"):
                        lines.append(
                            f"SPC ({spc.get('metric')}): mean "
                            f"{spc.get('mean')}, UCL {spc.get('ucl')}, "
                            f"LCL {spc.get('lcl')}, "
                            f"{spc.get('violations')} rule violations, "
                            f"trend {spc.get('trend')}.")
                    else:
                        lines.append(
                            "SPC: " + spc.get("note",
                                              "insufficient data for control "
                                              "limits"))
                return " ".join(lines)
            return ("No batch history is available yet — analyze a few "
                    "micrographs and I can report pass rates, means and SPC "
                    "control limits.")

        if has("anomaly", "unusual", "wrong", "concern"):
            anomalies = _ctx_val(context, "anomalies")
            if isinstance(anomalies, dict) and anomalies.get("is_anomaly"):
                reasons = "; ".join(anomalies.get("reasons", []))
                return (f"Anomaly check: {anomalies.get('severity')} "
                        f"(score {anomalies.get('anomaly_score')}/100). "
                        f"Reasons: {reasons}.")
            if isinstance(anomalies, dict):
                return ("No anomaly signals for this analysis — nodularity "
                        "and morphology are within the observed batch range.")
            return ("That information isn't available — no anomaly "
                    "assessment was computed for this analysis.")

        if has("which measurement", "which metric", "caused it",
               "caused the"):
            ds = _ctx_val(context, "decision_support") or {}
            obs = ds.get("observed") or []
            meas = ds.get("measured") or []
            if obs or meas:
                parts = []
                if meas:
                    parts.append("Measured: " + "; ".join(meas) + ".")
                if obs:
                    parts.append("Observed: " + "; ".join(obs) + ".")
                irr_note = [o for o in obs if "irregular" in o.lower()]
                if irr_note:
                    parts.append(
                        "The irregular-particle fraction is the measurement "
                        "driving the nodularity result — it is derived "
                        "directly from the per-particle roundness values.")
                return " ".join(parts)
            return ("That information isn't available for the current "
                    "analysis.")

        if has("compare", "versus", " vs ", "previous sample"):
            comp = _ctx_val(context, "comparison")
            if isinstance(comp, dict) and comp.get("summary"):
                return comp["summary"]
            return ("That information isn't available — no comparison "
                    "sample was set in the conversation context.")

        if has("why", "explain", "failed", "low", "cause"):
            ds = _ctx_val(context, "decision_support") or {}
            parts = []
            if ds.get("measured"):
                parts.append("MEASURED: " + "; ".join(ds["measured"]) + ".")
            if ds.get("observed"):
                parts.append("OBSERVED: " + "; ".join(ds["observed"]) + ".")
            if ds.get("interpretation"):
                parts.append("INTERPRETATION: "
                             + " ".join(ds["interpretation"]))
            if ds.get("recommendation"):
                parts.append("RECOMMENDATION: "
                             + " ".join(ds["recommendation"]))
            if parts:
                return "\n\n".join(parts)
            return ("That information isn't available for the current "
                    "analysis.")

        if has("count", "how many", "nodularity", "result", "jis", "iso"):
            if count is None and iso is None:
                return ("No analysis is loaded in the current context. "
                        "Upload or select a micrograph first.")
            text = []
            if count is not None:
                text.append(f"Measured: {count} graphite particles detected")
            if iso is not None:
                text.append(f"ISO nodularity {_fmt(iso, 1, '%')}")
            if jis is not None:
                text.append(f"JIS nodularity {_fmt(jis, 1, '%')}")
            if f1 is not None:
                text.append(f"self-check F1 {_fmt(f1, 1, '%')}")
            return (". ".join(text) + "."
                    + (f" (Sample: {filename})" if filename else ""))

        if has("report", "generate"):
            return ("I can generate a report from the current analysis — "
                    "it will contain the measured results, quality, "
                    "calibration status, anomaly analysis and recommendations. "
                    "Use the Reports page, or ask me to 'generate a report' "
                    "while an analysis is loaded.")

        # default: summarize the loaded analysis from real data
        if count is not None or iso is not None:
            return (f"Current analysis{(' — ' + filename) if filename else ''}: "
                    f"{_fmt(count, 0)} particles, ISO nodularity "
                    f"{_fmt(iso, 1, '%')}, JIS {_fmt(jis, 1, '%')}, "
                    f"self-check F1 {_fmt(f1, 1, '%')}, image quality "
                    f"{_fmt(quality, 0)}. "
                    "Ask me about quality, calibration, anomalies, "
                    "comparisons, SPC or reports.")
        return ("I'm running in offline fallback mode (no LLM configured), "
                "answering from measured NODIQ-X data only. Load an analysis "
                "and ask about the count, nodularity, quality, calibration, "
                "anomalies, batch statistics or reports. To enable full "
                "conversational AI, install Ollama and set AI_PROVIDER=local.")
