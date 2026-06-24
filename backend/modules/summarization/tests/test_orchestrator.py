"""Orchestrator — pipeline paths: cache hit, cost degrade, source unavailable, summary,
grounding-fail abstain, translate (business-logic-model.md §2)."""

from __future__ import annotations

from summarization.domain.models import (
    AbstainDTO,
    Anchor,
    AnchorTarget,
    AuthSession,
    CostDegradedDTO,
    RequestContext,
    SourceUnavailableDTO,
    SummaryDraft,
    SummaryRequest,
    Task,
)
from tests.stubs import (
    StubCostGuard,
    StubFullText,
    StubLlm,
    StubStore,
    _Budget,
    make_orchestrator,
)


def _ctx() -> RequestContext:
    return RequestContext(auth_session=AuthSession(user_id="u1"), request_id="r1")


def _req(task: Task = Task.SUMMARY, abstract: str | None = None) -> SummaryRequest:
    return SummaryRequest(paper_id="2401.1", version=1, task=task, abstract=abstract)


def test_cache_hit_skips_llm() -> None:
    store = StubStore()
    llm = StubLlm()
    orch = make_orchestrator(store=store, llm=llm)
    # First run populates the cache.
    first = orch.run(_req(), _ctx())
    assert first.to_dict()["status"] == "ok"
    # Second run is a HIT — no new put, marked cached.
    puts_after_first = store.puts
    second = orch.run(_req(), _ctx())
    assert second.to_dict()["cached"] is True
    assert store.puts == puts_after_first  # no regeneration


def test_cost_degraded_abstains_before_llm() -> None:
    orch = make_orchestrator(cost_guard=StubCostGuard(_Budget(degrade_mode="lexical-only")))
    result = orch.run(_req(), _ctx())
    assert isinstance(result, CostDegradedDTO)


def test_source_unavailable() -> None:
    orch = make_orchestrator(full_text=StubFullText(text=None))
    result = orch.run(_req(), _ctx())  # no abstract → no source
    assert isinstance(result, SourceUnavailableDTO)


def test_summary_ok_writes_through() -> None:
    store = StubStore()
    orch = make_orchestrator(store=store)
    result = orch.run(_req(), _ctx())
    assert result.to_dict()["status"] == "ok"
    assert store.puts == 1


def test_grounding_failure_abstains_after_retry() -> None:
    bad_draft = SummaryDraft(
        tldr="x", contributions=("c",), method="m", results="achieves 42.7% accuracy",
        limitations="l", reproducibility={"code": "", "data": ""},
        anchors=(Anchor("results", AnchorTarget.TABLE, span="42.7% on nowhere"),),
    )
    llm = StubLlm(draft=bad_draft)
    orch = make_orchestrator(llm=llm)
    result = orch.run(_req(), _ctx())
    assert isinstance(result, AbstainDTO)
    assert result.reason == "insufficient_grounding"
    assert llm._calls == 2  # one retry (BR-S7)


def test_llm_outage_then_recovery() -> None:
    llm = StubLlm(raise_n=1)  # first call raises, retry succeeds
    orch = make_orchestrator(llm=llm)
    result = orch.run(_req(), _ctx())
    assert result.to_dict()["status"] == "ok"


def test_translate_path() -> None:
    orch = make_orchestrator()
    result = orch.run(_req(Task.TRANSLATE, abstract="An abstract about BERT."), _ctx())
    out = result.to_dict()
    assert out["status"] == "ok"
    assert out["task"] == "translate"
    assert "translation" in out


def test_translate_abstains_on_empty_translation() -> None:
    # A blank LLM response (empty translations map) leaves every field falling back to the source
    # English text — that must NOT be served as a successful translation. The empty-translation
    # gate compares against the source and abstains after a retry (BR-S18).
    orch = make_orchestrator(llm=StubLlm(empty=True))
    result = orch.run(_req(Task.TRANSLATE, abstract="An abstract about BERT."), _ctx())
    assert isinstance(result, AbstainDTO)
    assert result.reason == "empty_translation"


def test_orchestrator_abstains_on_map_reduce_length() -> None:
    # No map-reduce summarizer wired → MAP_REDUCE band still abstains (current behavior).
    from summarization.domain.length_router import LengthRouter
    length_router = LengthRouter(context_budget=10, input_cap=100)
    orch = make_orchestrator()
    orch._length = length_router

    result = orch.run(_req(), _ctx())
    assert isinstance(result, AbstainDTO)
    assert result.reason == "input_too_long"


