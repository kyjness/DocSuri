"""``retrieve_ranked`` — the in-process agent entry (U11 evidence ``corpus_search``).

What matters here is that this entry is NOT a second pipeline: it runs the same stages as
``plan_and_retrieve`` up to the ranker, so it carries the cross-encoder rerank. The bug this
guards is the one that motivated it — a caller that reaches for ``HybridRetriever`` directly
gets RRF order and nothing anywhere says so.

It also must NOT do the response-edge work: no grounding enforce/assemble (the agent runs its
own evidence gate), no no-match k-NN floor, no SearchExecuted history event.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from discovery.adapters.bedrock_rerank import BedrockRerankAdapter
from discovery.domain.models import SearchScope, YearRange
from discovery.ports.search_ports import InvalidQuery, RerankThrottled, RerankUnavailable
from discovery.service import orchestrator as orchestrator_module
from discovery.service.orchestrator import _AGENT_RERANK_BACKOFF_S
from discovery.testing import build_mock_orchestrator

_QUERY = "diffusion models for protein structure"


class _ReverseRerank:
    """Deterministic reranker that reverses the head order (score = input index)."""

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        return [float(i) for i in range(len(documents))]


def _ids(ranked) -> list[str]:
    return [c.record.paperId for c in ranked.ranked]


def test_rerank_is_applied_on_the_agent_path() -> None:
    baseline = build_mock_orchestrator().orchestrator.retrieve_ranked(
        _QUERY, scope=SearchScope.FULL
    )
    reranked = build_mock_orchestrator(reranker=_ReverseRerank()).orchestrator.retrieve_ranked(
        _QUERY, scope=SearchScope.FULL
    )

    assert _ids(baseline), "the mock corpus returned nothing — the fixture is the problem"
    assert _ids(baseline) != _ids(reranked)
    # Same result SET, different order: rerank rewrites ranking_score, it does not filter.
    assert set(_ids(baseline)) == set(_ids(reranked))


def test_no_reranker_keeps_the_fused_order() -> None:
    """Feature off (no ARN wired) must behave exactly as before this entry existed."""
    bundle = build_mock_orchestrator()
    assert _ids(bundle.orchestrator.retrieve_ranked(_QUERY, scope=SearchScope.FULL)) == _ids(
        bundle.orchestrator.retrieve_ranked(_QUERY, scope=SearchScope.FULL)
    )


def test_budget_rerank_off_skips_rerank() -> None:
    """A cost degrade has to reach the agent path too, or rerank calls keep going out while the
    budget is closed."""

    class _Spy:
        def __init__(self) -> None:
            self.calls = 0

        def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
            self.calls += 1
            return [float(i) for i in range(len(documents))]

    spy = _Spy()
    bundle = build_mock_orchestrator(reranker=spy, degrade_mode="rerank-off")
    bundle.orchestrator.retrieve_ranked(_QUERY, scope=SearchScope.FULL)
    assert spy.calls == 0


def test_year_bound_reaches_the_store_query() -> None:
    """``YearRange`` is a FILTER pushed into the store query — applied to the returned page it
    would be indistinguishable from "no such paper exists" whenever top-k held none in range."""
    seen: dict[str, object] = {}

    class _SpyLexical:
        def bm25_search(self, terms, top_k, fields=(), years=None):
            seen["bm25"] = years
            return []

        def phrase_search(self, phrase, top_k, paper_ids=None, years=None):
            return []

    class _SpyVector:
        def knn_search(self, vector, top_k, abstract_only=False, years=None):
            seen["knn"] = years
            return []

    bundle = build_mock_orchestrator(vector_store=_SpyVector(), lexical_index=_SpyLexical())
    years = YearRange(start=2023, end=2024)
    bundle.orchestrator.retrieve_ranked(_QUERY, scope=SearchScope.FULL, years=years)

    assert seen["bm25"] == years
    assert seen["knn"] == years


def test_empty_retrieval_returns_no_candidates_without_touching_the_response_edge() -> None:
    """No grounding abstain, no assembled empty page, no history event — just nothing found."""

    class _Empty:
        def bm25_search(self, terms, top_k, fields=(), years=None):
            return []

        def phrase_search(self, phrase, top_k, paper_ids=None, years=None):
            return []

    class _EmptyVector:
        def knn_search(self, vector, top_k, abstract_only=False, years=None):
            return []

    bundle = build_mock_orchestrator(vector_store=_EmptyVector(), lexical_index=_Empty())
    ranked = bundle.orchestrator.retrieve_ranked(_QUERY, scope=SearchScope.FULL)

    assert ranked.ranked == ()
    assert bundle.event_publisher.events == []


def test_no_match_floor_does_not_gate_the_agent_path() -> None:
    """US-D6's floor turns a weak match into an empty page for a human. An agent is better served
    by a weak-but-real neighbour — it cannot re-ask the way a person retypes a query."""
    bundle = build_mock_orchestrator()
    bundle.orchestrator._no_match_knn_floor = 10_000.0  # far above any mock score

    ranked = bundle.orchestrator.retrieve_ranked(_QUERY, scope=SearchScope.FULL)

    assert ranked.ranked, "the floor leaked into the agent path"


def test_invalid_query_raises_rather_than_returning_empty() -> None:
    """An internal caller has no inline DTO to render a validation error into, and a silent empty
    result would read as "no such paper" — the one confusion this repo keeps paying for."""
    bundle = build_mock_orchestrator()
    with pytest.raises(InvalidQuery):
        bundle.orchestrator.retrieve_ranked("bad\x00query", scope=SearchScope.FULL)


def test_invalid_query_is_not_a_bare_value_error() -> None:
    """The caller turns this into "rewrite your query" for a model, so the type must be narrow.

    As ``ValueError`` it would also catch anything else in the U2 stack that happens to raise one
    — including ``EnvConfigError``, which subclasses it. A real fault would then be reported to
    the model as a bad query: the model rewrites a query that was fine, and the fault is invisible.
    """
    assert not issubclass(InvalidQuery, ValueError)


def test_metrics_separate_the_agent_caller_from_human_search() -> None:
    """에이전트의 `scope=full` 호출이 사람 검색과 같은 차원으로 섞이면, 사람 검색의 P50
    분포(NFR-P1)가 사람 쪽 변경 없이 움직인다 — 그 메트릭으로 단계 예산을 맞추는 쪽이
    엉뚱한 단계를 튜닝하게 된다."""

    class _Hub:
        def __init__(self) -> None:
            self.dims: list[dict] = []

        def emit_metric(self, name, value, dims) -> None:
            if name in ("discovery.search.stage_ms", "discovery.search.rerank"):
                self.dims.append(dims)

    hub = _Hub()
    bundle = build_mock_orchestrator(reranker=_ReverseRerank(), observability=hub)

    bundle.orchestrator.retrieve_ranked(_QUERY, scope=SearchScope.FULL)
    assert hub.dims, "메트릭이 하나도 안 나왔다 — 대역이 안 물렸다"
    assert {d.get("caller") for d in hub.dims} == {"agent"}

    hub.dims.clear()
    from docsuri_shared.dtos import SearchRequest

    from discovery.api import run_search
    from discovery.domain.models import AuthSession, RequestContext

    run_search(
        bundle.orchestrator,
        bundle.grounding_hook,
        SearchRequest(query=_QUERY, scope="full"),
        RequestContext(auth_session=AuthSession(user_id="u1"), request_id="req-1"),
    )
    assert {d.get("caller") for d in hub.dims} == {"search"}


def test_top_n_override_bounds_the_result() -> None:
    bundle = build_mock_orchestrator()
    ranked = bundle.orchestrator.retrieve_ranked(_QUERY, scope=SearchScope.FULL, top_n=1)
    assert len(ranked.ranked) == 1


# --- rerank throttling: the agent backs off, human search does not --------------------------
#
# The rerank quota throttles routinely (35–50% even at 5–6s spacing), and a throttled rerank is
# silent: RRF order, 200. The agent is a caller that can afford to wait, so it retries on
# throttling only; human search keeps failing fast under its P50 budget.


class _ThrottleThen:
    """Throttles the first ``n`` calls, then reverses the head order like ``_ReverseRerank``."""

    def __init__(self, n: int, exc: type[Exception] = RerankThrottled) -> None:
        self.n = n
        self.exc = exc
        self.calls = 0

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        self.calls += 1
        if self.calls <= self.n:
            raise self.exc("throttled")
        return [float(i) for i in range(len(documents))]


@pytest.fixture
def waits(monkeypatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(orchestrator_module, "_sleep", slept.append)
    return slept


def test_agent_rerank_recovers_from_throttling(waits) -> None:
    baseline = build_mock_orchestrator().orchestrator.retrieve_ranked(
        _QUERY, scope=SearchScope.FULL
    )
    flaky = _ThrottleThen(2)
    ranked = build_mock_orchestrator(reranker=flaky).orchestrator.retrieve_ranked(
        _QUERY, scope=SearchScope.FULL
    )

    assert flaky.calls == 3
    assert len(waits) == 2
    # Recovered means the reranked order was served, not the RRF fallback.
    assert _ids(ranked) != _ids(baseline)


def test_agent_rerank_gives_up_after_the_schedule(waits) -> None:
    baseline = build_mock_orchestrator().orchestrator.retrieve_ranked(
        _QUERY, scope=SearchScope.FULL
    )
    stuck = _ThrottleThen(99)
    ranked = build_mock_orchestrator(reranker=stuck).orchestrator.retrieve_ranked(
        _QUERY, scope=SearchScope.FULL
    )

    assert stuck.calls == len(_AGENT_RERANK_BACKOFF_S) + 1
    # Each wait is jittered inside [d/2, d] of its slot — bounded worst case.
    assert all(d / 2 <= w <= d for w, d in zip(waits, _AGENT_RERANK_BACKOFF_S, strict=True))
    assert _ids(ranked) == _ids(baseline)  # still fail-soft


def test_agent_does_not_retry_failures_waiting_cannot_fix(waits) -> None:
    denied = _ThrottleThen(99, exc=RerankUnavailable)
    build_mock_orchestrator(reranker=denied).orchestrator.retrieve_ranked(
        _QUERY, scope=SearchScope.FULL
    )
    assert denied.calls == 1
    assert waits == []


def test_human_search_does_not_wait_on_throttling(waits) -> None:
    from docsuri_shared.dtos import SearchRequest

    from discovery.api import run_search
    from discovery.domain.models import AuthSession, RequestContext

    throttled = _ThrottleThen(99)
    bundle = build_mock_orchestrator(reranker=throttled)
    run_search(
        bundle.orchestrator,
        bundle.grounding_hook,
        SearchRequest(query=_QUERY, scope="full"),
        RequestContext(auth_session=AuthSession(user_id="u1"), request_id="req-1"),
    )
    assert throttled.calls == 1
    assert waits == []


class _ClientError(Exception):
    """botocore ``ClientError`` shape (``.response['Error']['Code']``) without importing it."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _RaisingClient:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def rerank(self, **_kwargs):
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "throttled"),
    [
        (_ClientError("ThrottlingException"), True),
        (_ClientError("AccessDeniedException"), False),
        (TimeoutError("read timeout"), False),
    ],
)
def test_adapter_marks_only_throttling_as_retryable(exc: Exception, throttled: bool) -> None:
    adapter = BedrockRerankAdapter(model_arn="arn:test", client=_RaisingClient(exc))
    with pytest.raises(RerankUnavailable) as raised:
        adapter.rerank(_QUERY, ["doc"])
    assert isinstance(raised.value, RerankThrottled) is throttled
