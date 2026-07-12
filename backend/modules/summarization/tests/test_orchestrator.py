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
    StubObservability,
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


def test_cost_degraded_blocks_llm_and_is_single_authority() -> None:
    """US-S6 AC: when U6 CostGuard flips degrade_mode ≠ normal (its 0.80-spend-ratio policy —
    'lexical-only' is what it sets at that ratio), U7 must make ZERO LLM calls and abstain with
    the user-facing 'AI 요약 일시 중단' DTO. U6 is the SINGLE cost authority: U7 consumes only
    the verdict fields (degrade_mode / circuit_state) — the stub budget carries no spend figures
    at all, so this passing proves U7 never re-judges the budget itself (BR-S13)."""
    llm = StubLlm()
    orch = make_orchestrator(
        llm=llm, cost_guard=StubCostGuard(_Budget(degrade_mode="lexical-only"))
    )
    result = orch.run(_req(), _ctx())
    assert isinstance(result, CostDegradedDTO)
    assert result.to_dict() == {"status": "cost_degraded", "message": "AI 요약 일시 중단"}
    assert llm._calls == 0, "U7 spent LLM tokens while cost-degraded"


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
    # gate compares against the source and abstains after a retry (BR-S18). A dedicated metric is
    # emitted so this failure mode is separable from generation_unavailable in observability.
    obs = StubObservability()
    orch = make_orchestrator(llm=StubLlm(empty=True), observability=obs)
    result = orch.run(_req(Task.TRANSLATE, abstract="An abstract about BERT."), _ctx())
    assert isinstance(result, AbstainDTO)
    assert result.reason == "empty_translation"
    assert any(name == "u7.translate.empty" for name, _v, _t in obs.metrics)


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


def test_orchestrator_full_translate_dispatches_async_when_multichunk() -> None:
    # SINGLE-CALL band (< 40K) but a large full-text translate is multi-chunk (output-bounded), so
    # inline it would exceed the gateway timeout (504). It must be dispatched to the async job
    # (pending → poll) instead — the worker runs it off the request path.
    from summarization.domain.models import Scope

    queue = _SpyQueue()
    # ~11K tokens: single-call band, but above the async-dispatch threshold (6K).
    orch = make_orchestrator(full_text=StubFullText(text="word " * 9000), summary_job_queue=queue)

    req = SummaryRequest(paper_id="2401.1", version=1, task=Task.TRANSLATE, scope=Scope.FULL)
    out = orch.run(req, _ctx()).to_dict()
    assert out["status"] == "pending"
    assert queue.calls == [("2401.1", "u1")]


def test_orchestrator_large_summary_dispatches_async() -> None:
    # A full-paper summary is one long LLM call (tens of seconds) → dispatch to the async job
    # (pending → poll) rather than block the request until it times out. Small sources stay inline.
    queue = _SpyQueue()
    orch = make_orchestrator(full_text=StubFullText(text="word " * 9000), summary_job_queue=queue)
    out = orch.run(_req(Task.SUMMARY), _ctx()).to_dict()
    assert out["status"] == "pending"
    assert queue.calls == [("2401.1", "u1")]


def test_orchestrator_small_summary_stays_inline() -> None:
    # A short source (below the async threshold) summarizes inline — no job, direct result.
    queue = _SpyQueue()
    orch = make_orchestrator(summary_job_queue=queue)
    out = orch.run(_req(Task.SUMMARY, abstract="A short abstract about BERT."), _ctx()).to_dict()
    assert out["status"] == "ok"
    assert queue.calls == []


def test_orchestrator_abstract_translate_stays_inline() -> None:
    # An abstract translate (small, scope != FULL) is NOT dispatched async — it runs inline and
    # returns a result directly, even with a job queue wired.
    queue = _SpyQueue()
    orch = make_orchestrator(summary_job_queue=queue)
    out = orch.run(_req(Task.TRANSLATE, abstract="An abstract about BERT."), _ctx()).to_dict()
    assert out["status"] == "ok"
    assert queue.calls == []


