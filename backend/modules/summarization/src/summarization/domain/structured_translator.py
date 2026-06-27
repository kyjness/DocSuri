"""StructuredTranslator — structured (doc-model-mirroring) translation (BR-S18 / FR-13, PR-2).

The body translation output keeps **the same structured form as the body** (FR-13): the source
doc-model is walked, its translatable text units (section titles, paragraphs, list items, and
table/figure captions) are translated, and a **translated doc-model** is reassembled with the
SAME structure/ids. Verbatim (never translated): table numeric cells (D8), formula LaTeX, code
blocks, block/section ids, and figure assetRefs — those are copied from the source unchanged.

Long inputs are handled **map-only** (BR-S6/BR-S18): the translatable units are split into
budget-sized chunks, each chunk is translated independently (map), and the results are
re-injected into the single source structure — i.e. the sections are concatenated back, with
**no reduce step** (translation, unlike summary, has nothing to fold). Because a translation's
output volume tracks its input, the per-call budget is bounded by the model's output cap, so
even a "single-call summary band" paper may translate in a few chunks; this is transparent to
the orchestrator.

This component owns only the *algorithm* + structure reassembly. Whether it runs inline or as a
background job is the orchestrator/deployment's concern (BR-S12). Its only LLM dependency is the
gateway's ``translate_segments`` (id → 번역텍스트), invoked once per chunk.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from docsuri_shared.dtos import DocModel

from ..ports.ports import LlmGatewayPort
from .models import Glossary, SummaryRequest, TranslationDraft, TranslationSegment

# Per-chunk budget: bounded by the model's *output* token cap (a translation is ~ the size of
# its input), not the much larger single-call *input* budget used for summary. Conservative
# defaults; runtime-tunable (NFR).
_DEFAULT_CHUNK_BUDGET_TOKENS = 6_000
_CHARS_PER_TOKEN = 4  # matches the refiner's cheap estimate

# Human-readable seg-id suffixes (BR-S18). NOTE: these descriptive ids are NOT used as the LLM
# segment key — translate() keys segments by reading-order index, so correctness does not depend
# on doc-model id uniqueness. The suffixes only make the walk's output legible (debug/tests).
_TITLE_SUFFIX = "#title"
_CAPTION_SUFFIX = "#caption"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


class StructuredTranslator:
    """Drop-in for the translate path: takes the source doc-model and returns a
    ``TranslationDraft`` whose ``doc_model`` mirrors the source structure with Korean text."""

    def __init__(
        self,
        llm: LlmGatewayPort,
        *,
        chunk_budget_tokens: int = _DEFAULT_CHUNK_BUDGET_TOKENS,
    ) -> None:
        self._llm = llm
        self._budget = chunk_budget_tokens

    def translate(
        self, doc: DocModel, request: SummaryRequest, glossary: Glossary
    ) -> TranslationDraft:
        # Work on a dict copy so the source pydantic stays untouched; re-validate at the end so
        # the result is a well-formed DocModel (schema parity, fail-closed on a malformed merge).
        doc_dict = doc.model_dump(mode="json")
        fields = list(iter_text_fields(doc_dict))  # (seg_id, text, setter), reading order
        # Key each segment by its READING-ORDER INDEX, not the doc-model block/section id: the
        # index is unique by construction, so re-injection is correct even if the parser ever
        # emits duplicate ids (the LLM only needs a stable handle to map text back).
        segments = [
            TranslationSegment(id=str(i), text=t) for i, (_sid, t, _set) in enumerate(fields)
        ]

        translations: dict[str, str] = {}
        kept: list[str] = []
        for chunk in self._chunk(segments):
            result = self._llm.translate_segments(chunk, request, glossary)  # map
            translations.update(result.translations)
            for term in result.kept_terms:
                if term not in kept:
                    kept.append(term)

        # Re-inject by index (map-only concat — no reduce). A missing/blank entry keeps the
        # source text; the orchestrator's empty-translation gate catches an all-untranslated draft.
        for i, (_sid, original, setter) in enumerate(fields):
            ko = translations.get(str(i))
            setter(ko if ko and ko.strip() else original)
        doc_dict["fullText"] = project_full_text(doc_dict)

        return TranslationDraft(
            doc_model=DocModel.model_validate(doc_dict), kept_terms=tuple(kept)
        )

    def _chunk(
        self, segments: list[TranslationSegment]
    ) -> Iterator[tuple[TranslationSegment, ...]]:
        """Group segments into output-bounded chunks. A single oversized segment becomes its
        own chunk (the gateway still translates it; the model's cap is the hard limit)."""
        cur: list[TranslationSegment] = []
        cur_tokens = 0
        for seg in segments:
            t = _estimate_tokens(seg.text)
            if cur and cur_tokens + t > self._budget:
                yield tuple(cur)
                cur, cur_tokens = [], 0
            cur.append(seg)
            cur_tokens += t
        if cur:
            yield tuple(cur)


# --- doc-model text-field walk (collect / re-inject) -------------------------
# A single walk yields ``(seg_id, current_text, setter)`` for every TRANSLATABLE text field, so
# collect (read text) and re-inject (call setter) share one id scheme. Reused by the assembler
# for post-substitution. Verbatim fields — table cells, formula latex, code text, ids, assetRefs
# — are never yielded (BR-S18).


def project_full_text(doc_dict: dict[str, Any]) -> str:
    """Flatten the structured doc-model text in reading order.

    This keeps the root ``fullText`` aligned with translated/post-substituted sections without
    exposing asset refs, URLs, or image payloads.
    """
    parts: list[str] = []

    def add(value: object) -> None:
        text = str(value or "").strip()
        if text:
            parts.append(text)

    def walk_section(section: dict[str, Any]) -> None:
        add(section.get("title"))
        for block in section.get("blocks") or []:
            kind = block.get("type")
            if kind in ("paragraph", "code"):
                add(block.get("text"))
            elif kind == "formula":
                add(block.get("latex"))
            elif kind in ("figure", "table"):
                add(" ".join(v for v in (block.get("anchorLabel"), block.get("caption")) if v))
                if kind == "table":
                    for row in block.get("rows") or []:
                        cells = [str(c.get("text", "")).strip() for c in row.get("cells") or []]
                        add(" ".join(cells))
            elif kind == "list":
                for item in block.get("items") or []:
                    add(item.get("text"))
        for sub in section.get("sections") or []:
            walk_section(sub)

    for section in doc_dict.get("sections") or []:
        walk_section(section)
    return "\n\n".join(parts)


def iter_text_fields(
    doc_dict: dict[str, Any],
) -> Iterator[tuple[str, str, Callable[[str], None]]]:
    for section in doc_dict.get("sections") or []:
        yield from _iter_section(section)


def _iter_section(
    section: dict[str, Any],
) -> Iterator[tuple[str, str, Callable[[str], None]]]:
    sid = str(section.get("id", ""))
    title = section.get("title")
    if title:
        yield (f"{sid}{_TITLE_SUFFIX}", title, _setter(section, "title"))
    for block in section.get("blocks") or []:
        yield from _iter_block(block)
    for sub in section.get("sections") or []:
        yield from _iter_section(sub)


def _iter_block(block: dict[str, Any]) -> Iterator[tuple[str, str, Callable[[str], None]]]:
    bid = str(block.get("id", ""))
    kind = block.get("type")
    if kind == "paragraph":
        if block.get("text"):
            yield (bid, block["text"], _setter(block, "text"))
    elif kind in ("table", "figure"):
        # Caption is translated; table numeric cells stay verbatim (D8). Figure pixels are the
        # asset (assetRef copied through).
        if block.get("caption"):
            yield (f"{bid}{_CAPTION_SUFFIX}", block["caption"], _setter(block, "caption"))
    elif kind == "list":
        for i, item in enumerate(block.get("items") or []):
            if item.get("text"):
                yield (f"{bid}#i{i}", item["text"], _setter(item, "text"))
    # formula, code → verbatim (not yielded).


def _setter(node: dict[str, Any], key: str) -> Callable[[str], None]:
    def _set(value: str) -> None:
        node[key] = value

    return _set
