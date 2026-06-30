"""U7 doc-model input transition (D2/D8): SourceSelector doc-model-first + InputRefiner.

The structured doc-model replaces plain `.txt` as the full-text input (input upgrade only —
selection/fallback/grounding/cache logic unchanged). Tables enter as DATA (numbers visible to
the LLM, D8); sections/formulas/captions come straight from the doc-model (no regex guessing).
"""

from __future__ import annotations

from docsuri_shared.dtos import DocModel

from summarization.domain.models import Scope, SourceKind, SourceText, Task
from summarization.domain.refiner import InputRefiner
from summarization.domain.source_selector import SourceSelector

_FULL_TEXT = (
    "Results\n\n"
    "We report accuracy.\n\n"
    "Table 1 Scores.\n"
    "Model Acc\n"
    "Ours 0.953\n\n"
    "E=mc^2\n\n"
    "Ablation\n\n"
    "Sub finding."
)


def _doc() -> DocModel:
    return DocModel.model_validate(
        {
            "meta": {
                "paperId": "2401.00001",
                "version": 1,
                "title": "T",
                "provenance": {
                    "sourceTier": "ar5iv",
                    "parserVersion": "p@1",
                    "schemaVersion": "1.0.0",
                    "generatedAt": "2026-06-23T00:00:00Z",
                },
            },
            "fullText": _FULL_TEXT,
            "sections": [
                {
                    "id": "s1",
                    "title": "Results",
                    "blocks": [
                        {"id": "s1.p1", "type": "paragraph", "text": "We report accuracy."},
                        {
                            "id": "s1.tbl1",
                            "type": "table",
                            "anchorLabel": "Table 1",
                            "caption": "Scores.",
                            "rows": [
                                {
                                    "cells": [
                                        {"text": "Model", "isHeader": True},
                                        {"text": "Acc", "isHeader": True},
                                    ]
                                },
                                {"cells": [{"text": "Ours"}, {"text": "0.953"}]},
                            ],
                        },
                        {"id": "s1.eq1", "type": "formula", "latex": "E=mc^2", "display": True},
                    ],
                    "sections": [
                        {
                            "id": "s1.1",
                            "title": "Ablation",
                            "blocks": [
                                {"id": "s1.1.p1", "type": "paragraph", "text": "Sub finding."}
                            ],
                        }
                    ],
                }
            ],
        }
    )


# --- InputRefiner.refine_doc_model ---------------------------------------


def test_refine_doc_model_projects_tables_as_visible_data() -> None:
    refined = InputRefiner().refine_doc_model(_doc())
    # Table numbers appear in the body so the LLM + grounding numeric-match can see them (D8).
    assert "0.953" in refined.body
    assert "Model | Acc" in refined.body
    assert len(refined.tables) == 1
    table = refined.tables[0]
    assert table.label == "Table 1"
    assert table.anchor == "s1.tbl1"
    assert table.rows[1] == ("Ours", "0.953")


def test_refine_doc_model_collects_sections_formulas_captions() -> None:
    refined = InputRefiner().refine_doc_model(_doc())
    assert [s.label for s in refined.sections] == ["Results", "Ablation"]
    # Section spans index into the projected body (anchor-existence resolves).
    first = refined.sections[0]
    assert refined.body[first.start : first.end] == "Results"
    assert refined.formulas == ("E=mc^2",)
    assert any("Scores." in c for c in refined.captions)
    assert "Sub finding." in refined.body  # nested subsection content included


def test_refine_doc_model_body_stays_aligned_with_root_full_text() -> None:
    doc = _doc()
    refined = InputRefiner().refine_doc_model(doc)

    for expected in ("We report accuracy.", "0.953", "E=mc^2", "Sub finding."):
        assert expected in doc.fullText
        assert expected in refined.body


def test_refine_doc_model_skips_image_only_formula() -> None:
    """A PDF/GROBID page-crop formula carries no LaTeX (assetRef only). Projecting it must not
    crash on the optional latex field — it is display-only, so it is simply omitted from the
    summary input (regression for the latex=None TypeError)."""
    doc = DocModel.model_validate(
        {
            "meta": {
                "paperId": "2401.00002",
                "version": 1,
                "title": "T",
                "provenance": {
                    "sourceTier": "pdf",
                    "parserVersion": "p@1",
                    "schemaVersion": "1.0.0",
                    "generatedAt": "2026-06-23T00:00:00Z",
                },
            },
            "fullText": "Results\n\nWe report accuracy.",
            "sections": [
                {
                    "id": "s1",
                    "title": "Results",
                    "blocks": [
                        {"id": "s1.p1", "type": "paragraph", "text": "We report accuracy."},
                        {
                            "id": "s1.eq1",
                            "type": "formula",
                            "display": True,
                            "anchorLabel": "(3)",
                            "assetRef": {"assetId": "a1", "type": "formula", "ordinal": 0},
                        },
                    ],
                }
            ],
        }
    )

    refined = InputRefiner().refine_doc_model(doc)  # must not raise

    assert refined.formulas == ()  # image-only formula contributes no LaTeX
    assert "We report accuracy." in refined.body


def test_refine_source_dispatches_on_doc_model() -> None:
    refiner = InputRefiner()
    via_doc = refiner.refine_source(SourceText(kind=SourceKind.FULL_TEXT, doc_model=_doc()))
    assert via_doc.tables  # doc-model path populated structured tables
    via_txt = refiner.refine_source(SourceText(kind=SourceKind.ABSTRACT, raw="Plain abstract."))
    assert via_txt.body == "Plain abstract." and via_txt.tables == ()


# --- SourceSelector doc-model-first --------------------------------------


class _FakeFullText:
    def __init__(self, txt: str | None) -> None:
        self._txt = txt

    def get_full_text(self, paper_id: str, version: int) -> str | None:
        return self._txt


class _FakeDocReader:
    def __init__(self, doc: DocModel | None) -> None:
        self._doc = doc
        self.calls: list[tuple] = []

    def get_doc_model(self, paper_id: str, version: int) -> DocModel | None:
        self.calls.append((paper_id, version))
        return self._doc


def _summary_request():
    return _req(Task.SUMMARY, Scope.FULL)


def _req(task, scope):
    from summarization.domain.models import Persona, SummaryRequest, TargetLang

    return SummaryRequest(
        paper_id="2401.00001",
        version=1,
        task=task,
        target_lang=TargetLang.KO,
        persona=Persona.EXPERT,
        scope=scope,
    )


def test_selector_prefers_doc_model_when_available() -> None:
    reader = _FakeDocReader(_doc())
    selector = SourceSelector(_FakeFullText("legacy txt"), doc_model_reader=reader)
    src = selector.select(_summary_request())
    assert src is not None
    assert src.kind is SourceKind.FULL_TEXT
    assert src.doc_model is not None and src.raw == ""
    assert reader.calls == [("2401.00001", 1)]


def test_selector_falls_back_to_plaintext_on_docmodel_miss() -> None:
    selector = SourceSelector(_FakeFullText("legacy txt"), doc_model_reader=_FakeDocReader(None))
    src = selector.select(_summary_request())
    assert src is not None
    assert src.doc_model is None
    assert src.raw == "legacy txt"


def test_selector_unchanged_without_reader() -> None:
    selector = SourceSelector(_FakeFullText("legacy txt"))
    src = selector.select(_summary_request())
    assert src is not None and src.raw == "legacy txt" and src.doc_model is None
