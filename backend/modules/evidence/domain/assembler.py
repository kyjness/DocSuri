"""결과 조립(BLM §5) — 결정론. LLM을 타지 않는다.

같은 입력이면 같은 출력이어야 회귀 픽스처와 PBT가 성립한다. 여기서 하는 일은
누적 근거를 논문 간 비교형으로 재편하고(BR-EV-5), 확인 범위를 싣는 것뿐이다.

**확인 범위가 새로 생긴 부분이다.** 탐색이 완결되지 않았어도 검증된 근거가 있으면
성공으로 반환하되, 몇 편 중 몇 편까지 봤는지와 왜 멈췄는지를 결과에 싣는다
(BR-EV-15). 터미널 상태를 늘리지 않는 이유는 D5 union을 바꾸면 U12·FE 분기가
함께 늘기 때문이다 — 저하는 상태가 아니라 필드로 표현한다.
"""

from __future__ import annotations

from docsuri_shared._generated.dtos.evidence_schema import (
    AbstainReason,
    AnswerChecks,
    AnswerSegment,
    AnswerSegmentKind,
    EvidenceAbstainResult,
    EvidenceAnswer,
    EvidenceCoverage,
    EvidenceResult,
    StoppedReason,
)

from .models import LoopState, TerminationReason

__all__ = [
    "ABSTAIN_CANCELLED",
    "ABSTAIN_INSUFFICIENT",
    "ABSTAIN_LLM_FAILURE",
    "ABSTAIN_OUT_OF_CORPUS",
    "assemble",
    "comparison_order",
    "fallback_answer",
]

# 비기술 사유만(SEC-9, INV-EV-5). 내부 상태·예외 상세는 절대 싣지 않는다.
# **어휘의 정본은 스키마의 `AbstainReason`이다** — 여기서 문자열을 새로 적으면 화면
# 라벨 맵과 조용히 갈린다(2026-08-24에 실제로 갈렸다).
ABSTAIN_OUT_OF_CORPUS = AbstainReason.out_of_corpus
ABSTAIN_INSUFFICIENT = AbstainReason.insufficient_evidence
ABSTAIN_LLM_FAILURE = AbstainReason.llm_unavailable
ABSTAIN_CANCELLED = AbstainReason.cancelled

_STOPPED_BY_REASON = {
    TerminationReason.SUFFICIENT: StoppedReason.sufficient,
    TerminationReason.BUDGET_EXHAUSTED: StoppedReason.budget_exhausted,
    TerminationReason.FATAL_ERROR: StoppedReason.partial_failure,
    TerminationReason.CANCELLED: StoppedReason.cancelled,
    # 실행자가 멈춘 것은 사용자 취소가 아니다 — 화면에는 "탐색이 중단됐다"로만 보인다.
    TerminationReason.INTERRUPTED: StoppedReason.partial_failure,
}


def assemble(
    state: LoopState, reason: TerminationReason, *, query_used: str | None = None
) -> EvidenceResult | EvidenceAbstainResult:
    items = state.accumulator.items

    if not items:
        # 빈 성공 금지(INV-EV-2). 후보조차 못 찾았으면 코퍼스 밖, 찾았는데 근거를
        # 못 뽑았으면 근거 부족 — 사용자에게 다른 행동을 시사하는 구분이다.
        if reason is TerminationReason.FATAL_ERROR:
            return EvidenceAbstainResult(state="abstain", abstainReason=ABSTAIN_LLM_FAILURE)
        if reason is TerminationReason.CANCELLED:
            # 근거를 찾기 전에 취소했다 — "근거 부족"으로 읽히면 다음 행동을 잘못 고른다.
            return EvidenceAbstainResult(state="abstain", abstainReason=ABSTAIN_CANCELLED)
        reason_code = (
            ABSTAIN_OUT_OF_CORPUS if state.candidates == 0 else ABSTAIN_INSUFFICIENT
        )
        return EvidenceAbstainResult(state="abstain", abstainReason=reason_code)

    coverage = EvidenceCoverage(
        paperCount=len(state.accumulator.cited_paper_ids),
        queryUsed=query_used,
        examined=state.examined,
        candidates=state.candidates,
        stoppedReason=_STOPPED_BY_REASON.get(reason, StoppedReason.partial_failure),
    )
    ordered = comparison_order(items)
    # `answer` 노드가 만든 판단이 있으면 그것이 답이다. 없으면(노드가 안 도는 경로 —
    # 판단 포트 미구성, 검사 전면 거부) 결정론 이어붙이기로 떨어진다: 답은 나가되
    # 판단 없이. 검사를 못 통과한 판단은 화면에 가지 않는다(§4.3, C-2 fail-closed).
    return EvidenceResult(
        state="ok",
        claims=ordered,
        coverage=coverage,
        answer=state.answer or fallback_answer(ordered),
    )


