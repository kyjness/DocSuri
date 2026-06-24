"""ResultAssembler — assemble + SEC-9 filter + post-substitution (BR-S9 / BR-S14).

Builds the terminal ``SummaryResultDTO`` from a grounded draft. SEC-9 exposure control
lives in ``SummaryResultDTO.to_dict`` (no tokens/cost/cache-key/model id). User-preference
simple-noun post-substitution is applied to translation text here (Q8).
"""

from __future__ import annotations

from docsuri_shared.dtos import DocModel

from .glossary import GlossaryResolver
from .models import (
    Glossary,
    SourceText,
    SummaryDraft,
    SummaryResultDTO,
    Task,
    TranslationDraft,
)
from .structured_translator import iter_text_fields


class ResultAssembler:
    def assemble_summary(self, draft: SummaryDraft, source: SourceText) -> SummaryResultDTO:
        meta = {"source": str(source.kind)}
        if source.fallback_reason:
            meta["fallback"] = source.fallback_reason  # honest "abstract-based summary" note
        return SummaryResultDTO(task=Task.SUMMARY, summary=draft, meta=meta)

    def assemble_translation(
        self, draft: TranslationDraft, glossary: Glossary, source: SourceText
    ) -> SummaryResultDTO:
        # Deterministic post-substitution for user-preference simple nouns (no LLM re-call),
        # applied to every translated text field of the doc-model (BR-S4/BR-S18). Verbatim
        # fields (table cells, formula latex, code) are not visited.
        doc_dict = draft.doc_model.model_dump(mode="json")
        for _seg_id, text, setter in iter_text_fields(doc_dict):
            setter(GlossaryResolver.post_substitute(text, glossary))
        final = TranslationDraft(
            doc_model=DocModel.model_validate(doc_dict), kept_terms=draft.kept_terms
        )
        meta = {"source": str(source.kind)}  # abstract | full_text (scope=full)
        if source.fallback_reason:
            meta["fallback"] = source.fallback_reason
        return SummaryResultDTO(task=Task.TRANSLATE, translation=final, meta=meta)
