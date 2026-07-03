"""map_bounded + concurrent map/map-reduce — bounded, order-preserving, fail-fast (BR-S6/BR-S18).

The concurrency is a latency optimization only: the RESULT must be byte-identical to the serial
path (same cache artifact), regardless of completion order or worker count.
"""

from __future__ import annotations

import threading
import time

import pytest

from summarization.domain.map_reduce import MapReduceSummarizer
from summarization.domain.models import (
    Glossary,
    RefinedSource,
    Section,
    SummaryRequest,
    Task,
)
from summarization.domain.parallel import map_bounded
from summarization.domain.structured_translator import StructuredTranslator
from tests.stubs import StubLlm, valid_draft

# --- map_bounded ------------------------------------------------------------------------


def test_map_bounded_preserves_input_order_despite_completion_order() -> None:
    # Earlier items sleep LONGER, so they finish last — the result must still be in input order.
    def fn(i: int) -> int:
        time.sleep((5 - i) * 0.01)
        return i * i

    assert map_bounded(fn, [0, 1, 2, 3, 4], max_workers=4) == [0, 1, 4, 9, 16]


def test_map_bounded_propagates_first_exception() -> None:
    def fn(i: int) -> int:
        if i == 2:
            raise ValueError("boom")
        return i

    with pytest.raises(ValueError, match="boom"):
        map_bounded(fn, [0, 1, 2, 3], max_workers=3)


def test_map_bounded_respects_worker_cap() -> None:
    # Track peak concurrency; it must never exceed max_workers.
    lock = threading.Lock()
    live = 0
    peak = 0

    def fn(_i: int) -> int:
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.02)
        with lock:
            live -= 1
        return _i

    map_bounded(fn, list(range(12)), max_workers=3)
    assert peak <= 3


def test_map_bounded_runs_inline_for_trivial_cases() -> None:
    assert map_bounded(lambda x: x + 1, [10], max_workers=8) == [11]  # single item
    assert map_bounded(lambda x: x + 1, [1, 2, 3], max_workers=1) == [2, 3, 4]  # serial
    assert map_bounded(lambda x: x, [], max_workers=4) == []  # empty


# --- structured translator: parallel == serial -----------------------------------------


def _multi_segment_doc():
    # A doc whose several paragraphs each become their own chunk under a tiny budget.
    from docsuri_shared.dtos import DocModel

    blocks = [{"id": f"s1.p{i}", "type": "paragraph", "text": f"Sentence number {i} about BERT."}
              for i in range(1, 7)]
    return DocModel.model_validate({
        "meta": {"paperId": "2401.1", "version": 1, "title": "T",
                 "provenance": {"sourceTier": "native_html", "parserVersion": "test",
                                "schemaVersion": "1", "generatedAt": "1970-01-01T00:00:00Z"}},
        "fullText": " ".join(b["text"] for b in blocks),
        "sections": [{"id": "s1", "title": "Intro", "blocks": blocks}],
    })


def _translate_req() -> SummaryRequest:
    return SummaryRequest(paper_id="2401.1", version=1, task=Task.TRANSLATE)


def test_translate_parallel_matches_serial() -> None:
    doc = _multi_segment_doc()
    req, gloss = _translate_req(), Glossary()
    # Tiny budget → many chunks → real fan-out.
    serial = StructuredTranslator(
        StubLlm(), chunk_budget_tokens=1, max_workers=1
    ).translate(doc, req, gloss)
    parallel = StructuredTranslator(
        StubLlm(), chunk_budget_tokens=1, max_workers=4
    ).translate(doc, req, gloss)
    assert parallel.doc_model.model_dump(mode="json") == serial.doc_model.model_dump(mode="json")
    assert parallel.kept_terms == serial.kept_terms


def test_translate_parallel_propagates_llm_outage() -> None:
    # A chunk-level LlmUnavailable must surface (→ orchestrator retry/abstain), not be swallowed.
    from summarization.ports.ports import LlmUnavailable

    tr = StructuredTranslator(StubLlm(raise_n=1), chunk_budget_tokens=1, max_workers=4)
    with pytest.raises(LlmUnavailable):
        tr.translate(_multi_segment_doc(), _translate_req(), Glossary())


# --- map-reduce summary: parallel map, sequential reduce --------------------------------


class _CountingLlm:
    """Records summarize() calls; returns a valid draft (map + reduce share this contract)."""

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def summarize(self, refined, request, glossary):
        with self._lock:
            self.calls += 1
        return valid_draft()


def _long_refined() -> RefinedSource:
    # Several sections over a tiny budget → multiple map chunks + one reduce.
    body = "".join(f"Section {i} body about representation learning. " * 40 for i in range(4))
    sections = tuple(Section(label=f"S{i}", start=i * 100, end=(i + 1) * 100) for i in range(4))
    return RefinedSource(body=body, sections=sections, token_count=99999)


def test_map_reduce_parallel_map_preserves_call_count() -> None:
    refined, gloss = _long_refined(), Glossary()
    req = SummaryRequest(paper_id="p", version=1, task=Task.SUMMARY)
    serial_llm, parallel_llm = _CountingLlm(), _CountingLlm()
    s = MapReduceSummarizer(
        serial_llm, chunk_budget_tokens=200, max_workers=1
    ).summarize(refined, req, gloss)
    p = MapReduceSummarizer(
        parallel_llm, chunk_budget_tokens=200, max_workers=3
    ).summarize(refined, req, gloss)
    # Same number of LLM calls (N map + 1 reduce) whether serial or parallel; both yield a draft.
    assert serial_llm.calls == parallel_llm.calls > 1
    assert s.tldr == p.tldr
