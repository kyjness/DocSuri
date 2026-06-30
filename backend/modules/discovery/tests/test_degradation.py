"""Degrade matrix (BR-11/Q6): RERANK_OFF banner, LEXICAL_ONLY fallback, KO no-match empty page."""

from __future__ import annotations

from enum import Enum

from docsuri_shared.dtos import DegradedResultDTO

from discovery.api import run_search
from discovery.domain.models import AuthSession, DegradeMode, RequestContext
from discovery.mocks import build_mock_orchestrator
from discovery.service.orchestrator import _derive_degradation


def _ctx() -> RequestContext:
    return RequestContext(auth_session=AuthSession(user_id="u1"), request_id="req-1")


class _PlainEnumMode(Enum):
    """A plain Enum whose str() is "Class.MEMBER" — what U6 might emit (BudgetState PROVISIONAL)."""

    LEXICAL_ONLY = "LEXICAL_ONLY"


class _Budget:
    def __init__(self, degrade_mode) -> None:
        self.degrade_mode = degrade_mode


def test_derive_degradation_unwraps_plain_enum() -> None:
    # BR-11: a plain Enum must map by its .value, not silently fall through to NORMAL (which it
    # would, since str(_PlainEnumMode.LEXICAL_ONLY) == "_PlainEnumMode.LEXICAL_ONLY").
    mode, signal = _derive_degradation(_Budget(_PlainEnumMode.LEXICAL_ONLY))
    assert mode is DegradeMode.LEXICAL_ONLY
    assert signal.llm_enabled is False


def test_derive_degradation_unknown_mode_is_normal() -> None:
    # Unrecognized / absent degrade mode → NORMAL (safe default — full functionality, no banner).
    assert _derive_degradation(_Budget("something-unexpected"))[0] is DegradeMode.NORMAL
    assert _derive_degradation(_Budget(None))[0] is DegradeMode.NORMAL


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
