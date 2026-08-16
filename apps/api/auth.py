# ============================================================================
# auth.py — who is calling, and are they allowed in?
#
# Responsibilities:
#   1. Sign up / log in / refresh / log out (delegating to Supabase Auth, which
#      handles email+password and issues JWTs).
#   2. "Onboarding": the first time a user appears, create a service_users row
#      for them and link it to their auth identity. This gives us a numeric
#      id (service_users.id) used everywhere else to scope their data.
#   3. require_service_user — a FastAPI "dependency" that guards every endpoint:
#      it reads the caller's token, verifies it, works out who they are, and
#      publishes their id on the request's sticky note (see user_settings.py)
#      so the rest of the pipeline is scoped to them.
#
# JWT in one line: a signed string the browser sends as "Authorization: Bearer
# <token>" that proves who you are. We validate it against Supabase's auth
# server (we do NOT trust it blindly).
# ============================================================================

from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException
from starlette.concurrency import run_in_threadpool  # lets async code call sync code safely
from supabase import create_client

from config import settings
from store import client, create_service_user
from user_settings import set_current_service_user

_BEARER = "Bearer "   # the standard prefix on auth headers


def _user_from_token(authorization: str | None) -> Any:
    """Extract and verify the caller's identity from the Authorization header.

    Returns Supabase's "user" object, or raises HTTPException 401 (unauthorized).
    """
    # The header must look exactly like:  Authorization: Bearer <token>
    if not authorization or not authorization.startswith(_BEARER):
        raise HTTPException(401, "Missing bearer token")
    token = authorization[len(_BEARER) :].strip()  # cut off "Bearer ", keep the token
    if not token:
        raise HTTPException(401, "Missing bearer token")
    try:
        # Ask Supabase's auth server to validate the token and return the user.
        return client().auth.get_user(token).user
    except Exception as exc:
        # Any failure (expired, revoked, garbage) = "you're not who you say you are".
        raise HTTPException(401, "Invalid or expired token") from exc


async def require_service_user(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """FASTAPI DEPENDENCY — the guard on every protected endpoint.

    FastAPI calls this automatically for any endpoint that declares it as a
    dependency (see `_sv: Annotated[dict, Depends(require_service_user)]` in
    main.py). It resolves the caller and returns a small dict:
        {"id": <service_users.id>, "name": <display name>}
    which the endpoint then uses to scope its data access.

    Two notes for the curious:
    * `authorization: str | None = Header(default=None)` means "take the
      Authorization HTTP header, or None if it wasn't sent".
    * The token is validated by the Supabase auth server, not decoded locally,
      and the service_users.id is read straight from the token's metadata — so
      no per-request database lookup is needed.
    * After resolving, we publish the id on the request's sticky note
      (set_current_service_user) so user_settings.py can find it.
    """
    # run_in_threadpool: the token validation makes a network call; we run it
    # in a background thread so the request loop isn't blocked while waiting.
    user = await run_in_threadpool(_user_from_token, authorization)
    # The token carries extra app-level metadata set at onboarding time.
    app_metadata = user.app_metadata or {}
    service_user_id = app_metadata.get("service_user_id")
    if not service_user_id:
        raise HTTPException(401, "Account not onboarded")
    # Publish the id on the request sticky note → user_settings reads it.
    set_current_service_user(int(service_user_id))
    name = (user.user_metadata or {}).get("n") or app_metadata.get("n")
    return {"id": int(service_user_id), "name": (str(name) if name else "").strip()}


def _onboard(auth_user: Any) -> int:
    """Ensure the auth user has a service_users row; return its id.

    Idempotent = safe to call many times. If the user already has a
    service_user_id stamped in their token metadata, just return it. Otherwise
    create the row and write its id back into the user's token metadata so the
    next request finds it immediately.
    """
    service_user_id = (auth_user.app_metadata or {}).get("service_user_id")
    if service_user_id:
        return int(service_user_id)
    # Create the service_users row (this returns the new id).
    service_user = create_service_user()
    # Stamp the id onto the user's auth record. `{**(metadata), key: val}` =
    # "take the existing metadata dict and add/overwrite this one key".
    client().auth.admin.update_user_by_id(
        auth_user.id,
        {"app_metadata": {**(auth_user.app_metadata or {}), "service_user_id": service_user["id"]}},
    )
    return int(service_user["id"])


def _tokens(session: Any) -> dict[str, Any]:
    """Shrink a Supabase session object down to the three fields a client needs."""
    return {
        "access_token": session.access_token,   # short-lived (minutes/hours), used on every request
        "refresh_token": session.refresh_token, # long-lived, used to get a new access token
        "expires_at": session.expires_at,
    }


def _sign_in(email: str, password: str) -> Any:
    """Log the user in on a FRESH, throwaway Supabase client.

    Why throwaway? The shared client() uses the admin/service-role key. If we
    logged in on that client, its token would be REPLACED by the user's normal
    token, breaking all the admin operations that rely on god-mode access.
    A fresh client keeps the admin client untouched.
    """
    fresh = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return fresh.auth.sign_in_with_password({"email": email, "password": password}).session


def signup(email: str, password: str) -> dict[str, Any]:
    """Create a new account: auth user + onboarding + return tokens."""
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    try:
        # email_confirm=True: skip the email verification step for now.
        created = client().auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
    except Exception as exc:
        raise HTTPException(400, f"Signup failed: {_clean_auth_error(exc)}") from exc
    service_user_id = _onboard(created.user)
    session = _sign_in(email, password)
    return {"service_user_id": service_user_id, **_tokens(session)}


def login(email: str, password: str) -> dict[str, Any]:
    """Authenticate against Supabase Auth, ensure onboarding, return tokens."""
    try:
        session = _sign_in(email, password)
    except Exception as exc:
        raise HTTPException(401, "Invalid email or password") from exc
    service_user_id = _onboard(session.user)
    return {"service_user_id": service_user_id, **_tokens(session)}


def refresh(refresh_token: str) -> dict[str, Any]:
    """Trade a (still-valid) refresh token for a fresh pair of tokens."""
    try:
        fresh = create_client(settings.supabase_url, settings.supabase_service_role_key)
        session = fresh.auth.refresh_session(refresh_token).session
    except Exception as exc:
        raise HTTPException(401, "Invalid or expired refresh token") from exc
    return _tokens(session)


def logout(access_token: str) -> None:
    """Invalidate the given access token server-side. Best-effort: ignore errors."""
    try:
        fresh = create_client(settings.supabase_url, settings.supabase_service_role_key)
        fresh.auth.sign_out(access_token)
    except Exception:
        pass


def _clean_auth_error(exc: Exception) -> str:
    """Make Supabase's verbose error messages readable for the user."""
    message = str(exc).strip()
    if not message or "HTTPError" in message:
        return "check the details and try again"
    # supabase-py wraps provider errors in long prefixes; keep just the tail.
    return message.split(":")[-1].strip()[:200]