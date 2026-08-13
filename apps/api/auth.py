from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException
from supabase import create_client

from config import settings
from store import client, create_service_user, get_service_user

_BEARER = "Bearer "


def _user_from_token(authorization: str | None) -> Any:
    if not authorization or not authorization.startswith(_BEARER):
        raise HTTPException(401, "Missing bearer token")
    token = authorization[len(_BEARER) :].strip()
    if not token:
        raise HTTPException(401, "Missing bearer token")
    try:
        return client().auth.get_user(token).user
    except Exception as exc:
        raise HTTPException(401, "Invalid or expired token") from exc


def require_service_user(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Resolve the calling service_user from a Supabase JWT.

    The token is validated through the Supabase auth server (not decoded
    locally); the linked service_users.id is read from the user's
    app_metadata.service_user_id, set at onboarding.
    """
    user = _user_from_token(authorization)
    service_user_id = (user.app_metadata or {}).get("service_user_id")
    if not service_user_id:
        raise HTTPException(401, "Account not onboarded")
    service_user = get_service_user(int(service_user_id))
    if not service_user:
        raise HTTPException(401, "Account not onboarded")
    return service_user


def _onboard(auth_user: Any) -> int:
    """Idempotently create the auth user's service_users row + api_key and link
    it via app_metadata.service_user_id. Returns the service_users.id."""
    service_user_id = (auth_user.app_metadata or {}).get("service_user_id")
    if service_user_id:
        return int(service_user_id)
    service_user = create_service_user()
    client().auth.admin.update_user_by_id(
        auth_user.id,
        {"app_metadata": {**(auth_user.app_metadata or {}), "service_user_id": service_user["id"]}},
    )
    return int(service_user["id"])


def _tokens(session: Any) -> dict[str, Any]:
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_at": session.expires_at,
    }


def _sign_in(email: str, password: str) -> Any:
    """Sign in on a throwaway client so the shared admin client's JWT (service
    role) is never replaced by a user token, which would break admin calls."""
    fresh = create_client(settings.supabase_url, settings.supabase_service_role_key)
    return fresh.auth.sign_in_with_password({"email": email, "password": password}).session


def signup(email: str, password: str) -> dict[str, Any]:
    """Create an auth user, onboard them as a service_user, and return tokens."""
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    try:
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
    try:
        fresh = create_client(settings.supabase_url, settings.supabase_service_role_key)
        session = fresh.auth.refresh_session(refresh_token).session
    except Exception as exc:
        raise HTTPException(401, "Invalid or expired refresh token") from exc
    return _tokens(session)


def logout(access_token: str) -> None:
    try:
        fresh = create_client(settings.supabase_url, settings.supabase_service_role_key)
        fresh.auth.sign_out(access_token)
    except Exception:
        pass


def _clean_auth_error(exc: Exception) -> str:
    message = str(exc).strip()
    if not message or "HTTPError" in message:
        return "check the details and try again"
    # supabase-py wraps provider errors in verbose prefixes; keep it short.
    return message.split(":")[-1].strip()[:200]
