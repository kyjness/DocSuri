"""ResultAssembler — assemble + SEC-9 filter + serve-time glossary render (BR-S9 / BR-S14).

Builds the terminal ``SummaryResultDTO`` from a grounded draft. SEC-9 exposure control
lives in ``SummaryResultDTO.to_dict`` (no tokens/cost/cache-key/model id). Translation is
assembled as a SHARED base that carries masked standard-term tokens (``⟦N⟧``); at serve time
``render_translation`` restores the tokens to their EFFECTIVE rendering (seed default or the
viewing user's strong override) with josa normalization, applies the user's weak
(post-substitution) terms, builds ``standardGlossary`` from the tokens that occur, and prunes
``keptTerms``. Nothing user-specific is baked into the base, so the cached artifact stays shared
across users (NFR-C1) and a term edit reflects by re-rendering, not by re-generating.
"""

from __future__ import annotations

import copy
import unicodedata

from .glossary import GlossaryResolver, is_glossary_worthy, term_in_text
from .masking import MaskEntry, build_mask_table, contains_token, render_tokens
from .models import (
    Glossary,
    SourceText,
    SummaryDraft,
    SummaryResultDTO,
    Task,
    TranslationDraft,
)
from .structured_translator import iter_text_fields, project_full_text


def _norm_term(s: str) -> str:
    """Canonical key for term comparison: NFC-normalize (so composed/decomposed Hangul match),
    strip, casefold to lower. Keeps the keptTerms/standard-rendering comparison robust to a model
    that emits decomposed Hangul (e.g. ``어텐션`` as jamo)."""
    return unicodedata.normalize("NFC", s).strip().lower()


