# ============================================================================
# tests/conftest.py — shared fixtures for the whole suite.
#
# The star is `authed_client`: it runs the REAL FastAPI app through a
# TestClient with the `require_service_user` dependency overridden to a fixed
# stub user. That lets route-level tests exercise the full HTTP stack (auth,
# validation, serialization, error handlers) without touching Supabase.
# Individual tests patch whatever store/LLM functions their route touches.
# ============================================================================

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # import path to apps/api/

import main  # noqa: E402


@pytest.fixture
def authed_client():
    """A TestClient on the real app acting as a fixed service user.

    Yields (client, service_user) — tests use client for requests and may use
    service_user's id to drive store fakes. Patch store functions per test.
    """
    from auth import require_service_user

    app = main.app
    service_user = {"id": 42, "name": "Tester"}

    app.dependency_overrides[require_service_user] = lambda: service_user
    try:
        with TestClient(app) as client:
            yield client, service_user
    finally:
        app.dependency_overrides.pop(require_service_user, None)