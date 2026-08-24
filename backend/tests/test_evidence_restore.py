"""저장된 턴 복원 — 계약이 바뀐 뒤에도 옛 행을 읽을 수 있어야 한다."""

from __future__ import annotations

from backend.modules.evidence.models import TurnSuccessResult
from backend.modules.evidence.repository import _restore

_LEGACY_OK = {
    "state": "ok",
    "claims": [
        {
            "statement": "s",
            "supporting": [{"paperId": "2310.11511", "recordRef": "rec-1", "quote": "q"}],
            "conflicting": [],
        }
    ],
    "coverage": {"paperCount": 1},
    # v3 §4 이전 — 결정론으로 이어붙인 문자열.
    "answer": "2310.11511이 s라고 말한다.\n둘째 줄.",
}


def test_a_legacy_string_answer_is_read_as_a_fallback_shaped_answer():
    """배포 DB에 이 모양의 ok 행이 남아 있다(2026-08-24: 5건). 그대로 `model_validate`하면
    던지고 그 세션 조회가 전부 500이 된다. 옛 문자열은 실제로 판단 없는 답이었으므로
    폴백 모양이 사실과 맞다."""
    result = _restore("ok", dict(_LEGACY_OK))

    assert isinstance(result, TurnSuccessResult)
    answer = result.outcome.answer
    assert answer is not None
    assert [s.text for s in answer.segments] == ["2310.11511이 s라고 말한다.", "둘째 줄."]
    assert all(s.kind.value == "synthesis" and s.refs == [] for s in answer.segments)
    assert answer.checks.fallback is True


def test_an_empty_legacy_answer_becomes_none_not_an_empty_answer():
    result = _restore("ok", {**_LEGACY_OK, "answer": "   "})

    assert isinstance(result, TurnSuccessResult)
    assert result.outcome.answer is None


def test_a_current_answer_passes_through_untouched():
    current = {
        **_LEGACY_OK,
        "answer": {
            "segments": [{"text": "t", "refs": [1], "kind": "cited"}],
            "checks": {"demoted": 0, "regenerated": False, "fallback": False},
        },
    }

    result = _restore("ok", current)

    assert isinstance(result, TurnSuccessResult)
    assert result.outcome.answer.checks.fallback is False
