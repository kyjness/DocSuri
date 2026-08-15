"""RES-12 fault injection (QT-3): embedding outage → lexical; index outage → fail-closed."""

from __future__ import annotations

import pytest
from docsuri_shared.dtos import DegradedResultDTO, SearchRequest

from discovery.api import run_search
from discovery.domain.models import AuthSession, RequestContext
from discovery.service.orchestrator import SearchUnavailable
from discovery.testing import build_mock_orchestrator
from discovery.testing.adapters import (
    FailingEmbeddingAdapter,
    FailingLexicalIndexAdapter,
    FailingVectorStoreAdapter,
)


def _ctx() -> RequestContext:
    return RequestContext(auth_session=AuthSession(user_id="u1"), request_id="req-1")


def test_embedding_outage_falls_back_to_lexical_only() -> None:
    bundle = build_mock_orchestrator(embedding_adapter=FailingEmbeddingAdapter())
    resp = run_search(
        bundle.orchestrator, bundle.grounding_hook,
        SearchRequest(query="diffusion protein structure"), _ctx(),
    )
    assert isinstance(resp.root, DegradedResultDTO)
    assert resp.root.mode.root == "lexical-only"


def test_index_outage_fails_closed() -> None:
    bundle = build_mock_orchestrator(lexical_index=FailingLexicalIndexAdapter())
    with pytest.raises(SearchUnavailable):
        run_search(
            bundle.orchestrator, bundle.grounding_hook,
            SearchRequest(query="diffusion protein"), _ctx(),
        )


def test_vector_store_outage_fails_closed() -> None:
    bundle = build_mock_orchestrator(vector_store=FailingVectorStoreAdapter())
    with pytest.raises(SearchUnavailable):
        run_search(
            bundle.orchestrator, bundle.grounding_hook,
            SearchRequest(query="diffusion protein"), _ctx(),
        )
