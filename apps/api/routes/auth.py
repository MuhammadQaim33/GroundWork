# ============================================================================
# routes/auth.py — the /api/auth/* endpoints (thin wrappers around auth.py).
# ============================================================================

from fastapi import APIRouter, Header

from auth import login, logout, refresh, signup
from schemas import Credentials, RefreshRequest

router = APIRouter(tags=["auth"])


@router.post("/api/auth/signup")
def api_signup(req: Credentials):
    """Create an account. Returns tokens + service_user_id."""
    return signup(req.email, req.password)


@router.post("/api/auth/login")
def api_login(req: Credentials):
    """Log in. Returns tokens + service_user_id."""
    return login(req.email, req.password)


@router.post("/api/auth/refresh")
def api_refresh(req: RefreshRequest):
    """Exchange a refresh token for a fresh access token."""
    return refresh(req.refresh_token)


@router.post("/api/auth/logout")
def api_logout(authorization: str | None = Header(default=None)):
    """Log out: invalidate the access token from the Authorization header."""
    if authorization and authorization.startswith("Bearer "):
        logout(authorization[len("Bearer ") :].strip())
    return {"ok": True}