# ============================================================================
# schemas.py — the Pydantic models shared by every route.
#
# These classes define the exact SHAPE of JSON the endpoints accept. If the
# browser sends JSON that doesn't match, FastAPI returns 422 before any of our
# logic runs. Each field's type is validated: `str` must be text, `int` must be
# a number, `list[...]` must be a list of that thing.
# ============================================================================

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class Answer(BaseModel):
    """One question+answer pair (for application-form questions)."""
    question: str
    answer: str


class Credentials(BaseModel):
    """Signup/login payload."""
    email: str
    password: str


class RefreshRequest(BaseModel):
    """Refresh-token payload."""
    refresh_token: str


class GenerateRequest(BaseModel):
    """The body of a /api/generate call: what the user asked for."""
    job_description: str
    answers: list[Answer] = []                       # optional answers to form questions
    cover_letter_formats: list[Literal["pdf", "text"]] = ["pdf"]   # which formats of the letter
    parts: list[Literal["resume", "cover_letter", "feedback"]] = ["resume", "cover_letter"]
    # ^ which artifacts to produce. Literal[...] means ONLY those exact values are allowed.


class SettingsUpdate(BaseModel):
    """Payload for saving user keys. Default "" = "don't change / clear"."""
    openrouter_api_key: str = ""
    gemini_api_key: str = ""


class LinksUpdate(BaseModel):
    """Payload for saving the user's profile links."""
    links: list[str] = []