"""SearchOrchestrationService — U2 domain orchestrator (business-logic-model.md §1).

The synchronous pipeline is SPLIT at the grounding seam so this U2 domain core NEVER calls
``enforce`` (INV-1):

  * ``plan_and_retrieve`` — validate → derive degrade → expand (embedding fallback) →
    retrieve → (no-match → empty-page terminal) → rank → shape grounding input.
  * ``finalize`` — map the U6 verdict → assemble → publish SearchExecuted (non-blocking).

The ``enforce`` call BETWEEN them is performed by the gateway seam (``discovery.api``,
standing in for the U6 gateway post-handler). Fail-fast (Q1): embedding failure → lexical
fallback (degraded); index failure → ``SearchUnavailable`` (fail-closed, INV-3).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import perf_counter

from docsuri_shared.dtos import (
    DegradedResultDTO,
    SearchRequest,
    SearchResponse,
    SearchResultPageDTO,
    ValidationErrorDTO,
)
from docsuri_shared.events import SearchExecutedEvent
from docsuri_shared.ports import CostGuardCircuitBreaker, ObservabilityHub

from ..domain.assembler import ResultAssembler
from ..domain.expander import QueryUnderstandingExpander
from ..domain.grounding_adapter import GroundingAdapter
from ..domain.models import (
    CandidateSet,
    DegradationSignal,
    DegradeMode,
    GroundingInput,
    NoMatchResult,
    RankedResults,
    RequestContext,
    SearchScope,
)
from ..domain.ranker import TOP_N, RelevanceRanker, apply_boosts
from ..domain.reranker import apply_rerank, rerank_text, rerank_width
from ..domain.retriever import HybridRetriever
from ..domain.validator import QueryValidator
from ..ports.search_ports import (
    EmbeddingUnavailable,
    EventPublisher,
    IndexUnavailable,
    RerankAdapter,
    SearchUnavailable,
)

# Generic, non-technical messages (SEC-9/SEC-15 — no internal detail).
_VALIDATION_MESSAGE = "Your search could not be processed. Please revise and try again."


@dataclass(frozen=True, slots=True)
class GroundingPending:
    """Pipeline state handed to the gateway seam for enforce + finalize (INV-1)."""

    grounding_input: GroundingInput
    ranked: RankedResults
    degrade_mode: DegradeMode
    user_id: str
    request_id: str
    query: str


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """Either an already-terminal response (validation/no-match) OR a grounding-pending state."""

    response: SearchResponse | None = None
    pending: GroundingPending | None = None


def _derive_degradation(budget) -> tuple[DegradeMode, DegradationSignal]:
    """Map the U6 advisory degrade mode to U2's signal (BR-11). U2 does not judge cost.

    ``degrade_mode`` is an opaque port value (BudgetState is PROVISIONAL): unwrap an Enum to its
    ``.value`` so a plain ``Enum`` (whose ``str()`` is ``"Class.MEMBER"``) maps the same as a
    ``StrEnum``/``str``. An unrecognized mode falls through to NORMAL (safe default — full
    functionality, no degrade banner)."""
    raw = getattr(budget, "degrade_mode", None)
    raw = getattr(raw, "value", raw)  # Enum → wire value; str/StrEnum unchanged
    mode_str = (str(raw) if raw is not None else "normal").lower().replace("_", "-")
    if mode_str == "lexical-only":
        return DegradeMode.LEXICAL_ONLY, DegradationSignal(llm_enabled=False, rerank_enabled=False)
    if mode_str == "rerank-off":
        return DegradeMode.RERANK_OFF, DegradationSignal(llm_enabled=True, rerank_enabled=False)
    return DegradeMode.NORMAL, DegradationSignal(llm_enabled=True, rerank_enabled=True)


def result_count(response: SearchResponse) -> int:
    """Card count for SearchExecuted (0 for abstain/validation). No internal fields (SEC-9)."""
    root = response.root
    if isinstance(root, (SearchResultPageDTO, DegradedResultDTO)):
        return len(root.cards)
    return 0


class SearchOrchestrationService:
    def __init__(
        self,
        *,
        validator: QueryValidator,
        expander: QueryUnderstandingExpander,
        retriever: HybridRetriever,
        ranker: RelevanceRanker,
        grounding_adapter: GroundingAdapter,
        assembler: ResultAssembler,
        cost_guard: CostGuardCircuitBreaker,
        observability: ObservabilityHub,
        event_publisher: EventPublisher,
        reranker: RerankAdapter | None = None,
        top_n: int = TOP_N,
        search_boosts: Callable[[str], dict[str, float]] | None = None,
        rerank_live: bool = False,
        no_match_knn_floor: float = 0.0,
    ) -> None:
        self._validator = validator
        self._expander = expander
        self._retriever = retriever
        self._ranker = ranker
        self._grounding_adapter = grounding_adapter
        self._assembler = assembler
        self._cost_guard = cost_guard
        self._observability = observability
        self._event_publisher = event_publisher
        # Cross-encoder reranker, optional (a ranking-QUALITY enhancement, FR-3). None = feature
        # off (baseline RRF order). When wired, still gated per-request by the cost budget.
        self._reranker = reranker
        self._top_n = top_n
        # US-P4 personalization boosts, best-effort. Default no-op; wiring patches in the real
        # provider (a per-request call into U9's read port).
        self._search_boosts = search_boosts or (lambda _user_id: {})
        # US-P4 go-live gate (#345). False = SHADOW (compute + emit the would-be re-rank, return
        # the baseline order); True = LIVE (return the reordered order). Set from
        # SEARCH_RERANK_LIVE at wiring so ops can flip live after reviewing shadow metrics — no
        # redeploy, and the metrics carry real data either way.
        self._rerank_live = rerank_live
        # US-D6 no-match relevance floor on the best RAW k-NN score. k-NN returns nearest
        # neighbors for ANY query, so without an absolute floor the "관련 논문 없음" empty page
        # is unreachable for out-of-corpus queries (QA 2026-07-10 F2). 0.0 = off (default);
        # ops sets DISCOVERY_NO_MATCH_KNN_FLOOR after calibrating against the
        # discovery.search.best_knn_score metric distribution — an uncalibrated guess would
        # false-abstain real queries, which is worse than the current false-match behavior.
        self._no_match_knn_floor = no_match_knn_floor

    def plan_and_retrieve(self, request: SearchRequest, ctx: RequestContext) -> SearchOutcome:
        validation = self._validator.validate(request.query)
        if not validation.ok:
            error = ValidationErrorDTO(field=validation.field, message=_VALIDATION_MESSAGE)
            return SearchOutcome(response=SearchResponse(error))

        normalized = self._validator.normalize(request.query)
        # Caller-requested breadth; the human search box default is lite (no k-NN, P50<3s).
        scope = SearchScope.FULL if request.scope == "full" else SearchScope.LITE
        budget = self._cost_guard.get_budget_state()  # U6 single authority (read-only)
        degrade_mode, degradation = _derive_degradation(budget)

        t_stage = perf_counter()
        try:
            plan = self._expander.expand(normalized, degradation, scope)
        except EmbeddingUnavailable:
            # Dependency fail-fast (Q1/BR-16): embedding down → lexical-only degrade. Also flip
            # ``degradation`` itself (not just the expander's copy) so the downstream rerank is
            # skipped — rerank is the SAME Bedrock provider that just failed, so attempting it
            # would only stall on the rerank timeout before failing soft (extra latency on an
            # already-degraded request).
            degrade_mode = DegradeMode.LEXICAL_ONLY
            degradation = DegradationSignal(llm_enabled=False, rerank_enabled=False)
            plan = self._expander.expand(normalized, degradation, scope)
        self._emit_stage_ms("expand", t_stage, scope)

        t_stage = perf_counter()
        try:
            candidates = self._retriever.retrieve(plan, degradation)
        except IndexUnavailable as exc:
            # No fallback for the index → fail-closed (INV-3/SEC-15).
            raise SearchUnavailable("search index unavailable") from exc
        self._emit_stage_ms("retrieve", t_stage, scope)
        if candidates.best_knn_score is not None:
            # The floor's calibration feed (US-D6): per-query best raw k-NN score. Ops reads
            # this distribution in CloudWatch to pick DISCOVERY_NO_MATCH_KNN_FLOOR.
            self._emit_guarded(
                "discovery.search.best_knn_score", candidates.best_knn_score, {"scope": scope.value}
            )

        if not candidates.candidates or self._below_no_match_floor(candidates):
            # No-match: nothing retrieved to ground against — or nothing above the semantic
            # relevance floor (US-D6: near-noise neighbors are not "관련 논문"). This is an
            # explicit empty page (resultCount=0), NOT a grounding abstain (BR-9 / U5 B3-a:
            # 기권 ≠ 빈 결과). It does not emit grounding-health — that metric tracks real
            # enforce verdicts only, so a zero-result query no longer inflates the
            # hallucination/abstain rate. Zero-result visibility comes from the SearchExecuted
            # event (resultCount=0) below. (US-R4)
            response = self._assembler.assemble(NoMatchResult(), degrade_mode)
            self._publish(ctx.auth_session.user_id, ctx.request_id, request.query, 0)
            return SearchOutcome(response=response)

        t_stage = perf_counter()
        candidates = self._maybe_rerank(normalized.text, candidates, degradation, scope)
        self._emit_stage_ms("rerank", t_stage, scope)
        ranked = self._ranker.rank(candidates, plan, degradation, self._top_n)
        ranked = self._apply_search_boosts(ctx.auth_session.user_id, ranked)
        grounding_input = self._grounding_adapter.to_grounding_input(ranked, plan)
        self._observability.emit_metric(
            "discovery.search.candidates", float(len(ranked.ranked)), {"mode": degrade_mode.value}
        )
        return SearchOutcome(
            pending=GroundingPending(
                grounding_input=grounding_input,
                ranked=ranked,
                degrade_mode=degrade_mode,
                user_id=ctx.auth_session.user_id,
                request_id=ctx.request_id,
                query=request.query,
            )
        )

    def finalize(self, pending: GroundingPending, decision) -> SearchResponse:
        """Map verdict → assemble → publish. ``decision`` came from the gateway's enforce."""
        result = self._grounding_adapter.map_decision(decision, pending.ranked)
        response = self._assembler.assemble(
            result, pending.degrade_mode, personalized=pending.ranked.personalized
        )
        self._emit_grounding_health(getattr(decision, "verdict", "unknown"))
        self._publish(pending.user_id, pending.request_id, pending.query, result_count(response))
        return response

    def _maybe_rerank(
        self,
        query: str,
        candidates: CandidateSet,
        degradation: DegradationSignal,
        scope: SearchScope,
    ) -> CandidateSet:
        """Cross-encoder rerank of the top-M fused candidates (FR-3 quality). Gated HERE (the I/O
        decision, not in the pure ranker): skipped when no reranker is wired (feature off) or the
        budget disabled it (``rerank_enabled`` False → RERANK_OFF/LEXICAL_ONLY). Any adapter
        failure is swallowed and the baseline RRF order is kept — rerank is a ranking-QUALITY
        enhancement that MUST NEVER block or degrade the response (fail-soft, BR-5). It only
        rewrites ``ranking_score`` on the head; the ranker re-sorts by that single key."""
        if self._reranker is None or not candidates.candidates:
            return candidates  # feature off, or nothing to rerank
        if not degradation.rerank_enabled:
            self._emit_rerank_metric(0.0, "budget-off", scope)
            return candidates
        width = min(rerank_width(scope), len(candidates.candidates))
        documents = [rerank_text(c.record) for c in candidates.candidates[:width]]
        try:
            scores = self._reranker.rerank(query, documents)
            reranked = apply_rerank(candidates.candidates, scores, width)
        except Exception:  # noqa: BLE001 — best-effort: keep baseline order, never block search
            self._emit_rerank_metric(0.0, "failed", scope)
            return candidates
        self._emit_rerank_metric(1.0, "applied", scope)
        return replace(candidates, candidates=reranked)

    def _below_no_match_floor(self, candidates: CandidateSet) -> bool:
        """US-D6 semantic relevance floor. True only when the floor is enabled (> 0), k-NN ran
        (``best_knn_score`` present — lexical-only degrade is never floor-gated: BM25 hits are
        term matches, not near-noise neighbors), and the query's BEST raw k-NN score is below
        it. Floor breaches are counted so ops can watch the abstain rate after enabling."""
        floor = self._no_match_knn_floor
        if floor <= 0.0 or candidates.best_knn_score is None:
            return False
        if candidates.best_knn_score >= floor:
            return False
        self._emit_guarded("discovery.search.no_match_floor", 1.0, {})
        return True

    def _emit_stage_ms(self, stage: str, started: float, scope: SearchScope) -> None:
        """Per-stage latency (QA 2026-07-10 F1): the cold-path seconds hide in expand (Bedrock
        embed), retrieve (OpenSearch cold k-NN graph load), or rerank — CloudWatch needs the
        split to tune the right budget."""
        self._emit_guarded(
            "discovery.search.stage_ms",
            (perf_counter() - started) * 1000.0,
            {"stage": stage, "scope": scope.value},
        )

    def _emit_guarded(self, name: str, value: float, dims: dict[str, str]) -> None:
        """Advisory metric emit — observability MUST NOT raise into the search path."""
        try:
            self._observability.emit_metric(name, value, dims)
        except Exception:  # noqa: BLE001
            pass

    def _emit_rerank_metric(self, value: float, status: str, scope: SearchScope) -> None:
        """Guarded rerank metric — observability is advisory and MUST NOT raise, otherwise a
        failed-rerank branch (already fail-soft) would re-raise and sink the whole search."""
        try:
            self._observability.emit_metric(
                "discovery.search.rerank", value, {"scope": scope.value, "status": status}
            )
        except Exception:  # noqa: BLE001
            pass

    def _apply_search_boosts(self, user_id: str, ranked: RankedResults) -> RankedResults:
        """US-P4 (#345): compute the bounded personalization re-rank (BR-P8, top band only) and
        emit its movement as a metric — ALWAYS. Return the reordered order only when the go-live
        gate (``_rerank_live`` ← SEARCH_RERANK_LIVE) is on; otherwise return the BASELINE order
        (SHADOW: measured, not applied). This lets ops review real shadow numbers, then flip live
        by toggling the flag — no redeploy. Best-effort (BR-P13): any failure (U9 down, no
        profile, boost/metric error) is swallowed and search proceeds on the baseline order.

        Metric names keep the ``rerank_shadow`` prefix for CloudWatch dashboard/alarm continuity.
        (ponytail: name kept for dashboard continuity; rename to ``rerank_live`` only if ops asks.)
        """
        try:
            boosts = self._search_boosts(user_id)
        except Exception:  # noqa: BLE001 — personalization never fails search
            return ranked
        if not boosts:
            return ranked
        try:
            boosted, diff = apply_boosts(ranked, boosts)
        except Exception:  # noqa: BLE001 — a boost error degrades to the baseline order, never blocks
            # apply_boosts is pure in-process compute: a raise here is a code bug, not "no boosts
            # to apply". Emit a distinct signal so the feature can't silently die into quiet
            # movement metrics (the no-op class #345 fixed). Guarded: metrics never sink search.
            try:
                self._observability.emit_metric(
                    "personalization.rerank_shadow.apply_failed", 1.0, {"scope": "search"}
                )
            except Exception:  # noqa: BLE001 — observability is advisory, must not sink search
                pass
            return ranked
        try:
            self._observability.emit_metric(
                "personalization.rerank_shadow", float(diff.positions_changed), {"scope": "search"}
            )
            self._observability.emit_metric(
                "personalization.rerank_shadow.max_shift",
                float(diff.max_shift),
                {"scope": "search"},
            )
            self._observability.emit_metric(
                "personalization.rerank_shadow.boosted_count",
                float(diff.boosted_count),
                {"scope": "search"},
            )
        except Exception:  # noqa: BLE001 — observability is advisory, must not sink search
            pass
        # Go-live gate: apply the reorder only when live; shadow measures without changing order.
        if not self._rerank_live:
            return ranked
        if diff.boosted_count > 0:
            # US-P4 (#155): mark the order as actually personalized so the response can carry
            # the optional meta.personalized flag (U5 '내 관심 주제 반영' indicator). Only set
            # when a boost really matched — live-but-untouched pages stay baseline (flag absent).
            return replace(boosted, personalized=True)
        return boosted

    def _emit_grounding_health(self, verdict: str) -> None:
        """Emit the grounding-health signal — the 'hallucination' AI-incident class (US-R4).

        ``verdict`` is one of "pass" | "block" | "abstain" (docsuri_shared.ports): a ``block``
        means the grounding gate caught a fabricated arXiv reference; ``abstain`` means the gate
        refused on no grounded evidence. Emitted ONLY for real enforce verdicts — the no-match
        path returns before the gate and is an empty page (not an abstain), so it is excluded
        and the abstain rate reflects grounding refusals only. One metric tagged by verdict so a
        CloudWatch alarm can route the block/abstain rate to the IR process.
        Must NOT raise — observability is advisory and off the response-correctness path.
        """
        try:
            self._observability.emit_metric("discovery.search.grounding", 1.0, {"verdict": verdict})
        except Exception:  # noqa: BLE001
            pass

    def _publish(self, user_id: str, request_id: str, query: str, count: int) -> None:
        """Fire-and-forget SearchExecuted (BR-14). Failure MUST NOT affect the response."""
        try:
            event = SearchExecutedEvent(
                userId=user_id,
                requestId=request_id,
                query=query,
                timestamp=datetime.now(UTC),
                resultCount=count,
            )
            self._event_publisher.publish_search_executed(event)
        except Exception:  # noqa: BLE001 — non-blocking history write (off the P50<3s path)
            pass
