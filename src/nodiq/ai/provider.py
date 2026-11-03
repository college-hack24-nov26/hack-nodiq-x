#!/usr/bin/env python3
"""
ai/provider.py — AI provider abstraction (Phases 13, 15).

Common interface:  chat(messages, context) -> {"content": str, "provider": str,
"model": str}  or raises ProviderUnavailable.

Selection (AI_PROVIDER=auto): local -> gemini (if key) -> openai (if key)
-> fallback. OFFLINE_MODE=true skips cloud providers entirely. If a selected
provider errors at call time, the chain degrades gracefully to the NODIQ-X
fallback provider — the app must never crash or dead-end.

Status is always TRUTHFUL (Phase: online/offline state):
  ONLINE           — a cloud/local LLM answered the latest call
  OFFLINE          — offline mode, or no provider configured
  NOT CONFIGURED   — no API key / local server for the requested provider
  ERROR            — a provider IS configured but the last call failed
The deterministic fallback provider may still answer, but it is labelled
"offline — NODIQ-X rules engine", never as an LLM.
"""
import importlib
import time


class ProviderUnavailable(Exception):
    pass


class AIProvider:
    """Base class. Subclasses implement chat()."""
    name = "base"

    def available(self) -> bool:
        return True

    def chat(self, messages, context=None, stream=False):
        raise NotImplementedError

    def supports_vision(self):
        return False

    def describe(self):
        return {"provider": self.name, "available": self.available(),
                "vision": self.supports_vision()}


# ---------------------------------------------------------------- registry ----
_PROVIDER_MODULES = {
    "local": "nodiq.ai.local_provider",
    "gemini": "nodiq.ai.gemini_provider",
    "openai": "nodiq.ai.openai_compatible_provider",
    "groq": "nodiq.ai.groq_provider",
    "fallback": "nodiq.ai.fallback_provider",
}

_last_good = None          # remembers a provider that answered recently
_last_good_ts = 0.0
_last_error = None         # truthful diagnostics for the ERROR state
_last_error_ts = 0.0


