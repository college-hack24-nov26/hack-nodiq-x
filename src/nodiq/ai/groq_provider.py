#!/usr/bin/env python3
"""Groq OpenAI-compatible provider for NODIQ-X."""
import json

import requests

from nodiq.ai import key_rotation
from nodiq.ai.config import get_config
from nodiq.ai.provider import AIProvider, ProviderUnavailable


_COOLDOWN_SECONDS = 60.0   # default 429 backoff when Groq gives no reset hint


def get_provider():
    return GroqProvider()


class GroqProvider(AIProvider):
    name = "groq"

    # Tried in order when the configured model itself fails (400/404), so a
    # retired or tool-allergic model degrades to a working one instead of
    # knocking every Copilot turn to the offline rules engine.
    _MODEL_FAILOVER = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]

    @property
    def model(self):
        cfg = get_config()
        return cfg.groq_model or cfg.model or cfg.groq_default_model

    def available(self):
        cfg = get_config()
        if cfg.offline_mode:
            return False
        # any key in the rotation queue (primary + extras) counts
        return bool(key_rotation.load_keys(cfg.groq_api_key or cfg.api_key))

    def supports_vision(self):
        return True

    def describe(self):
        cfg = get_config()
        keys = key_rotation.load_keys(cfg.groq_api_key or cfg.api_key)
        return {"provider": self.name, "available": self.available(),
                "vision": self.supports_vision(),
                "keys_configured": len(keys),
                "keys_in_cooldown": len(key_rotation._cooling_keys())}

    def chat(self, messages, context=None, stream=False):
        """chat() with API-key rotation (primary + up to 5 queue keys).

        A limit-type failure (429 / quota) rotates to the next queued key
        instead of surfacing "limit reached"; only an exhausted queue
        raises, and the provider chain degrades as before.
        """
        try:
            return key_rotation.chat_with_key_rotation(
                self, messages, context=context, stream=stream)
        except RuntimeError as exc:
            raise ProviderUnavailable(str(exc))

    # Nudge appended when the model tries NATIVE tool calling: the Copilot
    # protocol is text-based (a fenced ```action``` block). Models such as
    # openai/gpt-oss-20b sometimes emit a native tool_call instead, which
    # Groq rejects with 400 tool_use_failed and the whole turn degraded to
    # the rules engine ("provider could not be reached"). One nudged retry
    # recovers the answer without changing any measured data.
    _NO_NATIVE_TOOLS_NUDGE = (
        "You have NO native tool access. Never emit tool_call/function-call "
        "structures. To run a platform action, output plain text containing a "
        "fenced ```action block with JSON {\"tool\": ..., \"args\": {...}}. "
        "Otherwise answer in plain prose from the given context."
    )

    def chat_with_key(self, messages, context=None, stream=False, api_key=""):
        cfg = get_config()
        if not api_key or cfg.offline_mode:
            raise ProviderUnavailable("no GROQ_API_KEY configured for Groq")

        base_messages = self._to_openai_messages(messages)
        models = [self.model] + [m for m in self._MODEL_FAILOVER
                                 if m != self.model]
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        url = f"{cfg.groq_base_url.rstrip('/')}/chat/completions"

        response = None
        for model in models:
            payload = {
                "model": model,
                "messages": base_messages,
                "temperature": 0.2,
                "max_tokens": 900,
                "stream": bool(stream),
            }
            for attempt in (1, 2):
                try:
                    response = requests.post(url, json=payload, headers=headers,
                                             timeout=cfg.request_timeout,
                                             stream=bool(stream))
                except requests.RequestException as exc:
                    raise ProviderUnavailable(f"Groq unreachable: {exc}")

                if (response.status_code == 400
                        and "tool" in response.text.lower() and attempt == 1):
                    # native-tool-call attempt: nudge back to the text
                    # protocol (nudge injected before the latest message)
                    # and retry once with the same model
                    msgs = list(payload["messages"])
                    payload["messages"] = msgs[:-1] + [
                        {"role": "system",
                         "content": self._NO_NATIVE_TOOLS_NUDGE},
                        msgs[-1],
                    ]
                    continue
                break
            if response.status_code == 200:
                break   # this model answered
            # 404 model_not_found / 400 tool_use_failed after the nudge:
            # try the next failover model; other statuses are terminal
            if response.status_code in (400, 404) and model is not models[-1]:
                continue
            break

        if response.status_code == 401:
            raise ProviderUnavailable("Groq authentication failed (401)")
        if response.status_code == 403:
            raise ProviderUnavailable("Groq access forbidden (403)")
        if response.status_code == 404:
            raise ProviderUnavailable("Groq model endpoint not found (404)")
        if response.status_code == 408:
            raise ProviderUnavailable("Groq request timed out (408)")
        if response.status_code == 429:
            # Honor Groq's own token-window reset (x-ratelimit-reset-tokens,
            # seconds) so a key comes back the moment its TPM budget resets
            # instead of sitting out a fixed 60s — on small free plans the
            # whole rotation queue used to exhaust within one conversation.
            cooldown = _COOLDOWN_SECONDS
            headers = getattr(response, "headers", None) or {}
            try:
                cooldown = float(headers.get("x-ratelimit-reset-tokens",
                                             _COOLDOWN_SECONDS))
            except (TypeError, ValueError):
                pass
            exc = ProviderUnavailable(
                "Groq rate limit reached (429) - quota exhausted for this API key")
            exc.cooldown_s = min(max(cooldown, 1.0), 120.0)
            raise exc
        if response.status_code >= 500:
            raise ProviderUnavailable(f"Groq server error ({response.status_code})")
        if response.status_code != 200:
            raise ProviderUnavailable(f"Groq status {response.status_code}: {response.text[:200]}")

        if stream:
            def _stream_gen():
                try:
                    for line in response.iter_lines():
                        if not line:
                            continue
                        text = line.decode("utf-8", "ignore")
                        if not text.startswith("data:"):
                            continue
                        body = text[5:].strip()
                        if body == "[DONE]":
                            break
                        try:
                            parsed = json.loads(body)
                            delta = parsed["choices"][0]["delta"].get("content", "")
                        except Exception:
                            delta = ""
                        if delta:
                            yield delta
                finally:
                    response.close()

            return {"stream": True, "chunks": _stream_gen(), "provider": "groq",
                    "model": payload.get("model") or self.model}

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"Groq malformed JSON response: {exc}")

        content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        if not content:
            raise ProviderUnavailable("Groq returned an empty response")
        return {"content": str(content).strip(), "provider": "groq",
                "model": payload.get("model") or self.model}

    def _to_openai_messages(self, messages):
        out = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            imgs = m.get("images") or []
            entry = {"role": role, "content": content}
            if imgs:
                parts = [{"type": "text", "text": content or ""}]
                for img in imgs:
                    parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{img.get('mime_type', 'image/png')};base64,{img['data_b64']}"
                        },
                    })
                entry["content"] = parts
            out.append(entry)
        return out
