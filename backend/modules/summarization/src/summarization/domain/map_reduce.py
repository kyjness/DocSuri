"""MapReduceSummarizer — bounded long-input summary (BR-S6 / #135, slice 5).

A paper over the single-call context budget (LengthRouter MAP_REDUCE band) is split on
doc-model **section boundaries** (with a small character overlap to keep cross-boundary
context), each chunk is summarized independently (**map**), and the partial summaries are
folded into one final summary (**reduce**). The reduce output is an ordinary ``SummaryDraft``
— identical schema to the single-call path (BR-S6) — so the orchestrator's grounding gate,
retry, assembly, and cache flow are unchanged: it validates the final draft against the FULL
refined body (anchors must still resolve document-wide).

This component owns only the *algorithm*. Whether it runs inline or as a background job is the
orchestrator/deployment's concern (BR-S8); the only LLM dependency is the same
``LlmGatewayPort.summarize`` used by the single-call path, invoked once per chunk + once to
reduce. Extreme inputs beyond the MAP_REDUCE band (OVER_CAP) are rejected upstream — not
handled here.
"""

from __future__ import annotations

from ..ports.ports import LlmGatewayPort
from .models import Glossary, RefinedSource, Section, SummaryDraft, SummaryRequest
from .token_estimate import CHARS_PER_TOKEN, estimate_tokens

# Per-chunk budget kept below the single-call context budget so each map call fits comfortably;
# overlap re-includes a tail of the previous chunk so a result split across a boundary is not
# orphaned. Both are conservative defaults (runtime-tunable, NFR).
_DEFAULT_CHUNK_BUDGET_TOKENS = 30_000
_DEFAULT_OVERLAP_CHARS = 2_000


class MapReduceSummarizer:
    """Drop-in for ``LlmGatewayPort.summarize`` on the MAP_REDUCE band: same signature, returns
    a unified ``SummaryDraft`` produced by chunk → map → reduce."""

    def __init__(
        self,
        llm: LlmGatewayPort,
        *,
        chunk_budget_tokens: int = _DEFAULT_CHUNK_BUDGET_TOKENS,
        overlap_chars: int = _DEFAULT_OVERLAP_CHARS,
    ) -> None:
        self._llm = llm
        self._budget = chunk_budget_tokens
        self._overlap = overlap_chars

    def summarize(
        self, refined: RefinedSource, request: SummaryRequest, glossary: Glossary
    ) -> SummaryDraft:
        chunks = self._chunk(refined)
        if len(chunks) <= 1:
            # Fits one call after all (e.g. one huge section just under budget) — no fan-out.
            return self._llm.summarize(refined, request, glossary)
        partials = [self._llm.summarize(chunk, request, glossary) for chunk in chunks]  # map
        return self._llm.summarize(self._reduce_input(partials), request, glossary)  # reduce

    # --- chunking (section-aware, with overlap) ------------------------------

    def _chunk(self, refined: RefinedSource) -> list[RefinedSource]:
        chunks: list[str] = []
        cur = ""
        for piece in self._section_pieces(refined):
            for seg in self._fit(piece):  # each seg <= budget
                if cur and estimate_tokens(cur) + estimate_tokens(seg) > self._budget:
                    chunks.append(cur)
                    cur = self._tail(cur)  # carry overlap into the next chunk
                cur += seg
        if cur.strip():
            chunks.append(cur)
        return [RefinedSource(body=c, token_count=estimate_tokens(c)) for c in chunks]

    def _section_pieces(self, refined: RefinedSource) -> list[str]:
        """Slice the body at section starts so chunks fall on section boundaries. With no
        sections (span-only refine), the whole body is one piece (then window-split by _fit)."""
        body = refined.body
        starts = sorted({s.start for s in refined.sections if 0 <= s.start <= len(body)})
        if not starts:
            return [body]
        pieces: list[str] = []
        if starts[0] > 0:
            pieces.append(body[: starts[0]])  # preamble before the first section
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(body)
            pieces.append(body[start:end])
        return [p for p in pieces if p]

    def _fit(self, text: str) -> list[str]:
        """Hard-split a single oversized piece (a section larger than the budget) into
        budget-sized character windows; most pieces pass through unchanged."""
        limit = self._budget * CHARS_PER_TOKEN
        if len(text) <= limit:
            return [text]
        return [text[i : i + limit] for i in range(0, len(text), limit)]

    def _tail(self, text: str) -> str:
        return text[-self._overlap :] if self._overlap > 0 else ""

    # --- reduce ---------------------------------------------------------------

    def _reduce_input(self, partials: list[SummaryDraft]) -> RefinedSource:
        """Render the partial summaries as the body of a synthetic refined source, fed back to
        the same summarizer to produce one coherent summary over the whole paper."""
        blocks: list[str] = []
        for i, p in enumerate(partials, start=1):
            contributions = "\n".join(f"- {c}" for c in p.contributions)
            blocks.append(
                f"[부분 요약 {i}]\n"
                f"TL;DR: {p.tldr}\n"
                f"기여:\n{contributions}\n"
                f"방법: {p.method}\n"
                f"결과: {p.results}\n"
                f"한계: {p.limitations}"
            )
        body = "\n\n".join(blocks)
        # One synthetic section so downstream span logic stays well-formed.
        section = Section(label="부분 요약 모음", start=0, end=len(body))
        return RefinedSource(body=body, sections=(section,), token_count=estimate_tokens(body))