def note_provider_error(provider_name: str, detail: str):
    """Record the last real provider failure (shown via /api/ai/status)."""
    global _last_error, _last_error_ts
    _last_error = {"provider": provider_name, "detail": str(detail)[:300],
                   "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _last_error_ts = time.time()


def _load(name):
    module = importlib.import_module(_PROVIDER_MODULES[name])
    return module.get_provider()


def _probe(provider, timeout=1.2):
    """Cheap availability probe (local servers only; cloud checked by key)."""
    try:
        return provider.available()
    except Exception:
        return False


def get_provider_chain():
    """Ordered provider list per config."""
    from nodiq.ai.config import get_config
    cfg = get_config()
    order = []
    pref = cfg.provider
    if pref == "auto":
        order = ["groq", "gemini", "openai", "local", "fallback"]
    elif pref in _PROVIDER_MODULES:
        order = [pref, "fallback"] if pref != "fallback" else ["fallback"]
    else:
        order = ["fallback"]
    if cfg.offline_mode:
        order = [p for p in order if p in ("local", "fallback")]
    providers = []
    for name in order:
        try:
            p = _load(name)
            p.name = name
            providers.append(p)
        except Exception:
            continue
    return providers


def pick_provider():
    """First currently-available provider, preferring the last known-good."""
    global _last_good, _last_good_ts
    chain = get_provider_chain()
    if _last_good is not None and time.time() - _last_good_ts < 120:
        for p in chain:
            if p.name == _last_good and _probe(p):
                return p
    for p in chain:
        if _probe(p):
            return p
    return chain[-1] if chain else _load("fallback")


def _is_transient(exc) -> bool:
    """True when a failure is likely momentary (network blip / 5xx / 429),
    i.e. worth one retry before degrading to the rules engine."""
    text = str(exc).lower()
    if isinstance(exc, ProviderUnavailable) and any(
            m in text for m in ("401", "403", "404", "authentication",
                                "forbidden", "not found", "no groq_api_key",
                                "no api key", "no api keys")):
        return False   # permanent config/auth errors: retrying won't help
    return True


def chat(messages, context=None, stream=False):
    """chat() with graceful degradation across the chain (Phase 36/15).

    The preferred (configured) provider is always tried FIRST; previously
    good providers are only preferred when they are actually in the chain.
    Every real failure is recorded for truthful status reporting.

    Transient failures (network blips, timeouts, 5xx, rate limits) are
    retried once after a short backoff before the chain degrades — a single
    dropped request no longer flips the whole Copilot to the offline rules
    engine mid-conversation.
    """
    global _last_good, _last_good_ts
    chain = get_provider_chain()
    errors = []
    preferred = pick_provider()
    ordered = [p for p in chain if p is preferred]
    ordered += [p for p in chain if p is not preferred]
    for p in ordered:
        last_exc = None
        for attempt_no in (1, 2):
            try:
                result = p.chat(messages, context=context, stream=stream)
                if stream and isinstance(result, dict) and result.get("stream"):
                    # streaming results: success is decided by the consumer
                    _last_good, _last_good_ts = p.name, time.time()
                    return result
                _last_good, _last_good_ts = p.name, time.time()
                return result
            except ProviderUnavailable as exc:
                last_exc = exc
                errors.append(f"{p.name}: {exc}")
                note_provider_error(p.name, exc)
            except Exception as exc:
                last_exc = exc
                errors.append(f"{p.name}: {type(exc).__name__}: {exc}")
                note_provider_error(p.name, f"{type(exc).__name__}: {exc}")
            # retry only transient failures, and only the first round
            if attempt_no == 1 and _is_transient(last_exc):
                time.sleep(0.8)
                continue
            break
    # absolute last resort: deterministic fallback inline (never raises)
    fb = _load("fallback")
    result = fb.chat(messages, context=context, stream=False)
    result["degraded_from"] = errors
    return result


def _configured_primary():
    """The user-selected LLM provider module (not the fallback), if any."""
    from nodiq.ai.config import get_config
    cfg = get_config()
    if cfg.offline_mode:
        return "local" if cfg.provider in ("auto", "local", "groq") else None
    if cfg.provider == "auto":
        if cfg.groq_api_key:
            return "groq"
        if cfg.api_key:
            return "gemini"
        return "local"
    return cfg.provider if cfg.provider in _PROVIDER_MODULES and \
        cfg.provider != "fallback" else None


def status():
    """Truthful provider status for /api/ai/status and the Copilot chip."""
    from nodiq.ai.config import get_config
    cfg = get_config()
    provs = []
    for name in ("local", "gemini", "openai", "groq", "fallback"):
        try:
            p = _load(name)
            p.name = name
            provs.append(p.describe())
        except Exception as exc:
            provs.append({"provider": name, "available": False,
                          "error": str(exc)})

    active = pick_provider()
    primary = _configured_primary()
    fallback_answered = active is not None and active.name == "fallback"
    recent_error = (_last_error is not None
                    and time.time() - _last_error_ts < 300)

    if cfg.offline_mode:
        state = "OFFLINE"
        state_detail = "OFFLINE_MODE=true — cloud providers skipped"
    elif fallback_answered:
        if primary is None:
            state = "NOT_CONFIGURED"
            state_detail = "No AI provider configured (set AI_PROVIDER or GROQ_API_KEY)"
        elif recent_error and _last_error.get("provider") == primary:
            state = "ERROR"
            state_detail = _last_error.get("detail", "provider call failed")
        else:
            state = "ERROR"
            state_detail = "configured provider unavailable; answered by the offline rules engine"
    else:
        state = "ONLINE"
        state_detail = None

    # truthful key-rotation telemetry (Copilot limit-reached protection)
    try:
        from nodiq.ai import key_rotation
        keys = key_rotation.load_keys(cfg.groq_api_key or cfg.api_key)
        rotation = {"keys_configured": len(keys),
                    "keys_in_cooldown": len(key_rotation._cooling_keys())}
    except Exception:
        rotation = {"keys_configured": 0, "keys_in_cooldown": 0}

    return {
        "configured_provider": cfg.provider,
        "active_provider": active.name if active else "fallback",
        "key_rotation": rotation,
        "active_model": getattr(active, "model", None) or cfg.model or cfg.groq_model or None,
        "offline_mode": cfg.offline_mode,
        "model": getattr(active, "model", None) or cfg.model or cfg.groq_model or None,
        "state": state,
        "state_detail": state_detail,
        "last_error": _last_error if recent_error else None,
        "providers": provs,
    }
