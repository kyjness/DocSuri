"""Degrade matrix (BR-11/Q6): RERANK_OFF banner, LEXICAL_ONLY fallback, KO no-match empty page."""

from __future__ import annotations

from docsuri_shared.dtos import DegradedResultDTO

from discovery.api import run_search
from discovery.domain.models import AuthSession, RequestContext
from discovery.mocks import build_mock_orchestrator


def _ctx() -> RequestContext:
    return RequestContext(auth_session=AuthSession(user_id="u1"), request_id="req-1")


def test_rerank_off_is_degraded_banner() -> None:
    bundle = build_mock_orchestrator(degrade_mode="rerank-off")
    from docsuri_shared.dtos import SearchRequest

    resp = run_search(
        bundle.orchestrator, bundle.grounding_hook,
        SearchRequest(query="diffusion protein structure"), _ctx(),
    )
    assert isinstance(resp.root, DegradedResultDTO)
    assert resp.root.mode.root == "rerank-off"
    assert resp.root.meta.degraded is True


def test_lexical_only_english_returns_degraded_results() -> None:
    from docsuri_shared.dtos import SearchRequest

    bundle = build_mock_orchestrator(degrade_mode="lexical-only")
    resp = run_search(
        bundle.orchestrator, bundle.grounding_hook,
        SearchRequest(query="diffusion protein structure"), _ctx(),
    )
    assert isinstance(resp.root, DegradedResultDTO)
    assert resp.root.mode.root == "lexical-only"


def test_lexical_only_korean_is_empty_page() -> None:
    # Lexical (English) cannot match a Korean query → no candidates → explicit empty page
    # (resultCount=0), NOT an abstain (BR-9 / U5 B3-a: 기권 ≠ 빈 결과).
    from docsuri_shared.dtos import SearchRequest, SearchResultPageDTO

    bundle = build_mock_orchestrator(degrade_mode="lexical-only")
    resp = run_search(
        bundle.orchestrator, bundle.grounding_hook,
        SearchRequest(query="확산 모델 단백질"), _ctx(),
    )
    assert isinstance(resp.root, SearchResultPageDTO)
    assert resp.root.meta.resultCount == 0
