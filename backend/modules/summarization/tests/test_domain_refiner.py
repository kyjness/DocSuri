"""InputRefiner — BR-S3 / Q2 / Q6: remove noise, preserve experimental content, derive sections."""

from __future__ import annotations

from summarization.domain.refiner import InputRefiner


def test_removes_references_and_copyright(sample_paper: str) -> None:
    refined = InputRefiner().refine(sample_paper)
    assert "References" not in refined.body
    assert "Some citation" not in refined.body  # references tail dropped
    assert "All rights reserved" not in refined.body  # copyright line dropped


def test_preserves_captions_appendix_and_results(sample_paper: str) -> None:
    refined = InputRefiner().refine(sample_paper)
    # Experimental-info content MUST be preserved (Q2).
    assert "Appendix A" in refined.body
    assert "supplementary results" in refined.body
    assert any("Table 1" in c for c in refined.captions)
    assert "95.3%" in refined.body  # result number preserved


def test_single_line_full_text_survives_copyright_match() -> None:
    # U1-normalized full text arrives as ONE newline-free line. A copyright pattern anywhere in it
    # must not drop the "line" (= the whole document, empty body); only short standalone
    # boilerplate lines are noise (BR-S3/Q2).
    raw = (
        "Introduction We study X in depth. Results reach 95.3% on the benchmark. "
        "(c) 2026 Some Publisher. All rights reserved. Conclusion Y holds. "
    ) * 5
    refined = InputRefiner().refine(raw)
    assert "We study X" in refined.body
    assert "95.3%" in refined.body


def test_derives_sections(sample_paper: str) -> None:
    refined = InputRefiner().refine(sample_paper)
    labels = {s.label for s in refined.sections}
    assert any("INTRODUCTION" in lab for lab in labels)
    assert any("5.2" in lab for lab in labels)
    # Spans point into the body (anchor source, Q6).
    for s in refined.sections:
        assert refined.body[s.start : s.end].strip() == s.label
