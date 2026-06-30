"""SummarizationOrchestrationService — on-demand pipeline (business-logic-model.md §2).

  cacheLookup → costGate → selectSource → refine → loadGlossary → routeLength →
  generate(buffer) → groundingValidate(1 retry) → assemble → writeThrough → emitTelemetry

Three-tier degradation kept distinct (nfr-design §1.3):
  • cost   → CostDegradedDTO  (U6 get_budget_state, single authority — never re-judged)
  • outage → AbstainDTO       (LlmUnavailable after one retry; Bedrock circuit)
  • source → abstract fallback / SourceUnavailableDTO

Streaming (Q5/BR-S8) is buffer-validate-then-render: the structured draft is validated as
a whole before exposure (no ungrounded token leaks, FR-5). Progressive client render is an
API/presentation concern; the domain returns a complete, validated result.
"""

from __future__ import annotations

from dataclasses import replace

from docsuri_shared.dtos import DocModel
from docsuri_shared.ports import CostGuardCircuitBreaker, ObservabilityHub

from ..domain.assembler import ResultAssembler
from ..domain.cache_key import build_cache_key
from ..domain.glossary import GlossaryResolver
from ..domain.grounding import GroundingValidator
from ..domain.length_router import LengthRoute, LengthRouter
from ..domain.map_reduce import MapReduceSummarizer
from ..domain.models import (
    AbstainDTO,
    AssetRef,
    CostDegradedDTO,
    DocModelLookup,
    GroundingInput,
    PendingDTO,
    RequestContext,
    SourceUnavailableDTO,
    SummaryRequest,
    SummaryResponse,
    Task,
)
from ..domain.refiner import InputRefiner
from ..domain.source_selector import SourceSelector
from ..domain.structured_translator import StructuredTranslator, iter_text_fields
from ..ports.ports import (
    AssetReadPort,
    DocModelBuildQueuePort,
    DocModelReadPort,
    LlmGatewayPort,
    LlmUnavailable,
    SummaryJobQueuePort,
    SummaryStorePort,
)

# Client poll backoff hint after a lazy build was (re)triggered on a miss (BR-30/D6).
_BUILD_POLL_BACKOFF_MS = 2000
# Client poll backoff hint after a long summary was enqueued as a background job (BR-S6/BR-S8).
_SUMMARY_POLL_BACKOFF_MS = 3000


def _is_cost_degraded(budget) -> bool:
    """Any non-normal cost degrade or an open circuit gates LLM spend (BR-S13)."""
    mode = str(getattr(budget, "degrade_mode", "normal") or "normal").lower().replace("_", "-")
    circuit = str(getattr(budget, "circuit_state", "closed") or "closed").lower()
    return mode not in ("normal", "none") or circuit == "open"


