#!/usr/bin/env python3
"""
ai/local_provider.py — local model provider (Phase 13).

Talks to any OpenAI-compatible local server:
  * Ollama:            http://127.0.0.1:11434/v1   (ollama serve / ollama run)
  * llama.cpp server:  http://127.0.0.1:8080/v1   (set AI_BASE_URL)
  * LM Studio:         http://127.0.0.1:1234/v1   (set AI_BASE_URL)
No API key required. Unavailable -> ProviderUnavailable -> chain falls back.
"""
import json

import requests

from nodiq.ai.config import get_config
from nodiq.ai.provider import AIProvider, ProviderUnavailable

_MODEL = {"name": None}


def get_provider():
    return LocalProvider()


class LocalProvider(AIProvider):
    name = "local"

    @property
    def model(self):
        cfg = get_config()
        return cfg.ollama_default_model

    def _base(self):
        cfg = get_config()
        return cfg.ollama_base_url.rstrip("/")

    def available(self):
        try:
            r = requests.get(f"{self._base()}/models", timeout=1.2)
            if r.status_code == 200:
                _MODEL["name"] = self.model
                return True
            return False
        except Exception:
            return False

    def chat(self, messages, context=None, stream=False):
        cfg = get_config()
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": bool(stream),
            "temperature": 0.2,
            "max_tokens": 700,
        }
        try:
            if stream:
                return self._stream(payload, cfg.request_timeout)
            r = requests.post(f"{self._base()}/chat/completions",
                              json=payload, timeout=cfg.request_timeout)
            if r.status_code != 200:
                raise ProviderUnavailable(
                    f"local server status {r.status_code}")
            data = r.json()
            content = (data.get("choices") or [{}])[0].get("message", {}) \
                .get("content", "")
            if not content:
                raise ProviderUnavailable("empty response from local model")
            return {"content": content.strip(), "provider": "local",
                    "model": payload["model"]}
        except ProviderUnavailable:
            raise
        except requests.RequestException as exc:
            raise ProviderUnavailable(f"local server unreachable: {exc}")

    def _stream(self, payload, timeout):
        """Yield chunks as a generator result (Phase 28)."""
        def gen():
            try:
                with requests.post(f"{self._base()}/chat/completions",
                                   json=payload, timeout=timeout,
                                   stream=True) as r:
                    if r.status_code != 200:
                        raise ProviderUnavailable(
                            f"local server status {r.status_code}")
                    for line in r.iter_lines():
                        if not line:
                            continue
                        text = line.decode("utf-8", "ignore")
                        if not text.startswith("data:"):
                            continue
                        body = text[5:].strip()
                        if body == "[DONE]":
                            break
                        try:
                            delta = json.loads(body)["choices"][0] \
                                ["delta"].get("content", "")
                        except Exception:
                            delta = ""
                        if delta:
                            yield delta
            except ProviderUnavailable:
                raise
            except Exception as exc:
                raise ProviderUnavailable(f"stream failed: {exc}")
        return {"stream": True, "chunks": gen(), "provider": "local",
                "model": payload["model"]}
