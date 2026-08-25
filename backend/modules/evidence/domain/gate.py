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

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import (
    AnchorType,
    EvidenceItem,
    PaperIdNamespace,
    SourceRef,
    SourceScope,
)

from .projection import normalize

log = logging.getLogger("docsuri.evidence.gate")

__all__ = [
    "MIN_QUOTE_CHARS",
    "GateOutcome",
    "NumberPool",
    "PaperEvidenceSource",
    "RejectReason",
    "id_key",
    "numbers_in",
    "paper_id_namespace",
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
    MALFORMED_REF = "malformed_ref"
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
    # 표시용 제목 — 게이트는 이 값으로 아무것도 판정하지 않고 통과한 출처에 실어만 준다.
    # 판정 핸들은 paper_id·record_ref다. 제목이 여기 있는 이유는 출처를 만드는 자리가
    # 여기 하나이기 때문이다: 조립 단계에서 다시 붙이면 핸들 맵을 한 벌 더 들고 다녀야 하고,
    # 그 맵이 비면 제목만 조용히 사라진다(그 실패는 화면에서 id로 보인다).
    title: str = ""

    def block(self, anchor: str) -> tuple[str, str] | None:
        return self.blocks.get(anchor)


@dataclass(frozen=True, slots=True)
class GateOutcome:
    items: tuple[EvidenceItem, ...]
    rejections: Counter[str]

    @property
    def rejected_count(self) -> int:
        return sum(self.rejections.values())


def paper_id_namespace(paper_id: str) -> PaperIdNamespace | None:
    """`{namespace}:{id}`의 앞부분. 접두어가 없으면 **코퍼스 논문**이라 None이다.

    어휘를 아는 쪽이 판정해서 실어 보낸다. 소비자(화면)가 접두어를 직접 자르면 어휘가 두
    벌이 되고, 접두어가 하나 늘 때 한쪽만 고쳐져 화면이 조용히 링크를 잃는다 — 값이 실려
    오면 소비자의 분기가 컴파일에서 막힌다.

    어휘 밖 접두어는 None으로 떨어지지만 그것은 **정상 경로가 아니다** — 소비자가 코퍼스
    논문으로 오인할 수 있으므로 경고를 남긴다. 생산자를 어휘에 맞추거나 어휘를 넓혀야 한다
    (`attachment:`가 실제로 그랬다: 첨부 문서에 doc-model id가 없으면 러너가 그 접두어를
    만드는데 어휘에 없어서, 정상 첨부 인용마다 경고가 한 줄씩 쌓였다).
    """
    prefix, sep, _ = paper_id.partition(":")
    if not sep:
        return None
    try:
        return PaperIdNamespace(prefix)
    except ValueError:
        log.warning("evidence: unknown paperId namespace %r", prefix)
        return None


def numbers_in(text: str) -> set[str]:
    """§4.3 A2(판단 문장의 숫자 검사)도 이 함수를 쓴다 — 판정 지점이 둘이 되면 어긋난다."""
    return set(_NUMBER.findall(text))


def _to_float(token: str) -> float | None:
    try:
        return float(token.rstrip("%"))
    except ValueError:
        return None


def _decimals(token: str) -> int:
    """토큰이 적힌 소수 자릿수 — 반올림 허용 폭을 결정한다."""
    _, _, frac = token.rstrip("%").partition(".")
    return len(frac)


def _normalize_number(token: str) -> set[str]:
    """같은 수의 등가 표기 집합 — u7 grounding의 `_normalize_number` 이식.

    "0.953"과 "95.3%"는 같은 값이다. 정확 ×100/÷100 변환만 등가로 본다 —
    이 규칙은 u7 QT-1 eval 코퍼스(라벨 32건)에서 오통과 0으로 검증된 것이다.
    """
    forms = {token}
    value = _to_float(token)
    if value is None:
        return forms
    forms.add(f"{value:g}")
    if value > 1:  # percentage ↔ fraction
        forms.add(f"{value / 100:g}")
    else:
        forms.add(f"{value * 100:g}")
    return forms


@dataclass(slots=True)
class NumberPool:
    """statement 숫자의 대조 대상 — 등가 표기 집합 + 같은 스케일의 원값 목록.

    반올림 허용(95.3은 95.34에 근거)은 **같은 스케일에서만** 적용한다. ×100/÷100
    재스케일에 허용 폭을 얹으면 정수 statement "20"이 무관한 연도 "2020"
    (÷100=20.2, 정수 폭 0.5 안)에 근거해 버린다 — u7이 반례와 함께 금지한
    조합이라 그대로 따른다(스케일 교차는 위의 정확 변환으로만).
    """

    forms: set[str] = field(default_factory=set)
    values: list[float] = field(default_factory=list)

    def add_tokens(self, tokens: set[str]) -> None:
        for token in tokens:
            self.forms |= _normalize_number(token)
            value = _to_float(token)
            if value is not None:
                self.values.append(value)

    def merge(self, other: NumberPool) -> None:
        self.forms |= other.forms
        self.values.extend(other.values)

    def grounds(self, token: str) -> bool:
        if _normalize_number(token) & self.forms:
            return True
        value = _to_float(token)
        if value is None:
            return False
        band = 0.5 * 10 ** (-_decimals(token)) + 1e-9
        return any(abs(v - value) <= band for v in self.values)


def _resolve_source(
    paper_id: str, sources: dict[str, PaperEvidenceSource]
) -> PaperEvidenceSource | None:
    """확보한 논문 중에서 찾는다 — 표기 흔들림만 흡수하고 없는 논문은 없는 것이다.

    모델이 프롬프트의 id를 그대로 베끼지 않고 접두어(`arxiv:`)를 붙이거나 버전
    suffix를 떼는 일이 있다. 그때마다 근거를 통째로 버리면 실제로 확보한 논문의
    인용이 사라진다 — 실재성 판정은 유지하면서 표기만 맞춘다.
    """
    if not paper_id:
        return None
    direct = sources.get(paper_id)
    if direct is not None:
        return direct
    wanted = id_key(paper_id)
    for key, source in sources.items():
        if id_key(key) == wanted:
            return source
    return None


def id_key(paper_id: str) -> str:
    """논문 id 대조 키 — 버전 접미사·`arxiv:` 접두사를 뗀다. §4.3 A3도 이 키를 쓴다."""
    value = paper_id.strip().lower().removeprefix("arxiv:")
    head, sep, tail = value.rpartition("v")
    return head if sep and head and tail.isdigit() else value


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
    if not isinstance(raw, dict):
        # 모델이 출처를 객체가 아니라 문자열로 돌려주는 일이 실제로 있다.
        # 잘못된 출력은 예상 입력이다 — 게이트가 여기서 터지면 턴 전체가 죽는다.
        rejections[RejectReason.MALFORMED_REF] += 1
        return None

    paper_id = str(raw.get("paperId") or "").strip()
    source = _resolve_source(paper_id, sources)
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
        if quote not in source.text:
            # source.text는 as_source가 만든 정규화형이다 — ref마다 전문(수백 KB)을
            # 재정규화하지 않는다.
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
        namespace=paper_id_namespace(source.paper_id),
        title=source.title or None,
        anchor=anchor,
        quote=quote or None,
        anchorType=AnchorType(anchor_type) if anchor_type else None,
        sourceScope=SourceScope(scope),
    )
    return ref, quote


