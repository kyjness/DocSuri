from __future__ import annotations

import asyncio
import os
import sys
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.modules.accounts.models import Principal, UserRole
from backend.modules.citation_graph import controller


class FixtureProvider:
    def __init__(self, status: str = "ok") -> None:
        self.status = status
        self.calls = 0

    async def references(self, paper_id: str, limit: int):
        self.calls += 1
        if self.status != "ok":
            return self.status, []
        return "ok", [
            {
                "paperId": "s2-a",
                "title": "A paper",
                "year": 2021,
                "citationCount": 10,
                "externalIds": {"ArXiv": "2101.00001"},
                "url": "https://arxiv.org/abs/2101.00001",
            },
            {
                "paperId": "s2-b",
                "title": "B paper",
                "year": 2022,
                "citationCount": 2,
                "externalIds": {"DOI": "10.1/b"},
            },
            {"title": "Unresolved paper", "year": 2020},
        ]


def _client(monkeypatch, provider=None, store=None):
    monkeypatch.setenv("CITATION_GRAPH_ENABLED", "true")
    app = create_app(Settings(env="test", database_url="sqlite://"))
    app.dependency_overrides[controller.get_principal] = lambda: Principal(
        user_id=str(uuid4()), role=UserRole.USER
    )
    app.dependency_overrides[controller.get_provider] = lambda: provider or FixtureProvider()
    app.dependency_overrides[controller.get_snapshot_store] = (
        lambda: store or controller.InMemorySnapshotStore()
    )
    return TestClient(app)


def test_citation_tree_bounds_and_unresolved(monkeypatch) -> None:
    resp = _client(monkeypatch).get("/api/papers/root/citation-tree")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "Partial"
    assert body["depthReturned"] <= 2
    assert len(body["nodes"]) <= 30
    assert body["nodes"][0]["nodeId"] == "2101.00001"
    assert body["nodes"][0]["saveable"] is True
    assert body["unresolved"][0]["title"] == "Unresolved paper"
    assert body["unresolved"][0]["year"] == 2020


def test_citation_tree_marks_nodes_that_exist_in_corpus() -> None:
    class PaperService:
        def get_paper_meta(self, paper_id: str):
            return object() if paper_id == "2101.00001" else None

    body = controller._build_tree(
        "root",
        "root",
        [
            {
                "paperId": "s2-a",
                "title": "A paper",
                "externalIds": {"ArXiv": "2101.00001"},
            },
            {
                "paperId": "s2-b",
                "title": "B paper",
                "externalIds": {"ArXiv": "9999.99999"},
            },
        ],
        PaperService(),
    )

    by_id = {node.arxivId: node.inCorpus for node in body.nodes}
    assert by_id == {"2101.00001": True, "9999.99999": False}


@pytest.mark.asyncio
async def test_redis_snapshot_store_roundtrips_with_ttl(monkeypatch) -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.values = {}
            self.ttls = {}

        async def get(self, key: str):
            return self.values.get(key)

        async def set(self, key: str, value: str, ex: int) -> None:
            self.values[key] = value
            self.ttls[key] = ex

    fake_client = FakeClient()

    class FakeRedis:
        @staticmethod
        def from_url(url: str):
            assert url == "redis://cache"
            return fake_client

    import redis.asyncio
    monkeypatch.setattr(redis.asyncio, "Redis", FakeRedis)
    monkeypatch.setenv("CITATION_GRAPH_SNAPSHOT_TTL_SECONDS", "30")

    store = controller.RedisSnapshotStore("redis://cache", "cg:")
    response = controller.CitationTreeResponse(
        status="Success",
        rootPaperId="root",
        nodes=[],
        edges=[],
        depthReturned=1,
    )
    await store.set("root:root", response)

    cached = await store.get("root:root")
    assert cached is not None
    assert cached.cacheHit is True
    assert fake_client.ttls["cg:root:root"] == 30


