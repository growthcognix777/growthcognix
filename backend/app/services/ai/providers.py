"""Provider-agnostic LLM layer. Gemini and Groq are called over plain HTTPS (no SDK lock-in).

Every call asks for JSON and the caller validates it against a Pydantic schema. Adding Ollama or any
OpenAI-compatible endpoint later means adding one class with `generate_json`.
"""
from __future__ import annotations

import json
import re
from typing import Protocol

import httpx

from app.core.config import get_settings


class ProviderError(RuntimeError):
    """A provider call failed (network, quota, bad key). Retryable."""


class ProviderNotConfigured(RuntimeError):
    pass


class LLMProvider(Protocol):
    name: str
    model: str
    max_context_chars: int

    def generate_json(self, system: str, prompt: str) -> dict: ...


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ProviderError(f"Model did not return JSON: {e}") from e
        data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ProviderError("Model returned JSON that is not an object")
    return data


class GeminiProvider:
    name = "gemini"
    max_context_chars = 120_000

    def __init__(self, api_key: str, model: str, timeout: int):
        self.api_key, self.model, self.timeout = api_key, model, timeout

    def generate_json(self, system: str, prompt: str) -> dict:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        try:
            r = httpx.post(url, json=body, headers={"x-goog-api-key": self.api_key}, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise ProviderError(f"Gemini request failed: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"Gemini returned {r.status_code}: {r.text[:300]}")
        try:
            parts = r.json()["candidates"][0]["content"]["parts"]
            return _parse_json("".join(p.get("text", "") for p in parts))
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Unexpected Gemini response: {r.text[:300]}") from e


    def image_text(self, data: bytes, mime: str) -> str:
        """Transcribe the text visible in an image (catalogue page, brochure, label). Returns '' if none."""
        import base64
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {"contents": [{"role": "user", "parts": [
            {"text": "Transcribe all readable text in this image exactly as written. Do not describe or add "
                     "anything. If there is no readable text, reply with an empty string."},
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}]}],
            "generationConfig": {"temperature": 0}}
        try:
            r = httpx.post(url, json=body, headers={"x-goog-api-key": self.api_key}, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise ProviderError(f"Gemini request failed: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"Gemini returned {r.status_code}: {r.text[:300]}")
        try:
            return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"]).strip()
        except (KeyError, IndexError):
            return ""


class GroqProvider:
    """Groq exposes an OpenAI-compatible chat API."""
    name = "groq"
    max_context_chars = 24_000  # free-tier token-per-minute limits are small

    def __init__(self, api_key: str, model: str, timeout: int):
        self.api_key, self.model, self.timeout = api_key, model, timeout

    def generate_json(self, system: str, prompt: str) -> dict:
        body = {
            "model": self.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        try:
            r = httpx.post("https://api.groq.com/openai/v1/chat/completions", json=body,
                           headers={"Authorization": f"Bearer {self.api_key}"}, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise ProviderError(f"Groq request failed: {e}") from e
        if r.status_code != 200:
            raise ProviderError(f"Groq returned {r.status_code}: {r.text[:300]}")
        try:
            return _parse_json(r.json()["choices"][0]["message"]["content"])
        except (KeyError, IndexError) as e:
            raise ProviderError(f"Unexpected Groq response: {r.text[:300]}") from e


# Tests (and future local setups) can install an override here.
_OVERRIDE: dict[str, LLMProvider] = {}


def set_override(purpose: str, provider: LLMProvider | None) -> None:
    if provider is None:
        _OVERRIDE.pop(purpose, None)
    else:
        _OVERRIDE[purpose] = provider


def _build(name: str) -> LLMProvider | None:
    s = get_settings()
    if name == "gemini" and s.gemini_api_key:
        return GeminiProvider(s.gemini_api_key, s.gemini_model, s.ai_timeout_seconds)
    if name == "groq" and s.groq_api_key:
        return GroqProvider(s.groq_api_key, s.groq_model, s.ai_timeout_seconds)
    return None


def get_provider(purpose: str = "analysis") -> LLMProvider:
    """purpose: 'analysis' (long context) or 'fast'. Falls back to the other configured provider."""
    if purpose in _OVERRIDE:
        return _OVERRIDE[purpose]
    s = get_settings()
    preferred = s.ai_analysis_provider if purpose == "analysis" else s.ai_fast_provider
    for name in (preferred, "gemini", "groq"):
        p = _build(name)
        if p:
            return p
    raise ProviderNotConfigured(
        "No AI provider is configured. Add GEMINI_API_KEY or GROQ_API_KEY to the backend environment.")


def get_vision():
    """Image text extraction needs Gemini (Groq has no free OCR path here)."""
    if "vision" in _OVERRIDE:
        return _OVERRIDE["vision"]
    p = _build("gemini")
    return p


def provider_status() -> list[dict]:
    s = get_settings()
    overridden = bool(_OVERRIDE)
    return [
        {"name": "gemini", "model": s.gemini_model, "configured": bool(s.gemini_api_key) or overridden,
         "used_for": "analysis" if s.ai_analysis_provider == "gemini" else "fallback"},
        {"name": "groq", "model": s.groq_model, "configured": bool(s.groq_api_key) or overridden,
         "used_for": "fast" if s.ai_fast_provider == "groq" else "fallback"},
    ]
