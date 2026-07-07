"""ArxivHttpSource.fetch_html_source (BR-30, Q6 ladder): ar5iv-only doc-model source.

The doc-model is built from ar5iv (LaTeXML) HTML only — that is what the parser's sanitizer is
built for. Native arXiv HTML leaks raw TeX/pgf into fullText, so it is NOT a doc-model source
(it stays a full-text plain-text rung in ``_try_get_html``); when ar5iv is unavailable the
builder degrades to the PDF/text fallback instead.
"""

from __future__ import annotations

from docsuri_shared.dtos import SourceTier

from docsuri_ingestion.adapters.arxiv import ArxivHttpSource


def _source_with(html_by_base: dict[str, str]) -> ArxivHttpSource:
    src = ArxivHttpSource()

    def fake_get_html_at(base: str, arxiv_id: str) -> str | None:
        return html_by_base.get(base)

    src._get_html_at = fake_get_html_at  # type: ignore[method-assign]
    return src


def test_prefers_ar5iv_when_both_available() -> None:
    src = _source_with(
        {
            "https://ar5iv.labs.arxiv.org/html": "<html>ar5iv</html>",
            "https://arxiv.org/html": "<html>native</html>",
        }
    )
    result = src.fetch_html_source("2401.00001v1")
    assert result == ("<html>ar5iv</html>", SourceTier.ar5iv)


def test_uses_ar5iv_tier() -> None:
    src = _source_with({"https://ar5iv.labs.arxiv.org/html": "<html>ar5iv</html>"})
    result = src.fetch_html_source("2401.00001v1")
    assert result == ("<html>ar5iv</html>", SourceTier.ar5iv)


def test_does_not_use_native_html_for_doc_model() -> None:
    # Native arXiv HTML must never become a doc-model source (raw TeX/pgf leakage). With only
    # native available, fetch_html_source returns None → builder degrades to PDF/text fallback.
    src = _source_with({"https://arxiv.org/html": "<html>native</html>"})
    assert src.fetch_html_source("2401.00001v1") is None


def test_returns_none_when_no_html_rung_yields() -> None:
    assert _source_with({}).fetch_html_source("2401.00001v1") is None