# --- summary/translation input path: stale doc-model heal + generation-keyed cache (BR-30) ----
# The rich-view doc_model() path self-heals a servable-but-stale doc-model; the summary/translation
# input path (SourceSelector) must do the same (enqueue the heal for a user who only summarizes).
# The derived result IS cached — but under the ACTUAL doc generation's key, so it is async-safe (the
# cache write is the worker→poll handoff) yet a healed request keys elsewhere and never serves stale
# output. (Earlier the write was skipped for stale docs, which silently broke async job delivery.)

from docsuri_shared.docmodel_contract import DOCMODEL_PARSER_VERSION  # noqa: E402
from docsuri_shared.dtos import DocModel  # noqa: E402

from summarization.domain.models import Scope  # noqa: E402


def _grounding_doc(parser_version: str) -> DocModel:
    # Body carries the valid_draft() anchor span so a summary grounds and reaches the cache write.
    return DocModel.model_validate(
        {
            "meta": {
                "paperId": "2401.1",
                "version": 1,
                "title": "Sample",
                "provenance": {
                    "sourceTier": "ar5iv",
                    "parserVersion": parser_version,
                    "schemaVersion": "1.1.0",
                    "generatedAt": "1970-01-01T00:00:00Z",
                },
            },
            "fullText": "5.2 Results\n\nOur model achieves 95.3% accuracy on ImageNet.",
            "sections": [
                {
                    "id": "s1",
                    "title": "5.2 Results",
                    "blocks": [
                        {
                            "id": "s1.p1",
                            "type": "paragraph",
                            "text": "Our model achieves 95.3% accuracy on ImageNet.",
                        }
                    ],
                }
            ],
        }
    )


class _DocReader:
    def __init__(self, doc: DocModel) -> None:
        self._doc = doc

    def get_doc_model(self, paper_id: str, version: int) -> DocModel | None:
        return self._doc


class _SpyBuildQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def enqueue_build(self, paper_id: str, version: int) -> None:
        self.calls.append((paper_id, version))


def test_summary_from_fresh_docmodel_caches_and_no_heal() -> None:
    store = StubStore()
    queue = _SpyBuildQueue()
    orch = make_orchestrator(
        store=store,
        source_doc_model_reader=_DocReader(_grounding_doc(DOCMODEL_PARSER_VERSION)),
        doc_model_build_queue=queue,
    )
    result = orch.run(_req(), _ctx())
    assert result.to_dict()["status"] == "ok"
    assert store.puts == 1  # current-parser doc → result cached
    assert queue.calls == []  # already current → no heal enqueue


def test_summary_from_stale_docmodel_heals_and_caches_under_own_generation() -> None:
    store = StubStore()
    queue = _SpyBuildQueue()
    orch = make_orchestrator(
        store=store,
        source_doc_model_reader=_DocReader(_grounding_doc("docmodel-parser@2")),
        doc_model_build_queue=queue,
    )
    result = orch.run(_req(), _ctx())
    assert result.to_dict()["status"] == "ok"  # stale doc served for this response
    assert store.puts == 1  # cached under the stale doc's OWN generation key (async-safe)
    (path,) = list(store.data)
    assert "_d2." in path  # keyed on the ACTUAL (@2) generation, not the current one
    assert queue.calls == [("2401.1", 1)]  # background rebuild still enqueued to heal


def test_translate_from_stale_docmodel_heals_and_caches_under_own_generation() -> None:
    store = StubStore()
    queue = _SpyBuildQueue()
    orch = make_orchestrator(
        store=store,
        source_doc_model_reader=_DocReader(_grounding_doc("docmodel-parser@2")),
        doc_model_build_queue=queue,
    )
    # Translate must be scope=full to consume the structured doc-model (abstract scope never does).
    request = SummaryRequest(paper_id="2401.1", version=1, task=Task.TRANSLATE, scope=Scope.FULL)
    result = orch.run(request, _ctx(), allow_enqueue=False)
    assert result.to_dict()["status"] == "ok"
    assert store.puts == 1  # translate base cached under the @2 key
    (path,) = list(store.data)
    assert "_d2." in path
    assert queue.calls == [("2401.1", 1)]


