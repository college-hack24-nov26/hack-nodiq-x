#!/usr/bin/env python3
"""
ai/tools.py — controlled NODIQ-X tool system (Phases 19-21).

The LLM can ONLY call tools registered here. Every call passes through
validate_action(), which enforces:
  * allowlist (unknown tool -> rejected)
  * argument schema (type/required checks)
  * bounded string/ids (no paths, no shell metacharacters)

Tool implementations receive a ToolContext built by server.py (data access
injected; this module never touches the DB or disk directly).
NEVER any shell/arbitrary code/SQL/HTTP access from tools.
"""
import re
import threading

from nodiq.ai.provider import ProviderUnavailable

_LOCK = threading.Lock()
_TOOLS = {}


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- registry ----
def register_tool(name, description, args_schema, func):
    """args_schema: {arg_name: {"type": "str|int|float|bool", "required": bool,
    "max_len": int, "description": str}}"""
    with _LOCK:
        _TOOLS[name] = {"name": name, "description": description,
                        "args_schema": args_schema, "func": func}


def tool_digest():
    """Compact tool list for the system prompt."""
    lines = []
    for t in sorted(_TOOLS.values(), key=lambda x: x["name"]):
        args = ", ".join(
            f"{n}:{s['type']}{'?' if not s.get('required') else ''}"
            for n, s in t["args_schema"].items())
        lines.append(f"- {t['name']}({args}): {t['description']}")
    return "\n".join(lines)


def tool_names():
    with _LOCK:
        return sorted(_TOOLS.keys())


# ------------------------------------------------------------ validation ----
_ID_RE = re.compile(r"^[A-Za-z0-9_\-\.]{1,64}$")
_NAME_RE = re.compile(r"^micrograph_[0-9]{4}\.png$")


def _check_str(name, value, spec):
    if not isinstance(value, str):
        raise ToolError(f"argument '{name}' must be a string")
    max_len = spec.get("max_len", 200)
    if len(value) > max_len:
        raise ToolError(f"argument '{name}' too long (>{max_len})")
    if spec.get("format") == "analysis_id" and not _ID_RE.match(value):
        raise ToolError(f"argument '{name}' has invalid characters")
    if spec.get("format") == "image_name" and not _NAME_RE.match(value):
        raise ToolError(f"argument '{name}' must be a dataset image name")
    forbidden = ("..", "/", "\\", "$", "`", "|", ";", "&", ">", "<")
    if any(f in value for f in forbidden):
        raise ToolError(f"argument '{name}' contains forbidden characters")
    return value


def validate_action(action):
    """Validate a structured action against the registry (allowlist).

    Returns (tool_name, clean_args). Raises ToolError on any violation.
    """
    if not isinstance(action, dict):
        raise ToolError("action must be a JSON object")
    name = action.get("tool")
    if not isinstance(name, str) or name not in _TOOLS:
        raise ToolError(
            f"tool '{name}' is not in the registered allowlist")
    tool = _TOOLS[name]
    args = action.get("args") or {}
    if not isinstance(args, dict):
        raise ToolError("'args' must be an object")
    clean = {}
    for arg_name, spec in tool["args_schema"].items():
        if arg_name in args:
            value = args[arg_name]
            stype = spec.get("type", "str")
            if stype == "str":
                clean[arg_name] = _check_str(arg_name, value, spec)
            elif stype == "int":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ToolError(f"argument '{arg_name}' must be an integer")
                clean[arg_name] = value
            elif stype == "float":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ToolError(f"argument '{arg_name}' must be a number")
                clean[arg_name] = float(value)
            elif stype == "bool":
                if not isinstance(value, bool):
                    raise ToolError(f"argument '{arg_name}' must be a boolean")
                clean[arg_name] = value
        elif spec.get("required"):
            raise ToolError(f"missing required argument '{arg_name}'")
    # reject unknown args outright (prevents smuggling)
    unknown = set(args) - set(tool["args_schema"])
    if unknown:
        raise ToolError(f"unknown arguments: {sorted(unknown)}")
    return name, clean


