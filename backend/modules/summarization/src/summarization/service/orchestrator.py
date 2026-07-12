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

import logging
from dataclasses import replace

from docsuri_shared.docmodel_contract import DOCMODEL_PARSER_VERSION
from docsuri_shared.dtos import DocModel
from docsuri_shared.ports import CostGuardCircuitBreaker, ObservabilityHub

from ..domain.assembler import ResultAssembler
from ..domain.cache_key import build_cache_key
from ..domain.glossary import GlossaryResolver, seed_cache_segment
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
    Scope,
    SourceText,
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

logger = logging.getLogger(__name__)

# Client poll backoff hint after a lazy build was (re)triggered on a miss (BR-30/D6).
_BUILD_POLL_BACKOFF_MS = 2000


def _doc_parser_version(doc: DocModel) -> str | None:
    """Parser version a served doc-model was built with (None if the shape is unexpected)."""
    meta = getattr(doc, "meta", None)
    provenance = getattr(meta, "provenance", None)
    return getattr(provenance, "parserVersion", None)


def _source_doc_parser(source: SourceText) -> str:
    """The doc-model parser generation a derived summary/translation is keyed on. A stale
    (older-parser) doc keys its output under ITS OWN generation: a later request against the healed
    (current-parser) doc keys elsewhere and misses it (key rotation) rather than serving stale
    output — and, unlike skipping the write entirely, the async job path can still deliver its
    result via the cache (the write IS the worker→poll handoff). Sources with no doc-model (abstract
    / legacy .txt) carry no parser dimension → the current generation."""
    doc = getattr(source, "doc_model", None)
    ver = _doc_parser_version(doc) if doc is not None else None
    return ver or DOCMODEL_PARSER_VERSION
