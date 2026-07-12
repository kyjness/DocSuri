from __future__ import annotations

import re
from enum import StrEnum

# 자연어 topic을 두 갈래로 분류한다 — LITERAL_QUOTE는 LLM 추출을 우회하고 OpenSearch
# match_phrase 결과만으로 100% grounded 응답을 조립한다(환각 위험 자체가 없음, 비용도
# 절감). COMPARISON은 기존 LLM 추출 경로 그대로다. 분류 자체에 LLM을 쓰지 않는 이유는
# 이 판단 자체가 틀려도 최악의 경우 COMPARISON 경로로 처리되어 안전하게 저하될 뿐이라
# 규칙 기반으로 충분하기 때문이다(추가 Bedrock 호출/지연/쿼터 소모를 피함).


class QueryIntent(StrEnum):
    LITERAL_QUOTE = "literal_quote"
    COMPARISON = "comparison"


# 사용자가 "정확한 문장/표현을 찾아달라"는 신호. 따옴표로 감싼 문구가 가장 강한 신호이고,
# 그 외엔 한국어 지시어 표현으로 보조 판별한다.
_QUOTE_WRAPPED_RE = re.compile(r'["“”‘’\']([^"“”‘’\']{4,})["“”‘’\']')
_LITERAL_SIGNAL_RE = re.compile(
    r"(그대로|정확히|정확한 문장|문장이 있는|문구가 있는|라는 문장|이라는 표현|포함하는 논문|들어있는 논문)"
)

# 후속 좁히기(꼬리질문) 신호 — "이전에 찾은 논문들 안에서"를 뜻하는 지시어.
_FOLLOWUP_SIGNAL_RE = re.compile(
    r"(그\s*중에서|그중에서|그\s*논문|방금\s*(그|찾은)|위에서\s*찾은|앞서\s*찾은|이\s*논문들\s*중)"
)


def classify_intent(topic: str) -> QueryIntent:
    """topic이 '이 문장이 있는 논문을 찾아줘' 유형이면 LITERAL_QUOTE, 아니면 COMPARISON."""
    if _QUOTE_WRAPPED_RE.search(topic) or _LITERAL_SIGNAL_RE.search(topic):
        return QueryIntent.LITERAL_QUOTE
    return QueryIntent.COMPARISON


def is_followup_narrowing(topic: str) -> bool:
    """이전 턴에서 찾은 논문 집합으로 검색 범위를 좁혀야 하는 후속 질문인지 판별."""
    return bool(_FOLLOWUP_SIGNAL_RE.search(topic))


def extract_literal_phrase(topic: str) -> str:
    """LITERAL_QUOTE topic에서 검색할 정확 문구를 뽑는다.

    따옴표로 감싼 부분이 있으면 그 내부만 사용(사용자가 지시어 문장까지 검색하지
    않도록) — 없으면 topic 전체를 문구로 취급한다(공백류 정규화만 적용).
    """
    match = _QUOTE_WRAPPED_RE.search(topic)
    phrase = match.group(1) if match else topic
    return re.sub(r"\s+", " ", phrase).strip()
