# ============================================================================
# config.py — the API's "settings dials".
#
# This is the ONE place that reads environment configuration (the .env file /
# environment variables). Every other file imports `settings` from here so they
# never have to care where a value came from — they just read `settings.foo`.
#
# Think of it like the config page of an app, but stored in a text file that
# only the server reads.
# ============================================================================

# Magic incantation that makes newer Python type syntax work on older Pythons.
# In plain terms: it tells Python "don't try to *evaluate* type hints at import
# time, just keep them as text." Because of this we can write things like
# `str | None` (meaning "either a string or nothing") without Python choking.
from __future__ import annotations

# pydantic-settings is a library that turns a .env file into typed Python
# objects. BaseSettings = the base class that gives us that magic.
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # A Python "class" is a blueprint; here the blueprint just declares the
    # config knobs. Each line below = one setting: a NAME, a TYPE (": str" means
    # it holds text), and a default value ("= '...'").
    #
    # pydantic matches these field names to keys in the .env file and fills in
    # the values at startup. Anything not in .env keeps its default.

    # Where to look for the .env file (relative to the working directory).
    model_config = SettingsConfigDict(env_file=".env")

    # --- External services ------------------------------------------------
    # Supabase = the hosted database + auth + file storage backend.
    supabase_url: str = ""                     # web address of our Supabase project
    supabase_service_role_key: str = ""        # ADMIN key: full database access.
                                               #   Server-only secret — NEVER exposed to a browser.
                                               #   ("service role" = the app's god-mode account)

    # --- LLM providers (the AI backends that do the writing) ---------------
    groq_api_key: str = ""                     # Groq free tier — the default text provider ($0)
    openrouter_api_key: str = ""               # Bring-Your-Own-Key: pay-as-you-go, many models
    gemini_api_key: str = ""                   # Google AI Studio free tier
    llm_provider: str = "groq"                 # Primary provider: groq|gemini|openrouter|ollama
    llm_model: str = "llama-3.3-70b-versatile" # Text model used on Groq
    openrouter_model: str = "google/gemini-2.5-flash"
    openrouter_vision_model: str = "google/gemini-2.5-flash"  # vision-capable model on OpenRouter
    gemini_model: str = "gemini-3.6-flash"     # Text model on Gemini
    gemini_vision_model: str = "gemini-3.6-flash"
    ollama_base_url: str = "http://localhost:11434/v1"  # local models run on this machine ($0)
    ollama_model: str = "qwen2.5:14b"


# Create exactly ONE Settings instance at import time, so every other module
# reads the same shared values:  `from config import settings`.
settings = Settings()