# Client poll backoff hint after a long summary was enqueued as a background job (BR-S6/BR-S8).
_SUMMARY_POLL_BACKOFF_MS = 3000
# Generation above this input size is dispatched to the async job (pending → poll) instead of
# running inline: a full-paper summary is one big LLM call and a full translation is several
# output-bounded chunks — both take tens of seconds, well past the sync client/gateway budget (the
# request 504s while the backend keeps generating and caches). Small inputs (abstract source /
# abstract translate) stay inline (fast). The summary-worker (idle summary-job-queue) runs the
# dispatched job off the request path.
_ASYNC_GENERATION_MIN_TOKENS = 6_000


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
        # Both tasks key on the PROMPT-ENFORCED content signature: the derived artifact varies only
        # with terms that ride into the prompt. Post-substitution (weak) terms — today every
        # personal term — are applied as a read-time overlay on a SHARED base, so a weak-only edit
        # (or two users with different weak sets) does NOT fork the cache into an identical
        # re-generation (NFR-C1); the content signature (unlike a filtered MAX) still invalidates
        # when a prompt-enforced term is added/edited/demoted (BR-S1). Resolve once here and reuse
        # for generation below (one repo fetch); the seed segment self-invalidates on a seed edit.
        glossary = self._glossary.resolve(user_id)
        # Task-aware glossary signature (BR-S4): SUMMARY hashes ALL strong terms (prompt-enforced,
        # no masking there); TRANSLATE hashes only NON-SEED strong terms — seed standard terms are
        # masked + rendered on read, so a seed-term edit re-renders the SHARED base instead of
        # forking the cache (the Q2 win). Weak terms never fork either task (read-time overlay).
        glossary_ver = (
            GlossaryResolver.signature_of(glossary)
            if request.task == Task.SUMMARY
            else GlossaryResolver.signature_of_translate(glossary)
        )

        def _cache_key(docmodel_parser: str) -> object:
            return build_cache_key(
                request,
                glossary_ver=glossary_ver,
                model_ver=self._model_ver,
                user_id=user_id,
                seed_ver=seed_cache_segment(),
                docmodel_parser=docmodel_parser,
            )

        # Fast pre-select read on the CURRENT-parser key: a healed/hot paper hits here with zero
        # source fetch. A stale doc's output lives under its own generation's key, resolved after
        # source-select below, so this fast read misses it (correct — the fast key is @current).
        key_current = _cache_key(DOCMODEL_PARSER_VERSION)
        cached = self._store.get(key_current)
        if cached is not None:
            return self._serve_cached(cached, request, glossary)

        # 1. cost gate (U6 single authority) — BEFORE any LLM spend.
        if _is_cost_degraded(self._cost_guard.get_budget_state()):
            self._emit("u7.cost.degraded", 1.0, request)
            return CostDegradedDTO()

        # 2. source select (+ abstract fallback) — none → source unavailable.
        source = self._source.select(request)
        if source is None:
            return SourceUnavailableDTO(reason="no_full_text_or_abstract")

        # Self-heal parity with doc_model() (BR-30): the summary/translation input path also
        # consumes servable doc-models straight from the reader. If an older-parser doc was
        # selected, ALSO enqueue a background rebuild so it heals to the current parser — otherwise
        # a user who only ever summarizes/translates (never opens the rich view) would pin the stale
        # doc forever. The stale doc is still used for THIS response; its derived result is cached
        # under the stale doc's OWN generation key (below), which the healed doc's key rotates past.
        if (
            self._docmodel_build_queue is not None
            and source.doc_model is not None
            and _doc_parser_version(source.doc_model) != DOCMODEL_PARSER_VERSION
        ):
            self._docmodel_build_queue.enqueue_build(request.paper_id, request.version)

        # Key derived artifacts on the ACTUAL doc-model generation. For a healed/hot doc this equals
        # ``key_current`` (already missed above). For a stale doc it is a DISTINCT key: re-check the
        # store under it — this is where the async job path delivers, so the poll finds the worker's
        # write here (before re-enqueuing) instead of looping. Both the worker (write) and the poll
        # (read) re-run this same computation, so their keys align.
        key = _cache_key(_source_doc_parser(source))
        if key != key_current:
            cached = self._store.get(key)
            if cached is not None:
                return self._serve_cached(cached, request, glossary)

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

        # Large single-call-band generation (a full-paper summary, or a full-text translation that
        # is several output-bounded chunks) still runs tens of seconds — beyond the sync gateway
        # budget, so the request would 504 while the backend keeps generating. Dispatch it to the
        # async job (pending → client polls); the worker re-runs with allow_enqueue=False and
        # caches. Abstract-source summaries and abstract translations stay inline (fast).
        if (
            allow_enqueue
            and self._summary_job_queue is not None
            and refined.token_count > _ASYNC_GENERATION_MIN_TOKENS
            and (
                request.task == Task.SUMMARY
                or (
                    request.task == Task.TRANSLATE
                    and request.scope == Scope.FULL
                    and self._translator is not None
                )
            )
        ):
            self._summary_job_queue.enqueue(request, user_id)
            self._emit("u7.job.pending", 1.0, request)
            return PendingDTO(retry_after_ms=_SUMMARY_POLL_BACKOFF_MS)

        # 4. glossary — already resolved at step 0 (single repo fetch) and reused here.

        # 6-7. generate (buffer) → grounding validate, with ONE retry (BR-S7). On the MAP_REDUCE
        # band the summary is produced by the map-reduce summarizer (chunk→map→reduce); grounding
        # still validates the unified draft against the FULL refined body.
        if request.task == Task.TRANSLATE:
            response = self._run_translate(request, source, refined, glossary, key)
        else:
            summarizer = self._map_reduce if route == LengthRoute.MAP_REDUCE else self._llm
            response = self._run_summary(request, source, refined, glossary, key, summarizer)
        return response

    def _serve_cached(self, cached: object, request, glossary) -> _PayloadResult:
        # Shared cache-hit handler (fast pre-select read + actual-generation re-check). Translate
        # caches the shared base; apply the user's weak-term overlay + kept-term cleanup on read
        # (no-op when the user has no weak terms). Summary has no post-substitution — served as-is.
        self._emit("u7.cache.hit", 1.0, request)
        if request.task == Task.TRANSLATE:
            # Render the shared base for this viewer: restore masked standard-term tokens to their
            # effective rendering (+josa), apply weak terms, rebuild standardGlossary/keptTerms.
            cached = self._assembler.render_translation(cached, glossary)
        return _PayloadResult(cached, cached=True)

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
                # Write-through under the actual-generation ``key`` (stale docs key on their own
                # generation, so this is async-safe and never pins stale output past the heal).
                self._store.put(key, result.to_dict())
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
                    # Distinct from empty_translation: the LLM call itself failed after a retry
                    # (Bedrock circuit / repeated errors — e.g. a math-heavy batch whose raw-LaTeX
                    # JSON could not be parsed). Log it so this abstain mode is diagnosable, not
                    # only a metric — otherwise it is invisible on the API request path.
                    logger.warning(
                        "translate abstain generation_unavailable: paper=%s v=%s scope=%s",
                        request.paper_id, request.version, request.scope,
                    )
                    self._emit("u7.llm.unavailable", 1.0, request)
                    return AbstainDTO(reason="generation_unavailable")
                continue
            if not _has_translated_text(draft, doc):
                if attempt == 2:
                    # Distinct from ``generation_unavailable`` (LlmUnavailable above): here the
                    # model responded but produced no usable Korean. The translator already logged
                    # the per-chunk breakdown (returned/applied/truncated); record the terminal
                    # abstain with paper context + a metric so the two failure modes are separable.
                    logger.warning(
                        "translate abstain empty_translation: paper=%s v=%s scope=%s attempts=%d",
                        request.paper_id, request.version, request.scope, attempt,
                    )
                    self._emit("u7.translate.empty", 1.0, request)
                    return AbstainDTO(reason="empty_translation")
                continue
            # Assemble + cache the SHARED base. The base carries masked standard-term tokens; it is
            # user-agnostic (no override baked in), so every user shares it and a term edit reflects
            # by re-rendering — not by forking the cache (NFR-C1/BR-S4).
            base = self._assembler.assemble_translation(draft, source).to_dict()
            # Write-through (base) under the actual-generation ``key`` — async-safe (the write is
            # the worker→poll handoff) and never pins stale output past the heal (key rotation).
            self._store.put(key, base)
            self._emit("u7.translate.ok", 1.0, request)
            # Render for this requester (restore tokens → effective rendering, weak overlay,
            # standardGlossary/keptTerms) so the first requester also sees their own overrides.
            return _PayloadResult(self._assembler.render_translation(base, glossary))
        return AbstainDTO(reason="empty_translation")

    # --- personal glossary (Q8 / §9.1) ---------------------------------------
    def list_glossary_terms(self, user_id: str) -> list[dict]:
        """The user's saved personal terms as ``{termFrom, termTo, promptEnforced}`` (owner-scoped).
        Pre-fills the badge editor and lets it distinguish strong (프롬프트 강제) from weak (후치환)
        terms; ``glossary_ver`` and other internals stay hidden."""
        return [
            {"termFrom": m.term_from, "termTo": m.term_to, "promptEnforced": m.prompt_enforced}
            for m in self._glossary.list_user_terms(user_id)
        ]

    def upsert_glossary_term(
        self, user_id: str, term_from: str, term_to: str, *, prompt_enforced: bool = False
    ) -> int:
        """Persist a personal term override; return the bumped ``glossary_ver``.
        ``prompt_enforced`` selects strong (프롬프트 강제 → forks the owner-scoped cache) vs weak
        (후치환 → read-time overlay on the shared base, key unchanged). A strong override may
        replace a shared seed mapping for that user, taking precedence in the prompt (BR-S4)."""
        return self._glossary.upsert_term(
            user_id, term_from, term_to, prompt_enforced=prompt_enforced
        )

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
            # Serve the clean doc now. If an older parser built it, ALSO enqueue a background
            # rebuild so it heals to the current parser (BR-30 self-heal) — otherwise accepting
            # older-but-servable docs would pin them forever. The doc is still served meanwhile,
            # so there is no blank screen while the rebuild runs.
            if (
                self._docmodel_build_queue is not None
                and _doc_parser_version(doc) != DOCMODEL_PARSER_VERSION
            ):
                self._docmodel_build_queue.enqueue_build(paper_id, version)
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


class _PayloadResult:
    """Thin ``SummaryResponse`` over an already-serialized payload dict — used where the response
    is a stored/overlaid payload rather than a live DTO: a cache HIT (``cached=True``), or a fresh
    translate whose shared base was cached but whose returned view carries the read-time weak-term
    overlay (``cached=False``)."""

    __slots__ = ("_payload",)

    def __init__(self, payload: dict, *, cached: bool = False) -> None:
        self._payload = dict(payload)
        self._payload["cached"] = cached

    def to_dict(self) -> dict:
        return self._payload
