"""U4 — the app-shell actually mounts library (D10 mock-first: no live DB needed).

Verifies the integration seam end-to-end: create_app() reports library mounted, its routes are
in the OpenAPI, and a request flows through with an injected principal + the in-memory repo.
"""

from __future__ import annotations

from backend.app import create_app
from backend.config import Settings
from backend.modules.accounts.models import Principal, UserRole
from backend.modules.library import controller
from fastapi.testclient import TestClient

_SETTINGS = Settings(env="test", database_url="sqlite://")


def _make_principal() -> Principal:
    return Principal(user_id="11111111-1111-1111-1111-111111111111", role=UserRole.USER)


def test_library_is_mounted_by_app_shell() -> None:
    app = create_app(_SETTINGS)
    assert "library" in app.state.mounted_modules


def test_library_routes_in_openapi() -> None:
    app = create_app(_SETTINGS)
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert "/library/saved-searches" in paths
    assert "/library/items" in paths
    assert "/library/history" in paths


def test_library_serves_through_app_shell() -> None:
    app = create_app(_SETTINGS)
    # Inject a principal the way the (not-yet-wired) U6 middleware eventually will.
    app.dependency_overrides[controller.get_principal] = _make_principal
    client = TestClient(app)

    r = client.post("/library/saved-searches", json={"query": "mixture of experts"})
    assert r.status_code == 201
    assert client.get("/library/saved-searches").json()["items"][0]["query"] == "mixture of experts"


def test_history_consumer_seam_present() -> None:
    app = create_app(_SETTINGS)
    assert hasattr(app.state, "library_history_consumer")
    assert hasattr(app.state, "library_repo")
