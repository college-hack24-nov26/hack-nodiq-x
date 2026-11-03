#!/usr/bin/env python3
"""
ai/agent.py — the Copilot agent loop (Phases 12, 16-17, 19-22, 28, 30, 36).

Turn flow:
  user message + session + app context
    -> resolve referenced analysis (memory)
    -> build scientific contract (cached by analysis_id)
    -> assemble LLM messages (system prompt w/ capabilities+tools, history,
       context summary, user message)
    -> LLM may emit one ```action``` block
    -> allowlist-validated tool execution -> tool result message -> LLM again
    -> final answer (+ safe UI actions list for the frontend)
  every step degrades gracefully: if no LLM answers, the deterministic
  fallback provider answers from the same real context.
"""
import json
import re

from nodiq.ai import memory as mem
from nodiq.ai import provider as prov
from nodiq.ai import tools as ai_tools
from nodiq.ai.prompts import render_system_prompt, render_no_tool_prompt
from nodiq.services.capabilities import capabilities_digest

# Accept ```action``` (documented) and ```json``` fences — newer Gemini
# models often use the generic fence — but ONLY treat the block as a tool
# action after the parsed JSON contains a "tool" key.
_ACTION_RE = re.compile(r"```(?:action|json)?\s*(\{.*?\})\s*```", re.DOTALL)

# safe UI actions the Copilot may request (Phase 21) — frontend-only effects
SAFE_UI_ACTIONS = {"show_nodule", "open_analysis", "show_quality",
                   "show_calibration", "show_spc", "show_anomaly",
                   "show_batch", "open_comparison", "open_validation",
                   "generate_report"}

# One Copilot turn makes 1-3 LLM calls. On small Groq free plans the TPM
# budget is ~8k tokens/minute, and an untrimmed turn (5.9k-char system
# prompt + context JSON + 8 history turns, repeated 2-3x) exhausted the
# whole key rotation within a couple of questions — every answer then fell
# to the rules engine ("provider could not be reached"). Trim instead:
_MAX_SYSTEM_CHARS = 6000
_MAX_CONTEXT_CHARS = 2500
_MAX_HISTORY_TURNS = 6
_MAX_HISTORY_CHARS = 1200


