# ============================================================================
# test_routes.py — route-level tests over the real FastAPI app.
#
# These exercise the full HTTP stack (auth dependency, validation,
# serialization, error handlers) that the pure-logic tests in test_main.py
# can't reach. The `authed_client` fixture (conftest.py) overrides the auth
# dependency; each test fakes the specific store functions its route touches.
# ============================================================================

from __future__ import annotations

from errors import CompileError


def test_list_master_cvs_with_dependency_override(authed_client, monkeypatch) -> None:
    """GET /api/master-cvs runs under the overridden service user and returns
    whatever the (faked) store reports."""
    client, sv = authed_client
    monkeypatch.setattr(
        "routes.profile.list_cvs",
        lambda service_user_id: [{"id": 1, "file_name": "main.tex"}],
    )

    r = client.get("/api/master-cvs")

    assert r.status_code == 200
    assert r.json() == [{"id": 1, "file_name": "main.tex"}]


def test_domain_error_maps_to_http_via_exception_handler(authed_client, monkeypatch) -> None:
    """A GenerationError raised inside a route becomes the HTTP status it
    carries — proving the errors.py → main.py translation seam end to end."""
    client, _ = authed_client
    monkeypatch.setattr("routes.profile.list_cvs", lambda _: (_ for _ in ()).throw(
        CompileError("LaTeX compile failed. broken")
    ))

    r = client.get("/api/master-cvs")

    assert r.status_code == 502
    assert r.json() == {"detail": "LaTeX compile failed. broken"}