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

import logging
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from docsuri_shared.dtos import DocModel

from ..ports.ports import LlmGatewayPort, LlmUnavailable
from .masking import build_mask_table, found_token_indices, mask_text
from .models import Glossary, SummaryRequest, TranslationDraft, TranslationSegment
from .parallel import map_bounded
from .token_estimate import estimate_tokens

logger = logging.getLogger(__name__)

# Per-chunk budget, measured on INPUT tokens but bounded by the model's OUTPUT cap: a Korean
# translation of an English source expands (CJK costs more tokens/char) and the JSON envelope
# (keys, quotes, escaped LaTeX) adds overhead, so the output can outgrow a same-sized input and
# hit the 8192 cap. Kept well under that so a chunk rarely truncates in the first place; a chunk
# that still exceeds it is re-split by ``_translate_chunk`` (correctness no longer depends on this
# estimate being exact). Conservative default; runtime-tunable (NFR).
_DEFAULT_CHUNK_BUDGET_TOKENS = 3_500

# Concurrent chunk translations per request (map-only → chunks are independent, BR-S18). Bounded
# so a many-chunk full-text translation does not fan out unbounded Bedrock calls (throttle/cost).
# Translate chunks are small (output-capped ~3.5K tok), so a modest fan-out is safe; 1 = serial.
_DEFAULT_MAX_WORKERS = 4

# Bounded retries when the model DROPS a masked standard-term token (BR-S4). A dropped token is a
# vanished concept that no read-time step can resurrect (unlike a merely corrupted token, which the
# tolerant restore absorbs), so the chunk is re-sent (split when possible) a few times. After the
# bound the result is accepted fail-soft: the term is simply absent from that sentence — strictly
# better than the pre-masking failure (a WRONG rendering); the drop is logged for diagnosis.
_MAX_TOKEN_RETRIES = 2

# Human-readable seg-id suffixes (BR-S18). NOTE: these descriptive ids are NOT used as the LLM
# segment key — translate() keys segments by reading-order index, so correctness does not depend
# on doc-model id uniqueness. The suffixes only make the walk's output legible (debug/tests).
_TITLE_SUFFIX = "#title"
_CAPTION_SUFFIX = "#caption"


