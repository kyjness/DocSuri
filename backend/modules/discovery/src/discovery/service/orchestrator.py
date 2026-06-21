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

from dataclasses import dataclass
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
    DegradationSignal,
    DegradeMode,
    GroundingInput,
    NoMatchResult,
    RankedResults,
    RequestContext,
)
from ..domain.ranker import TOP_N, RelevanceRanker
from ..domain.retriever import HybridRetriever
from ..domain.validator import QueryValidator
from ..ports.search_ports import (
    EmbeddingUnavailable,
    EventPublisher,
    IndexUnavailable,
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
    query: str


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """Either an already-terminal response (validation/no-match) OR a grounding-pending state."""

    response: SearchResponse | None = None
    pending: GroundingPending | None = None


def _derive_degradation(budget) -> tuple[DegradeMode, DegradationSignal]:
    """Map the U6 advisory degrade mode to U2's signal (BR-11). U2 does not judge cost."""
    raw = getattr(budget, "degrade_mode", None)
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
        top_n: int = TOP_N,
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
        self._top_n = top_n

    def plan_and_retrieve(self, request: SearchRequest, ctx: RequestContext) -> SearchOutcome:
        validation = self._validator.validate(request.query)
        if not validation.ok:
            error = ValidationErrorDTO(field=validation.field, message=_VALIDATION_MESSAGE)
            return SearchOutcome(response=SearchResponse(error))

        normalized = self._validator.normalize(request.query)
        budget = self._cost_guard.get_budget_state()  # U6 single authority (read-only)
        degrade_mode, degradation = _derive_degradation(budget)

        try:
            plan = self._expander.expand(normalized, degradation)
        except EmbeddingUnavailable:
            # Dependency fail-fast (Q1/BR-16): embedding down → lexical-only degrade.
            degrade_mode = DegradeMode.LEXICAL_ONLY
            plan = self._expander.expand(
                normalized, DegradationSignal(llm_enabled=False, rerank_enabled=False)
            )

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
            self._publish(ctx.auth_session.user_id, request.query, 0)
            return SearchOutcome(response=response)

        ranked = self._ranker.rank(candidates, plan, degradation, self._top_n)
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
                query=request.query,
            )
        )

    def finalize(self, pending: GroundingPending, decision) -> SearchResponse:
        """Map verdict → assemble → publish. ``decision`` came from the gateway's enforce."""
        result = self._grounding_adapter.map_decision(decision, pending.ranked)
        response = self._assembler.assemble(result, pending.degrade_mode)
        self._emit_grounding_health(getattr(decision, "verdict", "unknown"))
        self._publish(pending.user_id, pending.query, result_count(response))
        return response

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
            self._observability.emit_metric(
                "discovery.search.grounding", 1.0, {"verdict": verdict}
            )
        except Exception:  # noqa: BLE001
            pass

    def _publish(self, user_id: str, query: str, count: int) -> None:
        """Fire-and-forget SearchExecuted (BR-14). Failure MUST NOT affect the response."""
        try:
            event = SearchExecutedEvent(
                userId=user_id,
                query=query,
                timestamp=datetime.now(UTC),
                resultCount=count,
            )
            self._event_publisher.publish_search_executed(event)
        except Exception:  # noqa: BLE001 — non-blocking history write (off the P50<3s path)
            pass
