from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auth import login, signup  # noqa: E402
from store import client as store_client  # noqa: E402


class _FakeSession:
    access_token = "acc-1"
    refresh_token = "ref-1"
    expires_at = 12345
    user = type("U", (), {"id": "u-1", "app_metadata": {}})()


class _FakeAdmin:
    def __init__(self, users: dict) -> None:
        self._users = users

    def create_user(self, attributes: dict) -> object:
        user = type("U", (), {"id": "u-1", "app_metadata": {}})()
        return type("R", (), {"user": user})()

    def update_user_by_id(self, uid: str, attributes: dict) -> None:
        self._users[uid]["app_metadata"] = attributes["app_metadata"]


class _FakeAuth:
    def __init__(self, users: dict) -> None:
        self.admin = _FakeAdmin(users)
        self._users = users

    def sign_in_with_password(self, credentials: dict) -> object:
        return type("R", (), {"session": _FakeSession()})()


class _FakeClient:
    def __init__(self, users: dict) -> None:
        self.auth = _FakeAuth(users)


def _mock_fresh_client(monkeypatch, users: dict) -> None:
    monkeypatch.setattr(store_client(), "auth", _FakeAuth(users))
    monkeypatch.setattr(
        sys.modules["auth"], "create_client", lambda url, key: _FakeClient(users)
    )


def test_signup_returns_tokens_and_onboards(monkeypatch):
    users: dict = {"u-1": {"app_metadata": {}}}
    _mock_fresh_client(monkeypatch, users)
    monkeypatch.setattr(sys.modules["auth"], "create_service_user", lambda: {"id": 7})
    monkeypatch.setattr(sys.modules["auth"], "get_service_user", lambda uid: {"id": 7})

    result = signup("a@b.com", "password123")
    assert result["access_token"] == "acc-1"
    assert result["refresh_token"] == "ref-1"
    assert result["service_user_id"] == 7
    assert users["u-1"]["app_metadata"]["service_user_id"] == 7


def test_login_onboards_existing_user(monkeypatch):
    users: dict = {"u-1": {"app_metadata": {}}}
    _mock_fresh_client(monkeypatch, users)
    monkeypatch.setattr(sys.modules["auth"], "create_service_user", lambda: {"id": 9})
    monkeypatch.setattr(sys.modules["auth"], "get_service_user", lambda uid: {"id": 9})

    result = login("a@b.com", "password123")
    assert result["service_user_id"] == 9
    assert users["u-1"]["app_metadata"]["service_user_id"] == 9


def test_signup_rejects_short_password(monkeypatch):
    users: dict = {"u-1": {"app_metadata": {}}}
    _mock_fresh_client(monkeypatch, users)

    import fastapi

    try:
        signup("a@b.com", "short")
        raise AssertionError("expected HTTPException")
    except fastapi.HTTPException as exc:
        assert exc.status_code == 400
