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
    EvidenceAbstainResult,
    EvidenceCoverage,
    EvidenceResult,
    StoppedReason,
)

from .models import LoopState, TerminationReason

__all__ = ["ABSTAIN_INSUFFICIENT", "ABSTAIN_LLM_FAILURE", "ABSTAIN_OUT_OF_CORPUS", "assemble"]

# 비기술 사유만(SEC-9, INV-EV-5). 내부 상태·예외 상세는 절대 싣지 않는다.
ABSTAIN_OUT_OF_CORPUS = "out_of_corpus"
ABSTAIN_INSUFFICIENT = "insufficient_evidence"
ABSTAIN_LLM_FAILURE = "llm_unavailable"

_STOPPED_BY_REASON = {
    TerminationReason.SUFFICIENT: StoppedReason.sufficient,
    TerminationReason.BUDGET_EXHAUSTED: StoppedReason.budget_exhausted,
    TerminationReason.FATAL_ERROR: StoppedReason.partial_failure,
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
    ordered = _comparison_order(items)
    return EvidenceResult(
        state="ok",
        claims=ordered,
        coverage=coverage,
        answer=_narrative(ordered),
    )


def _comparison_order(items: list) -> list:
    """논문 간 비교형 — 상충이 있는 명제를 먼저 둔다(쟁점 오버레이의 데이터 기반).

    단순 나열 금지(BR-EV-5)의 최소 구현이다. 정렬은 안정적이어야 하므로 원래
    순서를 보조 키로 유지한다.
    """
    # 안정 분할 — 각 그룹 안에서는 원래 순서를 지킨다.
    contested = [item for item in items if item.conflicting]
    rest = [item for item in items if not item.conflicting]
    return contested + rest


# 이름을 나열하는 상한 — 근거 논문이 많을 때 문장이 목록으로 변하는 것을 막는다.
_MAX_NAMED_PAPERS = 3


def _narrative(items: list) -> str | None:
    """claims만으로 조립하는 대화체 요약(v1 승계).

    C-2의 금지는 **새 사실**이지 요약 표현이 아니다 — 이미 게이트를 통과한
    statement와 paperId만 문장으로 잇는다. LLM을 타지 않으므로 결정론이다.
    """
    if not items:
        return None
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
    return " ".join(sentences)


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
