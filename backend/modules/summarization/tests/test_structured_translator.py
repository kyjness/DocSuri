"""StructuredTranslator — translated doc-model output, verbatim preservation, map-only chunking
(BR-S18)."""

from __future__ import annotations

from docsuri_shared.dtos import DocModel

from summarization.domain.models import (
    Glossary,
    SummaryRequest,
    Task,
    TranslationSegmentsResult,
)
from summarization.domain.structured_translator import StructuredTranslator, iter_text_fields


class _EchoLlm:
    """Translates each segment to ``번역:<text>`` and records how many batches it received
    (one per map chunk) so chunking is observable."""

    def __init__(self) -> None:
        self.batches: list[int] = []

    def translate_segments(self, segments, request, glossary) -> TranslationSegmentsResult:
        self.batches.append(len(segments))
        return TranslationSegmentsResult(
            translations={s.id: f"번역:{s.text}" for s in segments},
            kept_terms=("BERT",),
        )


def _rich_doc() -> DocModel:
    return DocModel.model_validate(
        {
            "meta": {
                "paperId": "2401.1",
                "version": 1,
                "title": "Sample",
                "provenance": {
                    "sourceTier": "native_html",
                    "parserVersion": "test",
                    "schemaVersion": "1",
                    "generatedAt": "1970-01-01T00:00:00Z",
                },
            },
            "fullText": (
                "Introduction\n\n"
                "We propose a model.\n\n"
                "E=mc^2\n\n"
                "print('x')\n\n"
                "Table 1 Accuracy comparison\n"
                "Method 95.3\n\n"
                "first point\n"
                "second point\n\n"
                "Background\n\n"
                "Prior work."
            ),
            "sections": [
                {
                    "id": "s1",
                    "title": "Introduction",
                    "blocks": [
                        {"id": "s1.p1", "type": "paragraph", "text": "We propose a model."},
                        {"id": "s1.eq1", "type": "formula", "latex": "E=mc^2"},
                        {"id": "s1.code1", "type": "code", "text": "print('x')"},
                        {
                            "id": "s1.tbl1",
                            "type": "table",
                            "caption": "Accuracy comparison",
                            "anchorLabel": "Table 1",
                            "rows": [{"cells": [{"text": "Method"}, {"text": "95.3"}]}],
                        },
                        {
                            "id": "s1.list1",
                            "type": "list",
                            "ordered": False,
                            "items": [{"text": "first point"}, {"text": "second point"}],
                        },
                    ],
                    "sections": [
                        {
                            "id": "s1.1",
                            "title": "Background",
                            "blocks": [
                                {"id": "s1.1.p1", "type": "paragraph", "text": "Prior work."}
                            ],
                        }
                    ],
                }
            ],
        }
    )


def _req() -> SummaryRequest:
    return SummaryRequest(paper_id="2401.1", version=1, task=Task.TRANSLATE)


def test_translates_text_fields_and_preserves_structure() -> None:
    draft = StructuredTranslator(_EchoLlm()).translate(_rich_doc(), _req(), Glossary())
    doc = draft.doc_model
    sec = doc.sections[0]

    # section title + nested section title translated
    assert sec.title == "번역:Introduction"
    assert sec.sections[0].title == "번역:Background"
    assert sec.sections[0].blocks[0].root.text == "번역:Prior work."

    blocks = {b.root.id: b.root for b in sec.blocks}
    assert blocks["s1.p1"].text == "번역:We propose a model."
    # list items translated
    assert [it.text for it in blocks["s1.list1"].items] == ["번역:first point", "번역:second point"]
    # table caption translated, numeric cells VERBATIM (D8)
    assert blocks["s1.tbl1"].caption == "번역:Accuracy comparison"
    assert [c.text for c in blocks["s1.tbl1"].rows[0].cells] == ["Method", "95.3"]
    # formula latex + code text verbatim (never translated)
    assert blocks["s1.eq1"].latex == "E=mc^2"
    assert blocks["s1.code1"].text == "print('x')"
    # ids preserved, kept terms surfaced
    assert blocks["s1.tbl1"].anchorLabel == "Table 1"
    assert draft.kept_terms == ("BERT",)
    assert "번역:Introduction" in doc.fullText
    assert "번역:Prior work." in doc.fullText
    assert "95.3" in doc.fullText


