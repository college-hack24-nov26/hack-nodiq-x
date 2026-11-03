#!/usr/bin/env python3
"""
ai/gemini_provider.py — optional Gemini provider (free-tier friendly).

Uses the Generative Language REST API directly with `requests` — no SDK
dependency. Only active when AI_API_KEY is set. Vision-capable (images can
be attached to messages as inline_data parts).

Root-cause fix (hackathon): Google retires model aliases over time (the
configured gemini-2.5-flash began returning 404 "no longer available to new
users"), which silently degraded every Copilot answer to the offline rules
engine. When the configured model returns 404/NOT_FOUND the provider now
retries the same request on known-current models (AI_MODEL first, then
gemini-flash-latest etc.) and reports which model actually answered.
"""
import requests

from nodiq.ai.config import get_config
from nodiq.ai.provider import AIProvider, ProviderUnavailable

# Tried in order when the configured model is gone (first success wins).
# gemini-flash-latest is Google's rolling alias for the current flash model.
_FALLBACK_MODELS = ("gemini-flash-latest", "gemini-2.5-flash-lite",
                    "gemini-flash-lite-latest")


def get_provider():
    return GeminiProvider()


class GeminiProvider(AIProvider):
    name = "gemini"

    @property
    def model(self):
        return get_config().gemini_default_model

    def available(self):
        cfg = get_config()
        return bool(cfg.api_key) and not cfg.offline_mode

    def supports_vision(self):
        return True

    def _candidate_models(self):
        cfg = get_config()
        seen, models = set(), []
        for m in (cfg.model, *_FALLBACK_MODELS):
            if m and m not in seen:
                seen.add(m)
                models.append(m)
        return models

    def chat(self, messages, context=None, stream=False):
        cfg = get_config()
        if not self.available():
            raise ProviderUnavailable("no AI_API_KEY configured for gemini")
        if stream:
            raise ProviderUnavailable("streaming handled via non-stream path")

        contents, system_text = [], None
        for m in messages:
            role = m.get("role")
            if role == "system":
                system_text = m.get("content", "")
                continue
            parts = []
            text = m.get("content", "")
            if text:
                parts.append({"text": text})
            for img in m.get("images", []) or []:
                parts.append({"inline_data": {
                    "mime_type": img.get("mime_type", "image/png"),
                    "data": img["data_b64"]}})
            contents.append({"role": "model" if role == "assistant"
                             else "user", "parts": parts or [{"text": ""}]})

        payload = {"contents": contents}
        if system_text:
            payload["system_instruction"] = {"parts": [{"text": system_text}]}
        payload["generationConfig"] = {"temperature": 0.2,
                                       "maxOutputTokens": 900}

        errors = []
        for model in self._candidate_models():
            url = (f"{cfg.gemini_base_url}/models/{model}:generateContent"
                   f"?key={cfg.api_key}")
            try:
                r = requests.post(url, json=payload,
                                  timeout=cfg.request_timeout)
            except requests.RequestException as exc:
                errors.append(f"{model}: unreachable ({exc})")
                continue                      # network issue -> try next model
            if r.status_code == 200:
                data = r.json()
                cands = data.get("candidates") or [{}]
                parts = (cands[0].get("content") or {}).get("parts") or []
                content = "".join(p.get("text", "") for p in parts).strip()
                if not content:
                    errors.append(f"{model}: empty response")
                    continue
                return {"content": content, "provider": "gemini",
                        "model": model}
            if r.status_code in (400, 404) and "NOT_FOUND" in r.text:
                errors.append(f"{model}: not available "
                              f"(HTTP {r.status_code})")
                continue                      # retired model -> try next
            # real configuration/auth/quota problem: report it honestly
            raise ProviderUnavailable(
                f"gemini status {r.status_code}: {r.text[:160]}")
        raise ProviderUnavailable("; ".join(errors) or
                                  "no gemini model responded")
