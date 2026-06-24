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
