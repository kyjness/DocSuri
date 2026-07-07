"""Rerank pipeline integration (FR-3) — the cross-encoder reorders the final page, is gated by
the cost budget, and is fail-soft (any adapter failure keeps the baseline order, search OK).

Driven through the gateway seam ``run_search`` like ``test_orchestrator`` (INV-1).
"""

from __future__ import annotations

from collections.abc import Sequence

from docsuri_shared.dtos import DegradedResultDTO, SearchRequest, SearchResultPageDTO

from discovery.api import run_search
from discovery.domain.models import AuthSession, RequestContext
from discovery.mocks import build_mock_orchestrator
from discovery.mocks.adapters import (
    FailingEmbeddingAdapter,
    FailingRerankAdapter,
    MockRerankAdapter,
)

_QUERY = "diffusion models for protein structure"


def _ctx() -> RequestContext:
    return RequestContext(auth_session=AuthSession(user_id="u1"), request_id="req-1")


class _ReverseRerank:
    """Deterministic reranker that reverses the head order (score = input index) — proves the
    final page order is driven by rerank scores, not the RRF order."""

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        return [float(i) for i in range(len(documents))]


class _SpyRerank:
    """Records whether rerank was invoked (to assert a path SKIPS rerank, not just fails soft)."""

    def __init__(self) -> None:
        self.calls = 0

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        self.calls += 1
        return [float(i) for i in range(len(documents))]


def _cards(orchestrator, grounding_hook):
    resp = run_search(orchestrator, grounding_hook, SearchRequest(query=_QUERY), _ctx())
    return resp


def _ids(bundle) -> list[str]:
    return [c.arxivId for c in _cards(bundle.orchestrator, bundle.grounding_hook).root.cards]


def test_rerank_reorders_the_final_page() -> None:
    baseline = build_mock_orchestrator()
    base_resp = _cards(baseline.orchestrator, baseline.grounding_hook)
    assert isinstance(base_resp.root, SearchResultPageDTO)
    base_ids = [c.arxivId for c in base_resp.root.cards]
    assert len(base_ids) >= 2  # need ≥2 cards for a reorder to be observable

    reranked = build_mock_orchestrator(reranker=_ReverseRerank())
    rr_resp = _cards(reranked.orchestrator, reranked.grounding_hook)
    assert isinstance(rr_resp.root, SearchResultPageDTO)
    rr_ids = [c.arxivId for c in rr_resp.root.cards]

    # Same result set, different order — the reverse reranker flips the head.
    assert set(rr_ids) == set(base_ids)
    assert rr_ids != base_ids
    assert rr_ids[0] == base_ids[-1]


def test_mock_rerank_returns_valid_page() -> None:
    bundle = build_mock_orchestrator(reranker=MockRerankAdapter())
    resp = _cards(bundle.orchestrator, bundle.grounding_hook)
    assert isinstance(resp.root, SearchResultPageDTO)
    assert resp.root.cards
    # No internal score leaks onto the card (SEC-9) — relevance is the display rank only.
    assert resp.root.cards[0].relevance == 1


def test_rerank_failure_is_fail_soft_baseline() -> None:
    baseline = build_mock_orchestrator()
    base_ids = _ids(baseline)

    failing = build_mock_orchestrator(reranker=FailingRerankAdapter())
    resp = _cards(failing.orchestrator, failing.grounding_hook)
    # Search still succeeds and keeps the baseline order — rerank never blocks (BR-5).
    assert isinstance(resp.root, SearchResultPageDTO)
    assert [c.arxivId for c in resp.root.cards] == base_ids


def test_embedding_outage_skips_rerank_not_just_fail_soft() -> None:
    # Embedding down → lexical-only fallback. Rerank is the SAME Bedrock provider, so it must be
    # SKIPPED (not attempted-then-fail-soft) to avoid stalling the degraded request on its timeout.
    spy = _SpyRerank()
    bundle = build_mock_orchestrator(embedding_adapter=FailingEmbeddingAdapter(), reranker=spy)
    resp = _cards(bundle.orchestrator, bundle.grounding_hook)
    assert resp.root.cards  # lexical fallback still returns results (exercises the rerank gate)
    assert spy.calls == 0  # rerank never invoked on the embedding-outage path


def test_budget_rerank_off_skips_rerank_and_flags_degraded() -> None:
    baseline = build_mock_orchestrator()
    base_ids = _ids(baseline)

    # rerank-off budget disables rerank even with a reordering reranker wired.
    degraded = build_mock_orchestrator(degrade_mode="rerank-off", reranker=_ReverseRerank())
    resp = _cards(degraded.orchestrator, degraded.grounding_hook)
    assert isinstance(resp.root, DegradedResultDTO)  # banner surfaced (BR-11)
    assert [c.arxivId for c in resp.root.cards] == base_ids  # order unchanged (rerank skipped)
