from __future__ import annotations

import asyncio
import json
import os
import sys
from uuid import uuid4

import httpx
import pytest
from docsuri_shared.authz import Principal, UserRole
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
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


def _raises_json_decode() -> None:
    raise json.JSONDecodeError("no json", "", 0)


@pytest.mark.parametrize(
    "json_body",
    [
        _raises_json_decode,  # 200 body is not JSON at all (HTML error page)
        lambda: None,  # 200 body is JSON null
        lambda: [1, 2, 3],  # 200 body is a bare array, not {"data": [...]}
        lambda: {"data": None},  # data key present but null -> `for row in None`
        lambda: {"data": [7]},  # data item is not a dict -> row.get(...)
    ],
)
def test_provider_degrades_on_bad_success_body(monkeypatch, json_body) -> None:
    # Regression for #342: a DOI leaf is always a live, cache-missing S2 call, and S2 often
    # answers /references with a 200 whose body is not {"data": [...]}. The real references()
    # parse must degrade to ("unavailable", []), not raise into the app catch-all (HTTP 500).
    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return json_body()

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> bool:
            return False

        async def get(self, *args, **kwargs):
            return _Resp()

    monkeypatch.setenv("CITATION_GRAPH_PROVIDER_RETRIES", "0")
    monkeypatch.setattr(controller.httpx, "AsyncClient", lambda *a, **k: _Client())

    status, items = asyncio.run(
        controller.SemanticScholarProvider().references("DOI:10.1/x", 30)
    )

    assert status == "unavailable"
    assert items == []


def test_citation_tree_degrades_on_malformed_provider_item(monkeypatch) -> None:
    # Regression for #342 (H2): a 200 with valid JSON but a misshapen item (S2 has returned
    # `year` as a string) must not 500 — the sort/model build inside _build_tree degrades to
    # Unavailable per BR-CG12.
    class BadItemProvider:
        async def references(self, paper_id: str, limit: int):
            return "ok", [
                {"paperId": "x", "title": "T", "year": "not-a-year", "externalIds": {}}
            ]

    resp = _client(monkeypatch, provider=BadItemProvider()).get(
        "/api/papers/root/citation-tree", params={"expandNodeId": "10.1/x"}
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "Unavailable"


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

    assert captured_timeouts == [5.0, 10.0]
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


# --- US-CG3 criteria-level tests (QA 2026-07-10 gap A) -------------------------------------


def test_unresolved_reference_never_promoted_to_node() -> None:
    # US-CG3: 제목만 있는/식별자가 모호한 인용은 unresolved로 분리 — 확정 노드로 승격 금지.
    tree = controller._build_tree(
        "root",
        "root",
        [
            {"title": "Title-only reference", "year": 2019},  # no identifier at all
            {"paperId": "s2-x", "externalIds": {}},  # identifier but no title
            {"title": "   ", "paperId": "s2-y", "externalIds": {}},  # whitespace title
            {"paperId": "s2-a", "title": "Confirmed", "externalIds": {"ArXiv": "2101.00001"}},
        ],
    )

    assert [node.title for node in tree.nodes] == ["Confirmed"]
    assert {edge.target for edge in tree.edges} == {"2101.00001"}  # unresolved never edges in
    assert [u.title for u in sorted(tree.unresolved, key=lambda u: u.title)] == [
        "(untitled)",
        "(untitled)",
        "Title-only reference",
    ]
    assert all(u.reason == "unresolved" for u in tree.unresolved)
    assert tree.status == "Partial"


def test_duplicate_reference_folds_to_already_shown() -> None:
    # US-CG3: 중복 노드는 '이미 표시됨'(alreadyShown)으로 접힘 — 두 번째 등장은 확정 신규
    # 노드가 아니고 저장도 불가.
    first = {
        "paperId": "s2-a",
        "title": "Same paper",
        "citationCount": 10,
        "externalIds": {"ArXiv": "2101.00001"},
    }
    second = dict(first, paperId="s2-b", citationCount=5)  # same ArXiv id, new provider row
    tree = controller._build_tree("root", "root", [first, second])

    assert [node.alreadyShown for node in tree.nodes] == [False, True]
    assert tree.nodes[1].saveable is False
    confirmed = [node.nodeId for node in tree.nodes if not node.alreadyShown]
    assert confirmed == ["2101.00001"]  # exactly one confirmed instance


def test_root_cycle_folds_to_already_shown() -> None:
    # US-CG3: 순환은 무한 확장되지 않는다 — 루트가 참조로 되돌아오면 접힌다.
    tree = controller._build_tree(
        "2101.00001",
        "2101.00001",
        [{"paperId": "s2-r", "title": "Root again", "externalIds": {"ArXiv": "2101.00001"}}],
    )

    assert tree.nodes[0].alreadyShown is True
    assert tree.nodes[0].saveable is False


def test_expand_self_citation_folds_to_already_shown() -> None:
    # US-CG3: 확장 대상(parent)이 자기 자신을 인용하는 사이클(A→A)도 접힌다 — 접히지 않으면
    # 클라이언트가 A→A→…를 무한 확장할 수 있다.
    tree = controller._build_tree(
        "root",
        "2102.00002",
        [{"paperId": "s2-s", "title": "Self citation", "externalIds": {"ArXiv": "2102.00002"}}],
    )

    assert tree.nodes[0].alreadyShown is True
    assert tree.nodes[0].saveable is False


def test_cyclic_expansion_terminates_at_depth_cap(monkeypatch) -> None:
    # US-CG3: A↔root 상호 인용을 끝까지 따라가도 응답 depth는 MAX_DEPTH(2)에서 멈추고,
    # 재등장 노드는 alreadyShown으로 접힌다.
    class CyclicProvider:
        async def references(self, paper_id: str, limit: int):
            target = "2202.00001" if "root" in paper_id else "root-arxiv"
            return "ok", [
                {
                    "paperId": f"s2-{target}",
                    "title": f"Paper {target}",
                    "externalIds": {"ArXiv": target},
                }
            ]

    client = _client(monkeypatch, provider=CyclicProvider())
    first = client.get("/api/papers/root-arxiv/citation-tree").json()
    assert first["depthReturned"] == 1
    assert first["nodes"][0]["nodeId"] == "2202.00001"

    expanded = client.get(
        "/api/papers/root-arxiv/citation-tree", params={"expandNodeId": "2202.00001"}
    ).json()

    assert expanded["depthReturned"] == 2 <= controller.MAX_DEPTH
    assert all(node["depth"] <= controller.MAX_DEPTH for node in expanded["nodes"])
    # the cycle back to the root folds instead of spawning a fresh expandable node
    assert expanded["nodes"][0]["nodeId"] == "root-arxiv"
    assert expanded["nodes"][0]["alreadyShown"] is True


# --- US-CG6 metrics via the U6 ObservabilityHub (QA 2026-07-10 gap B) -----------------------


class RecordingHub:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict]] = []
        self.logs: list[dict] = []

    def emit_metric(self, name, value, tags) -> None:
        self.metrics.append((name, float(value), dict(tags)))

    def emit_log(self, entry) -> None:
        self.logs.append(dict(entry))

    def by_name(self, name: str) -> list[tuple[float, dict]]:
        return [(value, tags) for n, value, tags in self.metrics if n == name]


