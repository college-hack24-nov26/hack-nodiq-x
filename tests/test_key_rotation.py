#!/usr/bin/env python3
"""
tests/test_key_rotation.py — Copilot API-key rotation tests (offline).

Covers: queue loading from env, limit-error detection, rotation on
429/quota failures, cooldown skipping, exhaustion surfacing, fail-fast
on non-key errors, and the GroqProvider end-to-end rotation path with
a mocked HTTP layer (no network).
"""
import sys
from pathlib import Path

import pytest


from nodiq.ai import key_rotation
from nodiq.ai.provider import ProviderUnavailable


@pytest.fixture(autouse=True)
def _clean_rotation_state(monkeypatch):
    """Isolate env + in-memory cooling state per test."""
    key_rotation.reset_rotation_state()
    for name in ("GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3",
                 "GROQ_API_KEY_4", "GROQ_API_KEY_5", "GROQ_API_KEY_6",
                 "GROQ_API_KEYS"):
        monkeypatch.delenv(name, raising=False)
    yield
    key_rotation.reset_rotation_state()


# --------------------------------------------------------------- queue ----

def test_load_keys_primary_only():
    assert key_rotation.load_keys("primary-key") == ["primary-key"]


def test_load_keys_primary_plus_queue():
    monkey_keys = {"GROQ_API_KEY_2": "k2", "GROQ_API_KEY_3": "k3"}
    for name, val in monkey_keys.items():
        monkeypatch_setenv(name, val)
    assert key_rotation.load_keys("k1") == ["k1", "k2", "k3"]


def test_load_keys_deduplicates():
    monkeypatch_setenv("GROQ_API_KEY_2", "k1")
    monkeypatch_setenv("GROQ_API_KEY_3", "k2")
    assert key_rotation.load_keys("k1") == ["k1", "k2"]


def test_load_keys_grouped_env():
    monkeypatch_setenv("GROQ_API_KEYS", "k2, k3 ,,k4")
    assert key_rotation.load_keys("k1") == ["k1", "k2", "k3", "k4"]


def test_load_keys_empty_is_empty():
    assert key_rotation.load_keys("") == []


def monkeypatch_setenv(name, val):
    import os
    os.environ[name] = val


# ----------------------------------------------------- limit detection ----

def test_is_limit_error_variants():
    for text in ("Groq rate limit reached (429)",
                 "HTTP 429 Too Many Requests",
                 "quota exhausted for this API key",
                 "usage limit reached",
                 "resource_exhausted"):
        assert key_rotation.is_limit_error(text), text


def test_is_limit_error_negative():
    assert not key_rotation.is_limit_error("Groq authentication failed (401)")
    assert not key_rotation.is_limit_error("connection timeout")


# --------------------------------------------------------- rotation ----

def test_attempt_rotates_on_limit_error():
    calls = []

    def func(api_key):
        calls.append(api_key)
        if api_key == "k1":
            raise ProviderUnavailable("rate limit reached (429)")
        return f"ok:{api_key}"

    result, used = key_rotation.attempt(func, ["k1", "k2"])
    assert result == "ok:k2" and used == "k2"
    assert calls == ["k1", "k2"]
    # k1 is now cooling down
    assert key_rotation._cooling_keys() == {"k1"}


def test_attempt_skips_cooled_key_on_next_call():
    order = []

    def func(api_key):
        order.append(api_key)
        if api_key == "k1":
            raise ProviderUnavailable("429 too many requests")
        return "ok"

    key_rotation.attempt(func, ["k1", "k2"])
    # second call: k1 is cooling -> skipped entirely
    order.clear()
    result, used = key_rotation.attempt(func, ["k1", "k2"])
    assert result == "ok" and used == "k2"
    assert order == ["k2"]  # k1 never tried while cooling


def test_attempt_all_cooling_raises_clear_error():
    key_rotation._mark_cooling("k1")
    key_rotation._mark_cooling("k2")
    with pytest.raises(RuntimeError, match="cooling down"):
        key_rotation.attempt(lambda api_key: "x", ["k1", "k2"])


def test_attempt_raises_after_queue_exhausted():
    def func(api_key):
        raise ProviderUnavailable("quota exceeded")

    with pytest.raises(RuntimeError, match="all 2 API keys exhausted"):
        key_rotation.attempt(func, ["k1", "k2"])
    assert key_rotation._cooling_keys() == {"k1", "k2"}


def test_attempt_fail_fast_on_non_limit_error():
    calls = []

    def func(api_key):
        calls.append(api_key)
        raise ProviderUnavailable("authentication failed (401)")

    with pytest.raises(ProviderUnavailable):
        key_rotation.attempt(func, ["k1", "k2"])
    assert calls == ["k1"]  # never rotated on auth errors


def test_attempt_no_keys_raises():
    with pytest.raises(RuntimeError, match="no API keys"):
        key_rotation.attempt(lambda api_key: "x", [])


def test_cooldown_expires():
    key_rotation._mark_cooling("k1", seconds=0.01)
    import time
    time.sleep(0.03)
    assert "k1" not in key_rotation._cooling_keys()


# ------------------------------------------- provider end-to-end ----

class _FakeConfig:
    groq_api_key = "primary-key"
    api_key = ""
    offline_mode = False


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


def test_chat_with_key_rotation_end_to_end(monkeypatch):
    """429 on key 1 -> automatic retry with queue key 2 -> success."""
    from nodiq.ai.groq_provider import GroqProvider

    monkeypatch.setattr("nodiq.ai.key_rotation.load_keys",
                        lambda primary="": ["k1", "k2"])

    auth_headers = []

    def fake_post(url, json=None, headers=None, timeout=None, stream=False):
        auth_headers.append(headers["Authorization"])
        if len(auth_headers) == 1:
            return _FakeResponse(429)
        return _FakeResponse(200, {"choices": [
            {"message": {"content": "hello from key 2"}}]})

    monkeypatch.setattr("nodiq.ai.groq_provider.requests.post", fake_post)

    out = GroqProvider().chat([{"role": "user", "content": "hi"}])
    assert out["content"] == "hello from key 2"
    assert out["provider"] == "groq"
    # first call used key 1, retry used key 2 — no "limit reached" error
    assert auth_headers == ["Bearer k1", "Bearer k2"]


def test_chat_exhausted_queue_surfaces_error(monkeypatch):
    from nodiq.ai.groq_provider import GroqProvider

    monkeypatch.setattr("nodiq.ai.key_rotation.load_keys",
                        lambda primary="": ["k1", "k2"])
    monkeypatch.setattr(
        "nodiq.ai.groq_provider.requests.post",
        lambda url, json=None, headers=None, timeout=None, stream=False: _FakeResponse(429))

    with pytest.raises(ProviderUnavailable, match="keys exhausted"):
        GroqProvider().chat([{"role": "user", "content": "hi"}])


def test_groq_describe_reports_key_queue(monkeypatch):
    from nodiq.ai.groq_provider import GroqProvider

    monkeypatch.setattr("nodiq.ai.groq_provider.get_config", lambda: _FakeConfig())
    monkeypatch.setenv("GROQ_API_KEY_2", "k2")
    d = GroqProvider().describe()
    assert d["keys_configured"] == 2
    assert d["keys_in_cooldown"] == 0
