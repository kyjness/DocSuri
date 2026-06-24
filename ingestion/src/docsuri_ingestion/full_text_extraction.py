"""Full-text extraction (BR-29) — produce readable text for two consumers.

Decision D (``decision-q-full-text-extraction.md``): acquire arXiv **HTML first**, fall
back to **PDF text**. The viewer renders the HTML (sanitized at the render layer); the AI
(U7 summary/translate) consumes the derived plain text. The legacy e-print path decoded a
gzip/tar payload as UTF-8 and produced garbage (#139) — never decode a compressed payload
as text.

``html_to_text`` is pure (stdlib only) and unit/PBT tested. ``pdf_to_text`` requires
``pdfplumber`` — a **core** dependency (BR-29); the import is guarded only to fail loudly on a
broken install, not because it is an optional extra.

NOTE (known limitation — accepted until the doc-model parser lands): ``html_to_text`` keeps all
visible text including page chrome (nav/header/footer) and the full reference list, so the
plain-text projection is noisier than "cleanest plain text". The structured doc-model parser
(pivot) replaces this path with section-aware extraction; until then this is a tracked tradeoff.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser


class FullTextExtractionError(Exception):
    """A payload could not be parsed into text (corrupt / non-PDF bytes, etc.).

    Raised by ``pdf_to_text`` so the adapter can classify it (PermanentIngestionError /
    PARSE_FAILURE) instead of letting a raw library exception escape the resilience layer.
    """


# Tags whose text is never body content.
_SKIP_TAGS = {"script", "style", "head", "noscript", "svg", "template"}
# Tags that imply a line/paragraph boundary in the rendered view.
_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "table", "figure", "figcaption", "pre",
}
# Table cells: insert a separator so adjacent cells ("<td>0.92</td><td>0.88</td>") do not
# collapse into "0.920.88". The row stays one line (boundaries come from <tr>); cells split.
_CELL_TAGS = {"td", "th"}

_INLINE_WS = re.compile(r"[ \t\f\v ]+")
_PDF_DEP_MISSING = "pdfplumber not importable (it is a core dependency — check the install)"


class _HtmlTextExtractor(HTMLParser):
    """Collect visible text with coarse block boundaries; drop script/style/etc."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")
        elif tag in _CELL_TAGS:
            self._chunks.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


def html_to_text(html: str) -> str:
    """Strip an HTML document to normalized, readable plain text (pure, deterministic).

    Drops script/style; inserts line breaks at block boundaries; collapses inline
    whitespace and blank-line runs. Idempotent on already-plain text.
    """
    parser = _HtmlTextExtractor()
    parser.feed(html or "")
    parser.close()
    lines = (_INLINE_WS.sub(" ", line).strip() for line in parser.get_text().splitlines())
    return "\n".join(line for line in lines if line).strip()


def pdf_to_text(pdf: bytes) -> str:
    """Extract text from a PDF (best-effort per page).

    ``pdfplumber`` is a core dependency; the import guard only catches a broken install.
    Corrupt or non-PDF bytes (e.g. a 200 HTML stub served at a PDF URL) raise
    ``FullTextExtractionError`` so the adapter classifies them as a permanent parse failure
    rather than letting pdfminer's exception escape the resilience layer.
    """
    try:
        import io

        import pdfplumber
        from pdfplumber.utils.exceptions import PdfminerException
    except ImportError as exc:  # pragma: no cover - defensive guard for a broken core install
        raise RuntimeError(_PDF_DEP_MISSING) from exc

    pages: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            for page in doc.pages:
                extracted = page.extract_text() or ""
                if extracted.strip():
                    pages.append(extracted)
    except PdfminerException as exc:
        raise FullTextExtractionError("payload is not a parseable PDF") from exc
    lines = (_INLINE_WS.sub(" ", line).strip() for line in "\n".join(pages).splitlines())
    return "\n".join(line for line in lines if line).strip()