def test_snapshot_store_falls_back_when_redis_module_is_absent(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_HOST", "cache.internal")
    monkeypatch.setitem(sys.modules, "redis", None)
    monkeypatch.setitem(sys.modules, "redis.asyncio", None)
    monkeypatch.setattr(controller, "_store", None)

    store = controller.get_snapshot_store()

    assert isinstance(store, controller.InMemorySnapshotStore)


def test_feature_flag_blocks_endpoint_by_default() -> None:
    app = create_app(Settings(env="test", database_url="sqlite://"))
    assert TestClient(app).get("/api/papers/root/citation-tree").status_code == 404


def test_citation_tree_cache_hit(monkeypatch) -> None:
    provider = FixtureProvider()
    store = controller.InMemorySnapshotStore()
    client = _client(monkeypatch, provider=provider, store=store)

    assert client.get("/api/papers/root/citation-tree").json()["cacheHit"] is False
    cached = client.get("/api/papers/root/citation-tree").json()

    assert cached["cacheHit"] is True
    assert provider.calls == 1


def test_depth_query_does_not_create_duplicate_cache(monkeypatch) -> None:
    provider = FixtureProvider()
    store = controller.InMemorySnapshotStore()
    client = _client(monkeypatch, provider=provider, store=store)

    assert client.get("/api/papers/root/citation-tree", params={"depth": 2}).json()[
        "depthReturned"
    ] == 1
    assert client.get("/api/papers/root/citation-tree").json()["cacheHit"] is True
    assert provider.calls == 1


def test_citation_tree_rate_limited_and_unavailable(monkeypatch) -> None:
    assert (
        _client(monkeypatch, provider=FixtureProvider("rate_limited"))
        .get("/api/papers/root/citation-tree")
        .json()["status"]
        == "RateLimited"
    )
    assert (
        _client(monkeypatch, provider=FixtureProvider("unavailable"))
        .get("/api/papers/root/citation-tree")
        .json()["status"]
        == "Unavailable"
    )


def test_citation_tree_expand_returns_depth_two(monkeypatch) -> None:
    body = _client(monkeypatch).get(
        "/api/papers/root/citation-tree", params={"expandNodeId": "2101.00001"}
    ).json()

    assert body["depthReturned"] == 2
    assert all(node["depth"] == 2 for node in body["nodes"])


def test_save_citation_node(monkeypatch) -> None:
    client = _client(monkeypatch)
    node = client.get("/api/papers/root/citation-tree").json()["nodes"][0]

    resp = client.post("/api/papers/root/citation-tree/save", json={"node": node})

    assert resp.status_code == 200
    assert resp.json()["arXivId"] == "2101.00001"


def test_save_nulls_out_of_range_year(monkeypatch) -> None:
    client = _client(monkeypatch)
    node = client.get("/api/papers/root/citation-tree").json()["nodes"][0]
    node["year"] = 500

    resp = client.post("/api/papers/root/citation-tree/save", json={"node": node})

    assert resp.status_code == 200
    assert resp.json()["meta"].get("year") is None


def test_save_rejects_unsaveable_node(monkeypatch) -> None:
    node = _client(monkeypatch).get("/api/papers/root/citation-tree").json()["nodes"][1]

    resp = _client(monkeypatch).post("/api/papers/root/citation-tree/save", json={"node": node})

    assert resp.status_code == 422


def test_semantic_scholar_provider_url_encodes_path(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self):
            return {"data": []}

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def get(self, url: str, params, headers):
            captured["url"] = url
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    asyncio.run(controller.SemanticScholarProvider().references("ARXIV:1706.03762v7", 1))

    assert captured["url"].endswith("/paper/ARXIV%3A1706.03762/references")


@pytest.mark.asyncio
async def test_semantic_scholar_provider_uses_longer_retry_timeout(monkeypatch) -> None:
    captured_timeouts = []

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            captured_timeouts.append(timeout)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> None:
            pass

        async def get(self, url: str, params, headers):
            raise httpx.TimeoutException("slow")

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    status, items = await controller.SemanticScholarProvider().references("1706.03762", 1)

    assert captured_timeouts == [3.0, 5.0]
    assert status == "unavailable"
    assert items == []


def test_semantic_scholar_paper_id_normalizes_common_ids() -> None:
    assert controller._semantic_scholar_paper_id("1706.03762") == "ARXIV:1706.03762"
    assert controller._semantic_scholar_paper_id("1706.03762v7") == "ARXIV:1706.03762"
    assert controller._semantic_scholar_paper_id("ARXIV:1706.03762v7") == "ARXIV:1706.03762"
    assert (
        controller._semantic_scholar_paper_id("10.5555/3295222.3295349")
        == "DOI:10.5555/3295222.3295349"
    )
    assert (
        controller._semantic_scholar_paper_id("https://example.test/paper")
        == "URL:https://example.test/paper"
    )


def test_emit_ignores_observability_without_emit_log() -> None:
    class State:
        observability = object()

    class App:
        state = State()

    class Request:
        app = App()

    response = controller.CitationTreeResponse(
        status="Success",
        rootPaperId="root",
        nodes=[],
        edges=[],
        depthReturned=1,
    )

    controller._emit(Request(), response, latency_ms=1, depth_requested=1)


@pytest.mark.skipif(
    not os.getenv("CITATION_GRAPH_CONTRACT_TESTS"),
    reason="opt-in real provider contract test",
)
def test_semantic_scholar_contract_test_is_opt_in() -> None:
    assert os.getenv("SEMANTIC_SCHOLAR_API_KEY")