def _clip(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _clip_json(obj, limit):
    """Compact JSON that ALWAYS parses (never truncated mid-structure).
    Over the limit, the largest top-level values are dropped first."""
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return "{}"
    if len(s) <= limit:
        return s
    if isinstance(obj, dict):
        trimmed = dict(obj)
        while len(s) > limit and trimmed:
            biggest = max(trimmed, key=lambda k: len(
                json.dumps(trimmed[k], default=str)))
            trimmed.pop(biggest)
            s = json.dumps(trimmed, ensure_ascii=False, default=str)
        return s
    return "{}"


def _context_summary(contract, batch_stats=None, spc_data=None,
                     decision=None, comparison=None):
    """Compact context JSON for the LLM (no bulky nodule arrays)."""
    if not contract:
        return {"note": "no analysis loaded in context",
                "batch_summary": _batch_snapshot(batch_stats),
                "spc": spc_data if isinstance(spc_data, dict) else None}
    return {
        "sample": contract.get("sample"),
        "detections": contract.get("detections"),
        "iso945": contract.get("iso945"),
        "jis": contract.get("jis"),
        "morphology": contract.get("morphology"),
        "self_check": contract.get("self_check"),
        "quality": {"status": (contract.get("quality") or {}).get("status"),
                    "score": (contract.get("quality") or {}).get("score")},
        "calibration": contract.get("calibration"),
        "multifield": contract.get("multifield"),
        "warnings": contract.get("warnings"),
        "batch_summary": (_batch_snapshot(batch_stats)
                          or _batch_snapshot(contract.get("batch"))),
        "spc": spc_data if isinstance(spc_data, dict) else None,
        "decision_support": decision if isinstance(decision, dict) else None,
        "comparison": comparison if isinstance(comparison, dict) else None,
        "anomalies": _anomaly_snapshot(contract.get("anomalies")),
    }


def _batch_snapshot(batch):
    if isinstance(batch, dict) and batch.get("nodularity"):
        nod = batch["nodularity"]
        return {"samples": batch.get("samples"),
                "pass_rate_pct": batch.get("pass_rate_pct"),
                "mean_nodularity": nod.get("mean"),
                "std_nodularity": nod.get("std")}
    return None


def _anomaly_snapshot(anoms):
    if isinstance(anoms, list) and anoms:
        top = anoms[0]
        if top.get("is_anomaly"):
            return {"analysis_id": top.get("analysis_id"),
                    "severity": top.get("severity"),
                    "score": top.get("anomaly_score"),
                    "reasons": top.get("reasons", [])[:3]}
    return None


def _intent_action(message):
    """Deterministic intent router (safety net).

    High-value platform actions — report generation, comparisons, SPC — must
    execute the REAL registered services even when the LLM forgets the action
    protocol or leaks planning text instead of an action block. The LLM then
    presents the actual tool result; it never fabricates reports or metrics.
    """
    text = (message or "").lower()
    if re.search(
            r"\b(generate|create|make|produce|export|draft|prepare)\b[^.]*\breport\b"
            r"|\breport\b[^.]*\b(generate|create|make|produce|export)\b", text):
        return {"tool": "generate_report", "args": {}}
    if re.search(r"\bcompare\b|\bversus\b|\bvs\.?\b", text):
        return {"tool": "compare_samples", "args": {}}
    if re.search(r"\bspc\b|\bcontrol limits?\b", text):
        return {"tool": "get_spc", "args": {"metric": "nodularity"}}
    return None


def _deterministic_intent_answer(tool_name, tool_result):
    """Honest plain-prose presenter for router-executed tools (LLM-free).
    Guards against None/empty tool fields — it never invents a value."""
    if not isinstance(tool_result, dict):
        return "The tool returned no data."
    if tool_result.get("error"):
        return (f"I could not complete that action: {tool_result['error']}. "
                "Nothing was invented — ask me again once the data exists.")
    if tool_name == "generate_report":
        report_id = tool_result.get("report_id")
        if not report_id:
            return ("I could not complete that action: no report was "
                    "created. Nothing was invented — ask me again once the "
                    "data exists.")
        metrics = tool_result.get("metrics") or {}
        return (f"Report {report_id} — "
                f"\"{tool_result.get('title') or 'Technical report'}\" — "
                f"is ready. Measured values: nodularity "
                f"{metrics.get('nodularity_pct')}%, "
                f"{metrics.get('nodule_count')} particles. "
                "Open it from the Reports page (PDF, CSV and JSON downloads "
                "are available). I can summarize it if you like.")
    if tool_name == "compare_samples":
        return (str(tool_result.get("summary"))
                or "Comparison computed from the two most relevant stored "
                   "analyses. Ask me about any specific metric in it.")
    if tool_name == "get_spc":
        if tool_result.get("sufficient_data"):
            return (f"SPC ({tool_result.get('metric')}): mean "
                    f"{tool_result.get('mean')}, UCL {tool_result.get('ucl')}, "
                    f"LCL {tool_result.get('lcl')}, "
                    f"{tool_result.get('violations')} rule violations, "
                    f"trend {tool_result.get('trend')}.")
        return tool_result.get(
            "note", "Not enough history yet for SPC control limits.")
    return "Done — result recorded from the NODIQ-X services."


def _gather_context(ctx, app_context=None, session=None):
    aid = (app_context or {}).get("current_analysis_id") \
        or ctx.get("analysis_id") \
        or (mem.referenced_analysis_id(session) if session else None) \
        or ((ctx.get("latest_analysis") and ctx["latest_analysis"]()) or {}).get("id")
    ctx["analysis_id"] = aid
    if aid and session:
        mem.set_referenced_analysis(session, aid)

    contract = None
    if aid and ctx.get("contract"):
        try:
            contract = ctx["contract"](aid)
        except Exception:
            contract = None
    batch_stats = spc_data = decision = comparison = None
    try:
        if ctx.get("batch_enabled", True) and ctx.get("batch_stats"):
            batch_stats = ctx["batch_stats"]()
    except Exception:
        batch_stats = None
    try:
        if ctx.get("spc_enabled", True) and ctx.get("spc"):
            spc_data = ctx["spc"]("nodularity")
    except Exception:
        spc_data = None
    if contract and aid:
        try:
            if ctx.get("decision_support"):
                decision = ctx["decision_support"](aid)
        except Exception:
            decision = None
        try:
            if ctx.get("compare"):
                comparison = ctx["compare"](aid, None)
        except Exception:
            comparison = None
    return _context_summary(contract, batch_stats, spc_data, decision, comparison)


def handle_turn(message, session_id, ctx, history=None, app_context=None,
                owner_id=None):
    """Process one Copilot turn. Returns the response payload.

    ctx: ToolContext dict (injected by server.py)
    history: optional frontend-provided [{role, content}] (additive)
    app_context: optional {current_page, current_analysis_id, ...}
    owner_id: account id the conversation belongs to (server-verified);
              conversation memory is namespaced per account when given
    """
    session = mem.load_session(session_id, owner_id)
    session["owner_id"] = str(owner_id) if owner_id else None
    mem.append_message(session, "user", message)

    ctx_summary = _gather_context(ctx, app_context, session)
    ctx_json = json.dumps(ctx_summary, ensure_ascii=False, default=str)

    history_msgs = (history or [])[-_MAX_HISTORY_TURNS:]
    if not history_msgs:
        history_msgs = mem.recent_messages(session, limit=_MAX_HISTORY_TURNS + 2)

    system = _clip(render_system_prompt(capabilities_digest(),
                                        ai_tools.tool_digest()),
                   _MAX_SYSTEM_CHARS)
    llm_messages = (
        [{"role": "system", "content": system}]
        + [{"role": m["role"], "content": _clip(m["content"], _MAX_HISTORY_CHARS)}
           for m in history_msgs if m.get("role") in ("user", "assistant")]
        + [{"role": "system",
            "content": "Current measured context (JSON): "
                       + _clip_json(ctx_summary, _MAX_CONTEXT_CHARS)}]
        + [{"role": "user", "content": message}]
    )

    # ---------------- first LLM pass ----------------
    result = prov.chat(llm_messages, context=ctx_summary)
    answer = result.get("content", "") if isinstance(result, dict) else ""
    provider_used = result.get("provider") if isinstance(result, dict) else "?"

    # ---------------- tool-call loop (max one round-trip) ----------------
    ui_actions = []
    tool_trace = None
    action = None
    for _match in _ACTION_RE.finditer(answer or ""):
        try:
            candidate = json.loads(_match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("tool"):
            action = candidate
            break
    if action:
        tool_result = ai_tools.execute_action(action, ctx)
        tool_trace = {"requested": action, "result_digest":
                      _digest_tool_result(tool_result)}
        # keep conversation referential after actions
        if action.get("tool") == "analyze_image" \
                and isinstance(tool_result, dict):
            new_id = (tool_result.get("analysis")
                      or {}).get("analysis_id")
            if new_id:
                ctx["analysis_id"] = new_id
                mem.set_referenced_analysis(session, new_id)
        # second pass with tool result
        tool_json = json.dumps(tool_result, ensure_ascii=False,
                               default=str)
        action_json = json.dumps(action)
        llm_messages = llm_messages[:-1] + [
            {"role": "assistant",
             "content": "I'll use a tool for that.\n```action\n"
                        + action_json + "\n```"},
            {"role": "user",
             "content": "[tool result]: " + tool_json
                        + "\n\nNow answer the original question from "
                          "this data: " + message},
        ]
        result2 = prov.chat(llm_messages, context=ctx_summary)
        r2 = result2 if isinstance(result2, dict) else {}
        # If the presentation pass degraded to the canned fallback
        # provider, keep the LLM's own first-pass prose (minus the
        # executed action block) instead of an unrelated canned template.
        if r2.get("provider") != "fallback" and (r2.get("content") or ""):
            answer = r2["content"]
            provider_used = r2.get("provider", provider_used)
        answer = _ACTION_RE.sub("", answer).strip()
        if not answer:
            answer = ("Done — executed from the NODIQ-X services; the "
                      "measured result is recorded.")
        # extract safe UI actions implied by tool use
        ui_actions = _ui_actions_for(action.get("tool"), tool_result, ctx)

    # strip any unexecuted action blocks from the answer (defensive)
    answer = _ACTION_RE.sub("", answer).strip() or \
        "I could not generate a response — please try rephrasing."

    # ---------------- deterministic intent router (safety net) ----------------
    # If the LLM produced no tool call but the user clearly asked for a real
    # platform action, execute the registered tool anyway and present the
    # ACTUAL result. This guarantees "generate a report" generates a real
    # report through the deterministic engine — never an LLM-written fake.
    leak_markers = ("*formatting*", "style considerations", "output format",
                    "as an ai", "```tool", "tool_name", "discrepan",
                    # canned fallback templates — never a tool presentation
                    "measured image quality is", "the analysis engine ran")
    if tool_trace is None:
        intent = _intent_action(message)
        if intent:
            tool_result = ai_tools.execute_action(intent, ctx)
            tool_trace = {"requested": intent,
                          "result_digest": _digest_tool_result(tool_result),
                          "via": "intent-router"}
            ui_actions = _ui_actions_for(intent.get("tool"), tool_result, ctx)
            presented = None
            try:
                tool_json = _clip_json(tool_result, 1800)
                llm_present = llm_messages[:-1] + [
                    {"role": "assistant", "content": "I'll use a tool for that."},
                    {"role": "user",
                     "content": "[tool result]: " + tool_json
                                + "\n\nWrite ONLY 2-4 sentences of plain prose "
                                  "summarizing this ACTUAL tool result for the "
                                  "user (answering: " + message + "). "
                                  "No headings, no markdown, no lists, no "
                                  "planning notes, no fences, never invent "
                                  "values."},
                ]
                result2 = prov.chat(llm_present, context=ctx_summary)
                cand = (result2.get("content", "")
                        if isinstance(result2, dict) else "").strip()
                cand = _ACTION_RE.sub("", cand).strip()
                bad_planning = ("step ", "i will", "```", "# ", "* ",
                                "- ", "discrepan", "formatting")
                looks_clean = (cand and len(cand) < 1200
                               and not cand.startswith(("#", "*", "-", "{"))
                               and not any(m in cand.lower()
                                           for m in bad_planning)
                               and not any(m in cand.lower()
                                           for m in leak_markers))
                from_fallback = (isinstance(result2, dict)
                                 and result2.get("provider") == "fallback")
                if looks_clean and not from_fallback:
                    presented = cand
                    provider_used = (result2.get("provider", provider_used)
                                     if isinstance(result2, dict)
                                     else provider_used)
            except Exception:
                presented = None
            answer = presented or _deterministic_intent_answer(
                intent.get("tool"), tool_result)

    # Older/newer models sometimes leak planning/meta text into the visible
    # answer when they intended to call a tool. If the reply contains no tool
    # result and looks like leaked planning, produce one clean final answer
    # from the measured context instead.
    if tool_trace is None and any(m in answer.lower()
                                  for m in leak_markers):
        try:
            retry_msgs = [
                {"role": "system",
                 "content": "You are NODIQ Copilot. Answer the user directly "
                            "in plain prose using the measured context. No "
                            "planning notes, no meta-commentary, no fences."},
                {"role": "system", "content":
                    f"Current measured context (JSON): {ctx_json}"},
                {"role": "user", "content": message},
            ]
            result3 = prov.chat(retry_msgs, context=ctx_summary)
            clean = (result3.get("content", "")
                     if isinstance(result3, dict) else "").strip()
            if clean:
                answer = _ACTION_RE.sub("", clean).strip() or answer
                provider_used = result3.get("provider", provider_used) \
                    if isinstance(result3, dict) else provider_used
        except Exception:
            pass

    # non-streaming fallback providers should be honest about their nature —
    # and about WHY they answered (offline? misconfigured? provider error?)
    if provider_used == "fallback":
        try:
            st = prov.status()
            state = st.get("state")
            cfg_name = st.get("configured_provider")
        except Exception:
            state, cfg_name = None, None
        if state == "ERROR":
            answer += (f"\n\n_(The online AI provider ({cfg_name}) could not "
                       "be reached just now — answered by the deterministic "
                       "NODIQ-X rules engine from your measured data. "
                       "Retry shortly.)_")
        elif state == "OFFLINE":
            answer += ("\n\n_(Answered by the offline NODIQ-X rules engine — "
                       "OFFLINE_MODE is enabled. Everything above is "
                       "computed from your measured data.)_")
        else:
            answer += ("\n\n_(Answered by the offline NODIQ-X rules engine — "
                       "no LLM provider is configured. Everything above is "
                       "computed from your measured data.)_")

    mem.append_message(session, "assistant", answer,
                       meta={"provider": provider_used,
                             "tool": (tool_trace or {}).get("requested")})
    mem.save_session(session)

    return {
        "reply": answer,
        "provider": provider_used,
        "session_id": session_id,
        "analysis_id": ctx.get("analysis_id"),
        "ui_actions": ui_actions,
        "tool_trace": tool_trace,
    }


def _digest_tool_result(tool_result):
    """Small digest for session storage (avoid storing huge payloads)."""
    if not isinstance(tool_result, dict):
        return {"type": str(type(tool_result))}
    if tool_result.get("error"):
        return {"error": tool_result["error"]}
    keys = ("analysis_id", "report_id", "severity", "anomaly_score",
            "sufficient_data", "mean", "pass_rate_pct", "samples")
    return {k: tool_result[k] for k in keys if k in tool_result} or {
        k: tool_result[k] for k in list(tool_result)[:4]}


def _ui_actions_for(tool_name, tool_result, ctx):
    """Map executed tools to safe UI actions the frontend may perform."""
    acts = []
    aid = ctx.get("analysis_id")
    if tool_name == "analyze_image" and isinstance(tool_result, dict):
        new_id = (tool_result.get("analysis") or {}).get("analysis_id")
        if new_id:
            acts.append({"action": "open_analysis",
                         "analysis_id": new_id})
    elif tool_name == "get_quality_report" and aid:
        acts.append({"action": "show_quality", "analysis_id": aid})
    elif tool_name == "get_spc":
        acts.append({"action": "show_spc"})
    elif tool_name == "get_anomalies" and isinstance(tool_result, dict):
        top = (tool_result.get("anomalies") or [None])[0]
        acts.append({"action": "show_anomaly",
                     "analysis_id": (top or {}).get("analysis_id") or aid})
    elif tool_name == "generate_report" and isinstance(tool_result, dict):
        acts.append({"action": "generate_report",
                     "report_id": tool_result.get("report_id")})
    elif tool_name == "get_nodule_details" and aid:
        nid = tool_result.get("nodule", {}).get("nodule_id")
        acts.append({"action": "show_nodule", "analysis_id": aid,
                     "nodule_id": nid})
    return [a for a in acts if a.get("action") in SAFE_UI_ACTIONS]


def handle_turn_stream(message, session_id, ctx, history=None, app_context=None,
                       owner_id=None):
    """Streaming generator for Copilot turns.
    Yields dictionary chunks:
      {"type": "token", "delta": str}
      {"type": "done", "reply": str, "provider": str, "session_id": str, "ui_actions": list, ...}
    Supports genuine upstream token-by-token streaming from Groq / local LLMs
    with automatic tool execution and graceful fallback.
    """
    try:
        # 1. Check deterministic platform intent router first
        intent = _intent_action(message)
        if intent:
            tool_result = ai_tools.execute_action(intent, ctx)
            ui_actions = _ui_actions_for(intent.get("tool"), tool_result, ctx)
            answer = _deterministic_intent_answer(intent.get("tool"), tool_result)
            yield {"type": "token", "delta": answer}
            yield {
                "type": "done",
                "reply": answer,
                "provider": "intent-router",
                "ui_actions": ui_actions,
                "tool_used": intent.get("tool"),
                "session_id": session_id,
            }
            return

        # 2. Prepare context & session for conversational turn
        session = mem.load_session(session_id, owner_id=owner_id)
        ref_aid = mem.resolve_reference(session, message)
        if ref_aid and not ctx.get("analysis_id"):
            ctx["analysis_id"] = ref_aid

        ctx_summary = _gather_context(ctx, app_context, session)

        history_msgs = (history or [])[-_MAX_HISTORY_TURNS:]
        if not history_msgs:
            history_msgs = mem.recent_messages(session, limit=_MAX_HISTORY_TURNS + 2)

        system = _clip(render_system_prompt(capabilities_digest(), ai_tools.tool_digest()), _MAX_SYSTEM_CHARS)
        llm_messages = (
            [{"role": "system", "content": system}]
            + [{"role": m["role"], "content": _clip(m["content"], _MAX_HISTORY_CHARS)}
               for m in history_msgs if m.get("role") in ("user", "assistant")]
            + [{"role": "system", "content": "Current measured context (JSON): " + _clip_json(ctx_summary, _MAX_CONTEXT_CHARS)}]
            + [{"role": "user", "content": message}]
        )

        # 3. Call provider chain with stream=True
        result = prov.chat(llm_messages, context=ctx_summary, stream=True)

        if isinstance(result, dict) and result.get("stream") and result.get("chunks"):
            accumulated = []
            is_tool_call = False
            chunks_iter = result["chunks"]

            # Peek first chunks to detect if the model initiated a tool call
            for chunk in chunks_iter:
                accumulated.append(chunk)
                text_so_far = "".join(accumulated)
                if "```action" in text_so_far or "```tool" in text_so_far:
                    is_tool_call = True
                    for rest_chunk in chunks_iter:
                        accumulated.append(rest_chunk)
                    break
                else:
                    yield {"type": "token", "delta": chunk}
                    break

            if not is_tool_call:
                for chunk in chunks_iter:
                    accumulated.append(chunk)
                    yield {"type": "token", "delta": chunk}

                full_text = "".join(accumulated).strip()
                full_text = _ACTION_RE.sub("", full_text).strip()
                if not full_text:
                    full_text = "I analyzed your question, but have no additional metallurgical details."

                # Save completed turn to session memory
                mem.append_message(session, "user", message)
                mem.append_message(session, "assistant", full_text)
                mem.save_session(session)

                yield {
                    "type": "done",
                    "reply": full_text,
                    "provider": result.get("provider", "groq"),
                    "model": result.get("model"),
                    "session_id": session_id,
                    "ui_actions": [],
                }
                return

            # If tool call was detected in stream, delegate to full handle_turn to execute safely
            res = handle_turn(message, session_id, ctx, history=history,
                              app_context=app_context, owner_id=owner_id)
            reply = res.get("reply", "")
            yield {"type": "token", "delta": reply}
            done_payload = dict(res)
            done_payload["type"] = "done"
            yield done_payload
            return

        # 4. Fallback or non-streaming provider response
        res = handle_turn(message, session_id, ctx, history=history,
                          app_context=app_context, owner_id=owner_id)
        reply = res.get("reply", "")
        tokens = re.split(r"(\s+)", reply)
        buf = ""
        for token in tokens:
            buf += token
            if len(buf) >= 16 or any(p in token for p in (".", "!", "?", ",", "\n", ";", ":")):
                yield {"type": "token", "delta": buf}
                buf = ""
        if buf:
            yield {"type": "token", "delta": buf}

        done_payload = dict(res)
        done_payload["type"] = "done"
        yield done_payload
    except GeneratorExit:
        # Client disconnected / stream aborted by user
        return
    except Exception as exc:
        yield {
            "type": "error",
            "error": str(exc),
            "reply": "Encountered a processing exception during streaming.",
        }
