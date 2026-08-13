from __future__ import annotations

import json
from pathlib import Path

from config import settings

SETTINGS_PATH = Path(__file__).resolve().parent / "data" / "user_settings.json"


def _load() -> dict[str, str]:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict[str, str]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data), encoding="utf-8")


def get_openrouter_key() -> str:
    """Key saved in the UI wins; the env var is only a deploy-time default."""
    return _load().get("openrouter_api_key", "") or settings.openrouter_api_key


def set_openrouter_key(key: str) -> None:
    data = _load()
    data["openrouter_api_key"] = key.strip()
    _save(data)
