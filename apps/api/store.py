# ============================================================================
# store.py — the ONLY place that talks to the database & file storage.
#
# Every piece of user data (their master CVs, brag documents, API keys, links)
# lives in Supabase. Nothing is saved on the local disk. This file is the
# "data access layer": it wraps every read/write so the rest of the app never
# deals with SQL or storage URLs directly — it just calls plain functions like
# `list_cvs(user_id)`.
#
# Two kinds of storage are used:
#   * "tables"  — like rows in a spreadsheet (master CVs, brag docs, users).
#     We access them via `client().table("name").<operation>()`.
#   * "buckets" — file storage (the raw .tex / .md file contents). Accessed
#     via `client().storage.from_("bucket-name")`.
#
# Every query is filtered by `service_user_id` so users can only ever see
# their own rows (multi-tenant isolation, enforced again by RLS in the DB).
# ============================================================================

# Type-hint note: `dict[str, Any]` = "a dictionary whose keys are strings and
# whose values can be anything". `list[dict[str, Any]]` = a list of those.
from __future__ import annotations

import secrets  # generates cryptographically-random strings (for API keys)
from typing import Any
from uuid import uuid4  # generates unique IDs (so two uploads never collide)

from storage3.types import FileOptions  # Supabase's file-upload options type
from supabase import Client, create_client  # the Supabase Python SDK

from config import settings

# Module-level cache for the single shared Supabase connection.
# `None` means "not created yet" — we create it lazily on first use.
_client: Client | None = None


def client() -> Client:
    """Return the one shared Supabase connection, creating it if needed.

    This is the app's single door into Supabase. `global _client` says "use the
    module-level variable, not a local one" — so once created, every call to
    client() returns the SAME connection (we don't open a new one per request,
    which would be slow and wasteful).
    """
    global _client
    if _client is None:
        # If the .env is missing these two values, refuse to start silently —
        # better to crash with a clear message than fail mysteriously later.
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in apps/api/.env")
        _client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _client


# --- Master CVs (.tex files) ------------------------------------------------
# A "master CV" is the user's full-length LaTeX resume. It's stored as a FILE
# in the "master-cvs" bucket, and one ROW in the module_master_cvs table links
# the filename to the file.

def upload_cv(file_name: str, data: bytes, service_user_id: int) -> dict[str, Any]:
    """Save a new master CV (file + database row) and return the created row."""
    # Prefix the stored filename with 8 random hex chars so two users uploading
    # "resume.tex" can't overwrite each other's files.
    storage_path = f"{uuid4().hex[:8]}-{file_name}"
    # 1) Upload the raw bytes into the "master-cvs" storage bucket.
    client().storage.from_("master-cvs").upload(
        storage_path, data, FileOptions(content_type="application/x-tex")
    )
    # 2) Insert a row describing it, tagged with the owning user. .execute()
    #    actually sends the query; .data holds the result rows.
    row = client().table("module_master_cvs").insert(
        {"file_name": file_name, "storage_path": storage_path, "service_user_id": service_user_id}
    ).execute()
    return row.data[0]


def list_cvs(service_user_id: int) -> list[dict[str, Any]]:
    """Return every master CV belonging to one user, oldest first."""
    return (
        client()
        .table("module_master_cvs")
        .select("*")                            # grab all columns
        .eq("service_user_id", service_user_id)  # only THIS user's rows
        .order("created_at")                    # oldest first
        .execute()
        .data
    )


def get_cv(cv_id: int, service_user_id: int) -> dict[str, Any] | None:
    """Fetch one CV by id, but only if it belongs to this user (returns None if not)."""
    rows = (
        client()
        .table("module_master_cvs")
        .select("*")
        .eq("id", cv_id)
        .eq("service_user_id", service_user_id)  # the isolation guard
        .execute()
        .data
    )
    return rows[0] if rows else None


def cv_content(cv: dict[str, Any]) -> bytes:
    """Download the actual .tex file content (bytes) for a CV row."""
    return client().storage.from_("master-cvs").download(cv["storage_path"])


def delete_cv(cv_id: int, service_user_id: int) -> None:
    """Delete a CV: remove the file from storage AND the row from the table."""
    cv = get_cv(cv_id, service_user_id)
    if not cv:
        return  # not this user's CV (or doesn't exist) — nothing to do
    client().storage.from_("master-cvs").remove([cv["storage_path"]])  # delete file
    client().table("module_master_cvs").delete().eq("id", cv_id).execute()  # delete row


