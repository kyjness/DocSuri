"""날조 검사 게이트(C-2, INV-EV-3/INV-EV-6) — 근거가 결과로 들어가는 **유일한 관문**.

전부 문자열·집합 연산이다. LLM-judge를 쓰지 않는다(U7 grounding 게이트와 공유하는
원칙) — 같은 입력이면 같은 출력이어야 PBT와 회귀 픽스처가 성립한다.

탈락은 예외가 아니라 **정상 결과값**이다. 예외로 만들면 루프가 깨지고, 조용히
통과시키면 C-2가 깨진다. 사유는 집계만 노출하고 상세(어떤 quote가 왜)는 내부에
둔다(INV-EV-5).

범위별 검사(BLM §3):

============ ========= =========== =========================================
sourceScope  quote     anchor      대조 대상
============ ========= =========== =========================================
fulltext     필수      **필수**    전체 투영 + **그 앵커 블록의 투영**
abstract     필수      없음        취득한 초록 텍스트
figure       선택      **필수**    (인용문이 아니라 해석 — 숫자 규칙으로 검사)
============ ========= =========== =========================================

`fulltext`에서 앵커를 **필수**로 올린 것이 v1과의 차이다. v1은 앵커가 없거나
실재하지 않으면 앵커만 떼고 출처는 남겼는데, 그러면 (a) "인용문이 그 블록에서
왔는가"를 검사할 수 없고 (b) BR-EV-19의 "fulltext 출처는 반드시 앵커를 갖는다"가
깨진다(PBT-EV-8).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import (
    AnchorType,
    EvidenceItem,
    SourceRef,
    SourceScope,
)

from .projection import normalize

__all__ = [
    "MIN_QUOTE_CHARS",
    "GateOutcome",
    "PaperEvidenceSource",
    "RejectReason",
    "run_gate",
]

# 1~2토큰 인용("the", "0.9")은 우연히 어디에나 존재해 verbatim 검사를 무력화한다.
# 완전한 문장 단위는 아니지만 조각 인용을 걸러내는 최소 방어선(v1 승계).
MIN_QUOTE_CHARS = 20

# 측정값만 센다 — **식별자 안에 박힌 숫자는 수치가 아니다**.
#
# v1은 `\d+(?:\.\d+)?%?`를 썼는데, 그러면 "CASP14"의 14와 "AlphaFold2"의 2까지
# 수치로 잡힌다. 벤치마크·모델 이름에 숫자가 들어간 문장(AI/ML 논문에서는 흔하다)은
# 인용문이 그 이름을 똑같이 담고 있지 않으면 통째로 탈락했다 — 캡션 결함과 같은
# 부류의 조용한 오탈락이다. 앞뒤가 글자·숫자면 매치하지 않아 이름 속 숫자를 뺀다.
_NUMBER = re.compile(r"(?<![A-Za-z\d.])\d+(?:\.\d+)?%?(?![A-Za-z\d])")


class RejectReason:
    """탈락 사유 코드 — 집계·트레이스용. 사용자에게는 개별 사유를 노출하지 않는다."""

    UNKNOWN_PAPER = "unknown_paper"
    MISSING_QUOTE = "missing_quote"
    QUOTE_TOO_SHORT = "quote_too_short"
    QUOTE_NOT_VERBATIM = "quote_not_verbatim"
    ANCHOR_MISSING = "anchor_missing"
    ANCHOR_NOT_FOUND = "anchor_not_found"
    ANCHOR_TYPE_MISMATCH = "anchor_type_mismatch"
    QUOTE_OUTSIDE_ANCHOR = "quote_outside_anchor"
    ANCHOR_ON_ABSTRACT = "anchor_on_abstract"
    FIGURE_ANCHOR_REQUIRED = "figure_anchor_required"
    EMPTY_STATEMENT = "empty_statement"
    NO_SUPPORTING = "no_supporting"
    NUMBER_NOT_GROUNDED = "number_not_grounded"


@dataclass(frozen=True, slots=True)
class PaperEvidenceSource:
    """게이트가 한 논문에 대해 대조할 수 있는 전부.

    루프가 확보한 `PaperHandle`에서 만들어진다. `blocks`가 비어 있으면
    (초록만 확보한 논문) `fulltext`·`figure` 범위 인용은 성립하지 않는다.
    """

    paper_id: str
    record_ref: str
    scope: str
    text: str
    blocks: dict[str, tuple[str, str]] = field(default_factory=dict)

    def block(self, anchor: str) -> tuple[str, str] | None:
        return self.blocks.get(anchor)


@dataclass(frozen=True, slots=True)
class GateOutcome:
    items: tuple[EvidenceItem, ...]
    rejections: Counter[str]

    @property
    def rejected_count(self) -> int:
        return sum(self.rejections.values())


def _numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text))


def _scope_of(raw: dict[str, Any], source: PaperEvidenceSource) -> str:
    """모델이 범위를 선언할 수 있지만, **논문이 실제로 확보된 범위를 넘을 수 없다.**

    초록만 있는 논문에 `fulltext`를 선언해도 `abstract`로 강등된다 — 선언은
    의도일 뿐이고 확보 사실이 권위다.
    """
    declared = str(raw.get("sourceScope") or "").strip()
    if declared == SourceScope.figure.value:
        return SourceScope.figure.value
    if source.scope == SourceScope.abstract.value:
        return SourceScope.abstract.value
    if declared in (SourceScope.fulltext.value, SourceScope.abstract.value):
        return declared
    return SourceScope.fulltext.value


def _validate_ref(
    raw: dict[str, Any],
    sources: dict[str, PaperEvidenceSource],
    rejections: Counter[str],
) -> tuple[SourceRef, str] | None:
    """유효하면 (SourceRef, 검증에 쓰인 quote 텍스트)."""
    paper_id = str(raw.get("paperId") or "").strip()
    source = sources.get(paper_id)
    if source is None:
        rejections[RejectReason.UNKNOWN_PAPER] += 1
        return None

    scope = _scope_of(raw, source)
    quote = normalize(raw.get("quote"))
    anchor = str(raw.get("anchor") or "").strip() or None

    # --- 앵커 검사 (fulltext·figure는 필수, abstract는 금지) -------------------
    anchor_type: str | None = None
    block_text = ""
    if scope in (SourceScope.fulltext.value, SourceScope.figure.value):
        if not anchor:
            rejections[
                RejectReason.FIGURE_ANCHOR_REQUIRED
                if scope == SourceScope.figure.value
                else RejectReason.ANCHOR_MISSING
            ] += 1
            return None
        found = source.block(anchor)
        if found is None:
            rejections[RejectReason.ANCHOR_NOT_FOUND] += 1
            return None
        anchor_type, block_text = found
        if scope == SourceScope.figure.value and anchor_type != AnchorType.figure.value:
            # 그림 해석 범위는 그림 블록에만 붙는다 — 표·문단을 '해석'으로 인용해
            # quote 검사를 우회하는 길을 막는다.
            rejections[RejectReason.ANCHOR_TYPE_MISMATCH] += 1
            return None
    elif anchor:
        # 초록 범위는 DocModel이 없으므로 가리킬 블록도 없다. 앵커를 그대로 내보내면
        # FE가 이동 링크를 렌더하고 그 링크는 반드시 깨진다.
        rejections[RejectReason.ANCHOR_ON_ABSTRACT] += 1
        return None

    # --- 인용문 검사 (figure 범위는 인용문이 아니므로 면제) ---------------------
    if scope != SourceScope.figure.value:
        if not quote:
            rejections[RejectReason.MISSING_QUOTE] += 1
            return None
        if len(quote) < MIN_QUOTE_CHARS:
            rejections[RejectReason.QUOTE_TOO_SHORT] += 1
            return None
        if quote not in normalize(source.text):
            rejections[RejectReason.QUOTE_NOT_VERBATIM] += 1
            return None
        if scope == SourceScope.fulltext.value and quote not in normalize(block_text):
            # v2 신설 — v1은 문서 어딘가에 있기만 하면 통과시켜, 표를 가리키며
            # 서론 문장을 인용해도 막지 못했다.
            rejections[RejectReason.QUOTE_OUTSIDE_ANCHOR] += 1
            return None

    ref = SourceRef(
        paperId=source.paper_id,
        recordRef=source.record_ref,
        anchor=anchor,
        quote=quote or None,
        anchorType=AnchorType(anchor_type) if anchor_type else None,
        sourceScope=SourceScope(scope),
    )
    return ref, quote


def _grounded_numbers(
    refs: list[tuple[SourceRef, str]], sources: dict[str, PaperEvidenceSource]
) -> set[str]:
    """statement가 쓸 수 있는 숫자 집합.

    인용문의 숫자 + **그림 해석 출처가 있으면 그 논문 텍스트 전체의 숫자**.
    후자가 BLM §3의 검사 6이다 — 차트에서 눈으로 읽은 값이 논문 어디에도 없으면
    그것이 날조다. 정성 서술(추세·구조)은 숫자가 없어 이 규칙에 걸리지 않고,
    검증 강도 차이는 `sourceScope=figure` 표시로 드러낸다.
    """
    allowed: set[str] = set()
    for ref, quote in refs:
        allowed |= _numbers(quote)
        if ref.sourceScope == SourceScope.figure:
            source = sources.get(ref.paperId)
            if source is not None:
                allowed |= _numbers(source.text)
    return allowed


def run_gate(
    raw_items: list[dict[str, Any]],
    sources: dict[str, PaperEvidenceSource],
) -> GateOutcome:
    """LLM이 제안한 근거 항목 → 검증을 통과한 `EvidenceItem`만."""
    rejections: Counter[str] = Counter()
    items: list[EvidenceItem] = []

    for raw in raw_items or []:
        statement = normalize(raw.get("statement"))
        if not statement:
            rejections[RejectReason.EMPTY_STATEMENT] += 1
            continue

        supporting = [
            validated
            for validated in (
                _validate_ref(ref, sources, rejections) for ref in raw.get("supporting") or []
            )
            if validated is not None
        ]
        conflicting = [
            validated
            for validated in (
                _validate_ref(ref, sources, rejections) for ref in raw.get("conflicting") or []
            )
            if validated is not None
        ]

        if not supporting:
            rejections[RejectReason.NO_SUPPORTING] += 1
            continue

        statement_numbers = _numbers(statement)
        if statement_numbers and not statement_numbers <= _grounded_numbers(supporting, sources):
            rejections[RejectReason.NUMBER_NOT_GROUNDED] += 1
            continue

        items.append(
            EvidenceItem(
                statement=statement,
                supporting=[ref for ref, _ in supporting],
                conflicting=[ref for ref, _ in conflicting],
            )
        )

    return GateOutcome(items=tuple(items), rejections=rejections)