def comparison_order(items: list) -> list:
    """논문 간 비교형 — 상충이 있는 명제를 먼저 둔다(쟁점 오버레이의 데이터 기반).

    **판단 층도 이 순서를 쓴다.** `[n]`은 이 순서의 1-기반 번호이고 근거표 행 번호와 같은
    출처다 — 두 곳이 다른 순서를 쓰면 번호가 다른 행을 가리킨다(§4.2).

    단순 나열 금지(BR-EV-5)의 최소 구현이다. 정렬은 안정적이어야 하므로 원래
    순서를 보조 키로 유지한다.
    """
    # 안정 분할 — 각 그룹 안에서는 원래 순서를 지킨다.
    contested = [item for item in items if item.conflicting]
    rest = [item for item in items if not item.conflicting]
    return contested + rest


# 이름을 나열하는 상한 — 근거 논문이 많을 때 문장이 목록으로 변하는 것을 막는다.
_MAX_NAMED_PAPERS = 3


def fallback_answer(
    items: list, *, regenerated: bool = False
) -> EvidenceAnswer | None:
    """판단 없는 답 — claims만으로 조립하는 결정론 이어붙이기(v1 `_narrative` 승계).

    문장은 전부 `synthesis`다. 근거에서 뽑은 문장이지만 **판단 층 검사를 지나지 않았으므로**
    "기계가 확인함" 표시를 줄 수 없다 — 표시의 뜻이 §4.3 검사 통과라서, 여기에 cited를
    붙이면 화면에서 두 종류가 구분되지 않는다.

    C-2의 금지는 **새 사실**이지 요약 표현이 아니다 — 이미 게이트를 통과한 statement와
    paperId만 문장으로 잇는다. LLM을 타지 않으므로 결정론이다.
    """
    sentences = _narrative_sentences(items)
    if not sentences:
        return None
    return EvidenceAnswer(
        segments=[
            AnswerSegment(text=text, refs=[], kind=AnswerSegmentKind.synthesis)
            for text in sentences
        ],
        checks=AnswerChecks(demoted=0, regenerated=regenerated, fallback=True),
    )


def _narrative_sentences(items: list) -> list[str]:
    sentences: list[str] = []
    for item in items:
        sentence = item.statement.rstrip(".。 ")
        supporting = _distinct(item.supporting)
        if supporting:
            sentence += f" ({_listing(supporting)}에서 확인됨)"
        conflicting = _distinct(item.conflicting)
        if conflicting:
            sentence += f". 다만 {_listing(conflicting)}는 다른 결과를 보고합니다"
        sentences.append(sentence + ".")
    return sentences


def _distinct(refs) -> list[str]:
    seen: dict[str, None] = {}
    for ref in refs:
        if ref.paperId:
            seen.setdefault(ref.paperId, None)
    return list(seen)


def _listing(paper_ids: list[str]) -> str:
    listing = ", ".join(paper_ids[:_MAX_NAMED_PAPERS])
    remainder = len(paper_ids) - _MAX_NAMED_PAPERS
    return f"{listing} 외 {remainder}편" if remainder > 0 else listing
