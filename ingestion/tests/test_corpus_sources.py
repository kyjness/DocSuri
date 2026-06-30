from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from docsuri_ingestion.adapters.corpus_http import OpenAlexCorpusSource, SemanticScholarCorpusSource
from docsuri_ingestion.adapters.local import FakeArxivSource, sample_metadata
from docsuri_ingestion.corpus_sources import CorpusSourceAdapterSet, SourcePaperRecord
from docsuri_ingestion.domain.enums import SourceName
from docsuri_ingestion.domain.errors import PermanentIngestionError


class _Grobid:
    def __init__(self, text: str = "structured full text") -> None:
        self.text = text
        self.seen_pdf: bytes | None = None

    def extract_tei(self, pdf: bytes) -> str:
        self.seen_pdf = pdf
        return f"<TEI><text><body><div><p>{self.text}</p></div></body></text></TEI>"


class _ExternalSource:
    def __init__(self, record: SourcePaperRecord) -> None:
        self.record = record
        self.since = None
        self.categories = None
        self.until = None
        self.fetched_record: SourcePaperRecord | None = None

    def fetch_incremental(self, since, categories, until=None):
        self.since = since
        self.categories = tuple(categories)
        self.until = until
        return (self.record,)

    def fetch_pdf(self, record: SourcePaperRecord) -> bytes:
        self.fetched_record = record
        return b"%PDF"


def test_arxiv_source_reuses_existing_html_first_adapter() -> None:
    metadata = sample_metadata()
    adapters = CorpusSourceAdapterSet(arxiv=FakeArxivSource([metadata]))

    candidate = adapters.fetch_arxiv_text(metadata)

    assert candidate.source_name is SourceName.ARXIV
    assert candidate.source_tier == "ARXIV_HTML"
    assert candidate.payload_kind == "HTML"
    assert "deterministic ingestion" in candidate.text.lower()


def test_external_pdf_source_retains_pdf_bytes_for_crop_reuse() -> None:
    grobid = _Grobid()
    adapters = CorpusSourceAdapterSet(arxiv=FakeArxivSource([sample_metadata()]), grobid=grobid)
    record = SourcePaperRecord(
        source_name=SourceName.SEMANTIC_SCHOLAR,
        source_id="s2-1",
        title="Paper",
        pdf_url="https://example.test/paper.pdf",
    )

    candidate = adapters.extract_pdf_text(record, b"%PDF")

    assert grobid.seen_pdf == b"%PDF"
    assert candidate.source_tier == "SEMANTIC_SCHOLAR_GROBID"
    assert candidate.payload_kind == "PDF"
    assert candidate.text == "structured full text"
    # The PDF bytes are kept on the candidate (in-memory only) so the figure/formula crop step
    # reuses them instead of re-fetching — and crops against the same bytes the TEI coords came
    # from. The candidate is never serialized (the queue job carries the SourcePaperRecord).
    assert candidate.pdf == b"%PDF"


def test_external_pdf_source_requires_grobid() -> None:
    adapters = CorpusSourceAdapterSet(arxiv=FakeArxivSource([sample_metadata()]))
    record = SourcePaperRecord(
        source_name=SourceName.OPENALEX,
        source_id="oa-1",
        title="Paper",
        pdf_url="https://example.test/paper.pdf",
    )

    with pytest.raises(PermanentIngestionError):
        adapters.extract_pdf_text(record, b"%PDF")


