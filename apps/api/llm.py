# ============================================================================
# llm.py — how we talk to the AI language models.
#
# The core insight of this app: we don't pay for one fixed AI provider. We have
# a CHAIN of providers, cheapest/free-est first, and we fail over gracefully:
#
#   Ollama (local, $0)  →  Gemini (Google free tier, needs key)
#                       →  OpenRouter (BYOK)  →  Groq (free tier, last resort)
#
# All these providers speak the same "OpenAI-compatible" HTTP API, so one
# generic `chat()` function can talk to all of them. If one provider is out of
# quota (HTTP 429 = rate limited) we simply try the next one in the chain.
#
# There are two entry points:
#   * chat()        — plain text in, plain text out (resumes, letters, feedback)
#   * vision_chat() — text + images in, text out (reading screenshots of forms)
# ============================================================================

from __future__ import annotations

import base64  # encodes binary image data into text form for transport
import time

import httpx  # the HTTP client library (sends web requests)

from config import settings
from errors import TokenBudgetError
from user_settings import get_gemini_key, get_openrouter_key

# The web addresses of the AI providers' API endpoints. Each is "OpenAI-compatible".
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
RETRY_SLEEP_SECONDS = 45   # how long to wait before retrying a rate-limited provider


def chat(
    system: str,
    user: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    retries: int = 3,
) -> str:
    """One text completion, going through the provider chain with failover.

    PARAMETERS (read these even if you skip the rest):
    * system   — the "role instructions": WHO the model is and its rules.
                 (e.g. "You are a resume editor. Never invent metrics.")
    * user     — the actual request/context (job description, resume, ...).
    * temperature — 0.0 = always the same, robotic; 1.0 = creative/random.
                 Lower = more faithful to facts, which we want for documents.
    * max_tokens  — the largest answer (in word-ish units) we'll accept.
    * retries     — how many times to re-attempt one provider before moving on.

    Returns the model's answer as a string.
    """
    # Build the payload both APIs expect: a list of "messages" (system + user),
    # plus the generation settings. Then _post_completion walks the provider
    # chain until one answers.
    return _post_completion(
        _provider_chain(),
        {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        retries,
    )


def _post_completion(
    chain: list[tuple[str, str, dict[str, str]]],
    base_payload: dict,
    retries: int,
) -> str:
    """POST the payload to each provider in order; fail over on quota/timeout.

    chain elements are (base_url, model_name, headers) triples.
    Note the types: the chain is a list of TUPLES — fixed-size bundles —
    each holding the three things needed to call one provider.

    Failover rules:
    * HTTP 429/413 (rate-limited / too big): try the NEXT provider immediately.
      Only the LAST provider gets sleep-and-retry, because Groq's free tier
      rate-limit is a rolling 1-minute window that actually recovers.
    * HTTP timeouts: move on to the next provider.
    * Other HTTP errors: not recoverable, move on.
    * If EVERY provider fails, raise the last error (the request dies loudly).
    """
    last_error: Exception | None = None
    for index, (base_url, model, headers) in enumerate(chain):
        is_last = index == len(chain) - 1   # are we at the final provider?
        payload = {**base_payload, "model": model}  # same payload + this provider's model
        for attempt in range(retries):
            try:
                # `with httpx.Client(...)` = open a connection, auto-close when done.
                # timeout=180 = give each request up to 3 minutes.
                with httpx.Client(timeout=180) as client:
                    response = client.post(
                        f"{base_url}/chat/completions", json=payload, headers=headers
                    )
                    response.raise_for_status()  # if status isn't 2xx, raises HTTPStatusError
                # Success: pluck the text out of the standard response shape.
                # response.json() = "choices" -> [0] = first answer -> "message" -> "content"
                return response.json()["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code in (429, 413):
                    if not is_last:
                        break  # quota exhausted here — stop this provider, fail over
                    if attempt < retries - 1:
                        time.sleep(RETRY_SLEEP_SECONDS)  # wait out the rolling window
                        continue                          # then retry the same provider
                else:
                    break  # non-recoverable for this provider — fail over
            except httpx.TimeoutException as exc:
                last_error = exc
                break  # provider unresponsive — fail over

    raise last_error if last_error else RuntimeError("unreachable: chat retries exhausted")


def vision_chat(
    system: str,
    user_text: str,
    images: list[tuple[str, bytes]],
    temperature: float = 0.2,
    max_tokens: int = 2000,
    retries: int = 2,
) -> str:
    """Text + images completion (reads screenshots). Gemini or OpenRouter only.

    * images — a list of (mime_type, raw_bytes) pairs, e.g.
               [("image/png", b"...file bytes...")].
    * The images are encoded as base64 "data URIs" inside the request — they
      travel in the HTTP body and are NEVER saved to disk or the database
      (that's a privacy decision baked into this function).
    * Groq's free model is text-only, so a Gemini or OpenRouter key is
      required for vision (enforced in _vision_provider_chain below).
    """
    # The OpenAI-compatible content format: one list mixing text and images.
    content: list[dict] = [{"type": "text", "text": user_text}]
    for mime, data in images:
        encoded = base64.b64encode(data).decode()   # bytes → base64 text
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
        )
    return _post_completion(
        _vision_provider_chain(),
        {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},   # content is now text+images
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        retries,
    )


def active_provider() -> str:
    """Which provider a call will hit first: ollama, gemini, openrouter, or groq.

    Used elsewhere to decide things like "is this the free tier with a token
    budget?" — see _fit_max_tokens in main.py.
    """
    if settings.llm_provider.lower() == "ollama":
        return "ollama"
    if get_gemini_key():
        return "gemini"
    return "openrouter" if get_openrouter_key() else "groq"


def _provider_chain() -> list[tuple[str, str, dict[str, str]]]:
    """Build the full ordered list of providers available right now.

    Only providers that are actually configured are included:
    * Ollama first, ONLY if LLM_PROVIDER=ollama (explicit local-mode switch).
    * Gemini if the user has a key (DB-saved key beats the .env default).
    * OpenRouter if the user has a key.
    * Groq always (it's the free fallback) if a server key exists.

    If nothing at all is configured, raise a helpful error instead of a
    cryptic one later.
    """
    if settings.llm_provider.lower() == "ollama":
        return [(settings.ollama_base_url, settings.ollama_model, {})]  # no auth headers needed
    chain: list[tuple[str, str, dict[str, str]]] = []
    gemini_key = get_gemini_key()
    if gemini_key:
        chain.append(
            (GEMINI_BASE_URL, settings.gemini_model, {"Authorization": f"Bearer {gemini_key}"})
        )
    openrouter_key = get_openrouter_key()
    if openrouter_key:
        chain.append(
            (
                OPENROUTER_BASE_URL,
                settings.openrouter_model,
                {"Authorization": f"Bearer {openrouter_key}"},
            )
        )
    if settings.groq_api_key:
        chain.append(
            (
                GROQ_BASE_URL,
                settings.llm_model,
                {"Authorization": f"Bearer {settings.groq_api_key}"},
            )
        )
    if not chain:
        raise RuntimeError(
            "No LLM API key configured. Add a Gemini key in Settings "
            "(free, recommended), an OpenRouter key in Settings (best results), "
            "or set GROQ_API_KEY in apps/api/.env (or switch LLM_PROVIDER=ollama)."
        )
    return chain


def _endpoint() -> tuple[str, str, dict[str, str]]:
    """The PRIMARY provider (base_url, model, headers) — first item of the chain."""
    return _provider_chain()[0]


def _vision_provider_chain() -> list[tuple[str, str, dict[str, str]]]:
    """Vision-capable providers in precedence order: Gemini, then OpenRouter."""
    chain: list[tuple[str, str, dict[str, str]]] = []
    gemini_key = get_gemini_key()
    if gemini_key:
        chain.append(
            (
                GEMINI_BASE_URL,
                settings.gemini_vision_model,
                {"Authorization": f"Bearer {gemini_key}"},
            )
        )
    openrouter_key = get_openrouter_key()
    if openrouter_key:
        chain.append(
            (
                OPENROUTER_BASE_URL,
                settings.openrouter_vision_model,
                {"Authorization": f"Bearer {openrouter_key}"},
            )
        )
    if not chain:
        raise RuntimeError(
            "Vision needs a Gemini or OpenRouter key — add one in Settings "
            "(the free-tier Groq model is text-only)."
        )
    return chain


def _vision_endpoint() -> tuple[str, str, dict[str, str]]:
    """The PRIMARY vision provider — first item of the vision chain."""
    return _vision_provider_chain()[0]


# ============================================================================
# Token-budget math for the Groq free tier.
#
# Groq's free llama-3.3-70b model is capped at 12,000 "tokens per minute"
# (roughly word-parts). A request counts its INPUT length + the max_tokens we
# ask for as OUTPUT against that rolling budget. So we compute how many output
# tokens we can afford given the input size, and fail loudly if the input
# alone is already too big. This guard only applies to Groq — BYOK OpenRouter
# and local Ollama have no such ceiling.
# ============================================================================

TPM_BUDGET = 11000          # leave a little headroom under the 12,000 cap
MAX_OUT_TOKENS = 5000       # biggest output we'll ever request


def _fit_max_tokens(system: str, user: str, floor: int = 800) -> int:
    """How many output tokens may we request for this prompt?

    Rough input estimate: English is ~4 chars per token, so len(text)//4.
    * Non-Groq providers: no TPM ceiling — but OpenRouter RESERVES max_tokens
      worth of credits per call, so request only the floor (what the task
      needs), not the 5000 cap.
    * Groq: fit output within the budget left after the input, never below
      `floor`; if input alone busts the budget, raise a clear 400 error.
    """
    est_input = (len(system) + len(user)) // 4
    if active_provider() != "groq":
        return floor
    max_out = max(floor, min(MAX_OUT_TOKENS, TPM_BUDGET - est_input))
    if est_input + max_out > TPM_BUDGET + 500:   # +500 slack for estimate error
        raise TokenBudgetError(
            "Input is too large for the model's free-tier token budget. "
            "Shorten the job description or simplify the master CV "
            "(or add an OpenRouter key in Settings for no limits).",
        )
    return max_out