"""SourceSelector — task/scope→source with abstract fallback (BR-S2 / Q1 / D2).

summary → full text; absent → abstract fallback (NFR-R2) with a reason; both absent → None
(→ SourceUnavailableDTO). translate scope=full → full text (abstract fallback); scope=abstract
→ abstract.

(D2) The full-text input is the structured **doc-model** when a reader is wired and the
artifact exists (built lazily by U1); it degrades to the legacy plain-text ``.txt`` and then
the abstract. Selection/fallback/DTO logic is otherwise unchanged — only the input upgrades.
"""

from __future__ import annotations

from collections.abc import Callable

from ..ports.ports import DocModelReadPort, FullTextSourcePort
from .models import Scope, SourceKind, SourceText, SummaryRequest, Task


class SourceSelector:
    def __init__(
        self,
        full_text: FullTextSourcePort,
        abstract_lookup: Callable[[str], str | None] | None = None,
        doc_model_reader: DocModelReadPort | None = None,
    ) -> None:
        self._full_text = full_text
        self._abstract_lookup = abstract_lookup
        self._doc_model_reader = doc_model_reader

    def select(self, request: SummaryRequest) -> SourceText | None:
        if request.task == Task.TRANSLATE and request.scope == Scope.ABSTRACT:
            abstract = request.abstract
            if not abstract and self._abstract_lookup:
                try:
                    abstract = self._abstract_lookup(request.paper_id)
                except Exception:
                    abstract = None
            if abstract:
                return SourceText(kind=SourceKind.ABSTRACT, raw=abstract)
            return None

        # summary, or translate scope=full → full text with abstract fallback (Q1/NFR-R2).
        # (D2) Prefer the structured doc-model; degrade to legacy plain text, then abstract.
        if self._doc_model_reader is not None:
            doc = self._doc_model_reader.get_doc_model(request.paper_id, request.version)
            if doc is not None:
                return SourceText(kind=SourceKind.FULL_TEXT, doc_model=doc)

        raw = self._full_text.get_full_text(request.paper_id, request.version)
        if raw:
            return SourceText(kind=SourceKind.FULL_TEXT, raw=raw)

        abstract = request.abstract
        if not abstract and self._abstract_lookup:
            try:
                abstract = self._abstract_lookup(request.paper_id)
            except Exception:
                abstract = None

        if abstract:
            return SourceText(
                kind=SourceKind.ABSTRACT,
                raw=abstract,
                fallback_reason="full_text_unavailable",
            )
        return None
