from __future__ import annotations

from backend.modules.evidence.intent import (
    QueryIntent,
    classify_intent,
    extract_literal_phrase,
    is_followup_narrowing,
)


def test_classify_intent_detects_quoted_phrase() -> None:
    topic = '"attention is all you need" 라는 문장이 있는 논문을 찾아줘'
    assert classify_intent(topic) is QueryIntent.LITERAL_QUOTE


def test_classify_intent_detects_literal_signal_without_quotes() -> None:
    topic = 'transformer는 병렬화 가능하다는 문장이 그대로 있는 논문 알려줘'
    assert classify_intent(topic) is QueryIntent.LITERAL_QUOTE


def test_classify_intent_defaults_to_comparison() -> None:
    topic = 'in-context learning 성능을 향상시키는 방법들을 비교해줘'
    assert classify_intent(topic) is QueryIntent.COMPARISON


def test_extract_literal_phrase_prefers_quoted_span() -> None:
    topic = '이 문장이 있는 논문 찾아줘: "self-attention reduces computation"'
    assert extract_literal_phrase(topic) == 'self-attention reduces computation'


def test_extract_literal_phrase_falls_back_to_whole_topic() -> None:
    topic = 'self-attention reduces computation 이라는 표현'
    assert extract_literal_phrase(topic) == topic


def test_is_followup_narrowing_detects_reference_to_prior_results() -> None:
    assert is_followup_narrowing('그 중에서 2020년 이후 논문만 다시 보여줘')
    assert not is_followup_narrowing('completely new topic about diffusion models')
