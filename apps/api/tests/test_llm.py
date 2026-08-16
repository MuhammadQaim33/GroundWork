# ============================================================================
# test_llm.py — checks the LLM provider chain: which provider wins, in what
# order, and how failures fail over.
#
# Two things are tested here:
#   A. Precedence — given various saved keys, which provider does the app
#      pick? (Gemini beats OpenRouter beats Groq; no keys → Groq fallback.)
#   B. Failover   — if one provider returns 429 (rate limited), does chat()
#      move to the next provider instead of dying? And does it raise when
#      every provider is exhausted?
#
# KEY CONCEPT — mocking the network: tests never call real AI providers.
# They monkeypatch (swap) the HTTP client and the sleep function with fakes:
#   * _FakeResponse — stands in for an HTTP response (status code + body).
#   * _FakeClient   — stands in for the HTTP client; it has a QUEUE of
#     fake responses per provider URL and hands them out in order, also
#     recording every URL it was asked to call so tests can assert order.
#
# Note on user_settings: real settings are per-user in the DB, so tests fake
# get_service_user() to return a dict with whatever keys the test needs, and
# use set_current_service_user() to put a user "in context" first.
# ============================================================================

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # import path to apps/api/

# Settings live in the DB per service_user; tests fake the store lookup and
# the request-scoped contextvar instead of touching a file.
import user_settings  # noqa: E402
from llm import (  # noqa: E402
    _endpoint,
    _provider_chain,
    _vision_endpoint,
    active_provider,
    chat,
)
from user_settings import set_current_service_user  # noqa: E402


def _no_env_keys(monkeypatch):
    """Neutralize the .env's GEMINI_API_KEY (a server-side default) so the
    precedence tests below only see the DB-saved keys they set up."""
    monkeypatch.setattr(user_settings.settings, "gemini_api_key", "")


# --- Provider precedence tests -------------------------------------------------

def test_endpoint_prefers_openrouter_when_key_saved(monkeypatch):
    """With an OpenRouter key saved and no Gemini key, OpenRouter is primary."""
    set_current_service_user(1)
    _no_env_keys(monkeypatch)
    monkeypatch.setattr(
        user_settings,
        "get_service_user",
        lambda uid: {"id": uid, "openrouter_api_key": "sk-or-test"},
    )
    try:
        base, model, _headers = _endpoint()
        assert base == "https://openrouter.ai/api/v1"
        assert model == "google/gemini-2.5-flash"
    finally:
        set_current_service_user(None)   # always clean up the contextvar


def test_endpoint_falls_back_to_groq_without_key(monkeypatch):
    """No saved keys at all → the free Groq fallback is used."""
    set_current_service_user(1)
    _no_env_keys(monkeypatch)
    monkeypatch.setattr(
        user_settings, "get_service_user", lambda uid: {"id": uid, "openrouter_api_key": ""}
    )
    try:
        base, model, _headers = _endpoint()
        assert base == "https://api.groq.com/openai/v1"
        assert model == "llama-3.3-70b-versatile"
    finally:
        set_current_service_user(None)


def test_endpoint_prefers_gemini_when_key_saved(monkeypatch):
    """With a Gemini key saved, Gemini is primary (and the auth header carries
    that user's key)."""
    set_current_service_user(1)
    monkeypatch.setattr(
        user_settings,
        "get_service_user",
        lambda uid: {"id": uid, "gemini_api_key": "sk-gem-test"},
    )
    try:
        base, model, headers = _endpoint()
        assert base == "https://generativelanguage.googleapis.com/v1beta/openai"
        assert model == "gemini-3.6-flash"
        assert headers["Authorization"] == "Bearer sk-gem-test"
    finally:
        set_current_service_user(None)


def test_gemini_outranks_openrouter(monkeypatch):
    """Both keys saved → Gemini wins (it's free, OpenRouter is the fallback)."""
    set_current_service_user(1)
    _no_env_keys(monkeypatch)
    monkeypatch.setattr(
        user_settings,
        "get_service_user",
        lambda uid: {"id": uid, "gemini_api_key": "sk-gem", "openrouter_api_key": "sk-or"},
    )
    try:
        base, model, _headers = _endpoint()
        assert base == "https://generativelanguage.googleapis.com/v1beta/openai"
        assert active_provider() == "gemini"
    finally:
        set_current_service_user(None)


def test_vision_endpoint_prefers_gemini(monkeypatch):
    """Vision (screenshot reading) also prefers Gemini."""
    set_current_service_user(1)
    monkeypatch.setattr(
        user_settings,
        "get_service_user",
        lambda uid: {"id": uid, "gemini_api_key": "sk-gem", "openrouter_api_key": "sk-or"},
    )
    try:
        base, model, _headers = _vision_endpoint()
        assert base == "https://generativelanguage.googleapis.com/v1beta/openai"
        assert model == "gemini-3.6-flash"
    finally:
        set_current_service_user(None)


