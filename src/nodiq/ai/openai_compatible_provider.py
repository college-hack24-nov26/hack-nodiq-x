#!/usr/bin/env python3
"""
ai/openai_compatible_provider.py — any OpenAI-compatible endpoint.

Covers OpenAI itself and the many compatible gateways. Only active when
AI_API_KEY is set (or AI_BASE_URL points at a trusted local gateway).
"""
import json

import requests

from nodiq.ai.config import get_config
from nodiq.ai.provider import AIProvider, ProviderUnavailable


def get_provider():
    return OpenAICompatibleProvider()


class OpenAICompatibleProvider(AIProvider):
    name = "openai"

    @property
    def model(self):
        cfg = get_config()
        return cfg.model or cfg.openai_default_model

    def available(self):
        cfg = get_config()
        return bool(cfg.api_key) and not cfg.offline_mode

    def supports_vision(self):
        return True

    def chat(self, messages, context=None, stream=False):
        cfg = get_config()
        if not self.available():
            raise ProviderUnavailable("no AI_API_KEY configured for openai")
        out_messages = []
        for m in messages:
            entry = {"role": m.get("role"), "content": m.get("content", "")}
            imgs = m.get("images") or []
            if imgs:
                entry["content"] = [{"type": "text", "text": entry["content"]}]
                for img in imgs:
                    entry["content"].append({
                        "type": "image_url",
                        "image_url": {"url":
                                      f"data:{img.get('mime_type', 'image/png')};"
                                      f"base64,{img['data_b64']}"}})
            out_messages.append(entry)
        payload = {"model": self.model, "messages": out_messages,
                   "temperature": 0.2, "max_tokens": 900,
                   "stream": bool(stream)}
        try:
            if stream:
                return self._stream(payload, cfg)
            r = requests.post(f"{cfg.openai_base_url.rstrip('/')}/chat/completions",
                              json=payload, timeout=cfg.request_timeout,
                              headers={"Authorization":
                                       f"Bearer {cfg.api_key}"})
            if r.status_code != 200:
                raise ProviderUnavailable(
                    f"openai-compatible status {r.status_code}: {r.text[:160]}")
            data = r.json()
            content = (data.get("choices") or [{}])[0].get("message", {}) \
                .get("content", "")
            if not content:
                raise ProviderUnavailable("empty response")
            return {"content": content.strip(), "provider": "openai",
                    "model": payload["model"]}
        except ProviderUnavailable:
            raise
        except requests.RequestException as exc:
            raise ProviderUnavailable(f"endpoint unreachable: {exc}")

    def _stream(self, payload, cfg):
        def gen():
            try:
                with requests.post(
                        f"{cfg.openai_base_url.rstrip('/')}/chat/completions",
                        json=payload, timeout=cfg.request_timeout,
                        stream=True,
                        headers={"Authorization": f"Bearer {cfg.api_key}"}) as r:
                    if r.status_code != 200:
                        raise ProviderUnavailable(f"status {r.status_code}")
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
            except Exception as exc:
                raise ProviderUnavailable(f"stream failed: {exc}")
        return {"stream": True, "chunks": gen(), "provider": "openai",
                "model": payload["model"]}