def set_cv_preferred(cv_id: int, service_user_id: int) -> None:
    """Mark one CV as the 'preferred' default — clears the flag on all others first.

    Runs two statements so only ONE CV per user has preferred=True at a time.
    """
    # Step 1: set preferred=False on every CV this user currently marks preferred.
    client().table("module_master_cvs").update({"preferred": False}).eq(
        "service_user_id", service_user_id
    ).neq("preferred", False).execute()
    # Step 2: set preferred=True on the requested one.
    client().table("module_master_cvs").update({"preferred": True}).eq("id", cv_id).eq(
        "service_user_id", service_user_id
    ).execute()


# --- Brag documents (.md files) ----------------------------------------------
# A "brag document" = a Markdown file where the user writes down every
# achievement/skill/metric they have. It feeds the AI as grounding material.
# Each user has AT MOST ONE brag doc, so uploading again REPLACES the old one.

def get_brag(service_user_id: int) -> dict[str, Any] | None:
    """Return the user's current brag doc row, or None if they have none."""
    rows = (
        client()
        .table("module_brag_docs")
        .select("*")
        .eq("service_user_id", service_user_id)
        .limit(1)  # at most one per user
        .execute()
        .data
    )
    return rows[0] if rows else None


def upload_brag(file_name: str, data: bytes, service_user_id: int) -> dict[str, Any]:
    """Upload a brag doc; if one already exists, replace it (file + row)."""
    storage_path = f"{uuid4().hex[:8]}-{file_name}"
    client().storage.from_("brag-docs").upload(
        storage_path, data, FileOptions(content_type="text/markdown")
    )
    existing = get_brag(service_user_id)
    if existing:
        # User already had a brag doc → delete the old file, update the row to
        # point at the new file.
        client().storage.from_("brag-docs").remove([existing["storage_path"]])
        row = client().table("module_brag_docs").update(
            {"file_name": file_name, "storage_path": storage_path}
        ).eq("id", existing["id"]).execute()
    else:
        # First-ever brag doc → insert a fresh row.
        row = client().table("module_brag_docs").insert(
            {
                "file_name": file_name,
                "storage_path": storage_path,
                "service_user_id": service_user_id,
            }
        ).execute()
    return row.data[0]


def brag_content(brag: dict[str, Any]) -> str:
    """Download the brag doc file and decode the bytes into text."""
    return client().storage.from_("brag-docs").download(brag["storage_path"]).decode(
        "utf-8", errors="replace"   # if some bytes aren't valid text, swap in a replacement char
    )


def delete_brag(service_user_id: int) -> None:
    """Delete the user's brag doc (file + row)."""
    brag = get_brag(service_user_id)
    if not brag:
        return
    client().storage.from_("brag-docs").remove([brag["storage_path"]])
    client().table("module_brag_docs").delete().eq("id", brag["id"]).execute()


# --- service_users ------------------------------------------------------------
# A "service_user" is our own internal record for a paying/logged-in user.
# The auth system (Supabase Auth) keeps the email+password; this table holds
# per-user extra data (API keys, links) keyed by service_users.id.

def create_service_user() -> dict[str, Any]:
    """Create a new service_user row, giving it a random API key. Returns the row."""
    row = (
        client()
        .table("service_users")
        .insert({"api_key": secrets.token_urlsafe(32)})  # 32-char random URL-safe key
        .execute()
        .data[0]
    )
    return row


def get_service_user(user_id: int) -> dict[str, Any] | None:
    """Fetch one service_user row by id."""
    rows = client().table("service_users").select("*").eq("id", user_id).execute().data
    return rows[0] if rows else None


def set_service_user_openrouter_key(user_id: int, key: str) -> None:
    """Save the user's own OpenRouter API key in the DB."""
    client().table("service_users").update({"openrouter_api_key": key}).eq("id", user_id).execute()


def set_service_user_gemini_key(user_id: int, key: str) -> None:
    """Save the user's own Gemini API key in the DB."""
    client().table("service_users").update({"gemini_api_key": key}).eq("id", user_id).execute()


def set_service_user_links(user_id: int, links: list[str]) -> None:
    """Save the user's list of profile links (GitHub, LinkedIn, portfolio...)."""
    client().table("service_users").update({"links": links}).eq("id", user_id).execute()