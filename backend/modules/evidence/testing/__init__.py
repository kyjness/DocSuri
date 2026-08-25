"""evidence 테스트 대역과 픽스처 — **서빙 경로에 없다**.

한 포트에 대역이 여럿 생기면 그중 하나만 계약 변화를 따라가고 나머지는 낡은 채로 초록을
낸다. 실제로 `EvidenceAnswerPort`는 도입된 PR 안에서 이미 대역이 둘이었고, `EvidenceItem`
빌더는 여섯 파일에 흩어져 있었다. 그래서 한 곳에 둔다.

여기 없는 것 하나: `test_evidence_gate`의 `_item`은 **게이트 통과 전 원시 dict**라 이름만
비슷하고 다른 타입이다. 합치면 "검증 전"과 "검증 후"의 구분이 사라진다.

선례는 `discovery/testing/`이다.
"""

from .doubles import NoHits, NoItems, ScriptedAnswer, ScriptedLlm, ScriptedSearch
from .fixtures import accumulator, evidence_item, loop_budget, run_context

__all__ = [
    "NoHits",
    "NoItems",
    "ScriptedAnswer",
    "ScriptedLlm",
    "ScriptedSearch",
    "accumulator",
    "evidence_item",
    "loop_budget",
    "run_context",
]
