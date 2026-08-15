"""Live OpenSearch integration for the U2 real read path.

Exercises the real OpenSearch adapters against an actual cluster (local docker), with the
SAME index mapping the U1 writer uses, seeded from the deterministic fixtures. Embeddings use
the offline fixtures embedder (Bedrock is a separate cloud dependency), so this validates the
OpenSearch k-NN + BM25 + hybrid-retrieve path end-to-end with NO AWS.

Auto-skips when opensearch-py is absent (no ``real`` extra) or no cluster is reachable, so the
default ``uv run pytest`` stays green on a bare checkout. To run it:

    docker compose -f backend/docker-compose.yml up -d opensearch
    export DOCSURI_OPENSEARCH_ENDPOINT=http://localhost:9200
    export DOCSURI_OPENSEARCH_USE_SSL=0 DOCSURI_OPENSEARCH_VERIFY_CERTS=0
    uv run --extra real --extra dev pytest tests/test_opensearch_integration.py
"""

from __future__ import annotations

import pytest

pytest.importorskip("opensearchpy")  # skip whole module without the `real` extra

from discovery.adapters.opensearch_index import (  # noqa: E402
    OpenSearchClientFactory,
    OpenSearchLexicalIndexAdapter,
    OpenSearchVectorStoreAdapter,
)
from discovery.adapters.settings import DiscoverySettings  # noqa: E402
from discovery.domain.models import (  # noqa: E402
    DegradationSignal,
    QueryPlan,
    RetrievalMode,
)
from discovery.domain.retriever import HybridRetriever  # noqa: E402
from discovery.scripts.seed_local_opensearch import seed  # noqa: E402
from discovery.testing import fixtures  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live(settings_or_skip):
    settings = settings_or_skip
    client = OpenSearchClientFactory.build(
        endpoint=settings.opensearch_endpoint,
        username=settings.opensearch_username,
        password=settings.opensearch_password,
        use_ssl=settings.opensearch_use_ssl,
        verify_certs=settings.opensearch_verify_certs,
    )
    try:
        client.info()
    except Exception:  # noqa: BLE001
        pytest.skip("local OpenSearch endpoint configured but not reachable")
    seed(settings)
    client.indices.refresh(index=settings.opensearch_index)
    vector = OpenSearchVectorStoreAdapter(client, settings.opensearch_index)
    lexical = OpenSearchLexicalIndexAdapter(client, settings.opensearch_index)
    return vector, lexical


@pytest.fixture(scope="module")
def settings_or_skip() -> DiscoverySettings:
    settings = DiscoverySettings.from_env()
    if not settings.opensearch_endpoint:
        pytest.skip("DOCSURI_OPENSEARCH_ENDPOINT not set — live OpenSearch test skipped")
    return settings


def test_knn_returns_real_index_records(live) -> None:
    vector, _ = live
    query_vector = fixtures.embed("diffusion protein structure")
    results = vector.knn_search(query_vector, 20)
    assert results, "k-NN returned no hits from the seeded corpus"
    pids = {record.paperId for record, _score in results}
    assert "2401.00001" in pids  # the diffusion/protein paper
    # Real records round-trip back into the shared IndexRecord (SSOT, not a forked shape).
    record0 = results[0][0]
    assert record0.arxivUrl.startswith("https://arxiv.org/abs/")


def test_bm25_matches_lexical_terms(live) -> None:
    _, lexical = live
    results = lexical.bm25_search(["diffusion", "protein"], 50)
    pids = {record.paperId for record, _score in results}
    assert "2401.00001" in pids


def test_hybrid_retrieve_dedups_by_paper_id(live) -> None:
    vector, lexical = live
    retriever = HybridRetriever(vector, lexical)
    plan = QueryPlan(
        lexical_terms=("diffusion", "protein", "structure"),
        mode=RetrievalMode.HYBRID,
        embedding_vector=tuple(fixtures.embed("diffusion protein structure")),
    )
    candidates = retriever.retrieve(plan, DegradationSignal(llm_enabled=True, rerank_enabled=True))
    pids = [c.record.paperId for c in candidates.candidates]
    # Paper 2401.00001 has TWO chunks in the index — PaperId dedup keeps exactly one (PBT-07).
    assert pids.count("2401.00001") == 1
    assert "2401.00001" in pids
