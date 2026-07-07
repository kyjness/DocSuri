"""Internal U2 domain entities (domain-entities.md §2-4).

These are U2-internal shapes — distinct from the external ``docsuri_shared.dtos`` contract.
External DTOs (SearchResponse/ResultCardVM/...) and IndexRecord come from ``docsuri_shared``;
only these intermediate pipeline shapes live here. Internal fields (retrieval_score) are
NEVER projected onto a card (SEC-9 / INV-2) — see ``assembler.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

from docsuri_shared.vector_spec import IndexRecord


class DegradeMode(StrEnum):
    """U2 degradation state (business-rules.md BR-11 / Q6=A).

    Distinct from the external ``docsuri_shared.dtos.DegradationMode`` (a wire value);
    ``assembler.py`` maps NORMAL→success page and RERANK_OFF/LEXICAL_ONLY→degraded.
    """

    NORMAL = "normal"
    RERANK_OFF = "rerank-off"
    LEXICAL_ONLY = "lexical-only"


class RetrievalMode(StrEnum):
    HYBRID = "hybrid"
    LEXICAL_ONLY = "lexical-only"


class SearchScope(StrEnum):
    """Retrieval breadth requested by the caller (distinct from ``RetrievalMode``, which is the
    degradation state). ``LITE`` is the human search box (BM25 over title+abstract; k-NN
    restricted to abstract chunks — one vector/paper, P50<3s); ``FULL`` is hybrid over the
    full-body chunk index for the agent / opt-in toggle.
    Maps from the external ``docsuri_shared.dtos.Scope`` at the orchestrator boundary."""

    LITE = "lite"
    FULL = "full"


@dataclass(frozen=True, slots=True)
class AuthSession:
    """Authenticated principal injected by the U6 gateway (SEC-8; BR-13). U2 trusts it."""

    user_id: str


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Per-request context the gateway injects (component-methods U2 RequestContext)."""

    auth_session: AuthSession
    request_id: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """QueryValidator.validate output (FR-1/SEC-5)."""

    ok: bool
    reason: str | None = None
    field: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedQuery:
    """Deterministic normalized query (NFC; PBT-02)."""

    text: str


@dataclass(frozen=True, slots=True)
class DegradationSignal:
    """Derived from CostGuardCircuitBreaker.get_budget_state (BR-11/12)."""

    llm_enabled: bool
    rerank_enabled: bool


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """Expander output (BR-3 / Q1=A). embedding_vector is None in lexical-only mode.

    ``scope`` carries the caller's requested breadth (lite/full); the retriever uses it to gate
    k-NN and to pick the BM25 field set. It is independent of ``mode`` (degradation): a FULL
    request still degrades to lexical-only when embedding is unavailable."""

    lexical_terms: tuple[str, ...]
    mode: RetrievalMode
    embedding_vector: tuple[float, ...] | None = None
    scope: SearchScope = SearchScope.LITE


@dataclass(frozen=True, slots=True)
class Candidate:
    """A retrieved candidate bound to a real IndexRecord (FR-5 premise).

    ``retrieval_score`` is INTERNAL (RRF/merge score) — never exposed on a card (SEC-9).

    ``ranking_score`` is the SINGLE sort key the ranker reads (BR-5): score-*supplying* stages
    are decoupled from the score-*sorting* stage. Retrieval seeds it to ``retrieval_score``; a
    reranker (or a future personalization stage) overwrites it via ``with_ranking_score`` — the
    ranker never learns which stage set it, it only sorts by ``ranking_score``. Left None at
    construction → seeded to ``retrieval_score`` in ``__post_init__`` (so a plain
    ``Candidate(record, retrieval_score)`` is baseline-ordered and existing call sites are
    unaffected); always a float afterwards.
    """

    record: IndexRecord
    retrieval_score: float
    ranking_score: float | None = field(default=None)

    def __post_init__(self) -> None:
        # Seed the sort key from retrieval when a supplying stage did not set it (frozen: bypass).
        if self.ranking_score is None:
            object.__setattr__(self, "ranking_score", self.retrieval_score)

    def with_ranking_score(self, score: float) -> Candidate:
        """Frozen copy with a new sort key — the reranker/personalization *supply* stage."""
        return replace(self, ranking_score=score)


@dataclass(frozen=True, slots=True)
class CandidateSet:
    """HybridRetriever output: PaperId-deduped candidates (BR-4; PBT-07)."""

    candidates: tuple[Candidate, ...]
    retrieval_mode: RetrievalMode


@dataclass(frozen=True, slots=True)
class RankedResults:
    """RelevanceRanker output: baseline score-desc, top-N (BR-5; PBT-03)."""

    ranked: tuple[Candidate, ...]
    ranking_mode: str = "baseline"


@dataclass(frozen=True, slots=True)
class GroundedResults:
    """map_decision(verdict=pass) output → assembler (BR-8)."""

    items: tuple[Candidate, ...]


@dataclass(frozen=True, slots=True)
class AbstainResult:
    """map_decision(verdict=abstain|block) output — a grounding *refusal* (BR-8). NOT used for
    a no-match: an empty retrieval is a NoMatchResult (explicit empty page), not an abstain."""

    reason: str


@dataclass(frozen=True, slots=True)
class NoMatchResult:
    """Genuine zero-result outcome — retrieval (or a grounding pass that filtered out every
    candidate) left nothing to show, but the request was NOT refused. Assembled as an explicit
    empty page (resultCount=0), distinct from AbstainResult (BR-9 / U5 B3-a: 기권 ≠ 빈 결과)."""


@dataclass(frozen=True, slots=True)
class GroundingInput:
    """GroundingAdapter.to_grounding_input output → U6 enforce (ports.md §2).

    ``candidate_response`` is the U2 ranked candidates (CandidateResponse=Any);
    ``retrieved_records`` is the real IndexRecord set grounding is verified against.
    """

    candidate_response: RankedResults
    retrieved_records: tuple[IndexRecord, ...]
