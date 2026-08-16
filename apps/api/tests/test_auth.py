# ============================================================================
# test_auth.py — automated checks for the signup/login onboarding logic.
#
# These are TESTS: small functions that verify behavior and fail loudly if
# something breaks. You run them with `pytest tests/test_auth.py`. If the
# signup or login flow ever regresses, these light up red.
#
# KEY CONCEPT — monkeypatch: tests should NOT talk to the real Supabase
# server (that needs real credentials and would create real accounts). Instead
# we "fake" (monkeypatch) the network-touching functions with in-memory
# stand-ins. pytest's `monkeypatch` fixture swaps a function for a fake one
# during the test and restores it afterwards.
#
# The fakes below re-create enough of Supabase's API surface to run the code:
#   _FakeSession   — a fake login session object (holds tokens + user)
#   _FakeAdmin     — a fake "admin" object (create/update users)
#   _FakeAuth      — a fake auth client (sign-in + admin)
#   _FakeClient    — a fake top-level client whose .auth is _FakeAuth
# ============================================================================

from __future__ import annotations

import sys
from pathlib import Path

# Make Python able to import the app modules: add the PARENT folder
# (apps/api/) to the import search path. __file__ = this test file,
# .resolve() = full path, .parents[1] = two levels up = apps/api/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auth import login, signup  # noqa: E402   (noqa: E402 = "ignore import-order lint here")
from store import client as store_client  # noqa: E402

# --- The fake Supabase objects -----------------------------------------------

class _FakeSession:
    """Pretends to be a Supabase login session."""
    access_token = "acc-1"
    refresh_token = "ref-1"
    expires_at = 12345
    # A fake "user" object with an id and empty metadata, built on the fly.
    # type("U", (), {...}) creates a throwaway class named "U" with attributes.
    user = type("U", (), {"id": "u-1", "app_metadata": {}})()


class _FakeAdmin:
    """Pretends to be the Supabase admin API (create_user / update_user_by_id)."""

    def __init__(self, users: dict) -> None:
        self._users = users   # a dict we mutate to simulate the database

    def create_user(self, attributes: dict) -> object:
        """Simulate creating a user: return an object with .user, and DON'T
        touch self._users (the test asserts onboarding through other paths)."""
        user = type("U", (), {"id": "u-1", "app_metadata": {}})()
        return type("R", (), {"user": user})()

    def update_user_by_id(self, uid: str, attributes: dict) -> None:
        """Simulate stamping app_metadata onto the stored user."""
        self._users[uid]["app_metadata"] = attributes["app_metadata"]


class _FakeAuth:
    """Pretends to be the auth part of a Supabase client."""

    def __init__(self, users: dict) -> None:
        self.admin = _FakeAdmin(users)
        self._users = users

    def sign_in_with_password(self, credentials: dict) -> object:
        """Simulate logging in: always succeed and return our fake session."""
        return type("R", (), {"session": _FakeSession()})()


class _FakeClient:
    """Pretends to be a whole Supabase client (only .auth is used here)."""

    def __init__(self, users: dict) -> None:
        self.auth = _FakeAuth(users)


def _mock_fresh_client(monkeypatch, users: dict) -> None:
    """Swap the real network client for the fakes.

    1. Replace the shared client()'s .auth with _FakeAuth.
    2. Replace auth.py's create_client() (used by _sign_in) with a function
       that returns our _FakeClient instead of a real Supabase client.
    """
    monkeypatch.setattr(store_client(), "auth", _FakeAuth(users))
    monkeypatch.setattr(
        sys.modules["auth"], "create_client", lambda url, key: _FakeClient(users)
    )


# --- The actual tests ---------------------------------------------------------

def test_signup_returns_tokens_and_onboards(monkeypatch):
    """Signup must return both tokens AND a service_user_id, and must stamp
    service_user_id onto the user's metadata (that's the "onboarding" link)."""
    users: dict = {"u-1": {"app_metadata": {}}}
    _mock_fresh_client(monkeypatch, users)
    # Replace create_service_user so it returns id 7 WITHOUT hitting the DB.
    monkeypatch.setattr(sys.modules["auth"], "create_service_user", lambda: {"id": 7})

    result = signup("a@b.com", "password123")
    assert result["access_token"] == "acc-1"          # tokens came through
    assert result["refresh_token"] == "ref-1"
    assert result["service_user_id"] == 7             # the onboarding id
    assert users["u-1"]["app_metadata"]["service_user_id"] == 7  # and it was linked


def test_login_onboards_existing_user(monkeypatch):
    """Login must also ensure onboarding happens (idempotent per user)."""
    users: dict = {"u-1": {"app_metadata": {}}}
    _mock_fresh_client(monkeypatch, users)
    monkeypatch.setattr(sys.modules["auth"], "create_service_user", lambda: {"id": 9})

    result = login("a@b.com", "password123")
    assert result["service_user_id"] == 9
    assert users["u-1"]["app_metadata"]["service_user_id"] == 9


def test_signup_rejects_short_password(monkeypatch):
    """A password shorter than 8 chars must be rejected with a 400 error."""
    users: dict = {"u-1": {"app_metadata": {}}}
    _mock_fresh_client(monkeypatch, users)

    import fastapi

    try:
        signup("a@b.com", "short")
        raise AssertionError("expected HTTPException")   # fail test if no error was raised
    except fastapi.HTTPException as exc:
        assert exc.status_code == 400   # the error must be a "bad request"