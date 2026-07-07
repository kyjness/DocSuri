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
from ..domain.ranker import TOP_N, RelevanceRanker, shadow_rerank_diff
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
        # provider (a per-request call into U9's read port). SHADOW: measured, not applied.
        self._search_boosts = search_boosts or (lambda _user_id: {})

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

        try:
            candidates = self._retriever.retrieve(plan, degradation)
        except IndexUnavailable as exc:
            # No fallback for the index → fail-closed (INV-3/SEC-15).
            raise SearchUnavailable("search index unavailable") from exc

        if not candidates.candidates:
            # No-match: nothing retrieved to ground against. This is an explicit empty page
            # (resultCount=0), NOT a grounding abstain (BR-9 / U5 B3-a: 기권 ≠ 빈 결과). It does
            # not emit grounding-health — that metric tracks real enforce verdicts only, so a
            # zero-result query no longer inflates the hallucination/abstain rate. Zero-result
            # visibility comes from the SearchExecuted event (resultCount=0) below. (US-R4)
            response = self._assembler.assemble(NoMatchResult(), degrade_mode)
            self._publish(ctx.auth_session.user_id, ctx.request_id, request.query, 0)
            return SearchOutcome(response=response)

        candidates = self._maybe_rerank(normalized.text, candidates, degradation, scope)
        ranked = self._ranker.rank(candidates, plan, degradation, self._top_n)
        self._emit_rerank_shadow(ctx.auth_session.user_id, ranked)
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
        response = self._assembler.assemble(result, pending.degrade_mode)
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

    def _emit_rerank_metric(self, value: float, status: str, scope: SearchScope) -> None:
        """Guarded rerank metric — observability is advisory and MUST NOT raise, otherwise a
        failed-rerank branch (already fail-soft) would re-raise and sink the whole search."""
        try:
            self._observability.emit_metric(
                "discovery.search.rerank", value, {"scope": scope.value, "status": status}
            )
        except Exception:  # noqa: BLE001
            pass

    def _emit_rerank_shadow(self, user_id: str, ranked: RankedResults) -> None:
        """SHADOW ONLY (US-P4): compute the bounded personalization re-rank that WOULD happen and
        emit it as a metric — the order returned to the user is UNCHANGED. Best-effort (BR-P13):
        any failure (U9 down, no profile) is swallowed and search proceeds on the baseline. Go
        live later by applying ``shadow_rerank_diff``'s reordering instead of just measuring it.
        """
        try:
            boosts = self._search_boosts(user_id)
        except Exception:  # noqa: BLE001 — personalization never fails search
            return
        if not boosts:
            return
        try:
            diff = shadow_rerank_diff(ranked, boosts)
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
        except Exception:  # noqa: BLE001
            pass

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
