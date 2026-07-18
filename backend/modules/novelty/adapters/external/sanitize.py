"""도구별 payload allowlist 강제(BR-RA7, NFR-NV2-15) — 규칙 표를 데이터로 보유.

외부로 나가는 도구 인자는 허용 키·타입·길이 상한을 통과해야 한다. 에이전트가
원고 원문·근거 전문을 인자에 넣어도(프롬프트 인젝션 포함 — SECURITY-11) 이
경계에서 차단된다: 허용되지 않은 키는 위반, 길이 초과는 위반 — 위반이 있으면
도구는 실행되지 않고 오류를 반환한다(BLM §3.1, outcome=error).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ...ports.tools import TOOL_DATASET_SEARCH, TOOL_GITHUB_SEARCH

__all__ = ["PAYLOAD_ALLOWLISTS", "FieldRule", "PayloadViolation", "sanitize_payload"]

# 허용 payload의 정신(BLM §3.1): topic·키워드·논문 제목·기술명·익명화 요약 —
# 전부 짧은 텍스트다. 길이 상한이 '전문 투입'을 구조적으로 막는다.
_QUERY_MAX_LEN = 180


@dataclass(frozen=True, slots=True)
class FieldRule:
    max_length: int
    required: bool = False


PAYLOAD_ALLOWLISTS: dict[str, dict[str, FieldRule]] = {
    TOOL_GITHUB_SEARCH: {
        "query": FieldRule(max_length=_QUERY_MAX_LEN, required=True),
        "language": FieldRule(max_length=40),
    },
    TOOL_DATASET_SEARCH: {
        "query": FieldRule(max_length=_QUERY_MAX_LEN, required=True),
        "task": FieldRule(max_length=80),
    },
}


@dataclass(frozen=True, slots=True)
class PayloadViolation:
    key: str
    reason: str  # unknown_key | not_text | too_long | missing_required


def sanitize_payload(
    tool_name: str, args: dict[str, Any]
) -> tuple[dict[str, str], list[PayloadViolation]]:
    """(정제된 payload, 위반 목록). 위반이 있으면 호출자는 실행하지 않아야 한다."""
    rules = PAYLOAD_ALLOWLISTS.get(tool_name)
    if rules is None:
        return {}, [PayloadViolation(key="*", reason="unknown_tool")]
    sanitized: dict[str, str] = {}
    violations: list[PayloadViolation] = []
    for key, value in args.items():
        rule = rules.get(key)
        if rule is None:
            violations.append(PayloadViolation(key=key, reason="unknown_key"))
            continue
        if not isinstance(value, str):
            violations.append(PayloadViolation(key=key, reason="not_text"))
            continue
        cleaned = re.sub(r"\s+", " ", value).strip()
        if len(cleaned) > rule.max_length:
            violations.append(PayloadViolation(key=key, reason="too_long"))
            continue
        if cleaned:
            sanitized[key] = cleaned
    for key, rule in rules.items():
        if rule.required and key not in sanitized:
            violations.append(PayloadViolation(key=key, reason="missing_required"))
    return sanitized, violations
