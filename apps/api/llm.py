from __future__ import annotations

import base64
import time

import httpx

from config import settings
from user_settings import get_openrouter_key

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
RETRY_SLEEP_SECONDS = 45


def chat(
    system: str,
    user: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    retries: int = 3,
) -> str:
    """Single completion through the configured provider (OpenAI-compatible chat API).

    Provider precedence: Ollama (LLM_PROVIDER=ollama) → OpenRouter (bring-your-own
    key, saved in Settings) → Groq (free fallback). The free tier enforces a rolling
    TPM window per minute; 429 (and 413 for oversize requests) are recoverable once
    the window rolls. Sleep and retry.
    """
    base_url, model, headers = _endpoint()

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    for attempt in range(retries):
        try:
            with httpx.Client(timeout=180) as client:
                response = client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 413) and attempt < retries - 1:
                time.sleep(RETRY_SLEEP_SECONDS)
                continue
            raise

    raise RuntimeError("unreachable: chat retries exhausted")


def vision_chat(
    system: str,
    user_text: str,
    images: list[tuple[str, bytes]],
    temperature: float = 0.2,
    max_tokens: int = 2000,
    retries: int = 2,
) -> str:
    """Vision completion through OpenRouter (BYOK).

    Images travel as base64 data URIs inside the request and are never persisted.
    The free-tier Groq model is text-only, so a saved OpenRouter key is required.
    """
    if not get_openrouter_key():
        raise RuntimeError(
            "Vision needs an OpenRouter key — add one in Settings "
            "(the free-tier Groq model is text-only)."
        )
    content: list[dict] = [{"type": "text", "text": user_text}]
    for mime, data in images:
        encoded = base64.b64encode(data).decode()
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
        )

    payload = {
        "model": settings.openrouter_vision_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    for attempt in range(retries):
        try:
            with httpx.Client(timeout=180) as client:
                response = client.post(
                    f"{OPENROUTER_BASE_URL}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {get_openrouter_key()}"},
                )
                response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 413) and attempt < retries - 1:
                time.sleep(RETRY_SLEEP_SECONDS)
                continue
            raise

    raise RuntimeError("unreachable: vision chat retries exhausted")


def active_provider() -> str:
    """Which provider a call will hit: ollama, openrouter, or groq (fallback)."""
    if settings.llm_provider.lower() == "ollama":
        return "ollama"
    return "openrouter" if get_openrouter_key() else "groq"


def _endpoint() -> tuple[str, str, dict[str, str]]:
    """Resolve the active (base_url, model, headers) for the current provider."""
    provider = settings.llm_provider.lower()
    if provider == "ollama":
        return settings.ollama_base_url, settings.ollama_model, {}
    openrouter_key = get_openrouter_key()
    if openrouter_key:
        return OPENROUTER_BASE_URL, settings.openrouter_model, {
            "Authorization": f"Bearer {openrouter_key}"
        }
    if not settings.groq_api_key:
        raise RuntimeError(
            "No LLM API key configured. Add an OpenRouter key in Settings "
            "(recommended for best results), or set GROQ_API_KEY in apps/api/.env "
            "(or switch LLM_PROVIDER=ollama)."
        )
    return GROQ_BASE_URL, settings.llm_model, {"Authorization": f"Bearer {settings.groq_api_key}"}
