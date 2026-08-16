from __future__ import annotations

from contextvars import ContextVar

from config import settings
from store import (
    get_service_user,
    set_service_user_gemini_key,
    set_service_user_links,
    set_service_user_openrouter_key,
)

# The service_users.id resolved from the JWT's app_metadata.service_user_id
# custom claim. Set per-request by auth.require_service_user; read by
# get/set_openrouter_key so LLM provider selection is per-user, not global.
current_service_user_id: ContextVar[int | None] = ContextVar(
    "current_service_user_id", default=None
)


def set_current_service_user(service_user_id: int | None) -> None:
    current_service_user_id.set(service_user_id)


def get_openrouter_key() -> str:
    """Key saved for the current user wins; the env var is only a deploy default."""
    service_user_id = current_service_user_id.get()
    if service_user_id is not None:
        row = get_service_user(service_user_id)
        if row and row.get("openrouter_api_key"):
            return row["openrouter_api_key"]
    return settings.openrouter_api_key


def set_openrouter_key(key: str, service_user_id: int | None = None) -> None:
    sid = service_user_id if service_user_id is not None else current_service_user_id.get()
    if sid is None:
        raise RuntimeError("set_openrouter_key requires the request's service user")
    set_service_user_openrouter_key(sid, key.strip())


def get_gemini_key() -> str:
    """Key saved for the current user wins; the env var is only a deploy default."""
    service_user_id = current_service_user_id.get()
    if service_user_id is not None:
        row = get_service_user(service_user_id)
        if row and row.get("gemini_api_key"):
            return row["gemini_api_key"]
    return settings.gemini_api_key


def set_gemini_key(key: str, service_user_id: int | None = None) -> None:
    sid = service_user_id if service_user_id is not None else current_service_user_id.get()
    if sid is None:
        raise RuntimeError("set_gemini_key requires the request's service user")
    set_service_user_gemini_key(sid, key.strip())


def get_links() -> list[str]:
    service_user_id = current_service_user_id.get()
    if service_user_id is None:
        return []
    row = get_service_user(service_user_id)
    return list(row.get("links") or []) if row else []


def set_links(links: list[str], service_user_id: int | None = None) -> None:
    sid = service_user_id if service_user_id is not None else current_service_user_id.get()
    if sid is None:
        raise RuntimeError("set_links requires the request's service user")
    set_service_user_links(sid, links)