def test_external_source_incremental_delegates_by_source_name() -> None:
    record = SourcePaperRecord(
        source_name=SourceName.OPENALEX,
        source_id="oa-1",
        title="Paper",
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    provider = _ExternalSource(record)
    adapters = CorpusSourceAdapterSet(
        arxiv=FakeArxivSource([sample_metadata()]),
        openalex=provider,
    )

    records = tuple(
        adapters.fetch_incremental(
            SourceName.OPENALEX,
            datetime(2025, 1, 1, tzinfo=UTC),
            ("cs.LG",),
            datetime(2026, 1, 1, tzinfo=UTC),
        )
    )

    assert records == (record,)
    assert provider.since == datetime(2025, 1, 1, tzinfo=UTC)
    assert provider.categories == ("cs.LG",)
    assert provider.until == datetime(2026, 1, 1, tzinfo=UTC)


def test_source_paper_record_payload_round_trips_retry_metadata() -> None:
    record = SourcePaperRecord(
        source_name=SourceName.SEMANTIC_SCHOLAR,
        source_id="s2-1",
        title="Paper",
        abstract="Abstract",
        authors=("Ada",),
        categories=("cs.LG",),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        published_at=datetime(2025, 12, 1, tzinfo=UTC),
        year=2025,
        pdf_url="https://example.test/p.pdf",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        doi="10.1000/x",
        version=2,
    )

    assert SourcePaperRecord.from_payload(record.to_payload()) == record


def test_external_record_text_fetches_pdf_then_grobid() -> None:
    grobid = _Grobid()
    record = SourcePaperRecord(
        source_name=SourceName.OPENALEX,
        source_id="oa-1",
        title="Paper",
        pdf_url="https://example.test/paper.pdf",
    )
    provider = _ExternalSource(record)
    adapters = CorpusSourceAdapterSet(
        arxiv=FakeArxivSource([sample_metadata()]),
        grobid=grobid,
        openalex=provider,
    )

    candidate = adapters.extract_record_text(record)

    assert provider.fetched_record == record
    assert grobid.seen_pdf == b"%PDF"
    assert candidate.source_tier == "OPENALEX_GROBID"


def test_semantic_scholar_provider_fetches_oa_pdf_records() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("paper.pdf"):
            return httpx.Response(200, content=b"%PDF")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "s2-1",
                        "title": "Paper",
                        "abstract": "Abstract",
                        "authors": [{"name": "Ada"}],
                        "year": 2025,
                        "publicationDate": "2025-01-01",
                        "updated": "2026-01-02T00:00:00Z",
                        "isOpenAccess": True,
                        "externalIds": {"DOI": "10.1000/x", "ArXiv": "2401.00001"},
                        "openAccessPdf": {
                            "url": "https://example.test/paper.pdf",
                            "license": "CC-BY",
                        },
                    }
                ]
            },
        )

    source = SemanticScholarCorpusSource(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    records = source.fetch_incremental(datetime(2026, 1, 1, tzinfo=UTC), ("cs.LG",))

    assert len(records) == 1
    assert records[0].source_name is SourceName.SEMANTIC_SCHOLAR
    assert records[0].pdf_url == "https://example.test/paper.pdf"
    assert records[0].license_url == "https://creativecommons.org/licenses/by/4.0/"
    assert source.fetch_pdf(records[0]) == b"%PDF"


def test_semantic_scholar_bulk_request_omits_limit_and_updated_field() -> None:
    # /paper/search/bulk 400s on `limit` (it paginates by `token`) and on the non-existent
    # `updated` field — regression guard for the 400 that crashed the live tick.
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "search/bulk" in str(request.url):
            captured["has_limit"] = "limit" in request.url.params
            captured["fields"] = request.url.params.get("fields", "")
        return httpx.Response(200, json={"data": []})

    source = SemanticScholarCorpusSource(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    source.fetch_incremental(datetime(2026, 1, 1, tzinfo=UTC), ("cs.LG",))

    assert captured["has_limit"] is False
    assert "updated" not in captured["fields"]


def test_paged_harvest_retries_transient_429_then_succeeds(monkeypatch) -> None:
    # A transient 429 mid-pagination must not discard the whole accumulated run — the failing
    # page is retried. Regression for the unauthenticated-SS backfill aborting on the first 429.
    import docsuri_ingestion.adapters.corpus_http as ch

    monkeypatch.setattr(ch, "_RETRY_BACKOFF_SECONDS", 0.0)  # no real sleep in the test
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"message": "rate limited"})
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "s2-1",
                        "title": "Paper",
                        "abstract": "Abstract",
                        "authors": [{"name": "Ada"}],
                        "year": 2025,
                        "publicationDate": "2025-06-01",
                        "isOpenAccess": True,
                        "externalIds": {"DOI": "10.1000/x"},
                        "openAccessPdf": {
                            "url": "https://example.test/paper.pdf",
                            "license": "CC-BY",
                        },
                    }
                ]
            },
        )

    source = SemanticScholarCorpusSource(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    records = source.fetch_incremental(datetime(2025, 1, 1, tzinfo=UTC), ("cs.LG",))

    assert calls["n"] == 2  # first 429 retried, second attempt served 200
    assert len(records) == 1
    assert records[0].source_id == "s2-1"


def test_openalex_provider_reconstructs_abstract_and_pdf_record() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("paper.pdf"):
            return httpx.Response(200, content=b"%PDF")
        return httpx.Response(
            200,
            json={
                "meta": {"next_cursor": None},
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "ids": {"arxiv": "https://arxiv.org/abs/2401.00001"},
                        "doi": "https://doi.org/10.1000/x",
                        "display_name": "Paper",
                        "abstract_inverted_index": {"hello": [0], "world": [1]},
                        "authorships": [{"author": {"display_name": "Ada"}}],
                        "publication_year": 2025,
                        "publication_date": "2025-01-01",
                        "updated_date": "2026-01-02T00:00:00Z",
                        "primary_location": {
                            "pdf_url": "https://example.test/paper.pdf",
                            "landing_page_url": "https://example.test/paper",
                            "license": "cc-by",
                        },
                        "locations": [],
                    }
                ],
            },
        )

    source = OpenAlexCorpusSource(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )
    # Windowed by publication_date (2025-01-01) now, not updated_date — since must precede it.
    records = source.fetch_incremental(datetime(2024, 12, 31, tzinfo=UTC), ("cs.LG",))

    assert len(records) == 1
    assert records[0].source_name is SourceName.OPENALEX
    assert records[0].updated_at is None  # windows by published_at, uniform with SS
    assert records[0].abstract == "hello world"
    assert records[0].arxiv_id == "2401.00001"
    assert source.fetch_pdf(records[0]) == b"%PDF"