def test_map_only_chunks_long_input_without_reduce() -> None:
    # A tiny per-chunk budget forces multiple map batches; every field is still covered and the
    # single source structure is reassembled (no reduce — sections just concatenate).
    llm = _EchoLlm()
    translator = StructuredTranslator(llm, chunk_budget_tokens=1)
    draft = translator.translate(_rich_doc(), _req(), Glossary())

    assert len(llm.batches) > 1  # fanned out into multiple map calls
    # full coverage: no translatable field left untranslated
    doc_dict = draft.doc_model.model_dump(mode="json")
    assert all(text.startswith("번역:") for _id, text, _set in iter_text_fields(doc_dict))


def test_duplicate_block_ids_translate_independently() -> None:
    # Reading-order keying: even if the parser emitted duplicate block ids, each segment is keyed
    # by position, so two same-id blocks get their own translations (no merge/collision).
    doc = DocModel.model_validate(
        {
            "meta": {
                "paperId": "2401.1",
                "version": 1,
                "title": "S",
                "provenance": {
                    "sourceTier": "native_html",
                    "parserVersion": "test",
                    "schemaVersion": "1",
                    "generatedAt": "1970-01-01T00:00:00Z",
                },
            },
            "fullText": "first\n\nsecond",
            "sections": [
                {
                    "id": "s1",
                    "title": "",
                    "blocks": [
                        {"id": "dup", "type": "paragraph", "text": "first"},
                        {"id": "dup", "type": "paragraph", "text": "second"},
                    ],
                }
            ],
        }
    )
    draft = StructuredTranslator(_EchoLlm()).translate(doc, _req(), Glossary())
    texts = [b.root.text for b in draft.doc_model.sections[0].blocks]
    assert texts == ["번역:first", "번역:second"]


def test_truncated_chunk_is_resplit_and_retried() -> None:
    # Math-heavy regression: token estimates under-count LaTeX, so an "in-budget" chunk can
    # overflow the model's output cap and come back truncated (partial JSON). The translator must
    # re-split the truncated chunk and retry the halves so every field is still translated — not
    # silently left as source text (which the orchestrator would abstain as empty_translation).
    class _TruncateFirstBatch:
        """Models a math-heavy overflow: the initial oversized batch truncates (only its first
        segment comes back), the smaller retry halves fit. Records every batch size."""

        def __init__(self) -> None:
            self.batches: list[int] = []
            self._first = True

        def translate_segments(self, segments, request, glossary) -> TranslationSegmentsResult:
            self.batches.append(len(segments))
            if self._first and len(segments) > 1:
                self._first = False
                return TranslationSegmentsResult(
                    translations={segments[0].id: f"번역:{segments[0].text}"},
                    truncated=True,
                )
            return TranslationSegmentsResult(
                translations={s.id: f"번역:{s.text}" for s in segments}
            )

    llm = _TruncateFirstBatch()
    # One big chunk (huge budget) → truncates → re-splits into halves that fit.
    draft = StructuredTranslator(llm, chunk_budget_tokens=10_000).translate(
        _rich_doc(), _req(), Glossary()
    )
    doc_dict = draft.doc_model.model_dump(mode="json")
    # Full coverage after re-split: no translatable field left as source text.
    assert all(text.startswith("번역:") for _id, text, _set in iter_text_fields(doc_dict))
    # It fanned out: the oversized batch, then the two retried halves.
    assert len(llm.batches) == 3
    assert llm.batches[1] + llm.batches[2] == llm.batches[0]


def test_missing_translation_falls_back_to_original_text() -> None:
    class _Partial:
        def translate_segments(self, segments, request, glossary) -> TranslationSegmentsResult:
            # Only translate the first segment; the rest must keep their source text.
            first = segments[0]
            return TranslationSegmentsResult(translations={first.id: "번역됨"})

    draft = StructuredTranslator(_Partial()).translate(_rich_doc(), _req(), Glossary())
    texts = [t for _id, t, _s in iter_text_fields(draft.doc_model.model_dump(mode="json"))]
    assert "번역됨" in texts
    assert "We propose a model." in texts  # untranslated segment preserved verbatim


def test_unresolvable_truncation_fails_closed() -> None:
    # A leaf (single segment) that still truncates at the model's output cap cannot be split
    # further. The translator must NOT accept/cache a known-truncated (partial) translation as
    # success — it fails closed (raises LlmUnavailable → orchestrator abstains). QT-5 HARD fail.
    import pytest

    from summarization.ports.ports import LlmUnavailable

    class _AlwaysTruncate:
        def translate_segments(self, segments, request, glossary) -> TranslationSegmentsResult:
            return TranslationSegmentsResult(
                translations={s.id: f"번역:{s.text}" for s in segments}, truncated=True
            )

    with pytest.raises(LlmUnavailable):
        StructuredTranslator(_AlwaysTruncate()).translate(_rich_doc(), _req(), Glossary())
