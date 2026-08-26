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

from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceAnswer,
    EvidenceItem,
    SourceRef,
    SourceScope,
)

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
    "iter_refs",
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
    # 사용자가 취소했다 — 그 시점까지의 근거로 부분 답을 만든다(v3 §2.8).
    CANCELLED = "cancelled"
    # 실행자가 멈췄다(종료 신호·고아 마감) — 사용자 취소가 아니므로 따로 센다.
    INTERRUPTED = "interrupted"


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

    `fulltext_available`은 스냅샷 복원용이다 — 체크포인트는 DocModel 객체를 싣지 않으므로
    복원된 핸들은 `doc_model=None`이지만 "본문을 확보했었다"는 사실(확인 범위·근거 범위)은
    남아야 한다. 살아 있는 핸들에서는 `doc_model`이 권위다.
    """

    paper_id: str
    record_ref: str
    origin: PaperOrigin
    title: str = ""
    doc_model: Any | None = None
    abstract_text: str = ""
    fulltext_available: bool = False
    # 투영 캐시 — doc_model은 확보 후 불변이라 무효화가 필요 없다. 캐시가 없으면
    # extract·read_paper·프롬프트 렌더가 같은 문서를 턴당 수십 번 재투영한다
    # (전 블록 정규식 + 표 행 join이 매번 다시 돈다).
    _blocks_cache: list[tuple[str, str, str]] | None = None
    _source_cache: PaperEvidenceSource | None = None

    @property
    def has_fulltext(self) -> bool:
        """본문을 확보했는가 — 살아 있는 핸들은 `doc_model`이, 복원된 핸들은 플래그가 근거다.

        판정을 여기 하나로 모은다. 두 곳에서 재유도하면 한쪽이 `or`를 빠뜨린다.
        """
        return self.doc_model is not None or self.fulltext_available

    @property
    def scope(self) -> str:
        return SourceScope.fulltext.value if self.has_fulltext else SourceScope.abstract.value

    def to_snapshot(self, *, brief: bool = False) -> dict[str, Any]:
        """`brief`는 후보(discovered)용 — 초록 본문을 싣지 않는다.

        복원된 상태의 소비자(`assemble`)는 후보를 **개수로만** 쓴다. 초록까지 실으면 스냅샷의
        절반 가까이가 후보 초록이 되고, 검색 recall에 비례해 super-step마다 다시 쓰인다.
        이어가기(설계 §3.4)의 씨앗도 id·제목이면 되고 초록은 그때 재조회하는 편이 맞다.
        """
        snapshot: dict[str, Any] = {
            "paper_id": self.paper_id,
            "record_ref": self.record_ref,
            "origin": self.origin.value,
            "title": self.title,
            "fulltext_available": self.has_fulltext,
        }
        if not brief:
            snapshot["abstract_text"] = self.abstract_text
        return snapshot

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> PaperHandle:
        return cls(
            paper_id=data["paper_id"],
            record_ref=data["record_ref"],
            origin=PaperOrigin(data["origin"]),
            title=data.get("title", ""),
            abstract_text=data.get("abstract_text", ""),
            fulltext_available=bool(data.get("fulltext_available", False)),
        )

    def blocks(self) -> list[tuple[str, str, str]]:
        """(block_id, anchor_type, projection) — 문서당 1회만 계산."""
        if self.doc_model is None:
            return []
        if self._blocks_cache is None:
            self._blocks_cache = iter_blocks(self.doc_model)
        return self._blocks_cache

    def invalidate_projections(self) -> None:
        """doc_model이 나중에 채워지는 유일한 전이(승격) 직후 호출한다."""
        self._blocks_cache = None
        self._source_cache = None

    def as_source(self) -> PaperEvidenceSource:
        """게이트가 대조할 형태로. 투영은 `projection` 단일 지점에서만 나온다."""
        if self._source_cache is not None:
            return self._source_cache
        if self.doc_model is None:
            source = PaperEvidenceSource(
                paper_id=self.paper_id,
                record_ref=self.record_ref,
                scope=SourceScope.abstract.value,
                text=normalize(self.abstract_text),
                title=self.title,
            )
        else:
            source = PaperEvidenceSource(
                paper_id=self.paper_id,
                record_ref=self.record_ref,
                scope=SourceScope.fulltext.value,
                # 전문 텍스트도 정규화형으로 만든다 — 게이트가 ref마다 전문을
                # 재정규화하지 않도록(E3) 대조는 항상 정규화형끼리 한다.
                text=normalize(paper_projection(self.doc_model)),
                blocks={bid: (kind, text) for bid, kind, text in self.blocks()},
                title=self.title,
            )
        self._source_cache = source
        return source


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
    """결정 트레이스 1건(FR-46, BR-EV-16) — 진행 활동 피드의 유일한 원천.

    `stance`는 모델이 그 호출에 붙인 탐색 방향 선언이다(§3.2·§7). **일급 필드여야 한다** —
    `args_summary`는 렌더 형식(길이 절단·구분자)이라 되파싱하면 바닥 검사가 화면 문자열에
    묶인다. 선언이 없거나 어휘 밖이면 None이다.
    """

    seq: int
    tool: str
    args_summary: str
    outcome: ToolCallOutcome
    result_summary: str = ""
    cost_usd: float | None = None
    stance: str | None = None
    at: datetime = field(default_factory=utc_now)


def iter_refs(item: EvidenceItem) -> tuple[SourceRef, ...]:
    """근거 한 건의 출처 전부 — 지지 + 상충. 순서는 지지가 먼저다.

    이 순회가 세 가지 철자로 여섯 곳에 흩어져 있었다(`list(a) + list(b)`,
    `(*a, *b)`, 두 번 도는 for). 한쪽만 상충을 빠뜨려도 조용히 덜 세는 모양이라
    이름을 하나 둔다.
    """
    return (*item.supporting, *item.conflicting)


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
            for ref in iter_refs(item):
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
    # 실시간 조회가 온전히 못 돌았는가(설계 §7). **마감이 읽으므로 스냅샷에 싣는다** —
    # 확인 범위 줄에 "실시간 조회 불가"를 실을지가 여기서 갈린다. 부분 저하도 true다:
    # 셋 중 둘이 죽은 턴과 멀쩡한 턴이 같은 화면을 내면 "그 논문이 세상에 없다"로 읽힌다.
    #
    # **소스 이름은 담지 않는다.** 유일한 소비자(마감)가 SEC-9 때문에 그것을 쓸 수 없고,
    # 모델이 보는 이름은 상태가 아니라 도구 결과에서 온다. 도메인이 못 쓰는 값을 들고 있으면
    # 언젠가 누가 그것을 렌더한다.
    live_lookup_degraded: bool = False
    termination_reason: TerminationReason | None = None
    notes: list[str] = field(default_factory=list)
    # 모델이 종료 시점에 선언한 질문 유형(§3.3). 판단 프롬프트가 읽고, PR 4의 바닥 규칙이
    # 이 값으로 반대측 탐색 조건을 면제한다.
    question_kind: str | None = None
    # `answer` 노드가 만든 판단(§4). **마감이 읽으므로 스냅샷에 싣는다** — 고아 턴은
    # 체크포인트에서 복원해 마감하는데, 여기 없으면 판단만 사라진 부분 답이 나간다.
    answer: EvidenceAnswer | None = None

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

    # -- 체크포인트 스냅샷 ----------------------------------------------------
    # 순수 JSON만 싣는다(enum은 값, set은 정렬 list, Counter는 dict). 체크포인터의 기본
    # 직렬화기가 dataclass·enum을 받기는 하지만 "미등록 타입은 막힌다"고 경고하므로
    # 그쪽 동작에 기대지 않는다.
    #
    # **싣는 것은 마감(`assemble`)이 읽는 것 + 이어가기(PR 4)의 씨앗이다.** 마감은 확인·후보
    # 논문 수와 누적 근거만 본다; trace·notes·termination_reason·rejections는 마감엔 불필요하지만
    # 작고(수 kB) 이어가기가 "무엇을 했었나"를 복원할 재료라 남긴다. DocModel·투영 캐시·이미지는
    # 직렬화가 안 되고, 도구 결과(`recent_results`)는 관찰 윈도우일 뿐 되읽는 소비자가 없다 —
    # 프리뷰만 실어도 스냅샷의 4분의 1이었다. 소모 예산(`BudgetConsumed`)도 복원처가 없어 뺐다.

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "discovered": [h.to_snapshot(brief=True) for h in self.discovered.values()],
            "papers": [h.to_snapshot() for h in self.papers.values()],
            "items": [item.model_dump(mode="json") for item in self.accumulator.items],
            "rejections": dict(self.accumulator.rejections),
            "trace": [
                {
                    "seq": r.seq,
                    "tool": r.tool,
                    "args_summary": r.args_summary,
                    "outcome": r.outcome.value,
                    "result_summary": r.result_summary,
                    "cost_usd": r.cost_usd,
                    "stance": r.stance,
                    "at": r.at.isoformat(),
                }
                for r in self.trace
            ],
            "candidates_seen": sorted(self.candidates_seen),
            "live_lookup_degraded": self.live_lookup_degraded,
            "termination_reason": (
                self.termination_reason.value if self.termination_reason else None
            ),
            "notes": list(self.notes),
            "question_kind": self.question_kind,
            "answer": self.answer.model_dump(mode="json") if self.answer else None,
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> LoopState:
        state = cls(topic=data["topic"])
        for row in data.get("discovered", []):
            handle = PaperHandle.from_snapshot(row)
            state.discovered[handle.paper_id] = handle
        for row in data.get("papers", []):
            handle = PaperHandle.from_snapshot(row)
            state.papers[handle.paper_id] = handle
        state.accumulator.items = [
            EvidenceItem.model_validate(item) for item in data.get("items", [])
        ]
        state.accumulator.rejections = Counter(data.get("rejections", {}))
        state.trace = [
            ToolCallRecord(
                seq=int(r["seq"]),
                tool=r["tool"],
                args_summary=r.get("args_summary", ""),
                outcome=ToolCallOutcome(r["outcome"]),
                result_summary=r.get("result_summary", ""),
                cost_usd=r.get("cost_usd"),
                stance=r.get("stance"),
                at=datetime.fromisoformat(r["at"]),
            )
            for r in data.get("trace", [])
        ]
        state.candidates_seen = set(data.get("candidates_seen", []))
        state.live_lookup_degraded = bool(data.get("live_lookup_degraded", False))
        reason = data.get("termination_reason")
        state.termination_reason = TerminationReason(reason) if reason else None
        state.notes = list(data.get("notes", []))
        state.question_kind = data.get("question_kind")
        answer = data.get("answer")
        state.answer = EvidenceAnswer.model_validate(answer) if answer else None
        return state


@dataclass(slots=True)
class AgentRunContext:
    """루프 실행 문맥(SEC-8 owner-scoped)."""

    owner_id: str
    session_id: str
    turn_id: str
    request_id: str = ""
    prior_topics: tuple[str, ...] = ()
    prior_paper_ids: tuple[str, ...] = ()
    # 직전 턴의 id — 이어가기 씨앗(§3.4)을 그 턴의 체크포인트에서 읽는다. 없으면(세션 첫 턴,
    # 포트 경로) 이식할 것이 없다.
    prior_turn_id: str | None = None
    # 밀려난 이전 턴들의 요약 한 단락(§3.5 토큰 예산). 세션에 저장되고 매 턴 재요약하지 않는다.
    prior_summary: str = ""