def test_lookup_emits_citation_graph_metrics(monkeypatch) -> None:
    hub = RecordingHub()
    client = _client(monkeypatch)
    client.app.state.observability = hub

    assert client.get("/api/papers/root/citation-tree").status_code == 200

    assert hub.by_name("citation.graph.lookup") == [(1.0, {"cache": "miss"})]
    assert hub.by_name("citation.graph.node_count") == [(2.0, {})]
    ((ratio, _),) = hub.by_name("citation.graph.unresolved_ratio")
    assert ratio == pytest.approx(1 / 3)  # fixture: 2 resolved + 1 unresolved
    ((latency, _),) = hub.by_name("citation.graph.latency_ms")
    assert latency >= 0.0
    assert hub.by_name("citation.graph.provider_error") == []
    assert hub.logs and hub.logs[0]["event"] == "citation_graph.lookup"


def test_cache_hit_emits_hit_tagged_lookup_metric(monkeypatch) -> None:
    hub = RecordingHub()
    client = _client(monkeypatch, store=controller.InMemorySnapshotStore())
    client.app.state.observability = hub

    client.get("/api/papers/root/citation-tree")
    client.get("/api/papers/root/citation-tree")

    assert [tags["cache"] for _, tags in hub.by_name("citation.graph.lookup")] == ["miss", "hit"]


@pytest.mark.parametrize("provider_status", ["rate_limited", "unavailable"])
def test_provider_failure_emits_error_metric(monkeypatch, provider_status) -> None:
    # US-CG6: 외부 API 오류·429가 카운트로 남는다 — 실패 경로도 lookup/latency를 남긴다.
    hub = RecordingHub()
    client = _client(monkeypatch, provider=FixtureProvider(provider_status))
    client.app.state.observability = hub

    assert client.get("/api/papers/root/citation-tree").status_code == 200

    assert hub.by_name("citation.graph.provider_error") == [(1.0, {"status": provider_status})]
    assert hub.by_name("citation.graph.lookup") == [(1.0, {"cache": "miss"})]
    assert hub.by_name("citation.graph.node_count") == [(0.0, {})]
    assert len(hub.by_name("citation.graph.latency_ms")) == 1


def test_observability_failure_never_breaks_lookup(monkeypatch) -> None:
    # US-CG6: 허브 장애는 조회 경로로 전파되지 않는다 (discovery _emit_guarded와 동일 계약).
    class RaisingHub:
        def emit_metric(self, name, value, tags) -> None:
            raise RuntimeError("cloudwatch down")

        def emit_log(self, entry) -> None:
            raise RuntimeError("log sink down")

    client = _client(monkeypatch)
    client.app.state.observability = RaisingHub()

    resp = client.get("/api/papers/root/citation-tree")

    assert resp.status_code == 200
    assert len(resp.json()["nodes"]) == 2
