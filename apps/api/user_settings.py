# ============================================================================
# user_settings.py — per-user settings, resolved through a request-scoped context.
#
# The twist this file exists for: which LLM provider is used must be decided
# PER USER, not globally. Alice saved her own Gemini key; Bob uses his own
# OpenRouter key; Carol has no key and gets the free Groq fallback.
#
# The problem: deep helper functions (like the LLM caller in llm.py) don't get
# the user's id passed to them as a parameter — that would mean threading an id
# through every function call. Instead we use a Python "ContextVar":
#
#     A ContextVar is a value that exists only for the duration of one request.
#     When a request arrives, auth.py does set_current_service_user(id).
#     From then on, ANY code running during that request can read that id back
#     with current_service_user_id.get() — even without it being passed around.
#
# It's like a sticky note attached to the current request: put it on at the
# door, read it anywhere inside. FastAPI runs each request in its own context,
# so two simultaneous users can't read each other's sticky note.
# ============================================================================

from __future__ import annotations

from contextvars import ContextVar

from config import settings
from store import (
    get_service_user,
    set_service_user_gemini_key,
    set_service_user_links,
    set_service_user_openrouter_key,
)

# The sticky note: the service_users.id of the user currently being served.
# Default None = "no user in context right now" (e.g. during tests/startup).
# Set per-request by auth.require_service_user.
current_service_user_id: ContextVar[int | None] = ContextVar(
    "current_service_user_id", default=None
)


def set_current_service_user(service_user_id: int | None) -> None:
    """Put the current user's id on the request's sticky note (called by auth)."""
    current_service_user_id.set(service_user_id)


def get_openrouter_key() -> str:
    """The key the CURRENT user saved in the DB wins; the env var is only a server default.

    Logic: if we know which user this request is for, look up their row and
    return their saved key if they have one. Otherwise fall back to the
    server-wide .env value.
    """
    service_user_id = current_service_user_id.get()
    if service_user_id is not None:
        row = get_service_user(service_user_id)
        if row and row.get("openrouter_api_key"):
            return row["openrouter_api_key"]
    return settings.openrouter_api_key


def set_openrouter_key(key: str, service_user_id: int | None = None) -> None:
    """Save the current user's OpenRouter key to the DB."""
    # If the caller didn't pass an explicit id, read it from the sticky note.
    sid = service_user_id if service_user_id is not None else current_service_user_id.get()
    if sid is None:
        # No user in context → we literally don't know whose key this is. Refuse.
        raise RuntimeError("set_openrouter_key requires the request's service user")
    set_service_user_openrouter_key(sid, key.strip())  # .strip() removes accidental spaces


def get_gemini_key() -> str:
    """The key the CURRENT user saved wins; the env var is only a server default."""
    service_user_id = current_service_user_id.get()
    if service_user_id is not None:
        row = get_service_user(service_user_id)
        if row and row.get("gemini_api_key"):
            return row["gemini_api_key"]
    return settings.gemini_api_key


def set_gemini_key(key: str, service_user_id: int | None = None) -> None:
    """Save the current user's Gemini key to the DB."""
    sid = service_user_id if service_user_id is not None else current_service_user_id.get()
    if sid is None:
        raise RuntimeError("set_gemini_key requires the request's service user")
    set_service_user_gemini_key(sid, key.strip())


def get_links() -> list[str]:
    """Return the current user's profile links (GitHub, LinkedIn, ...)."""
    service_user_id = current_service_user_id.get()
    if service_user_id is None:
        return []
    row = get_service_user(service_user_id)
    return list(row.get("links") or []) if row else []  # `or []` guards against None


def set_links(links: list[str], service_user_id: int | None = None) -> None:
    """Save the current user's profile links to the DB."""
    sid = service_user_id if service_user_id is not None else current_service_user_id.get()
    if sid is None:
        raise RuntimeError("set_links requires the request's service user")
    set_service_user_links(sid, links)