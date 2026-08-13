from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# settings.json lives under data/ (gitignored); tests use a throwaway location.
import user_settings  # noqa: E402
from llm import _endpoint  # noqa: E402
from user_settings import set_openrouter_key  # noqa: E402

_TEST_SETTINGS = Path(__file__).resolve().parents[1] / "data" / "user_settings.test.json"


def test_endpoint_prefers_openrouter_when_key_saved():
    user_settings.SETTINGS_PATH = _TEST_SETTINGS
    set_openrouter_key("sk-or-test")
    try:
        base, model, _headers = _endpoint()
        assert base == "https://openrouter.ai/api/v1"
        assert model == "meta-llama/llama-3.3-70b-instruct"
    finally:
        _TEST_SETTINGS.unlink(missing_ok=True)


def test_endpoint_falls_back_to_groq_without_key():
    user_settings.SETTINGS_PATH = _TEST_SETTINGS
    set_openrouter_key("")
    try:
        base, model, _headers = _endpoint()
        assert base == "https://api.groq.com/openai/v1"
        assert model == "llama-3.3-70b-versatile"
    finally:
        _TEST_SETTINGS.unlink(missing_ok=True)