class ResultAssembler:
    def assemble_summary(self, draft: SummaryDraft, source: SourceText) -> SummaryResultDTO:
        meta = {"source": str(source.kind)}
        if source.fallback_reason:
            meta["fallback"] = source.fallback_reason  # honest "abstract-based summary" note
        return SummaryResultDTO(task=Task.SUMMARY, summary=draft, meta=meta)

    def assemble_translation(
        self, draft: TranslationDraft, source: SourceText
    ) -> SummaryResultDTO:
        # Assemble the SHARED base translation. The generated text carries masked standard-term
        # tokens (``⟦N⟧``); rendering, weak-term overlay and standardGlossary are all deferred to
        # ``render_translation`` on read, so the cached base is user-agnostic and a term edit
        # reflects by re-rendering the SAME base rather than forking/regenerating (NFR-C1/BR-S4).
        meta = {"source": str(source.kind)}  # abstract | full_text (scope=full)
        if source.fallback_reason:
            meta["fallback"] = source.fallback_reason
        return SummaryResultDTO(task=Task.TRANSLATE, translation=draft, meta=meta)

    @staticmethod
    def render_translation(payload: dict, glossary: Glossary) -> dict:
        """Serve-time render of a cached BASE translation payload (BR-S4/BR-S18).

        Steps: ① restore ``⟦N⟧`` tokens to the EFFECTIVE rendering — the user's strong override for
        a seed term, else the seed default (keep-as-is → English, mapping → Korean) — with Korean
        josa normalization; ② apply the user's weak (post-substitution) simple-noun terms; ③
        re-project ``fullText``; ④ build ``standardGlossary`` from the tokens that ACTUALLY occur
        (exact — no string-match heuristic) and prune ``keptTerms`` of math notation. Always run on
        read so a token never reaches the reader; the shared base is unchanged, so different users'
        overrides never fork it. No-op — returns the SAME payload — when not a translation docmodel.

        Migration: an OLD base (pre-masking, no tokens) renders as a clean no-op on the text and
        yields an empty ``standardGlossary``; a PROMPT_VER bump regenerates it under a new key, so
        such bases are not served post-deploy."""
        tr = payload.get("translation")
        if not isinstance(tr, dict) or not isinstance(tr.get("docModel"), dict):
            return payload

        table = build_mask_table()
        strong = {
            m.term_from.lower(): m.term_to
            for m in glossary.user_overrides
            if m.prompt_enforced
        }

        def _effective(entry: MaskEntry) -> str:
            return strong.get(entry.term_from.lower(), entry.seed_render)

        out = copy.deepcopy(payload)
        tr = out["translation"]
        doc = tr["docModel"]
        seen: set[int] = set()
        for _seg_id, text, setter in iter_text_fields(doc):
            rendered, found = render_tokens(text, table, _effective)
            seen |= found
            # Weak simple-noun terms are a per-user overlay on the rendered Korean (idempotent).
            setter(GlossaryResolver.post_substitute(rendered, glossary))
        doc["fullText"] = project_full_text(doc)

        # standardGlossary from the tokens that actually occur in THIS paper (BR-S4). keep-as-is →
        # English chip (carries ``translated`` only when the user overrode it, so the chip stays
        # editable); mapping → always shows the effective Korean rendering. Order follows the table.
        std: list[dict] = []
        for entry in table.entries:
            if entry.index not in seen:
                continue
            eff = _effective(entry)
            if entry.kind == "keepasis":
                chip: dict = {"term": entry.term_from}
                if eff != entry.seed_render:
                    chip["translated"] = eff
            else:
                chip = {"term": entry.term_from, "translated": eff}
            std.append(chip)
        # Fallback: a keep-as-is term occurring ONLY in a verbatim field (table cell / formula) is
        # never masked, so it carries no token — yet it IS present. Recover it by exact presence in
        # the (rendered) fullText so it still shows as a 표준 용어 chip, not dropped or mis-grouped
        # under 원어 유지 (mappings can't reach here: verbatim cells stay English).
        full_text = doc.get("fullText") or ""
        for entry in table.entries:
            if entry.kind != "keepasis" or entry.index in seen:
                continue
            if term_in_text(entry.term_from, full_text):
                eff = _effective(entry)
                chip = {"term": entry.term_from}
                if eff != entry.seed_render:
                    chip["translated"] = eff
                std.append(chip)
        tr["standardGlossary"] = std

        # keptTerms: the model's free-form English-kept terms → the 원어 유지 용어 group. Drop:
        #  · math notation (Greek vars, W_q, mathbb{E}…) via is_glossary_worthy;
        #  · placeholder tokens the model echoed back as "kept" (⟦N⟧) via contains_token;
        #  · standard-term renderings the model echoes from the prompt's variant guidance — these
        #    belong to the 표준 용어 group only (the FE dedup keys on term_from, so it can't catch
        #    the Korean side). Two sources, NFC-normalized for comparison (the model may emit
        #    decomposed Hangul): (a) renderings of standard terms PRESENT in this paper (the ``std``
        #    chips), so a non-standard kept term merely coinciding with an ABSENT seed rendering
        #    (a person "Adam" vs the Adam optimizer) is NOT wrongly removed; (b) ALL mapping
        #    renderings (attention→어텐션…) globally — the model echoes the mapping Korean even for
        #    un-masked variant forms (plurals), and those never collide with a non-standard term.
        strip_set: set[str] = set()
        for chip in std:
            strip_set.add(_norm_term(chip["term"]))
            if chip.get("translated"):
                strip_set.add(_norm_term(chip["translated"]))
        for entry in table.entries:
            if entry.kind == "mapping":
                strip_set.add(_norm_term(entry.term_from))
                strip_set.add(_norm_term(entry.seed_render))
                strip_set.add(_norm_term(_effective(entry)))
        kept = tr.get("keptTerms")
        if isinstance(kept, list):
            tr["keptTerms"] = [
                t
                for t in kept
                if isinstance(t, str)
                and is_glossary_worthy(t)
                and not contains_token(t)
                and _norm_term(t) not in strip_set
            ]
        return out
