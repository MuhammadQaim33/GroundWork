from __future__ import annotations

import secrets
from typing import Any
from uuid import uuid4

from storage3.types import FileOptions
from supabase import Client, create_client

from config import settings

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in apps/api/.env")
        _client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return _client


def upload_cv(file_name: str, data: bytes) -> dict[str, Any]:
    storage_path = f"{uuid4().hex[:8]}-{file_name}"
    client().storage.from_("master-cvs").upload(
        storage_path, data, FileOptions(content_type="application/x-tex")
    )
    row = client().table("module_master_cvs").insert(
        {"file_name": file_name, "storage_path": storage_path}
    ).execute()
    return row.data[0]


def list_cvs() -> list[dict[str, Any]]:
    return client().table("module_master_cvs").select("*").order("created_at").execute().data


def get_cv(cv_id: int) -> dict[str, Any] | None:
    rows = client().table("module_master_cvs").select("*").eq("id", cv_id).execute().data
    return rows[0] if rows else None


def cv_content(cv: dict[str, Any]) -> bytes:
    return client().storage.from_("master-cvs").download(cv["storage_path"])


def delete_cv(cv_id: int) -> None:
    cv = get_cv(cv_id)
    if not cv:
        return
    client().storage.from_("master-cvs").remove([cv["storage_path"]])
    client().table("module_master_cvs").delete().eq("id", cv_id).execute()


def set_cv_preferred(cv_id: int) -> None:
    client().table("module_master_cvs").update({"preferred": False}).neq("preferred", False).execute()
    client().table("module_master_cvs").update({"preferred": True}).eq("id", cv_id).execute()


def get_brag() -> dict[str, Any] | None:
    rows = client().table("module_brag_docs").select("*").limit(1).execute().data
    return rows[0] if rows else None


def upload_brag(file_name: str, data: bytes) -> dict[str, Any]:
    storage_path = f"{uuid4().hex[:8]}-{file_name}"
    client().storage.from_("brag-docs").upload(
        storage_path, data, FileOptions(content_type="text/markdown")
    )
    existing = get_brag()
    if existing:
        client().storage.from_("brag-docs").remove([existing["storage_path"]])
        row = client().table("module_brag_docs").update(
            {"file_name": file_name, "storage_path": storage_path}
        ).eq("id", existing["id"]).execute()
    else:
        row = client().table("module_brag_docs").insert(
            {"file_name": file_name, "storage_path": storage_path}
        ).execute()
    return row.data[0]


def brag_content(brag: dict[str, Any]) -> str:
    return client().storage.from_("brag-docs").download(brag["storage_path"]).decode(
        "utf-8", errors="replace"
    )


def delete_brag() -> None:
    brag = get_brag()
    if not brag:
        return
    client().storage.from_("brag-docs").remove([brag["storage_path"]])
    client().table("module_brag_docs").delete().eq("id", brag["id"]).execute()


def create_service_user() -> dict[str, Any]:
    row = (
        client()
        .table("service_users")
        .insert({"api_key": secrets.token_urlsafe(32)})
        .execute()
        .data[0]
    )
    return row


def get_service_user(user_id: int) -> dict[str, Any] | None:
    rows = client().table("service_users").select("*").eq("id", user_id).execute().data
    return rows[0] if rows else None
