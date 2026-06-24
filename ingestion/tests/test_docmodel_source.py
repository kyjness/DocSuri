"""ArxivHttpSource.fetch_html_source (BR-30, Q6 ladder): native HTML -> ar5iv tiering."""

from __future__ import annotations

from docsuri_shared.dtos import SourceTier

from docsuri_ingestion.adapters.arxiv import ArxivHttpSource


def _source_with(html_by_base: dict[str, str]) -> ArxivHttpSource:
    src = ArxivHttpSource()

    def fake_get_html_at(base: str, arxiv_id: str) -> str | None:
        return html_by_base.get(base)

    src._get_html_at = fake_get_html_at  # type: ignore[method-assign]
    return src


def test_prefers_native_html_tier() -> None:
    src = _source_with({"https://arxiv.org/html": "<html>native</html>"})
    result = src.fetch_html_source("2401.00001v1")
    assert result == ("<html>native</html>", SourceTier.native_html)


def test_falls_back_to_ar5iv_tier() -> None:
    src = _source_with({"https://ar5iv.labs.arxiv.org/html": "<html>ar5iv</html>"})
    result = src.fetch_html_source("2401.00001v1")
    assert result == ("<html>ar5iv</html>", SourceTier.ar5iv)


def test_returns_none_when_no_html_rung_yields() -> None:
    assert _source_with({}).fetch_html_source("2401.00001v1") is None
