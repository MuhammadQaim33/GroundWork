# ============================================================================
# services/sse.py — Server-Sent Events wire-format helpers.
#
# SSE in one line: the server opens a long-lived response and writes plain-text
# lines like  event: <name>  /  data: <json>  down it. The browser reads them
# as they arrive — progress without polling.
# ============================================================================

from __future__ import annotations

import json

import httpx
from fastapi import HTTPException

from errors import GenerationError


def _sse(event: str, data: dict) -> str:
    """Format one SSE event as the wire format:
       event: <name>\n
       data: <json>\n
       \n
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_error(exc: Exception) -> str:
    """Turn any exception into a short, human-readable error string for SSE."""
    if isinstance(exc, HTTPException):      # a deliberate API error → use its message
        return str(exc.detail)
    if isinstance(exc, GenerationError):    # a domain error → its message, no class prefix
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):   # an AI provider error
        return f"LLM provider error ({exc.response.status_code}). {exc.response.text[:300]}"
    return f"Generation failed: {exc}"      # anything else → generic message