def test_vision_endpoint_raises_without_key(monkeypatch):
    """Vision needs a key (Groq's free model is text-only) — no key must raise."""
    set_current_service_user(1)
    _no_env_keys(monkeypatch)
    monkeypatch.setattr(
        user_settings, "get_service_user", lambda uid: {"id": uid, "openrouter_api_key": ""}
    )
    try:
        _vision_endpoint()
        raise AssertionError("expected RuntimeError")   # fail test if nothing was raised
    except RuntimeError:
        pass
    finally:
        set_current_service_user(None)


# --- Fake HTTP layer for the failover tests -------------------------------------

class _FakeResponse:
    """Stands in for an HTTP response. Holds a status code and (optionally)
    body text; raise_for_status() raises if the status is an error."""

    def __init__(self, status: int, text: str = ""):
        self.status_code = status
        self._text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("boom", request=None, response=self)

    def json(self) -> dict:
        # Shape of a real LLM chat response: the answer text lives here.
        return {"choices": [{"message": {"content": self._text}}]}


class _FakeClient:
    """Stands in for the HTTP client. Returns queued responses per provider
    base URL, in call order, and records every URL it was asked to call."""

    def __init__(self, queue: dict[str, list[_FakeResponse]], timeout: int = 0):
        self._queue = queue      # {provider base URL: [responses to hand out]}
        self._calls: list[str] = []   # every URL we were asked to post to

    # These two methods make the object usable with `with` (context manager),
    # which is how llm.py uses httpx.Client.
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url: str, json: dict | None = None, headers: dict | None = None):
        self._calls.append(url)
        base = url.rsplit("/", 2)[0]     # strip the path → provider base URL
        resp = self._queue[base].pop(0)  # hand out the next queued response
        return resp

    @property
    def calls(self) -> list[str]:
        return self._calls


# --- Failover behavior tests ----------------------------------------------------

def test_chat_fails_over_to_next_provider_on_quota(monkeypatch):
    """Gemini is primary but returns 429 (rate limit) → chat() must fall
    through to Groq and return Groq's answer. Also assert the call ORDER."""
    set_current_service_user(1)
    monkeypatch.setattr(
        user_settings,
        "get_service_user",
        lambda uid: {"id": uid, "gemini_api_key": "sk-gem", "openrouter_api_key": ""},
    )
    client = _FakeClient(
        {
            "https://generativelanguage.googleapis.com/v1beta/openai": [
                _FakeResponse(429, "quota exceeded")     # Gemini: rate-limited
            ],
            "https://api.groq.com/openai/v1": [_FakeResponse(200, "from groq")],  # Groq: success
        }
    )
    monkeypatch.setattr("llm.httpx.Client", lambda *a, **k: client)  # swap real HTTP client
    monkeypatch.setattr("llm.time.sleep", lambda s: None)            # don't actually sleep
    try:
        assert chat("sys", "user") == "from groq"
        assert client.calls[0].startswith("https://generativelanguage.googleapis.com")
        assert client.calls[1].startswith("https://api.groq.com")
    finally:
        set_current_service_user(None)


def test_chat_raises_when_all_providers_exhausted(monkeypatch):
    """Every provider is rate-limited → the request must FAIL (raise), not
    hang or silently return garbage."""
    set_current_service_user(1)
    monkeypatch.setattr(
        user_settings,
        "get_service_user",
        lambda uid: {"id": uid, "gemini_api_key": "sk-gem", "openrouter_api_key": ""},
    )
    client = _FakeClient(
        {
            "https://generativelanguage.googleapis.com/v1beta/openai": [_FakeResponse(429)],
            "https://api.groq.com/openai/v1": [_FakeResponse(429)],
        }
    )
    monkeypatch.setattr("llm.httpx.Client", lambda *a, **k: client)
    monkeypatch.setattr("llm.time.sleep", lambda s: None)
    import httpx

    try:
        try:
            chat("sys", "user", retries=1)     # retries=1 → one shot per provider
            raise AssertionError("expected HTTPStatusError")
        except httpx.HTTPStatusError:
            pass   # correct: an error WAS raised
        assert len(client.calls) == 2   # both providers got exactly one attempt
    finally:
        set_current_service_user(None)


def test_provider_chain_orders_gemini_openrouter_groq(monkeypatch):
    """Both keys saved → the chain must be ordered Gemini → OpenRouter → Groq."""
    set_current_service_user(1)
    _no_env_keys(monkeypatch)
    monkeypatch.setattr(
        user_settings,
        "get_service_user",
        lambda uid: {"id": uid, "gemini_api_key": "sk-gem", "openrouter_api_key": "sk-or"},
    )
    try:
        chain = _provider_chain()
        assert [base for base, _, _ in chain] == [
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "https://openrouter.ai/api/v1",
            "https://api.groq.com/openai/v1",
        ]
    finally:
        set_current_service_user(None)