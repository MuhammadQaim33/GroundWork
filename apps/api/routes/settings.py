# ============================================================================
# routes/settings.py — the /api/settings and /api/links endpoints.
# ============================================================================

from typing import Annotated

from fastapi import APIRouter, Depends

from auth import require_service_user
from llm import active_provider
from schemas import LinksUpdate, SettingsUpdate
from services.text import _clamp_links
from user_settings import (
    get_gemini_key,
    get_links,
    get_openrouter_key,
    set_gemini_key,
    set_links,
    set_openrouter_key,
)

router = APIRouter(tags=["settings"])


@router.get("/api/settings")
def api_get_settings(_sv: Annotated[dict, Depends(require_service_user)]):
    """Report which LLM provider is active and which keys the user has saved.

    bool(x) turns a value into True/False, so the dashboard can show
    "Gemini key: set ✓" or "not set".
    """
    return {
        "provider": active_provider(),
        "openrouter_key_set": bool(get_openrouter_key()),
        "gemini_key_set": bool(get_gemini_key()),
    }


@router.put("/api/settings")
def api_put_settings(req: SettingsUpdate, _sv: Annotated[dict, Depends(require_service_user)]):
    """Save the user's own LLM API keys to the DB (BYOK)."""
    set_openrouter_key(req.openrouter_api_key)
    set_gemini_key(req.gemini_api_key)
    return {"ok": True}


@router.get("/api/links")
def api_get_links(_sv: Annotated[dict, Depends(require_service_user)]):
    """Return the user's saved profile links."""
    return {"links": get_links()}


@router.put("/api/links")
def api_put_links(req: LinksUpdate, _sv: Annotated[dict, Depends(require_service_user)]):
    """Save the user's profile links (sanitized by _clamp_links)."""
    links = _clamp_links(req.links)
    set_links(links)
    return {"links": links}