class StructuredTranslator:
    """Drop-in for the translate path: takes the source doc-model and returns a
    ``TranslationDraft`` whose ``doc_model`` mirrors the source structure with Korean text."""

    def __init__(
        self,
        llm: LlmGatewayPort,
        *,
        chunk_budget_tokens: int = _DEFAULT_CHUNK_BUDGET_TOKENS,
        max_workers: int = _DEFAULT_MAX_WORKERS,
    ) -> None:
        self._llm = llm
        self._budget = chunk_budget_tokens
        self._max_workers = max_workers

    def translate(
        self, doc: DocModel, request: SummaryRequest, glossary: Glossary
    ) -> TranslationDraft:
        # Work on a dict copy so the source pydantic stays untouched; re-validate at the end so
        # the result is a well-formed DocModel (schema parity, fail-closed on a malformed merge).
        doc_dict = doc.model_dump(mode="json")
        fields = list(iter_text_fields(doc_dict))  # (seg_id, text, setter), reading order
        # Mask standard terms (BR-S4) into opaque tokens BEFORE the LLM sees the source, so
        # ``Transformer``/``attention`` cannot be translated away; the token-carrying Korean is
        # cached as the shared base and rendered (restored) at serve time. One table per call
        # (seed-derived, deterministic) so tokens are consistent across chunks. ``planted_by_id``
        # records which tokens each segment carried, so a dropped token is detectable post-call.
        table = build_mask_table()
        # Key each segment by its READING-ORDER INDEX, not the doc-model block/section id: the
        # index is unique by construction, so re-injection is correct even if the parser ever
        # emits duplicate ids (the LLM only needs a stable handle to map text back).
        segments: list[TranslationSegment] = []
        planted_by_id: dict[str, set[int]] = {}
        for i, (_sid, t, _set) in enumerate(fields):
            masked, planted = mask_text(t, table)
            segments.append(TranslationSegment(id=str(i), text=masked))
            planted_by_id[str(i)] = planted

        # Map (BR-S18): translate each chunk independently and concurrently (bounded). Each chunk
        # produces a LOCAL (translations, kept, unresolved) tuple — no shared mutation across
        # threads — then results are folded back IN CHUNK ORDER so the merge is deterministic
        # (identical artifact to the serial path; segment ids are global reading-order indices, so
        # the per-chunk translation dicts are disjoint and never collide on merge).
        chunks = list(self._chunk(segments))
        chunk_results = map_bounded(
            lambda chunk: self._translate_chunk(chunk, request, glossary, planted_by_id),
            chunks,
            max_workers=self._max_workers,
        )
        translations: dict[str, str] = {}
        kept: list[str] = []
        unresolved_truncations = 0
        for local_translations, local_kept, unresolved in chunk_results:
            translations.update(local_translations)
            for term in local_kept:
                if term not in kept:
                    kept.append(term)
            unresolved_truncations += unresolved

        if unresolved_truncations:
            # A single oversized segment hit the model's output cap and cannot be split further, so
            # its translation is truncated (partial). Do NOT assemble/cache a known-truncated
            # translation as success (QT-5 HARD fail; FR-13/BR-S18 require a complete structured
            # doc-model). Fail closed → the orchestrator retries then abstains
            # (generation_unavailable), instead of caching a partial doc-model that every later
            # request would then be served.
            logger.warning(
                "structured translate truncated (unresolved leaf) — fail-closed: "
                "paper=%s v=%s scope=%s segments=%d",
                request.paper_id, request.version, request.scope, len(segments),
            )
            raise LlmUnavailable("translation output truncated at the model cap")

        # Re-inject by index (map-only concat — no reduce). A missing/blank entry keeps the
        # source text; the orchestrator's empty-translation gate catches an all-untranslated draft.
        applied = 0
        for i, (_sid, original, setter) in enumerate(fields):
            ko = translations.get(str(i))
            use = ko if ko and ko.strip() else original
            if use != original:
                applied += 1
            setter(use)
        doc_dict["fullText"] = project_full_text(doc_dict)

        # Observability (Part 2-A): an all-unchanged draft makes the orchestrator abstain
        # 'empty_translation' (no model output vs verbatim-only). Log the breakdown so the cause is
        # diagnosable from logs, not only a metric. (Truncation already failed closed above.)
        total = len(fields)
        if applied == 0:
            logger.warning(
                "structured translate low-yield: paper=%s v=%s scope=%s fields=%d "
                "translations_returned=%d applied=0",
                request.paper_id, request.version, request.scope, total, len(translations),
            )
        else:
            logger.info(
                "structured translate: paper=%s v=%s fields=%d applied=%d",
                request.paper_id, request.version, total, applied,
            )

        return TranslationDraft(
            doc_model=DocModel.model_validate(doc_dict), kept_terms=tuple(kept)
        )

    def _translate_chunk(
        self,
        chunk: Sequence[TranslationSegment],
        request: SummaryRequest,
        glossary: Glossary,
        planted_by_id: dict[str, set[int]],
        *,
        token_retries: int = _MAX_TOKEN_RETRIES,
    ) -> tuple[dict[str, str], list[str], int]:
        """Translate one chunk (map) and return its LOCAL ``(translations, kept, unresolved)``.

        Returning local results (rather than mutating shared state) keeps the concurrent map
        thread-safe; the caller folds them back in chunk order. ``unresolved`` is the number of
        leaf chunks that remained truncated after splitting as far as possible. A truncated
        MULTI-segment chunk (the model hit its output cap mid-batch → partial JSON) is split in
        half and each half retried — recursively, down to single segments — so a LaTeX-dense batch
        that under-estimated its output size still yields full translations. A SINGLE segment that
        still truncates cannot be split further; its partial result is folded in (the field is not
        silently lost) but it is reported UNRESOLVED so the caller fails closed rather than caching
        a known-truncated translation (QT-5). The recursive re-split runs inline (a rare truncation
        path within one chunk), not fanned out.

        Masked standard-term tokens (BR-S4) are verified on return: if the model DROPPED a planted
        token (the term vanished — unrecoverable at read time), the chunk is re-sent (split when
        possible) up to ``token_retries`` times. After the bound the result is accepted fail-soft
        (the term is absent from that sentence, never mis-rendered) and the drop is logged.
        """
        result = self._llm.translate_segments(chunk, request, glossary)
        dropped = self._token_drops(chunk, result.translations, planted_by_id)
        # Split a multi-segment chunk when it truncated OR dropped tokens: a smaller batch both
        # fits the output cap and gives the model less to lose, so re-sending halves is a genuinely
        # different (not identical) request. Truncation re-splits regardless of ``token_retries``.
        if len(chunk) > 1 and (result.truncated or (dropped and token_retries > 0)):
            mid = len(chunk) // 2
            reason = "truncated" if result.truncated else "dropped tokens"
            logger.warning(
                "translate chunk %s (%d segs); re-splitting into %d+%d",
                reason, len(chunk), mid, len(chunk) - mid,
            )
            next_retries = token_retries if result.truncated else token_retries - 1
            left = self._translate_chunk(
                chunk[:mid], request, glossary, planted_by_id, token_retries=next_retries
            )
            right = self._translate_chunk(
                chunk[mid:], request, glossary, planted_by_id, token_retries=next_retries
            )
            merged = {**left[0], **right[0]}
            kept = left[1] + [t for t in right[1] if t not in left[1]]
            return merged, kept, left[2] + right[2]
        # Single-segment (unsplittable) token drop: re-send the same segment a bounded number of
        # times (sampling variance can recover the token) before accepting fail-soft.
        if dropped and not result.truncated and len(chunk) <= 1 and token_retries > 0:
            logger.warning(
                "translate token drop on single segment; re-sending (left=%d)", token_retries
            )
            return self._translate_chunk(
                chunk, request, glossary, planted_by_id, token_retries=token_retries - 1
            )
        if dropped and not result.truncated:
            n_dropped = sum(len(d) for d in dropped.values())
            logger.warning(
                "translate token drop persists (fail-soft): paper=%s v=%s segs=%d dropped=%d",
                request.paper_id, request.version, len(chunk), n_dropped,
            )
        return dict(result.translations), list(result.kept_terms), 1 if result.truncated else 0

    @staticmethod
    def _token_drops(
        chunk: Sequence[TranslationSegment],
        translations: dict[str, str],
        planted_by_id: dict[str, set[int]],
    ) -> dict[str, set[int]]:
        """Per-segment set of planted token indices the model failed to return (empty when none)."""
        drops: dict[str, set[int]] = {}
        for seg in chunk:
            planted = planted_by_id.get(seg.id) or set()
            if not planted:
                continue
            missing = planted - found_token_indices(translations.get(seg.id) or "")
            if missing:
                drops[seg.id] = missing
        return drops

    def _chunk(
        self, segments: list[TranslationSegment]
    ) -> Iterator[tuple[TranslationSegment, ...]]:
        """Group segments into output-bounded chunks. A single oversized segment becomes its
        own chunk (the gateway still translates it; the model's cap is the hard limit)."""
        cur: list[TranslationSegment] = []
        cur_tokens = 0
        for seg in segments:
            t = estimate_tokens(seg.text)
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
    # The paper title (meta.title) is a translatable text field too, so the 전문 번역 header is
    # Korean rather than the carried-through original. It is not a section/block, so yield it here
    # (before the section walk) with a setter back into meta. Glossary post-substitution applies.
    meta = doc_dict.get("meta")
    if isinstance(meta, dict) and meta.get("title"):
        yield (f"#meta{_TITLE_SUFFIX}", meta["title"], _setter(meta, "title"))
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
