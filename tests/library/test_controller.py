"""U4 — controller HTTP integration (TestClient): status codes, auth, owner-scoping."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.modules.library import controller
from backend.modules.library.audit import InMemoryAuditSink
from backend.modules.library.gateway import DiscoverySearchGateway, StubSearchGateway
from backend.modules.library.services.history import SearchHistoryService
from docsuri_shared.events import SearchExecutedEvent
from fastapi import FastAPI
from fastapi.testclient import TestClient

META = {"title": "T", "arxivId": "2401.00001", "authors": ["A"], "year": 2024}


def test_saved_search_crud_over_http(make_app, make_principal):
    app, _repo = make_app(make_principal())
    client = TestClient(app)

    r = client.post("/library/saved-searches", json={"query": "graph neural networks"})
    assert r.status_code == 201

    # Idempotent re-save returns 200
    r_dup = client.post("/library/saved-searches", json={"query": "graph neural networks"})
    assert r_dup.status_code == 200

    item_id = r.json()["id"]
    assert r.json()["query"] == "graph neural networks"

    r = client.get("/library/saved-searches")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1

    r = client.post(f"/library/saved-searches/{item_id}/rerun")
    assert r.status_code == 200
    assert r.json()["meta"]["resultCount"] == 0

    r = client.delete(f"/library/saved-searches/{item_id}")
    assert r.status_code == 204

    assert client.get("/library/saved-searches").json()["items"] == []


def test_library_add_and_idempotency_over_http(make_app, make_principal):
    app, _repo = make_app(make_principal())
    client = TestClient(app)
    r1 = client.post("/library/items", json={"arXivId": "2401.00001", "meta": META})
    assert r1.status_code == 201
    r2 = client.post(
        "/library/items",
        json={"arXivId": "2401.00001", "meta": {"title": "X", "arxivId": "2401.00001"}},
    )
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]  # idempotent
    assert client.get("/library/items").json()["items"][0]["meta"]["title"] == "T"


def test_history_list_over_http(make_app, make_principal):
    p = make_principal()
    app, repo = make_app(p)
    # record via the same repo the routers read from
    svc = SearchHistoryService(repo, StubSearchGateway(), InMemoryAuditSink())
    svc.record_search(
        SearchExecutedEvent(
            userId=p.user_id,
            requestId="req-1",
            query="recorded",
            timestamp=datetime.now(UTC),
            resultCount=4,
        )
    )
    client = TestClient(app)
    r = client.get("/library/history")
    assert r.status_code == 200
    assert r.json()["items"][0]["query"] == "recorded"
    assert r.json()["items"][0]["resultCount"] == 4

    assert client.delete("/library/history").status_code == 204
    assert client.get("/library/history").json()["items"] == []


def test_invalid_input_returns_422(make_app, make_principal):
    app, _repo = make_app(make_principal())
    client = TestClient(app)
    assert client.post("/library/saved-searches", json={"query": "   "}).status_code == 422
    assert client.post("/library/items", json={"arXivId": "bad", "meta": META}).status_code == 422

    # limit < 1 returns clean validation error message instead of raw FastAPI details.
    r_saved = client.get("/library/saved-searches?limit=0")
    assert r_saved.status_code == 422
    assert r_saved.json()["detail"] == "limit must be >= 1"

    r_lib = client.get("/library/items?limit=-5")
    assert r_lib.status_code == 422
    assert r_lib.json()["detail"] == "limit must be >= 1"

    r_hist = client.get("/library/history?limit=0")
    assert r_hist.status_code == 422
    assert r_hist.json()["detail"] == "limit must be >= 1"


def test_unauthenticated_returns_401():
    """get_principal with no request.state.principal → 401 (fail-closed, INV-L4)."""
    app = FastAPI()
    for router in controller.routers:
        app.include_router(router)
    client = TestClient(app)
    assert client.get("/library/saved-searches").status_code == 401
    assert (
        client.post("/library/items", json={"arXivId": "2401.00001", "meta": META}).status_code
        == 401
    )


def test_cross_owner_access_returns_404(make_app, make_principal):
    owner, attacker = make_principal(), make_principal()
    app_owner, repo = make_app(owner)
    app_attacker, _ = make_app(attacker, repo)  # shares the repo
    c_owner, c_attacker = TestClient(app_owner), TestClient(app_attacker)

    item_id = c_owner.post("/library/saved-searches", json={"query": "private"}).json()["id"]
    # attacker cannot see or delete it → generalized 404 (SEC-9)
    assert c_attacker.delete(f"/library/saved-searches/{item_id}").status_code == 404
    assert c_attacker.post(f"/library/saved-searches/{item_id}/rerun").status_code == 404
    # owner still can
    assert c_owner.delete(f"/library/saved-searches/{item_id}").status_code == 204


def test_rerun_returns_503_when_discovery_gateway_unavailable(make_app, make_principal):
    p = make_principal()
    app, _repo = make_app(p)
    app.dependency_overrides[controller.get_search_gateway] = lambda: DiscoverySearchGateway(app)
    client = TestClient(app)
    item_id = client.post("/library/saved-searches", json={"query": "private"}).json()["id"]

    r = client.post(f"/library/saved-searches/{item_id}/rerun")

    assert r.status_code == 503
    assert r.json()["detail"] == "search temporarily unavailable"
