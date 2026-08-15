from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Settings live in the DB per service_user; tests fake the store lookup and
# the request-scoped contextvar instead of touching a file.
import user_settings  # noqa: E402
from llm import _endpoint  # noqa: E402
from user_settings import set_current_service_user  # noqa: E402


def test_endpoint_prefers_openrouter_when_key_saved(monkeypatch):
    set_current_service_user(1)
    monkeypatch.setattr(
        user_settings,
        "get_service_user",
        lambda uid: {"id": uid, "openrouter_api_key": "sk-or-test"},
    )
    try:
        base, model, _headers = _endpoint()
        assert base == "https://openrouter.ai/api/v1"
        assert model == "meta-llama/llama-3.3-70b-instruct"
    finally:
        set_current_service_user(None)


def test_endpoint_falls_back_to_groq_without_key(monkeypatch):
    set_current_service_user(1)
    monkeypatch.setattr(
        user_settings, "get_service_user", lambda uid: {"id": uid, "openrouter_api_key": ""}
    )
    try:
        base, model, _headers = _endpoint()
        assert base == "https://api.groq.com/openai/v1"
        assert model == "llama-3.3-70b-versatile"
    finally:
        set_current_service_user(None)