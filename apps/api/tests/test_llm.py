from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Settings live in the DB per service_user; tests fake the store lookup and
# the request-scoped contextvar instead of touching a file.
import user_settings  # noqa: E402
from llm import _endpoint, _vision_endpoint, active_provider  # noqa: E402
from user_settings import set_current_service_user  # noqa: E402


def _no_env_keys(monkeypatch):
    # The .env may set GEMINI_API_KEY as a deploy default; the precedence tests
    # below assert DB-saved keys, so neutralize the env fallback (GROQ stays:
    # the groq fallback test asserts the real env key path).
    monkeypatch.setattr(user_settings.settings, "gemini_api_key", "")


def test_endpoint_prefers_openrouter_when_key_saved(monkeypatch):
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
        set_current_service_user(None)


def test_endpoint_falls_back_to_groq_without_key(monkeypatch):
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
    set_current_service_user(1)
    _no_env_keys(monkeypatch)
    monkeypatch.setattr(
        user_settings, "get_service_user", lambda uid: {"id": uid, "openrouter_api_key": ""}
    )
    try:
        _vision_endpoint()
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
    finally:
        set_current_service_user(None)