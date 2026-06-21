"""Terminal states (BR-9/Q4) + SearchExecuted publish (BR-14) + cross-lingual (TD-3).

The full pipeline is exercised via the gateway seam ``run_search`` (which performs the single
``enforce`` call, INV-1) — the orchestrator itself never calls enforce.
"""

from __future__ import annotations

from docsuri_shared.dtos import (
    AbstainDTO,
    SearchRequest,
    SearchResultPageDTO,
    ValidationErrorDTO,
)

from discovery.api import run_search
from discovery.domain.models import AuthSession, RequestContext
from discovery.mocks import build_mock_orchestrator


def _ctx() -> RequestContext:
    return RequestContext(auth_session=AuthSession(user_id="u1"), request_id="req-1")


def test_success_returns_ranked_page_and_publishes() -> None:
    bundle = build_mock_orchestrator()
    resp = run_search(
        bundle.orchestrator, bundle.grounding_hook,
        SearchRequest(query="diffusion models for protein structure"), _ctx(),
    )
    assert isinstance(resp.root, SearchResultPageDTO)
    assert resp.root.cards
    assert resp.root.cards[0].arxivId.startswith("2401.00001")
    # PaperId dedup: the two chunks of 2401.00001 collapse to one card.
    arxiv_ids = [c.arxivId for c in resp.root.cards]
    assert len(arxiv_ids) == len(set(arxiv_ids))
    assert len(bundle.event_publisher.events) == 1  # FR-10 non-blocking publish (BR-14)
    assert bundle.event_publisher.events[0].resultCount == len(resp.root.cards)


def test_no_match_is_empty_page_not_abstain() -> None:
    # A no-match is an explicit empty page (resultCount=0), NOT an abstain (BR-9 / U5 B3-a).
    bundle = build_mock_orchestrator()
    resp = run_search(
        bundle.orchestrator, bundle.grounding_hook,
        SearchRequest(query="zzz nonsense token"), _ctx(),
    )
    assert isinstance(resp.root, SearchResultPageDTO)
    assert resp.root.cards == []
    assert resp.root.meta.resultCount == 0
    assert bundle.event_publisher.events[0].resultCount == 0


def test_grounding_verdict_abstain_maps_to_abstain() -> None:
    bundle = build_mock_orchestrator(grounding_verdict="abstain")
    resp = run_search(
        bundle.orchestrator, bundle.grounding_hook,
        SearchRequest(query="diffusion protein"), _ctx(),
    )
    assert isinstance(resp.root, AbstainDTO)


def test_validation_error_does_not_publish() -> None:
    bundle = build_mock_orchestrator()
    resp = run_search(
        bundle.orchestrator, bundle.grounding_hook, SearchRequest(query="   "), _ctx()
    )
    assert isinstance(resp.root, ValidationErrorDTO)
    assert bundle.event_publisher.events == []


def test_korean_query_matches_english_paper_cross_lingual() -> None:
    bundle = build_mock_orchestrator()
    resp = run_search(
        bundle.orchestrator, bundle.grounding_hook,
        SearchRequest(query="확산 모델 단백질 구조"), _ctx(),
    )
    assert isinstance(resp.root, SearchResultPageDTO)
    assert resp.root.cards[0].arxivId.startswith("2401.00001")
