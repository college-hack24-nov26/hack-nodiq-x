#!/usr/bin/env python3
"""ai/key_rotation.py — API-key rotation for the Copilot provider.

The user's Copilot hits provider limits (Groq free tier: 429 / quota
errors) during a demo. Instead of failing with "limit reached", the
provider rotates to the next key in a queue until one works or the
queue is exhausted. Keys come ONLY from environment variables:

    GROQ_API_KEY        primary key
    GROQ_API_KEY_2 ... GROQ_API_KEY_6    up to 5 extra queue keys
    (comma-separated GROQ_API_KEYS is also accepted)

Rotation is stateful per process: after a key rate-limits (429/quota),
it is marked cooling (60s backoff) and skipped on subsequent calls.
State is intentionally in-memory: restarting the server resets it.

The public entry point is ``chat_with_key_rotation`` — a drop-in wrapper
around a provider's ``chat()`` that re-runs the same request with the
next available key after a limit-type failure.
"""
import os
import threading
import time

# Environment names of the queue slots, in rotation order.
_QUEUE_ENVS = ["GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4",
               "GROQ_API_KEY_5", "GROQ_API_KEY_6"]
_COOLDOWN_SECONDS = 60.0

_lock = threading.Lock()
# key -> monotonic time until which the key is considered rate-limited
_cooling: dict = {}


def load_keys(primary: str = "") -> list:
    """Return the ordered [primary, *queue] key list, de-duplicated.

    Keys are read from the environment at call time (tests can patch
    os.environ); empty entries are dropped.
    """
    keys = []
    if primary and primary.strip():
        keys.append(primary.strip())
    for name in _QUEUE_ENVS:
        val = (os.environ.get(name) or "").strip()
        if val and val not in keys:
            keys.append(val)
    # convenience: GROQ_API_KEYS="k2, k3, k4" (primary stays separate)
    grouped = (os.environ.get("GROQ_API_KEYS") or "").strip()
    if grouped:
        for val in grouped.split(","):
            val = val.strip()
            if val and val not in keys:
                keys.append(val)
    return keys


def _mark_cooling(key: str, seconds: float = _COOLDOWN_SECONDS) -> None:
    with _lock:
        _cooling[key] = time.monotonic() + seconds


def _cooling_keys() -> set:
    with _lock:
        now = time.monotonic()
        expired = [k for k, until in _cooling.items() if until <= now]
        for k in expired:
            _cooling.pop(k, None)
        return set(_cooling.keys())


def reset_rotation_state() -> None:
    """Clear the cooling map (used by tests and after config reloads)."""
    with _lock:
        _cooling.clear()


def is_limit_error(exc_or_text) -> bool:
    """True when an exception/text represents a quota / rate-limit failure."""
    text = str(exc_or_text).lower()
    return any(marker in text for marker in
               ("429", "rate limit", "rate-limit", "ratelimit",
                "quota", "too many requests", "limit reached",
                "limit_exceeded", "resource_exhausted",
                "usage limit", "tpm", "rpm"))


def attempt(func, keys, **call_kwargs):
    """Run ``func(api_key=..., **call_kwargs)`` rotating through ``keys``.

    ``func`` must accept an ``api_key`` keyword and raise on failure.
    Returns (result, api_key) of the first successful attempt. Keys that
    fail with a LIMIT-type error are cooled down (60s) and skipped on
    subsequent calls; other errors fail fast (they are not key-specific).
    Raises when every key fails or every key is still cooling down.
    """
    if not keys:
        raise RuntimeError("no API keys configured")
    last_error = None
    cooling = _cooling_keys()
    skipped = 0
    for key in keys:
        if key in cooling:
            skipped += 1
            continue
        try:
            return func(api_key=key, **call_kwargs), key
        except Exception as exc:  # noqa: BLE001 - rotate on any failure
            last_error = exc
            if is_limit_error(exc):
                # honor the provider's own reset window when the caller
                # attached one (see groq_provider 429 handling); otherwise
                # use the default fixed backoff
                _mark_cooling(key, getattr(exc, "cooldown_s", None)
                              or _COOLDOWN_SECONDS)
                continue
            raise  # non-key errors (network 5xx, auth) fail fast
    if skipped and skipped == len(keys):
        raise RuntimeError(
            f"all {len(keys)} API keys are rate-limited (cooling down); "
            "retry in a moment")
    # everything failed: surface the last error with queue context
    raise RuntimeError(
        f"all {len(keys)} API keys exhausted (last error: {last_error})"
    ) from last_error


def chat_with_key_rotation(provider, messages, context=None, stream=False):
    """Wrap a provider ``chat()`` with key rotation (Groq-compatible).

    Builds the key queue from config (primary + queue env vars), then
    calls ``provider.chat_with_key(messages, context, stream, api_key)``
    if the provider implements it; otherwise calls the provider's chat
    with a temporarily patched config key. On a limit-type failure the
    next key is tried. Non-limit failures propagate immediately (the
    provider chain in ai/provider.py handles them as before).
    """
    from nodiq.ai.config import get_config

    cfg = get_config()
    primary = getattr(provider, "primary_api_key", None) or cfg.groq_api_key \
        or cfg.api_key
    keys = load_keys(primary)
    if not keys:
        raise RuntimeError("no API keys configured for rotation")

    if not hasattr(provider, "chat_with_key"):
        raise RuntimeError(
            f"provider {provider.name} does not support key rotation")

    def _call(api_key):
        return provider.chat_with_key(messages, context=context,
                                      stream=stream, api_key=api_key)

    result, used_key = attempt(_call, keys)
    # remember the working key so status/monitoring can surface it
    try:
        provider.last_used_key_hint = (used_key[:6] + "…") if used_key else None
    except Exception:  # pragma: no cover - cosmetic only
        pass
    return result