def test_stale_docmodel_result_deliverable_via_cache_no_reenqueue_loop() -> None:
    # Regression for the 2308.08469 async pending loop: a stale doc's worker-written result must be
    # found on a later request via the actual-generation key (the poll re-check), so async delivery
    # completes instead of re-enqueuing forever. Skipping the write (the old behavior) broke this.
    store = StubStore()
    orch = make_orchestrator(
        store=store,
        source_doc_model_reader=_DocReader(_grounding_doc("docmodel-parser@2")),
    )
    orch.run(_req(), _ctx(), allow_enqueue=False)  # worker writes under the @2 key
    assert store.puts == 1
    second = orch.run(_req(), _ctx()).to_dict()  # poll finds it via the actual-generation re-check
    assert second["cached"] is True
    assert store.puts == 1  # no regeneration → loop broken


def test_healed_docmodel_does_not_serve_stale_generation_cache() -> None:
    # Correctness (the original #337 concern preserved): output cached from a stale (@2) doc must
    # NOT be served once the doc heals to the current parser — the keys differ by generation.
    store = StubStore()
    make_orchestrator(
        store=store, source_doc_model_reader=_DocReader(_grounding_doc("docmodel-parser@2"))
    ).run(_req(), _ctx(), allow_enqueue=False)  # cache the @2-derived result
    assert store.puts == 1
    healed = make_orchestrator(
        store=store, source_doc_model_reader=_DocReader(_grounding_doc(DOCMODEL_PARSER_VERSION))
    ).run(_req(), _ctx()).to_dict()
    assert healed["cached"] is False  # healed key misses the @2 entry → regenerated, not stale


def test_stale_heal_enqueue_is_best_effort_when_no_queue() -> None:
    # No build queue wired → no heal enqueue; the stale-derived result is still cached (async-safe)
    # under its own generation key.
    store = StubStore()
    orch = make_orchestrator(
        store=store,
        source_doc_model_reader=_DocReader(_grounding_doc("docmodel-parser@2")),
    )
    result = orch.run(_req(), _ctx())
    assert result.to_dict()["status"] == "ok"
    assert store.puts == 1


def test_legacy_cached_object_without_docmodel_segment_is_not_served() -> None:
    # Reviewer's backlog scenario: a summary cached BEFORE the parser dimension existed lives at a
    # path with no ``_dN`` segment. Once the key carries the current parser generation, that legacy
    # object is never looked up → miss → regenerate. This heals results derived from a
    # since-superseded doc-model even though they were already stored (blocking new writes alone
    # cannot). Belt-and-suspenders with the write-skip: existing objects self-invalidate by path.
    store = StubStore()
    orch = make_orchestrator(
        store=store,
        source_doc_model_reader=_DocReader(_grounding_doc(DOCMODEL_PARSER_VERSION)),
    )
    # Cache the object the normal way, then relocate it to its pre-migration (no-segment) path.
    orch.run(_req(), _ctx())
    (current_path,) = list(store.data)
    gen = DOCMODEL_PARSER_VERSION.rpartition("@")[2]
    legacy_path = current_path.replace(f"_d{gen}.json", ".json")
    assert legacy_path != current_path  # sanity: the segment is actually present
    store.data.clear()
    store.data[legacy_path] = {"status": "ok", "marker": "STALE_LEGACY"}

    result = orch.run(_req(), _ctx()).to_dict()
    assert result.get("marker") != "STALE_LEGACY"  # legacy object was not served
    assert result["cached"] is False  # miss → regenerated under the segmented path
