"""MapReduceSummarizer (BR-S6, #135, slice 5): section-aware chunk → map → reduce.

The summarizer fans a long refined body out on section boundaries, summarizes each chunk, and
folds the partial summaries into one — returning an ordinary SummaryDraft (same schema as the
single-call path). Uses a recording stub LLM to assert the call fan-out and the reduce input.
"""

from __future__ import annotations

from summarization.domain.map_reduce import MapReduceSummarizer
from summarization.domain.models import RefinedSource, Section, SummaryDraft, SummaryRequest, Task


def _draft(tldr: str = "t") -> SummaryDraft:
    return SummaryDraft(
        tldr=tldr,
        contributions=("c",),
        method="m",
        results="r",
        limitations="l",
        reproducibility={"code": "", "data": ""},
        anchors=(),
    )


class _RecordingLlm:
    """Records each summarize() body so we can assert chunk fan-out + the reduce input."""

    def __init__(self) -> None:
        self.bodies: list[str] = []

    def summarize(self, refined, request, glossary) -> SummaryDraft:
        self.bodies.append(refined.body)
        return _draft(f"d{len(self.bodies)}")

    def translate(self, text, request, glossary):  # pragma: no cover - unused
        raise NotImplementedError


_REQ = SummaryRequest(paper_id="2401.1", version=1, task=Task.SUMMARY)


def _refined_with_three_sections() -> RefinedSource:
    s1 = "Intro paragraph here. " * 4  # ~88 chars ≈ 22 tokens
    s2 = "Method paragraph here. " * 4
    s3 = "Results paragraph here. " * 4
    body = s1 + s2 + s3
    sections = (
        Section(label="Intro", start=0, end=len(s1)),
        Section(label="Method", start=len(s1), end=len(s1) + len(s2)),
        Section(label="Results", start=len(s1) + len(s2), end=len(body)),
    )
    return RefinedSource(body=body, sections=sections, token_count=len(body) // 4)


def test_fans_out_on_section_boundaries_then_reduces() -> None:
    llm = _RecordingLlm()
    # budget 25 tok (~100 chars); each section ~22 tok → one section per chunk → 3 maps + 1 reduce.
    # max_workers=1 keeps the map serial so this test can assert the SECTION order of the recorded
    # bodies deterministically (the parallel-map path is covered by test_parallel.py). Under the
    # default parallel map, `_RecordingLlm.bodies` would reflect worker-completion order, not
    # section order — a scheduling-dependent flaky assertion.
    mr = MapReduceSummarizer(llm, chunk_budget_tokens=25, overlap_chars=0, max_workers=1)

    draft = mr.summarize(_refined_with_three_sections(), _REQ, None)

    assert len(llm.bodies) == 4  # 3 map + 1 reduce
    assert llm.bodies[0].startswith("Intro")
    assert llm.bodies[1].startswith("Method")
    assert llm.bodies[2].startswith("Results")
    # Reduce input is built from the partial summaries (not the raw body).
    assert "부분 요약" in llm.bodies[3]
    assert "d1" in llm.bodies[3] and "d3" in llm.bodies[3]
    # Final draft is the reduce output.
    assert draft.tldr == "d4"


def test_single_call_when_body_fits_budget() -> None:
    llm = _RecordingLlm()
    mr = MapReduceSummarizer(llm)  # default 30K-tok budget → small body fits in one call
    mr.summarize(_refined_with_three_sections(), _REQ, None)
    assert len(llm.bodies) == 1  # no fan-out, no reduce


def test_span_only_body_window_splits_when_oversized() -> None:
    llm = _RecordingLlm()
    # No sections (span-only refine) + body over budget → window-split into multiple chunks.
    body = "x" * 130
    refined = RefinedSource(body=body, sections=(), token_count=len(body) // 4)
    mr = MapReduceSummarizer(llm, chunk_budget_tokens=10, overlap_chars=0)  # 10 tok = 40 chars

    mr.summarize(refined, _REQ, None)

    # 130 chars / 40-char windows → 4 chunks → 4 map + 1 reduce.
    assert len(llm.bodies) == 5
    assert "부분 요약" in llm.bodies[-1]
