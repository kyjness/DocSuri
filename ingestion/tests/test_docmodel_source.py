"""ArxivHttpSource.fetch_html_source (BR-30, Q6 ladder): ar5iv-only HTML rung.

Since the 2026-08-10 revision native arXiv HTML is gone from BOTH ladders (doc-model and full
text) — the adapter is not even configured with the ``arxiv.org/html`` base. When ar5iv yields
nothing, fetch_html_source returns ``None`` and the builder moves down the ladder (PDF/GROBID)
instead of ever touching a different HTML toolchain.
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


def test_uses_ar5iv_tier() -> None:
    src = _source_with({"https://ar5iv.labs.arxiv.org/html": "<html>ar5iv</html>"})
    result = src.fetch_html_source("2401.00001v1")
    assert result == ("<html>ar5iv</html>", SourceTier.ar5iv)


def test_native_base_is_not_configured() -> None:
    # The native rung is removed at the CONFIG level, not by a filter: even if arxiv.org/html
    # would answer, the adapter never asks it — the base is absent from the ladder entirely.
    src = _source_with({"https://arxiv.org/html": "<html>native</html>"})
    assert src.fetch_html_source("2401.00001v1") is None
    assert "ar5iv" in src._html_base_url


def test_returns_none_when_no_html_rung_yields() -> None:
    assert _source_with({}).fetch_html_source("2401.00001v1") is None


class _RawStoreWithNativeLeftover:
    """A raw cache written before the native removal: it still holds a native_html object."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    def get_raw(self, paper_id: str, version: int, kind: str) -> bytes | None:
        self.requested.append(kind)
        return b"<html>stale native</html>" if kind == SourceTier.native_html.value else None

    def put_raw(self, *a, **k) -> None:  # pragma: no cover - not exercised
        raise AssertionError("only-mode must never write")


def test_only_mode_ignores_stale_native_raw_cache() -> None:
    from docsuri_ingestion.domain.models import MetadataRecord

    # Re-serving a pre-removal native_html raw object would re-admit the removed rung through
    # the cache. The adapter must ask the cache for ar5iv only and report a miss.
    store = _RawStoreWithNativeLeftover()
    src = ArxivHttpSource(raw_store=store, raw_cache_mode="only")
    md = MetadataRecord(arxiv_ref="2401.00001v1", title="t", authors=(), abstract="",
                        categories=(), updated_at=None, published_at=None)
    html, _url = src._acquire_html(md)
    assert html is None
    assert store.requested == [SourceTier.ar5iv.value]  # never asked for the native object