def _grounded_pool(
    refs: list[tuple[SourceRef, str]],
    sources: dict[str, PaperEvidenceSource],
    text_pools: dict[str, NumberPool],
) -> NumberPool:
    """statement가 쓸 수 있는 숫자의 대조 풀.

    인용문의 숫자 + **그림 해석 출처가 있으면 그 논문 텍스트 전체의 숫자**.
    후자가 BLM §3의 검사 6이다 — 차트에서 눈으로 읽은 값이 논문 어디에도 없으면
    그것이 날조다. 정성 서술(추세·구조)은 숫자가 없어 이 규칙에 걸리지 않고,
    검증 강도 차이는 `sourceScope=figure` 표시로 드러낸다.

    전문 숫자 풀은 `run_gate` 호출당 논문마다 1회만 만든다(`text_pools` 캐시) —
    항목마다 전문 정규식·정규화를 다시 돌리지 않는다.
    """
    pool = NumberPool()
    for ref, quote in refs:
        pool.add_tokens(numbers_in(quote))
        if ref.sourceScope == SourceScope.figure:
            source = sources.get(ref.paperId)
            if source is not None:
                cached = text_pools.get(ref.paperId)
                if cached is None:
                    cached = NumberPool()
                    cached.add_tokens(numbers_in(source.text))
                    text_pools[ref.paperId] = cached
                pool.merge(cached)
    return pool


def run_gate(
    raw_items: list[dict[str, Any]],
    sources: dict[str, PaperEvidenceSource],
) -> GateOutcome:
    """LLM이 제안한 근거 항목 → 검증을 통과한 `EvidenceItem`만."""
    rejections: Counter[str] = Counter()
    items: list[EvidenceItem] = []
    text_pools: dict[str, NumberPool] = {}

    for raw in raw_items or []:
        if not isinstance(raw, dict):
            rejections[RejectReason.MALFORMED_REF] += 1
            continue
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

        statement_numbers = numbers_in(statement)
        if statement_numbers:
            pool = _grounded_pool(supporting, sources, text_pools)
            if not all(pool.grounds(token) for token in statement_numbers):
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