def execute_action(action, ctx):
    """Validate then execute. Returns a JSON-safe dict (tool result)."""
    try:
        name, args = validate_action(action)
    except ToolError as exc:
        return {"error": f"action rejected: {exc}"}
    try:
        result = _TOOLS[name]["func"](ctx=ctx, **args)
        return result if isinstance(result, dict) else {"result": result}
    except ToolError as exc:
        return {"error": str(exc)}
    except ProviderUnavailable as exc:
        return {"error": f"provider unavailable: {exc}"}
    except Exception as exc:  # tool-level failure reported to the LLM
        return {"error": f"{type(exc).__name__}: {exc}"}


# ------------------------------------------------------------------ tools ----
def _register_all():
    if _TOOLS:            # already registered
        return

    def get_current_analysis(ctx):
        """The analysis the conversation is about."""
        aid = ctx.get("analysis_id")
        if not aid:
            latest = ctx["latest_analysis"]()
            if not latest:
                return {"error": "no analyses in history yet"}
            aid = latest["id"]
            ctx["analysis_id"] = aid
        contract = ctx["contract"](aid)
        if not contract:
            return {"error": f"analysis {aid} not found"}
        return _compact_contract(contract)

    register_tool(
        "get_current_analysis",
        "Get the full measured results of the analysis currently in context",
        {}, get_current_analysis)

    def get_analysis(ctx, analysis_id=None):
        aid = analysis_id or ctx.get("analysis_id") \
            or (ctx["latest_analysis"]() or {}).get("id")
        if not aid:
            return {"error": "no analysis id available"}
        contract = ctx["contract"](aid)
        if not contract:
            return {"error": f"analysis {aid} not found"}
        return _compact_contract(contract)

    register_tool(
        "get_analysis",
        "Get measured results for a specific analysis id",
        {"analysis_id": {"type": "str", "format": "analysis_id",
                         "required": False,
                         "description": "analysis id like ANL-1A2B3C"}},
        get_analysis)

    def analyze_image(ctx, dataset_image=None):
        """Run the CV engine on a dataset image (upload path handled by API)."""
        if not dataset_image:
            return {"error": "provide dataset_image (e.g. micrograph_0042.png) "
                             "or use the upload endpoint"}
        return ctx["analyze_dataset_image"](dataset_image)

    register_tool(
        "analyze_image",
        "Run the NODIQ-X engine on a dataset image and return measured results",
        {"dataset_image": {"type": "str", "format": "image_name",
                           "required": True,
                           "description": "dataset file name"}},
        analyze_image)

    def get_nodule_details(ctx, nodule_id=None):
        aid = ctx.get("analysis_id")
        if not aid:
            return {"error": "no analysis in context"}
        return ctx["nodule_details"](aid, nodule_id)

    register_tool(
        "get_nodule_details",
        "Inspect one nodule (or list notable nodules) from the current analysis",
        {"nodule_id": {"type": "int", "required": False,
                       "description": "nodule number; omit for notable ones"}},
        get_nodule_details)

    def get_quality_report(ctx):
        aid = ctx.get("analysis_id")
        if not aid:
            return {"error": "no analysis in context"}
        contract = ctx["contract"](aid)
        if not contract:
            return {"error": f"analysis {aid} not found"}
        return {"analysis_id": aid, "quality": contract.get("quality")}

    register_tool(
        "get_quality_report",
        "Get the image quality assessment of the current analysis",
        {}, get_quality_report)

    def get_calibration(ctx):
        aid = ctx.get("analysis_id")
        if not aid:
            return {"error": "no analysis in context"}
        contract = ctx["contract"](aid) or {}
        iso = contract.get("iso945") or {}
        return {"analysis_id": aid,
                "calibration": contract.get(
                    "calibration", {"available": False,
                                    "notes": "Scale unavailable"}),
                "size_filter": iso.get("size_filter"),
                "iso_size_qualified_pct": iso.get(
                    "nodularity_size_qualified_pct")}

    register_tool(
        "get_calibration",
        "Get the scale calibration status (µm per pixel) and the ISO 10 um "
        "size-filter state of the current analysis",
        {}, get_calibration)

    def compare_samples(ctx, sample_b=None):
        comp = ctx["compare"](ctx.get("analysis_id"), sample_b)
        if comp is None:
            return {"error": "comparison needs two analyses in history"}
        return comp

    register_tool(
        "compare_samples",
        "Compare the current analysis with another one (defaults to the "
        "previous/best other analysis)",
        {"sample_b": {"type": "str", "format": "analysis_id",
                      "required": False}},
        compare_samples)

    def get_batch_statistics(ctx):
        if not ctx.get("batch_enabled", True):
            return {"error": "batch analytics disabled by feature flag"}
        return ctx["batch_stats"]()

    register_tool(
        "get_batch_statistics",
        "Aggregate statistics over all stored analyses "
        "(mean/median/std, pass rate, distributions)",
        {}, get_batch_statistics)

    def get_spc(ctx, metric="nodularity"):
        if not ctx.get("spc_enabled", True):
            return {"error": "SPC disabled by feature flag"}
        return ctx["spc"](metric)

    register_tool(
        "get_spc",
        "Statistical process control over history: control limits, outliers, "
        "trend",
        {"metric": {"type": "str", "required": False,
                    "description": "nodularity (default) or count"}},
        get_spc)

    def get_anomalies(ctx):
        if not ctx.get("anomaly_enabled", True):
            return {"error": "anomaly detection disabled by feature flag"}
        return ctx["anomalies"]()

    register_tool(
        "get_anomalies",
        "Explainable anomaly scan over the analysis history",
        {}, get_anomalies)

    def get_decision_support(ctx):
        aid = ctx.get("analysis_id")
        if not aid:
            return {"error": "no analysis in context"}
        return ctx["decision_support"](aid)

    register_tool(
        "get_decision_support",
        "MEASURED/OBSERVED/INTERPRETATION/RECOMMENDATION chain for the "
        "current analysis",
        {}, get_decision_support)

    def get_validation(ctx, kind="internal"):
        return ctx["validation"](kind)

    register_tool(
        "get_validation",
        "Engine validation metrics; kind = internal | blind | synthetic "
        "(reported separately, never merged)",
        {"kind": {"type": "str", "required": False}},
        get_validation)

    def generate_report(ctx):
        aid = ctx.get("analysis_id")
        if not aid:
            latest = ctx["latest_analysis"]()
            if not latest:
                return {"error": "no analyses in history yet"}
            aid = latest["id"]
        report = ctx["generate_report"](aid)
        # Propagate generator failures honestly — never mask an error as a
        # report with None fields (that would read as a fabricated report).
        if not isinstance(report, dict):
            return {"error": "report generator returned no data"}
        if report.get("error"):
            return report
        return {"report_id": report.get("id"),
                "title": report.get("title"),
                "metrics": report.get("metrics"),
                "summary": report.get("summary"),
                "note": "open the Reports page to view/download "
                        "(PDF, CSV, JSON available)"}

    register_tool(
        "generate_report",
        "Generate an engineering report from the current analysis",
        {}, generate_report)

    def get_report(ctx, report_id):
        return ctx["get_report"](report_id)

    register_tool(
        "get_report",
        "Fetch a previously generated report",
        {"report_id": {"type": "str", "format": "analysis_id",
                       "required": True}},
        get_report)

    def search_reference(ctx, query):
        return ctx["search_reference"](query)

    register_tool(
        "search_reference",
        "Search the local reference layer (methodology, ISO/JIS concepts, "
        "app documentation)",
        {"query": {"type": "str", "required": True, "max_len": 120}},
        search_reference)

    def get_available_features(ctx):
        from nodiq.services.capabilities import get_capabilities
        return {"capabilities": get_capabilities()}

    register_tool(
        "get_available_features",
        "List all registered NODIQ-X capabilities (dynamic registry)",
        {}, get_available_features)


def _compact_contract(contract):
    """Trim the contract for LLM consumption: keep numbers, sample nodules."""
    nodules = contract.get("nodules") or []
    notable = sorted(
        nodules,
        key=lambda r: (-(r.get("confidence") or 0), -(r.get("area_px") or 0)))
    return {
        "sample": contract.get("sample"),
        "detections": contract.get("detections"),
        "iso945": contract.get("iso945"),
        "jis": contract.get("jis"),
        "morphology": contract.get("morphology"),
        "self_check": contract.get("self_check"),
        "quality": contract.get("quality"),
        "calibration": contract.get("calibration"),
        "warnings": contract.get("warnings"),
        "nodules_notable": notable[:8],
        "nodules_total": len(nodules),
    }


_register_all()
