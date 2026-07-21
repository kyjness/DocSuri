"""Ingesting one paper must not repeat expensive per-paper work.

arXiv is fetched under a 1-request-per-3-seconds politeness budget, so a duplicated GET is not a
micro-cost — it doubles the wall-clock time of the paper it happens on. Page rendering is the
same shape of problem inside the asset path: a 2x page render costs tens of milliseconds, and a
page carrying several figures used to be rendered once per crop.
"""

from __future__ import annotations

from docsuri_ingestion.adapters.arxiv import ArxivHttpSource
from docsuri_ingestion.adapters.local import sample_metadata

_AR5IV_HTML = "<html><body><p>" + ("Body prose. " * 500) + "</p></body></html>"


def _counting_source(monkeypatch) -> tuple[ArxivHttpSource, list[tuple[str, str]]]:
    source = ArxivHttpSource()
    calls: list[tuple[str, str]] = []

    def _fake_fetch(base: str, arxiv_id: str) -> str | None:
        calls.append((base, arxiv_id))
        return _AR5IV_HTML if "ar5iv" in base else None

    monkeypatch.setattr(source, "_fetch_html_at", _fake_fetch)
    return source, calls


def test_full_text_and_doc_model_share_one_html_fetch(monkeypatch) -> None:
    # The eager path asks twice for the same paper's HTML: fetch_full_text takes the plain-text
    # rung and throws the markup away, then the doc-model builder asks for the ar5iv source.
    source, calls = _counting_source(monkeypatch)
    metadata = sample_metadata()

    raw = source.fetch_full_text(metadata)
    assert raw.text
    after_full_text = len(calls)
    assert after_full_text >= 1

    html, tier = source.fetch_html_source(metadata.identifier.arxiv_id)
    assert html == _AR5IV_HTML
    assert tier.value == "ar5iv"

    assert len(calls) == after_full_text, f"doc-model rung re-fetched HTML: {calls}"


def test_a_missing_ar5iv_build_is_not_requested_again(monkeypatch) -> None:
    # A paper with no ar5iv build is the common case for the doc-model rung; re-asking on every
    # call would spend the politeness budget on a known miss.
    source = ArxivHttpSource()
    calls: list[tuple[str, str]] = []

    def _always_missing(base: str, arxiv_id: str) -> str | None:
        calls.append((base, arxiv_id))
        return None

    monkeypatch.setattr(source, "_fetch_html_at", _always_missing)

    assert source.fetch_html_source("2401.00001") is None
    first = len(calls)
    assert source.fetch_html_source("2401.00001") is None
    assert len(calls) == first, "a memoized miss was re-fetched"


def test_the_memo_does_not_serve_one_paper_the_next_papers_html(monkeypatch) -> None:
    # The memo holds a single entry, so it must key on the paper, not just exist.
    source, calls = _counting_source(monkeypatch)

    first = source.fetch_html_source("2401.00001")
    second = source.fetch_html_source("2401.99999")

    assert first is not None and second is not None
    assert [arxiv_id for _base, arxiv_id in calls] == ["2401.00001", "2401.99999"]


def test_one_page_is_rendered_once_for_all_of_its_crops() -> None:
    # A page with several figures produced one full-page render per crop.
    from docsuri_ingestion.asset_extraction import _PageBitmapCache

    renders: list[int] = []

    class _FakePage:
        def __init__(self, page_no: int) -> None:
            self._page_no = page_no

        def render(self, scale: float):
            del scale
            renders.append(self._page_no)
            return self

        def to_pil(self):
            return f"bitmap-of-page-{self._page_no}"

    class _FakeDoc:
        def __getitem__(self, page_no: int) -> _FakePage:
            return _FakePage(page_no)

    doc, cache = _FakeDoc(), _PageBitmapCache()

    for _ in range(5):
        assert cache.page_image(doc, 3) == "bitmap-of-page-3"
    assert renders == [3], f"page 3 rendered {len(renders)} times"

    # Moving to the next page renders it, and the cache holds a single entry so memory stays
    # bounded on a long paper rather than pinning every page.
    assert cache.page_image(doc, 4) == "bitmap-of-page-4"
    assert renders == [3, 4]

    # Returning to a page that fell out of the single slot re-renders — correctness over reuse.
    assert cache.page_image(doc, 3) == "bitmap-of-page-3"
    assert renders == [3, 4, 3]


def test_assets_read_the_pdf_the_text_path_already_cached() -> None:
    # Full text and assets are fetched by two different adapters, so an assets-enabled paper
    # whose text came from the PDF rung downloaded that multi-MB PDF twice. With the B3 cache on,
    # the asset source reads what the text source stored.
    from docsuri_ingestion.adapters.assets import ArxivAssetSource

    class _RawStore:
        def __init__(self) -> None:
            self.rows: dict[tuple[str, int, str], bytes] = {}

        def put_raw(self, paper_id, version, tier, data, *, content_type=""):
            self.rows[(paper_id, version, tier)] = data
            return f"mem://{paper_id}/v{version}/{tier}"

        def get_raw(self, paper_id, version, tier):
            return self.rows.get((paper_id, version, tier))

    metadata = sample_metadata()
    store = _RawStore()
    store.put_raw(metadata.paper_id, metadata.version, "pdf", b"%PDF-cached")

    source = ArxivAssetSource(raw_store=store, raw_cache_mode="prefer")
    downloads: list[str] = []
    source._get = lambda url: downloads.append(url) or b"%PDF-network"  # noqa: SLF001

    assert source.fetch_pdf(metadata) == b"%PDF-cached"
    assert downloads == [], "asset source re-downloaded a cached PDF"


def test_assets_still_fetch_when_the_cache_is_off() -> None:
    # Default configuration must be byte-identical to before the cache was wired in.
    from docsuri_ingestion.adapters.assets import ArxivAssetSource

    source = ArxivAssetSource()
    downloads: list[str] = []
    source._get = lambda url: downloads.append(url) or b"%PDF-network"  # noqa: SLF001

    assert source.fetch_pdf(sample_metadata()) == b"%PDF-network"
    assert len(downloads) == 1