class SummarizationOrchestrationService:
    def __init__(
        self,
        *,
        store: SummaryStorePort,
        source_selector: SourceSelector,
        refiner: InputRefiner,
        glossary_resolver: GlossaryResolver,
        length_router: LengthRouter,
        llm: LlmGatewayPort,
        grounding: GroundingValidator,
        assembler: ResultAssembler,
        cost_guard: CostGuardCircuitBreaker,
        observability: ObservabilityHub,
        model_ver: str,
        asset_reader: AssetReadPort | None = None,
        doc_model_reader: DocModelReadPort | None = None,
        doc_model_build_queue: DocModelBuildQueuePort | None = None,
        map_reduce_summarizer: MapReduceSummarizer | None = None,
        summary_job_queue: SummaryJobQueuePort | None = None,
        structured_translator: StructuredTranslator | None = None,
    ) -> None:
        self._store = store
        self._source = source_selector
        self._refiner = refiner
        self._glossary = glossary_resolver
        self._length = length_router
        self._llm = llm
        self._grounding = grounding
        self._assembler = assembler
        self._cost_guard = cost_guard
        self._obs = observability
        self._model_ver = model_ver
        self._asset_reader = asset_reader
        self._docmodel_reader = doc_model_reader
        self._docmodel_build_queue = doc_model_build_queue
        # Long-input map-reduce summarizer (BR-S6). None → summary MAP_REDUCE band abstains
        # (gate OFF); wired → summary map-reduce runs. Its presence also gates the *translate*
        # long-input band (shared DOCSURI_MAP_REDUCE_ENABLED flag — one switch for both).
        self._map_reduce = map_reduce_summarizer
        # Async long-input job queue (BR-S8/BR-S12). When wired, the API path enqueues + returns
        # pending; the worker re-runs with allow_enqueue=False so the long job executes inline.
        # task-agnostic — carries summary and translate jobs alike.
        self._summary_job_queue = summary_job_queue
        # Structured (doc-model-mirroring) translator (BR-S18). Drives the translate path; chunks
        # internally for map-only long translation. None only in legacy wiring (translate then
        # abstains as generation_unavailable).
        self._translator = structured_translator

    def run(
        self, request: SummaryRequest, ctx: RequestContext, *, allow_enqueue: bool = True
    ) -> SummaryResponse:
        # ``allow_enqueue`` is True on the API request path (long summaries are dispatched to a
        # background job → pending) and False on the worker path (map-reduce runs inline there).
        user_id = ctx.auth_session.user_id

        # 0. cache lookup (read-through) — HIT ends here (LLM 0 calls, §11).
        # Summary output only varies with PROMPT-ENFORCED terms, so it keys on a content signature
        # of that subset; translate also varies with post-substitution terms, so it keys on the
        # full monotonic version. This keeps a translate-only term edit from forking the per-user
        # summary cache into an identical re-summary (NFR-C1), while the content signature (unlike a
        # filtered MAX) still invalidates when a prompt-enforced term is demoted (BR-S1).
        glossary_ver = (
            self._glossary.prompt_glossary_signature(user_id)
            if request.task == Task.SUMMARY
            else self._glossary.glossary_version(user_id)
        )
        key = build_cache_key(
            request, glossary_ver=glossary_ver, model_ver=self._model_ver, user_id=user_id
        )
        cached = self._store.get(key)
        if cached is not None:
            self._emit("u7.cache.hit", 1.0, request)
            return _CachedResult(cached)

        # 1. cost gate (U6 single authority) — BEFORE any LLM spend.
        if _is_cost_degraded(self._cost_guard.get_budget_state()):
            self._emit("u7.cost.degraded", 1.0, request)
            return CostDegradedDTO()

        # 2. source select (+ abstract fallback) — none → source unavailable.
        source = self._source.select(request)
        if source is None:
            return SourceUnavailableDTO(reason="no_full_text_or_abstract")

        # 3. refine (structure-aware; doc-model direct or legacy .txt regex — D2) → 5. length
        #    route (shape; over-cap or map-reduce → abstain).
        refined = self._refiner.refine_source(source)
        route = self._length.route(refined.token_count)
        # OVER_CAP always abstains (extreme inputs are rejected, not partial-summarized — mobile
        # decision; both tasks). MAP_REDUCE (CONTEXT_BUDGET~INPUT_CAP, ~40K-120K tok) runs the
        # long-input path: summary = section-aware map-reduce, translate = section map-only
        # (BR-S6/BR-S18). The shared DOCSURI_MAP_REDUCE_ENABLED flag gates both (proxied by
        # ``self._map_reduce``); OFF → the band abstains, preserving prior behavior.
        if route == LengthRoute.OVER_CAP:
            return AbstainDTO(reason="input_too_long")
        if route == LengthRoute.MAP_REDUCE:
            if self._map_reduce is None:
                return AbstainDTO(reason="input_too_long")
            if allow_enqueue and self._summary_job_queue is not None:
                # Async long input (BR-S8/BR-S12): enqueue a background job, return pending →
                # client polls. The worker re-runs with allow_enqueue=False so the long job
                # (summary map-reduce / translate map-only) executes inline below.
                self._summary_job_queue.enqueue(request, user_id)
                self._emit("u7.job.pending", 1.0, request)
                return PendingDTO(retry_after_ms=_SUMMARY_POLL_BACKOFF_MS)

        # 4. glossary
        glossary = self._glossary.resolve(user_id)

        # 6-7. generate (buffer) → grounding validate, with ONE retry (BR-S7). On the MAP_REDUCE
        # band the summary is produced by the map-reduce summarizer (chunk→map→reduce); grounding
        # still validates the unified draft against the FULL refined body.
        if request.task == Task.TRANSLATE:
            response = self._run_translate(request, source, refined, glossary, key)
        else:
            summarizer = self._map_reduce if route == LengthRoute.MAP_REDUCE else self._llm
            response = self._run_summary(request, source, refined, glossary, key, summarizer)
        return response

    # --- summary path --------------------------------------------------------
    def _run_summary(self, request, source, refined, glossary, key, summarizer) -> SummaryResponse:
        # ``summarizer`` is the single-call LLM gateway or the map-reduce summarizer (same
        # ``summarize(refined, request, glossary)`` contract) chosen by the length route.
        for attempt in (1, 2):
            try:
                draft = summarizer.summarize(refined, request, glossary)
            except LlmUnavailable:
                if attempt == 2:
                    self._emit("u7.llm.unavailable", 1.0, request)
                    return AbstainDTO(reason="generation_unavailable")
                continue
            verdict = self._grounding.validate(GroundingInput(draft=draft, refined=refined))
            self._emit("u7.grounding", 1.0, request, verdict=verdict.outcome)
            if verdict.ok:
                # Option D: assemble with only the verified anchors — unverifiable ones
                # (table/paraphrase/math spans) are dropped, not abstained on.
                draft = replace(draft, anchors=verdict.kept_anchors)
                result = self._assembler.assemble_summary(draft, source)
                self._store.put(key, result.to_dict())  # write-through
                self._emit("u7.summary.ok", 1.0, request)
                return result
            if attempt == 2:
                return AbstainDTO(reason="insufficient_grounding")
        return AbstainDTO(reason="insufficient_grounding")  # unreachable; satisfies type checker

    # --- translate path ------------------------------------------------------
    def _run_translate(self, request, source, refined, glossary, key) -> SummaryResponse:
        # Structured translation (BR-S18): translate the doc-model into a 'translated doc-model'
        # (same structure, Korean text). The translator chunks internally (map-only) for long
        # inputs. When the source is not a structured doc-model (scope=abstract, or full-text
        # fell back to abstract/legacy .txt), wrap the refined body in a one-paragraph doc-model
        # so the output contract is uniform.
        if self._translator is None:
            return AbstainDTO(reason="generation_unavailable")
        doc = source.doc_model or _wrap_plain_doc(refined.body, request)
        for attempt in (1, 2):
            try:
                draft = self._translator.translate(doc, request, glossary)
            except LlmUnavailable:
                if attempt == 2:
                    self._emit("u7.llm.unavailable", 1.0, request)
                    return AbstainDTO(reason="generation_unavailable")
                continue
            if not _has_translated_text(draft, doc):
                if attempt == 2:
                    return AbstainDTO(reason="empty_translation")
                continue
            result = self._assembler.assemble_translation(draft, glossary, source)
            self._store.put(key, result.to_dict())  # write-through
            self._emit("u7.translate.ok", 1.0, request)
            return result
        return AbstainDTO(reason="empty_translation")

    # --- personal glossary (Q8 / §9.1) ---------------------------------------
    def list_glossary_terms(self, user_id: str) -> list[dict]:
        """The user's saved personal terms as ``{termFrom, termTo}`` (owner-scoped). Used to
        pre-fill the badge editor; exposes only the two display fields (no internal flags)."""
        return [
            {"termFrom": m.term_from, "termTo": m.term_to}
            for m in self._glossary.list_user_terms(user_id)
        ]

    def upsert_glossary_term(self, user_id: str, term_from: str, term_to: str) -> int:
        """Persist a personal term override; return the bumped ``glossary_ver`` (Phase 1:
        simple-noun, applied to translation via post-substitution). The version bump folds
        into ``build_cache_key``, invalidating the user's cached results so the next request
        reflects the new term."""
        return self._glossary.upsert_term(user_id, term_from, term_to)

    # --- structured doc-model (BR-30, rich-view + summary input) -------------
    def doc_model(self, paper_id: str, version: int) -> DocModelLookup:
        """Read the cached structured doc-model; on a miss, (re)trigger U1's lazy build and tell
        the client to poll (BR-30/D6). Read-only — building is U1's role (boundary B: this only
        enqueues a job, never runs the builder). OA license gating is applied at the router
        (parallel to full_text/list_assets).

        Returns a :class:`DocModelLookup`: ``doc`` set on a cache hit; ``building`` True when a
        build was enqueued on a miss (a build queue is wired); otherwise empty → the router maps
        it to ``source_unavailable`` (prior behavior when no queue is configured)."""
        if self._docmodel_reader is None:
            return DocModelLookup()
        doc = self._docmodel_reader.get_doc_model(paper_id, version)
        if doc is not None:
            return DocModelLookup(doc=doc)
        if self._docmodel_build_queue is not None:
            self._docmodel_build_queue.enqueue_build(paper_id, version)
            return DocModelLookup(building=True, retry_after_ms=_BUILD_POLL_BACKOFF_MS)
        return DocModelLookup()

    # --- figure/table assets (FR-17, BR-S15) ---------------------------------
    def list_assets(self, paper_id: str, version: int) -> list[AssetRef] | None:
        """Read the paper's asset manifest and presign each object ref (SEC-9: only the
        signed URL leaves U7). None when the reader is not configured; OA license gating
        is applied at the router (parallel to full_text)."""
        if self._asset_reader is None:
            return None
        refs: list[AssetRef] = []
        for a in self._asset_reader.list_assets(paper_id, version):
            url = self._asset_reader.presign(a.object_ref)
            if url is None:
                # Non-presignable ref (not an S3 URI): skip rather than leak the raw
                # object_ref to the response (SEC-9). One bad row drops only its asset.
                continue
            refs.append(
                AssetRef(
                    asset_id=a.asset_id,
                    type=a.type,
                    ordinal=a.ordinal,
                    caption=a.caption,
                    source_mode=a.source_mode,
                    url=url,
                    page_ref=a.page_ref,
                    bbox=a.bbox,
                )
            )
        return refs

    # --- helpers -------------------------------------------------------------
    def _emit(self, name: str, value: float, request, *, verdict: str | None = None) -> None:
        """Non-blocking telemetry → U6 ObservabilityHub. MUST NOT raise (off response path)."""
        try:
            tags = {"task": str(request.task)}
            if verdict is not None:
                tags["verdict"] = verdict
            self._obs.emit_metric(name, value, tags)
        except Exception:  # noqa: BLE001, S110 — telemetry is advisory, off the response path
            pass