def test_orchestrator_map_reduce_summary_when_wired() -> None:
    # MAP_REDUCE band + summarizer wired → the summary is produced via map-reduce (BR-S6).
    from summarization.domain.length_router import LengthRouter
    orch = make_orchestrator()
    orch._length = LengthRouter(context_budget=5, input_cap=10_000)
    map_reduce = StubLlm()  # records calls, returns valid_draft → passes grounding
    orch._map_reduce = map_reduce

    out = orch.run(_req(), _ctx()).to_dict()
    assert out["status"] == "ok"
    assert out["task"] == "summary"
    assert map_reduce._calls >= 1  # map-reduce summarizer produced the draft


class _SpyQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def enqueue(self, request, user_id) -> None:
        self.calls.append((request.paper_id, user_id))


def test_orchestrator_enqueues_pending_on_long_summary() -> None:
    # API path: MAP_REDUCE + queue wired → enqueue a background job, return pending (BR-S8).
    from summarization.domain.length_router import LengthRouter
    orch = make_orchestrator()
    orch._length = LengthRouter(context_budget=5, input_cap=10_000)
    orch._map_reduce = StubLlm()
    queue = _SpyQueue()
    orch._summary_job_queue = queue

    out = orch.run(_req(), _ctx()).to_dict()
    assert out["status"] == "pending"
    assert out["retryAfterMs"] >= 1
    assert queue.calls == [("2401.1", "u1")]


def test_orchestrator_runs_map_reduce_inline_on_worker_path() -> None:
    # Worker path: allow_enqueue=False → map-reduce runs inline (no re-enqueue), ok summary.
    from summarization.domain.length_router import LengthRouter
    orch = make_orchestrator()
    orch._length = LengthRouter(context_budget=5, input_cap=10_000)
    map_reduce = StubLlm()
    orch._map_reduce = map_reduce
    queue = _SpyQueue()
    orch._summary_job_queue = queue

    out = orch.run(_req(), _ctx(), allow_enqueue=False).to_dict()
    assert out["status"] == "ok"
    assert out["task"] == "summary"
    assert queue.calls == []  # worker never re-enqueues
    assert map_reduce._calls >= 1


def test_orchestrator_over_cap_rejects_even_with_map_reduce() -> None:
    # Beyond INPUT_CAP → rejected regardless of the summarizer (extreme inputs are not handled).
    from summarization.domain.length_router import LengthRouter
    orch = make_orchestrator()
    orch._length = LengthRouter(context_budget=1, input_cap=3)
    orch._map_reduce = StubLlm()

    result = orch.run(_req(), _ctx())
    assert isinstance(result, AbstainDTO)
    assert result.reason == "input_too_long"


def test_orchestrator_translate_abstains_when_gate_off() -> None:
    # Gate OFF (no map-reduce wired) → long translate (MAP_REDUCE band) abstains (BR-S6/S18).
    from summarization.domain.length_router import LengthRouter
    from summarization.domain.models import Scope

    orch = make_orchestrator()
    orch._length = LengthRouter(context_budget=5, input_cap=10_000)

    req = SummaryRequest(paper_id="2401.1", version=1, task=Task.TRANSLATE, scope=Scope.FULL)
    result = orch.run(req, _ctx())
    assert isinstance(result, AbstainDTO)
    assert result.reason == "input_too_long"


def test_orchestrator_translate_map_only_inline_when_gate_on() -> None:
    # Gate ON (map-reduce wired), no queue → long translate runs map-only INLINE → ok translation
    # (a 'translated doc-model'), no reduce step (BR-S18).
    from summarization.domain.length_router import LengthRouter
    from summarization.domain.models import Scope

    orch = make_orchestrator()
    orch._length = LengthRouter(context_budget=5, input_cap=10_000)
    orch._map_reduce = StubLlm()  # shared gate proxy (DOCSURI_MAP_REDUCE_ENABLED)

    req = SummaryRequest(paper_id="2401.1", version=1, task=Task.TRANSLATE, scope=Scope.FULL)
    out = orch.run(req, _ctx()).to_dict()
    assert out["status"] == "ok"
    assert out["task"] == "translate"
    assert "docModel" in out["translation"]


def test_orchestrator_translate_enqueues_pending_on_long_input() -> None:
    # API path: MAP_REDUCE band + queue wired → enqueue a translate job, return pending (BR-S12).
    from summarization.domain.length_router import LengthRouter
    from summarization.domain.models import Scope

    orch = make_orchestrator()
    orch._length = LengthRouter(context_budget=5, input_cap=10_000)
    orch._map_reduce = StubLlm()
    queue = _SpyQueue()
    orch._summary_job_queue = queue

    req = SummaryRequest(paper_id="2401.1", version=1, task=Task.TRANSLATE, scope=Scope.FULL)
    out = orch.run(req, _ctx()).to_dict()
    assert out["status"] == "pending"
    assert queue.calls == [("2401.1", "u1")]
