"""루프 도메인 엔티티(domain-entities.md §2~§4) — 저장·전송 계약이 아니라 실행 상태.

v1의 `PaperSearchResult`(단발 검색 묶음)·`EvidenceExtractInput`(일괄 추출 입력)은
루프 구조에서 의미를 잃어 승계하지 않는다. 대신 확보 논문을 출처·범위와 함께
표현하는 `PaperHandle`과, 게이트 통과분만 담는 `EvidenceAccumulator`를 둔다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import EvidenceItem, SourceScope

from .gate import GateOutcome, PaperEvidenceSource
from .projection import iter_blocks, normalize, paper_projection

__all__ = [
    "AgentRunContext",
    "BudgetConsumed",
    "EvidenceAccumulator",
    "LoopBudget",
    "LoopState",
    "PaperHandle",
    "PaperOrigin",
    "PromotionOutcome",
    "TerminationReason",
    "ToolCallOutcome",
    "ToolCallRecord",
    "utc_now",
]


def utc_now() -> datetime:
    return datetime.now(UTC)


class PaperOrigin(StrEnum):
    CORPUS = "corpus"
    EXTERNAL = "external"
    ATTACHMENT = "attachment"


class PromotionOutcome(StrEnum):
    """`fetch_paper` 결과. 실패도 **정상 결과값**이다 — 루프를 깨지 않는다."""

    PROMOTED = "promoted"
    LICENSE_BLOCKED = "license_blocked"
    PARSE_FAILED = "parse_failed"
    TIMED_OUT = "timed_out"


class TerminationReason(StrEnum):
    SUFFICIENT = "sufficient"
    BUDGET_EXHAUSTED = "budget_exhausted"
    NO_EVIDENCE = "no_evidence"
    FATAL_ERROR = "fatal_error"


class ToolCallOutcome(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    ERROR = "error"
    BUDGET_DENIED = "budget_denied"


@dataclass(slots=True)
class PaperHandle:
    """확보한 논문 1편 — 출처와 **근거 범위**를 한 몸에 담는다.

    `scope`는 선언이 아니라 사실이다: DocModel을 확보했으면 `fulltext`, 초록만
    있으면 `abstract`. 게이트가 이 값을 권위로 삼아 모델의 범위 선언을 강등한다.
    """

    paper_id: str
    record_ref: str
    origin: PaperOrigin
    title: str = ""
    doc_model: Any | None = None
    abstract_text: str = ""

    @property
    def scope(self) -> str:
        return (
            SourceScope.fulltext.value
            if self.doc_model is not None
            else SourceScope.abstract.value
        )

    def as_source(self) -> PaperEvidenceSource:
        """게이트가 대조할 형태로. 투영은 `projection` 단일 지점에서만 나온다."""
        if self.doc_model is None:
            return PaperEvidenceSource(
                paper_id=self.paper_id,
                record_ref=self.record_ref,
                scope=SourceScope.abstract.value,
                text=normalize(self.abstract_text),
            )
        return PaperEvidenceSource(
            paper_id=self.paper_id,
            record_ref=self.record_ref,
            scope=SourceScope.fulltext.value,
            text=paper_projection(self.doc_model),
            blocks={bid: (kind, text) for bid, kind, text in iter_blocks(self.doc_model)},
        )


@dataclass(slots=True)
class BudgetConsumed:
    iterations: int = 0
    tool_calls_total: int = 0
    tool_calls: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0


@dataclass(slots=True)
class LoopBudget:
    """3중 한도(FR-45, BR-EV-13). 수치는 설정에서 주입되며 도메인은 상수를 갖지 않는다.

    비용 판정의 단일 권위는 U6 `get_budget_state()`이고 `token_cost_limit_usd`는
    그 배분 안의 per-turn 상한이다 — U11 전용 CostGuard를 만들지 않는다.
    """

    max_iterations: int
    max_tool_calls_total: int
    max_tool_calls: dict[str, int]
    token_cost_limit_usd: float
    consumed: BudgetConsumed = field(default_factory=BudgetConsumed)


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """결정 트레이스 1건(FR-46, BR-EV-16) — 진행 활동 피드의 유일한 원천."""

    seq: int
    tool: str
    args_summary: str
    outcome: ToolCallOutcome
    result_summary: str = ""
    cost_usd: float | None = None
    at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class EvidenceAccumulator:
    """게이트 통과분만 쌓인다(INV-EV-6). 루프의 종료 판단 입력이다."""

    items: list[EvidenceItem] = field(default_factory=list)
    rejections: Counter[str] = field(default_factory=Counter)

    def absorb(self, outcome: GateOutcome) -> int:
        self.items.extend(outcome.items)
        self.rejections.update(outcome.rejections)
        return len(outcome.items)

    @property
    def cited_paper_ids(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for item in self.items:
            for ref in (*item.supporting, *item.conflicting):
                seen.setdefault(ref.paperId, None)
        return tuple(seen)

    @property
    def has_conflicts(self) -> bool:
        return any(item.conflicting for item in self.items)


@dataclass(slots=True)
class LoopState:
    """한 턴의 루프 실행 상태."""

    topic: str
    # 검색으로 **발견**한 논문(제목·초록만) — 아직 확인 대상이 아니다.
    discovered: dict[str, PaperHandle] = field(default_factory=dict)
    # 에이전트가 실제로 **확인**한 논문(본문을 확보했거나 근거 추출 대상으로 삼은 것).
    papers: dict[str, PaperHandle] = field(default_factory=dict)
    accumulator: EvidenceAccumulator = field(default_factory=EvidenceAccumulator)
    trace: list[ToolCallRecord] = field(default_factory=list)
    recent_results: list[Any] = field(default_factory=list)
    candidates_seen: set[str] = field(default_factory=set)
    termination_reason: TerminationReason | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def examined(self) -> int:
        """실제로 확보(열람)한 논문 수 — 후보 중 몇 편까지 갔는지의 분자."""
        return len(self.papers)

    @property
    def candidates(self) -> int:
        """탐색 중 발견한 후보 수. 확인분을 포함한다."""
        return len(self.candidates_seen | set(self.papers) | set(self.discovered))

    def handle(self, paper_id: str) -> PaperHandle | None:
        """확인분 우선 — 같은 논문이 양쪽에 있으면 본문을 가진 쪽이 권위다."""
        return self.papers.get(paper_id) or self.discovered.get(paper_id)

    def examine(self, handle: PaperHandle) -> PaperHandle:
        """발견 → 확인으로 승격. 근거 추출·본문 열람의 대상이 된다."""
        self.discovered.pop(handle.paper_id, None)
        self.papers[handle.paper_id] = handle
        return handle

    def sources(self) -> dict[str, PaperEvidenceSource]:
        return {pid: handle.as_source() for pid, handle in self.papers.items()}


@dataclass(slots=True)
class AgentRunContext:
    """루프 실행 문맥(SEC-8 owner-scoped)."""

    owner_id: str
    session_id: str
    turn_id: str
    request_id: str = ""
    prior_topics: tuple[str, ...] = ()
    prior_paper_ids: tuple[str, ...] = ()
