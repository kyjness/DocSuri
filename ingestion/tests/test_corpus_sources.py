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

    def extract_text(self, pdf: bytes) -> str:
        self.seen_pdf = pdf
        return self.text


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


def test_external_pdf_source_uses_grobid_without_returning_pdf_bytes() -> None:
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
    assert not hasattr(candidate, "pdf")


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
    records = source.fetch_incremental(datetime(2026, 1, 1, tzinfo=UTC), ("cs.LG",))

    assert len(records) == 1
    assert records[0].source_name is SourceName.OPENALEX
    assert records[0].abstract == "hello world"
    assert records[0].arxiv_id == "2401.00001"
    assert source.fetch_pdf(records[0]) == b"%PDF"
