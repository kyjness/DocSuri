"""ResultAssembler — assemble + SEC-9 filter + read-time glossary overlay (BR-S9 / BR-S14).

Builds the terminal ``SummaryResultDTO`` from a grounded draft. SEC-9 exposure control
lives in ``SummaryResultDTO.to_dict`` (no tokens/cost/cache-key/model id). Translation is
assembled as a SHARED base (strong/seed terms only); the user's weak (post-substitution) terms
are applied as a read-time overlay on the serialized payload (``overlay_translation``, Q8/BR-S4)
so the cached artifact stays shared across users (NFR-C1).
"""

from __future__ import annotations

import copy

from .glossary import GlossaryResolver, is_glossary_worthy
from .models import (
    Glossary,
    SourceText,
    SummaryDraft,
    SummaryResultDTO,
    Task,
    TranslationDraft,
)
from .structured_translator import iter_text_fields, project_full_text


class ResultAssembler:
    def assemble_summary(self, draft: SummaryDraft, source: SourceText) -> SummaryResultDTO:
        meta = {"source": str(source.kind)}
        if source.fallback_reason:
            meta["fallback"] = source.fallback_reason  # honest "abstract-based summary" note
        return SummaryResultDTO(task=Task.SUMMARY, summary=draft, meta=meta)

    def assemble_translation(
        self, draft: TranslationDraft, source: SourceText
    ) -> SummaryResultDTO:
        # Assemble the SHARED base translation (strong/seed terms already applied in the generated
        # text; the translator projected ``fullText``). Weak-term post-substitution is deliberately
        # NOT baked in here — it is a read-time overlay (``overlay_translation``) so the cached
        # artifact is shared across users and a weak edit doesn't fork the cache (NFR-C1/BR-S4).
        meta = {"source": str(source.kind)}  # abstract | full_text (scope=full)
        if source.fallback_reason:
            meta["fallback"] = source.fallback_reason
        return SummaryResultDTO(task=Task.TRANSLATE, translation=draft, meta=meta)

    @staticmethod
    def overlay_translation(payload: dict, glossary: Glossary) -> dict:
        """Read-time overlay: apply the user's weak (post-substitution) simple-noun terms to a
        cached BASE translation payload and return the viewed payload (BR-S4/BR-S18).

        Weak terms are per-user, cheap, deterministic and idempotent (PBT-S3), so they are applied
        on read rather than baked into the shared cache. Verbatim fields (table numeric cells,
        formula LaTeX, code) are not visited; ``fullText`` is re-projected from the substituted
        sections so it stays aligned. No-op — returns the SAME payload — when the user has no weak
        terms (the common case today) or the payload is not a translation doc-model."""
        weak = [m for m in glossary.user_overrides if not m.prompt_enforced]
        if not weak:
            return payload
        doc = payload.get("translation", {}).get("docModel")
        if not isinstance(doc, dict):
            return payload
        out = copy.deepcopy(payload)
        doc = out["translation"]["docModel"]
        for _seg_id, text, setter in iter_text_fields(doc):
            setter(GlossaryResolver.post_substitute(text, glossary))
        doc["fullText"] = project_full_text(doc)
        return out

    @staticmethod
    def filter_kept_terms(payload: dict) -> dict:
        """Drop math-notation entries (Greek vars, ``W_q``, ``L(w+delta)``…) from a translation
        view's ``keptTerms`` so the 원어 유지 용어 list shows keywords, not symbols (BR-S4). Applied
        on the READ path so it also cleans results cached before the filter shipped. Idempotent;
        copies only when it removes something, and never mutates the shared cached object."""
        tr = payload.get("translation")
        if not isinstance(tr, dict) or not isinstance(tr.get("keptTerms"), list):
            return payload
        kept = tr["keptTerms"]
        filtered = [t for t in kept if isinstance(t, str) and is_glossary_worthy(t)]
        if len(filtered) == len(kept):
            return payload
        return {**payload, "translation": {**tr, "keptTerms": filtered}}
