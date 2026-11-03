#!/usr/bin/env python3
"""
services/capabilities.py — dynamic Capability Registry (Phases 18, 24, 45).

Every NODIQ-X capability (existing or future) registers itself here with a
description, its tools and its safe UI actions. The Copilot discovers
capabilities dynamically — "what can you do?" is answered from this registry,
never hard-coded. Adding a feature tomorrow = one register_capability() call.
"""
import threading

_LOCK = threading.Lock()
_CAPABILITIES = {}


def register_capability(name, description, tools=None, actions=None,
                        ui=None):
    """Register (or update) a capability.

    name         stable id, e.g. "quality_gate"
    description  one sentence the Copilot can quote to users
    tools        list of tool names the Copilot may call for this capability
    actions      list of safe UI action names this capability can trigger
    ui           optional dict describing related UI controls (for Phase 24
                 "what does Calibration do?" answers)
    """
    with _LOCK:
        _CAPABILITIES[name] = {
            "name": name,
            "description": description,
            "tools": list(tools or []),
            "actions": list(actions or []),
            "ui": ui or {},
        }
    return _CAPABILITIES[name]


def get_capabilities():
    with _LOCK:
        return sorted(_CAPABILITIES.values(), key=lambda c: c["name"])


def get_capability(name):
    with _LOCK:
        return _CAPABILITIES.get(name)


def capabilities_digest():
    """Compact text listing for LLM prompts / fallback answers."""
    lines = []
    for c in get_capabilities():
        lines.append(f"- {c['name']}: {c['description']}")
    return "\n".join(lines)


# ------------------------- built-in registrations (tools registered in ai/) --
register_capability(
    "analysis",
    "Detect and count graphite nodules; measure ISO/JIS nodularity from "
    "micrographs",
    tools=["get_current_analysis", "get_analysis", "analyze_image",
           "get_nodule_details"],
    actions=["show_nodule", "open_analysis"],
    ui={"page": "New Analysis", "controls": {
        "upload": "analyze an uploaded micrograph",
        "dataset_browser": "pick one of the 1000 validated dataset images"}})

register_capability(
    "quality_gate",
    "Evaluate micrograph image quality (resolution, focus, contrast, "
    "illumination, noise) before trusting measurements",
    tools=["get_quality_report"],
    actions=["show_quality"])

register_capability(
    "calibration",
    "Convert pixel measurements to physical dimensions (µm) via scale-bar "
    "detection or manual calibration",
    tools=["get_calibration"],
    actions=["show_calibration"],
    ui={"controls": {
        "manual": "provide the scale-bar pixel length and its physical "
                  "length to enable µm measurements"}})

register_capability(
    "nodule_details",
    "Inspect individual nodules: geometry (area, perimeter, circularity, "
    "solidity, aspect), roundness, ISO/JIS class, detection source and "
    "confidence",
    tools=["get_nodule_details"],
    actions=["show_nodule"])

register_capability(
    "comparison",
    "Compare two samples on measured metrics: nodularity, count, ISO/JIS, "
    "roundness, size distribution",
    tools=["compare_samples"],
    actions=["open_comparison"])

register_capability(
    "batch_analytics",
    "Aggregate statistics over analysis history: mean/median/std, pass-fail "
    "rates, distributions",
    tools=["get_batch_statistics"],
    actions=["show_batch"])

register_capability(
    "spc",
    "Statistical process control: control limits (UCL/LCL), Western-Electric "
    "rule violations and trend for nodularity and related metrics",
    tools=["get_spc"],
    actions=["show_spc"])

register_capability(
    "anomaly_detection",
    "Explainable anomaly detection over history: severity + explicit reasons",
    tools=["get_anomalies"],
    actions=["show_anomaly"])

register_capability(
    "validation",
    "Engine validation: internal 1000-image batch, blind tests, synthetic "
    "and external validation — each reported separately",
    tools=["get_validation"],
    actions=["open_validation"])

register_capability(
    "reports",
    "Generate engineering reports (PDF/CSV/JSON) with measured facts, "
    "anomaly analysis and AI interpretation clearly separated",
    tools=["generate_report", "get_report"],
    actions=["generate_report"])

register_capability(
    "decision_support",
    "Deterministic MEASURED -> OBSERVED -> INTERPRETATION -> RECOMMENDATION "
    "chains from morphology evidence; never claims process causation",
    tools=["get_decision_support"],
    actions=[])

register_capability(
    "reference",
    "Explain NODIQ-X methodology, ISO/JIS classification concepts and "
    "microstructure terminology used by this application",
    tools=["search_reference"],
    actions=[])