def _wrap_plain_doc(body: str, request: SummaryRequest) -> DocModel:
    """Wrap a plain refined body (abstract / legacy .txt fallback) in a minimal one-section,
    one-paragraph doc-model so the structured translation output contract is uniform (BR-S18).
    This synthetic doc-model is never cached as a real doc-model — ``parserVersion`` marks it."""
    return DocModel.model_validate(
        {
            "meta": {
                "paperId": request.paper_id,
                "version": request.version,
                "title": "",
                "provenance": {
                    "sourceTier": "native_html",
                    "parserVersion": "synthetic-plain-wrap",
                    "schemaVersion": "1",
                    "generatedAt": "1970-01-01T00:00:00Z",
                },
            },
            "fullText": body,
            "sections": [
                {
                    "id": "s1",
                    "title": "",
                    "blocks": [{"id": "s1.p1", "type": "paragraph", "text": body}],
                }
            ],
        }
    )


def _has_translated_text(draft, source: DocModel) -> bool:
    """True when at least one translatable field was actually translated — i.e. differs from the
    source text. A blank LLM response leaves every field falling back to the source (English), so
    checking 'non-empty' is not enough (BR-S18): we compare against the source by reading-order
    position (same structure → same field order) and require at least one real change. An
    all-unchanged draft is treated as a failed generation (fail-closed → retry, then abstain)."""
    src = [t for _id, t, _set in iter_text_fields(source.model_dump(mode="json"))]
    out = [t for _id, t, _set in iter_text_fields(draft.doc_model.model_dump(mode="json"))]
    return any(o.strip() and o != s for o, s in zip(out, src, strict=False))


class _CachedResult:
    """Thin wrapper so a cache HIT serializes the stored payload (cached=True) directly."""

    __slots__ = ("_payload",)

    def __init__(self, payload: dict) -> None:
        self._payload = dict(payload)
        self._payload["cached"] = True

    def to_dict(self) -> dict:
        return self._payload
