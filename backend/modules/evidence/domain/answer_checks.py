"""판단 문장 검사(설계 v3 §4.3) — 기계식. LLM-judge 없음.

게이트가 근거 한 건을 검사하듯 **답변도 기계가 검사한다.** 전부 문자열·집합 연산이라
같은 답변·같은 근거면 같은 판정이 나온다 — `answer`가 LLM 출력이 되면서 `assemble()`이
잃은 결정론이 여기로 옮겨온 것이다(§4.4). 회귀 픽스처·PBT는 이 모듈에 건다.

검사는 두 급이다:

- **강등**(A1·A2) — 문장은 남되 "기계가 확인함" 표시를 잃는다. `refs`를 비우면 `kind`가
  synthesis로 유도된다. 거부가 아니다.
- **거부**(A3·A4·A5) — 답변 전체를 물린다. 호출자가 사유를 실어 재생성하고, 재생성도
  거부되면 결정론 이어붙이기로 떨어진다. 검사를 못 통과한 판단은 화면에 가지 않는다
  (C-2 fail-closed).

숫자 판정은 게이트의 `numbers_in`·`NumberPool`을 **그대로** 쓴다. 같은 질문("이 숫자가
원문에 있나")에 판정 지점이 둘이면 어긋난다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from docsuri_shared._generated.dtos.evidence_schema import (
    AnswerChecks,
    AnswerSegment,
    AnswerSegmentKind,
    AnswerSegmentRole,
    EvidenceAnswer,
    EvidenceItem,
)

from ..ports.llm import AnswerSentence
from .gate import NumberPool, id_key, numbers_in
from .models import iter_refs

__all__ = [
    "REJECT_NO_CITED_SENTENCE",
    "REJECT_SYNTHESIS_RATIO",
    "REJECT_UNKNOWN_PAPER",
    "SYNTHESIS_RATIO_LIMIT",
    "AnswerRejected",
    "CheckedAnswer",
    "check_answer",
]

# 거부 사유 코드 — 재생성 프롬프트에 실린다(모델이 무엇을 고쳐야 하는지 알아야 한다).
REJECT_UNKNOWN_PAPER = "unknown_paper"
REJECT_NO_CITED_SENTENCE = "no_cited_sentence"
REJECT_SYNTHESIS_RATIO = "synthesis_ratio"

# A5 — 종합 문장 비율 상한. **시작값 50%이고 표준 수치가 아니다**(§4.3). 골든셋 결과로
# 조정하며, 조정할 때는 근거를 함께 남긴다. 낮추면 "판단을 안 한 답"이 늘고, 높이면
# 기계가 확인하지 못한 문장이 화면을 채운다.
SYNTHESIS_RATIO_LIMIT = 0.5

# 논문 id로 읽힐 수 있는 토큰 — arXiv 신형(2310.11511[v3])·구형(cs.AI/0112017) 둘 다.
# A3은 "근거 목록에 없는 논문이 등장하는가"를 보는데, 모델이 지어낸 id가 가장 흔한 모양이다.
#
# `\b`를 쓰면 안 된다 — 한국어 조사가 id에 바로 붙는다("2401.99999도 같은 결론"). 한글은
# 유니코드 단어 문자라 `\b`가 성립하지 않아 매치가 통째로 빠지고, A3이 조용히 무력해진다.
# 앞뒤 조건은 **라틴 문자·숫자·점**으로만 건다.
#
# 신형 id의 앞 넷은 YYMM이다 — **달이 01~12여야 한다.** 이 제약이 없으면 `1234.5678`이나
# 표 셀의 `1074.3094`가 논문 id로 읽혀 A3이 답변째로 거부한다(코퍼스에서 그런 수치 126개).
# 뒤 조건은 "숫자가 더 이어지거나 소수점이 이어지지 않는다"이지 "점이 안 온다"가 아니다 —
# 문장 끝의 마침표(`2401.99999.`)를 막으면 가장 흔한 문장 모양에서 A3이 조용히 빠진다.
_PAPER_ID = re.compile(
    r"(?<![A-Za-z\d.])"
    r"(?:\d{2}(?:0[1-9]|1[0-2])\.\d{4,5}(?:v\d+)?|[a-z-]{2,}(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)"
    r"(?!\d)(?!\.\d)"
)

# 본문 속 인용 표기 `[1]`·`[1, 2]`. refs가 권위이므로 파서가 이미 걷어내지만, 검사기는
# 파서를 거치지 않은 입력(대역·재생 픽스처)도 받으므로 여기서 한 번 더 걷는다 — 안 걷으면
# 게이트의 숫자 정규식이 `[1]`의 1을 수치로 뽑아 문장을 강등하고, 그것이 쌓여 A4가 터진다.
_CITATION_MARKER = re.compile(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]")


@dataclass(frozen=True, slots=True)
class AnswerRejected:
    """A3·A4·A5 위반 — 답변 전체를 물린다."""

    code: str
    detail: str


@dataclass(slots=True)
class CheckedAnswer:
    """검사를 통과한 답변 + 그 과정에서 벌어진 일.

    강등 **건수**는 `answer.checks.demoted`가 이미 들고 있으므로 여기 두지 않는다.
    여기 남는 것은 화면 계약에 안 들어가는 쪽, 즉 **왜** 강등됐는지다 — 호출자가 로그로
    남긴다. 계산해놓고 아무도 안 읽으면 강등이 조용해진다.
    """

    answer: EvidenceAnswer
    demotion_reasons: list[str] = field(default_factory=list)


def check_answer(
    sentences: Sequence[AnswerSentence],
    claims: list[EvidenceItem],
    *,
    regenerated: bool = False,
) -> CheckedAnswer | AnswerRejected:
    """§4.3 검사 5종. 통과하면 `CheckedAnswer`, 거부면 `AnswerRejected`.

    `claims`는 `assemble`이 화면에 낼 **표시 순서 그대로** 와야 한다 — `[n]`은 그 순서의
    1-기반 번호이고, 근거표 행 번호와 같은 출처다. 순서가 다르면 번호가 다른 행을 가리킨다.

    `kind`는 여기서 정해진다 — 살아남은 `refs`가 있으면 cited, 없으면 synthesis.
    """
    valid_refs = range(1, len(claims) + 1)
    pools = [_claim_pool(item) for item in claims]
    known_papers = {
        id_key(ref.paperId) for item in claims for ref in iter_refs(item) if ref.paperId
    }
    # 달 검사를 지나고도 남는 모호함(2401.5678이 수치일 수 있다)은 근거로 푼다 — 어느 근거의
    # 수치 풀에라도 있는 토큰은 논문 id가 아니라 그 수치다.
    every_number = NumberPool()
    for pool in pools:
        every_number.merge(pool)

    checked: list[AnswerSegment] = []
    demoted = 0
    reasons: list[str] = []

    for sentence in sentences:
        # A3 — 근거 목록에 없는 논문이 등장하는가. **강등이 아니라 거부다**: 지어낸 논문은
        # 표시를 낮춘다고 덜 위험해지지 않는다. 그래서 강등 판정보다 **먼저** 본다 — 뒤에
        # 두면 A1·A2를 다 돌려놓고 답변째로 버리게 된다.
        stray = sorted(
            {
                found
                for found in _PAPER_ID.findall(sentence.text)
                if id_key(found) not in known_papers and not every_number.grounds(found)
            }
        )
        if stray:
            return AnswerRejected(REJECT_UNKNOWN_PAPER, f"근거 목록에 없는 논문 {stray}")

        refs = list(dict.fromkeys(sentence.refs))  # 중복 번호는 표시에 의미가 없다
        reason = None
        if refs:
            # A1 — 번호가 실재하는가.
            unknown = [n for n in refs if n not in valid_refs]
            if unknown:
                reason = f"A1: 없는 근거 번호 {unknown}"
            else:
                # A2 — 문장의 숫자가 참조한 근거(statement·quote)에 있는가.
                pool = NumberPool()
                for n in refs:
                    pool.merge(pools[n - 1])
                ungrounded = sorted(
                    t for t in numbers_in(_without_paper_ids(sentence.text)) if not pool.grounds(t)
                )
                if ungrounded:
                    reason = f"A2: 근거에 없는 수치 {ungrounded}"

        if reason is not None:
            demoted += 1
            reasons.append(f'{reason} — "{sentence.text[:60]}"')
            refs = []
        checked.append(
            AnswerSegment(
                text=sentence.text,
                refs=refs,
                kind=AnswerSegmentKind.cited if refs else AnswerSegmentKind.synthesis,
                # 역할은 **검사하지 않고 통과시킨다**(§4.2). 강등(A1·A2)은 "기계가 확인했는가"를
                # 낮추는 것이지 문장이 무엇을 하는지를 바꾸지 않는다 — 강등된 결론은 여전히
                # 결론이고, 화면은 그것을 앞에 세우되 '종합' 배지를 함께 붙인다. 여기서 역할을
                # 지우면 강등된 답변만 문단 구조를 잃는다.
                role=_role_of(sentence),
            )
        )

    # A4 — 번호 붙은 문장이 하나도 없으면 판단이 아니라 감상이다.
    cited = [s for s in checked if s.kind is AnswerSegmentKind.cited]
    if not cited:
        return AnswerRejected(
            REJECT_NO_CITED_SENTENCE, "인용 번호가 붙은 문장이 0개다"
        )

    # A5 — 종합 비율 상한.
    ratio = (len(checked) - len(cited)) / len(checked)
    if ratio > SYNTHESIS_RATIO_LIMIT:
        return AnswerRejected(
            REJECT_SYNTHESIS_RATIO,
            f"종합 문장 비율 {ratio:.0%}가 상한 {SYNTHESIS_RATIO_LIMIT:.0%}를 넘는다",
        )

    return CheckedAnswer(
        answer=EvidenceAnswer(
            segments=checked,
            checks=AnswerChecks(demoted=demoted, regenerated=regenerated, fallback=False),
        ),
        demotion_reasons=reasons,
    )


def _role_of(sentence: AnswerSentence) -> AnswerSegmentRole:
    """선언이 없거나 어휘 밖이면 evidence — 산문은 그대로 나가고 구조만 평평해진다."""
    try:
        return AnswerSegmentRole(sentence.role)
    except ValueError:
        return AnswerSegmentRole.evidence


def _without_paper_ids(text: str) -> str:
    """A2가 보기 전에 논문 id와 인용 표기를 걷어낸다 — 둘 다 수치가 아니다.

    "2310.11511이 그렇게 보고한다"에서 `2310.11511`은 게이트의 숫자 정규식에 걸린다(뒤가
    한글이라 이름 속 숫자 배제 규칙에도 안 걸린다). 걷어내지 않으면 논문을 언급한 문장이
    **항상** 근거 없는 수치로 강등되고, 그것이 쌓이면 A4로 답변 전체가 거부된다.
    """
    return _CITATION_MARKER.sub(" ", _PAPER_ID.sub(" ", text))


def _claim_pool(item: EvidenceItem) -> NumberPool:
    """근거 한 건이 뒷받침하는 수치 — statement와 인용문 양쪽에서 모은다.

    인용문을 포함하는 이유는 게이트가 이미 "statement의 수치가 인용문에 있음"을 통과시킨
    뒤이기 때문이다. 판단 문장이 인용문 쪽 표기(95.3% vs 0.953)를 쓸 수 있다.
    """
    pool = NumberPool()
    pool.add_tokens(numbers_in(item.statement))
    for ref in iter_refs(item):
        if ref.quote:
            pool.add_tokens(numbers_in(ref.quote))
    return pool



