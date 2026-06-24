"""BR-S18 — structured translation prompt: scope-aware unit + id-keyed segments JSON."""

from __future__ import annotations

import json

from summarization.domain.models import (
    Glossary,
    Scope,
    SummaryRequest,
    Task,
    TranslationSegment,
)
from summarization.prompts.templates import build_translate_segments_prompt

_GLOSSARY = Glossary(seed_mappings=(), keep_as_is=(), user_overrides=())


def _req(scope: Scope) -> SummaryRequest:
    return SummaryRequest(paper_id="2401.1", version=1, task=Task.TRANSLATE, scope=scope)


def _segs() -> tuple[TranslationSegment, ...]:
    return (
        TranslationSegment(id="s1", text="Attention is all you need"),
        TranslationSegment(id="s1.p1", text="We propose a model."),
    )


def test_abstract_scope_uses_abstract_unit_label() -> None:
    system, _user = build_translate_segments_prompt(_segs(), _req(Scope.ABSTRACT), _GLOSSARY)
    assert "초록을" in system


def test_full_scope_uses_body_unit_label() -> None:
    system, _user = build_translate_segments_prompt(_segs(), _req(Scope.FULL), _GLOSSARY)
    assert "본문을" in system


def test_segments_are_isolated_as_json_data() -> None:
    # Injection isolation (SEC): segment data goes inside <segments> as JSON; the model is told
    # to keep ids and to preserve formulas/numbers/code verbatim.
    system, user = build_translate_segments_prompt(_segs(), _req(Scope.FULL), _GLOSSARY)
    assert user.startswith("<segments>\n") and user.endswith("\n</segments>")
    body = user[len("<segments>\n") : -len("\n</segments>")]
    parsed = json.loads(body)
    assert parsed == [
        {"id": "s1", "text": "Attention is all you need"},
        {"id": "s1.p1", "text": "We propose a model."},
    ]
    assert "id는 절대 바꾸지 마라" in system
    assert "translations" in system
