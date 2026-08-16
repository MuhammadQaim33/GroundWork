# ============================================================================
# routes/profile.py — master CV + brag document endpoints.
#
# NOTE the recurring pattern below:
#   `_sv: Annotated[dict, Depends(require_service_user)]`
# This is FastAPI dependency injection. Depends(...) says "before running this
# endpoint, call require_service_user". That call verifies the caller's token
# and returns {"id": ..., "name": ...}. `_sv["id"]` is then used to scope every
# data access to that user. `_sv` (service user) is named with a leading
# underscore to signal "internal plumbing, not a real parameter".
# ============================================================================

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from auth import require_service_user
from store import (
    delete_brag,
    delete_cv,
    get_brag,
    list_cvs,
    set_cv_preferred,
    upload_brag,
    upload_cv,
)

router = APIRouter(tags=["profile"])


@router.get("/api/master-cvs")
def api_list_cvs(_sv: Annotated[dict, Depends(require_service_user)]):
    """List the caller's master CVs."""
    return list_cvs(_sv["id"])


@router.post("/api/master-cvs")
def api_upload_cv(
    _sv: Annotated[dict, Depends(require_service_user)],
    file: Annotated[UploadFile, File(...)],   # File(...) = a required file upload
):
    """Upload a new master CV. Only .tex files are allowed."""
    if not file.filename or not file.filename.lower().endswith(".tex"):
        raise HTTPException(400, "Master CVs must be .tex (LaTeX) files.")
    return upload_cv(file.filename, file.file.read(), _sv["id"])


@router.delete("/api/master-cvs/{cv_id}")
def api_delete_cv(cv_id: int, _sv: Annotated[dict, Depends(require_service_user)]):
    """Delete one master CV. `{cv_id}` in the URL is passed as an int."""
    delete_cv(cv_id, _sv["id"])
    return {"ok": True}


@router.put("/api/master-cvs/{cv_id}/preferred")
def api_cv_preferred(cv_id: int, _sv: Annotated[dict, Depends(require_service_user)]):
    """Mark a CV as the preferred default."""
    set_cv_preferred(cv_id, _sv["id"])
    return {"ok": True}


@router.get("/api/brag-doc")
def api_get_brag(_sv: Annotated[dict, Depends(require_service_user)]):
    """Return the caller's brag doc row (or null)."""
    return get_brag(_sv["id"])


@router.post("/api/brag-doc")
def api_upload_brag(
    _sv: Annotated[dict, Depends(require_service_user)],
    file: Annotated[UploadFile, File(...)],
):
    """Upload/replace the caller's brag document. Only .md allowed."""
    if not file.filename or not file.filename.lower().endswith(".md"):
        raise HTTPException(400, "The brag document must be a Markdown (.md) file.")
    return upload_brag(file.filename, file.file.read(), _sv["id"])


@router.delete("/api/brag-doc")
def api_delete_brag(_sv: Annotated[dict, Depends(require_service_user)]):
    """Delete the caller's brag document."""
    delete_brag(_sv["id"])
    return {"ok": True}