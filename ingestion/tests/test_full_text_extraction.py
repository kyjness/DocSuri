"""BR-29 full-text extraction — HTML→text purity/idempotence + fetch HTML→PDF fallback."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from docsuri_ingestion.adapters.local import sample_metadata
from docsuri_ingestion.domain.models import RawDocument
from docsuri_ingestion.full_text_extraction import html_to_text


def test_html_to_text_drops_script_style_and_keeps_blocks() -> None:
    html = (
        "<html><head><style>p{color:red}</style></head>"
        "<body><h1>Title</h1><p>Hello   world</p>"
        "<script>steal()</script><p>Second  line</p></body></html>"
    )
    assert html_to_text(html) == "Title\nHello world\nSecond line"


def test_html_to_text_empty_inputs() -> None:
    assert html_to_text("") == ""
    assert html_to_text("<html><body></body></html>") == ""


def test_html_to_text_idempotent_on_plain_text() -> None:
    plain = "Title\nHello world\nSecond line"
    assert html_to_text(plain) == plain


@given(st.text())
def test_html_to_text_is_pure_and_introduces_no_replacement_chars(text: str) -> None:
    out = html_to_text(text)  # must never raise (purity)
    # html_to_text never DECODES bytes, so it must not *introduce* U+FFFD that the input
    # lacked (the #139 defect lived in the fetch/decode layer, not here). It may faithfully
    # preserve a U+FFFD that the input already contained — st.text() can emit that codepoint.
    assert "�" not in out or "�" in text


class _FakeSource:
    """Minimal ArxivHttpSource double exercising the HTML→PDF fallback branch (BR-29).

    Both branches yield normalized *plain text* only (the viewer renders plain text); HTML is
    the preferred source, PDF the fallback.
    """

    def __init__(self, *, html: str | None, pdf_text: str) -> None:
        self._html = html
        self._pdf_text = pdf_text

    def fetch_full_text(self, metadata) -> RawDocument:
        if self._html is not None:
            text = html_to_text(self._html)
            if text:
                return RawDocument(metadata=metadata, text=text, source_url="html://x")
        return RawDocument(metadata=metadata, text=self._pdf_text, source_url="pdf://x")


def test_fetch_prefers_html_source_as_plain_text() -> None:
    meta = sample_metadata()
    raw = _FakeSource(html="<p>Body text</p>", pdf_text="ignored").fetch_full_text(meta)
    assert raw.text == "Body text"
    assert raw.source_url == "html://x"


def test_fetch_falls_back_to_pdf_when_no_html() -> None:
    meta = sample_metadata()
    raw = _FakeSource(html=None, pdf_text="Extracted PDF body").fetch_full_text(meta)
    assert raw.text == "Extracted PDF body"
    assert raw.source_url == "pdf://x"


def test_html_to_text_separates_adjacent_table_cells() -> None:
    # Adjacent cells must not collapse into a single token ("0.920.88"); the row stays one line.
    out = html_to_text("<table><tr><td>0.92</td><td>0.88</td></tr></table>")
    assert out == "0.92 0.88"
    assert "0.920.88" not in out


def test_pdf_to_text_raises_extraction_error_on_non_pdf_payload() -> None:
    # A 200 HTML stub / corrupt bytes served at a PDF URL must surface as a classifiable
    # FullTextExtractionError, not a raw pdfminer exception (Finding 2 — resilience bypass).
    import pytest

    from docsuri_ingestion.full_text_extraction import FullTextExtractionError, pdf_to_text

    with pytest.raises(FullTextExtractionError):
        pdf_to_text(b"<html>not a pdf</html>")


def test_fetch_full_text_classifies_unparseable_pdf_as_permanent(monkeypatch) -> None:
    # End-to-end of Finding 2: HTML absent → PDF fallback → a 200 non-PDF payload must be
    # classified (PermanentIngestionError / PARSE_FAILURE), never escape as a raw exception.
    import pytest

    from docsuri_ingestion.adapters.arxiv import ArxivHttpSource
    from docsuri_ingestion.domain.enums import FailureReason
    from docsuri_ingestion.domain.errors import PermanentIngestionError

    src = ArxivHttpSource()
    monkeypatch.setattr(src, "_try_get_html", lambda arxiv_id: (None, "html://x"))
    monkeypatch.setattr(
        src, "_get_bytes", lambda url, *, params, stage: b"<html>200 stub, not a pdf</html>"
    )

    with pytest.raises(PermanentIngestionError) as excinfo:
        src.fetch_full_text(sample_metadata())
    assert excinfo.value.reason == FailureReason.PARSE_FAILURE
    assert excinfo.value.stage == "fetch_full_text"


def test_fetch_full_text_prefers_pdf_when_html_conversion_is_truncated(monkeypatch) -> None:
    # A truncated ar5iv conversion returns HTTP 200 but only a sentence of body — worse than the
    # PDF text, so fetch_full_text must fall through to the PDF rather than storing the fragment.
    from docsuri_ingestion.adapters import arxiv as arxiv_mod
    from docsuri_ingestion.adapters.arxiv import ArxivHttpSource

    src = ArxivHttpSource()
    monkeypatch.setattr(
        src, "_try_get_html", lambda arxiv_id: ("<p>Abstract. Let us start.</p>", "html://x")
    )
    monkeypatch.setattr(src, "_get_bytes", lambda url, *, params, stage: b"%PDF-stub")
    monkeypatch.setattr(arxiv_mod, "pdf_to_text", lambda pdf: "Full recovered PDF body. " * 200)

    raw = src.fetch_full_text(sample_metadata())
    assert "Full recovered PDF body." in raw.text
    assert "/pdf/" in raw.source_url  # took the PDF rung, not the truncated HTML


def test_fetch_full_text_keeps_complete_html_conversion(monkeypatch) -> None:
    # A complete HTML conversion (body well above the floor) stays the preferred source and the
    # PDF is never fetched.
    from docsuri_ingestion.adapters.arxiv import ArxivHttpSource

    src = ArxivHttpSource()
    long_html = "<p>" + ("Complete body paragraph. " * 300) + "</p>"

    def _no_pdf(*_a, **_k):
        raise AssertionError("PDF must not be fetched when HTML is complete")

    monkeypatch.setattr(src, "_try_get_html", lambda arxiv_id: (long_html, "html://x"))
    monkeypatch.setattr(src, "_get_bytes", _no_pdf)

    raw = src.fetch_full_text(sample_metadata())
    assert raw.source_url == "html://x"
    assert "Complete body paragraph." in raw.text


def test_fetch_full_text_falls_back_to_short_html_when_pdf_permanently_unavailable(
    monkeypatch,
) -> None:
    # Truncated HTML present + the PDF is PERMANENTLY gone (404 → PermanentIngestionError from
    # _get_bytes, before any parse). A fragment beats failing the paper, so it must fall back to
    # the short HTML rather than propagating the fetch error (regression: only pdf_to_text parse
    # errors used to be caught, so a PDF 404 failed a paper that had usable HTML).
    from docsuri_ingestion.adapters.arxiv import ArxivHttpSource
    from docsuri_ingestion.domain.enums import FailureReason
    from docsuri_ingestion.domain.errors import PermanentIngestionError

    src = ArxivHttpSource()

    def _pdf_404(url, *, params, stage):
        raise PermanentIngestionError(
            "arXiv resource not found", reason=FailureReason.FETCH_FAILURE, stage=stage
        )

    monkeypatch.setattr(
        src, "_try_get_html", lambda arxiv_id: ("<p>Abstract. Let us start.</p>", "html://x")
    )
    monkeypatch.setattr(src, "_get_bytes", _pdf_404)

    raw = src.fetch_full_text(sample_metadata())
    assert raw.source_url == "html://x"  # settled for the short HTML fragment
    assert "Let us start." in raw.text


def test_fetch_full_text_propagates_retriable_pdf_failure_over_short_html(monkeypatch) -> None:
    # Truncated HTML present + a TRANSIENT PDF failure (5xx/timeout → RetriableIngestionError).
    # This must propagate so a later retry can still recover the full PDF, rather than prematurely
    # caching the fragment as the paper's full text.
    import pytest

    from docsuri_ingestion.adapters.arxiv import ArxivHttpSource
    from docsuri_ingestion.domain.enums import FailureReason
    from docsuri_ingestion.domain.errors import RetriableIngestionError

    src = ArxivHttpSource()

    def _pdf_503(url, *, params, stage):
        raise RetriableIngestionError(
            "arXiv returned retriable status 503",
            reason=FailureReason.FETCH_FAILURE,
            stage=stage,
        )

    monkeypatch.setattr(
        src, "_try_get_html", lambda arxiv_id: ("<p>Abstract. Let us start.</p>", "html://x")
    )
    monkeypatch.setattr(src, "_get_bytes", _pdf_503)

    with pytest.raises(RetriableIngestionError):
        src.fetch_full_text(sample_metadata())
