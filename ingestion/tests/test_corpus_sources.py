from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from docsuri_ingestion.adapters.corpus_http import OpenAlexCorpusSource, SemanticScholarCorpusSource
from docsuri_ingestion.adapters.local import FakeArxivSource, sample_metadata
from docsuri_ingestion.corpus_sources import CorpusSourceAdapterSet, SourcePaperRecord
from docsuri_ingestion.domain.enums import SourceName
from docsuri_ingestion.domain.errors import (
    PermanentIngestionError,
    RetriableIngestionError,
)


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
        return b"%PDF-1.7 body"


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

    candidate = adapters.extract_pdf_text(record, b"%PDF-1.7 body")

    assert grobid.seen_pdf == b"%PDF-1.7 body"
    assert candidate.source_tier == "SEMANTIC_SCHOLAR_GROBID"
    assert candidate.payload_kind == "PDF"
    assert candidate.text == "structured full text"
    # The PDF bytes are kept on the candidate (in-memory only) so the figure/formula crop step
    # reuses them instead of re-fetching — and crops against the same bytes the TEI coords came
    # from. The candidate is never serialized (the queue job carries the SourcePaperRecord).
    assert candidate.pdf == b"%PDF-1.7 body"


def test_external_pdf_source_requires_grobid() -> None:
    adapters = CorpusSourceAdapterSet(arxiv=FakeArxivSource([sample_metadata()]))
    record = SourcePaperRecord(
        source_name=SourceName.OPENALEX,
        source_id="oa-1",
        title="Paper",
        pdf_url="https://example.test/paper.pdf",
    )

    with pytest.raises(PermanentIngestionError):
        adapters.extract_pdf_text(record, b"%PDF-1.7 body")


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
    assert grobid.seen_pdf == b"%PDF-1.7 body"
    assert candidate.source_tier == "OPENALEX_GROBID"


def test_semantic_scholar_provider_fetches_oa_pdf_records() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("paper.pdf"):
            return httpx.Response(200, content=b"%PDF-1.7 body")
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
    records = list(source.fetch_incremental(datetime(2026, 1, 1, tzinfo=UTC), ("cs.LG",)))

    assert len(records) == 1
    assert records[0].source_name is SourceName.SEMANTIC_SCHOLAR
    assert records[0].pdf_url == "https://example.test/paper.pdf"
    assert records[0].license_url == "https://creativecommons.org/licenses/by/4.0/"
    assert source.fetch_pdf(records[0]) == b"%PDF-1.7 body"


def test_semantic_scholar_rejects_spoofed_license_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
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
                        "isOpenAccess": True,
                        "externalIds": {"DOI": "10.1000/x"},
                        "openAccessPdf": {
                            "url": "https://example.test/paper.pdf",
                            "license": (
                                "https://example.test/?next="
                                "https://creativecommons.org/licenses/by/4.0/"
                            ),
                        },
                    }
                ]
            },
        )

    source = SemanticScholarCorpusSource(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
    )

    assert list(source.fetch_incremental(datetime(2025, 1, 1, tzinfo=UTC), ("cs.LG",))) == []


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
    # list() drives the generator: the harvest is lazy now, so a bare call would make no
    # request at all and leave the assertions below inspecting nothing.
    list(source.fetch_incremental(datetime(2026, 1, 1, tzinfo=UTC), ("cs.LG",)))

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
    records = list(source.fetch_incremental(datetime(2025, 1, 1, tzinfo=UTC), ("cs.LG",)))

    assert calls["n"] == 2  # first 429 retried, second attempt served 200
    assert len(records) == 1
    assert records[0].source_id == "s2-1"


def test_openalex_provider_reconstructs_abstract_and_pdf_record() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("paper.pdf"):
            return httpx.Response(200, content=b"%PDF-1.7 body")
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
    records = list(source.fetch_incremental(datetime(2024, 12, 31, tzinfo=UTC), ("cs.LG",)))

    assert len(records) == 1
    assert records[0].source_name is SourceName.OPENALEX
    assert records[0].updated_at is None  # windows by published_at, uniform with SS
    assert records[0].abstract == "hello world"
    assert records[0].arxiv_id == "2401.00001"
    assert source.fetch_pdf(records[0]) == b"%PDF-1.7 body"


# --- 기동 검증에서 드러난 결함들 (2026-08-10) ---------------------------------
#
# The S2/OpenAlex path had never been run. Doing so end-to-end put 0 of 6 papers into a doc-model:
# every failure was in how we talk to publishers, not in the parser. These pin the fixes.


def _openalex_work(locations: list[dict], primary: dict | None = None) -> dict:
    return {
        "id": "https://openalex.org/W1",
        "ids": {},
        "display_name": "Paper",
        "abstract_inverted_index": {"hello": [0]},
        "authorships": [],
        "publication_year": 2025,
        "publication_date": "2025-01-01",
        "primary_location": primary if primary is not None else locations[0],
        "locations": locations,
    }


def _openalex_source(handler) -> OpenAlexCorpusSource:
    return OpenAlexCorpusSource(
        base_url="https://example.test", transport=httpx.MockTransport(handler)
    )


def _harvest(source) -> list[SourcePaperRecord]:
    return list(source.fetch_incremental(datetime(2024, 12, 31, tzinfo=UTC), ("cs.LG", "cs.CV")))


def test_outbound_requests_say_who_we_are() -> None:
    """Unidentified requests are answered with a landing page or a 403 by real publishers.

    Springer and Nature returned HTTP 200 with 3 KB of HTML — not an error, just not the paper —
    and Cureus returned 403, all of which stopped when the client identified itself.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        if str(request.url).endswith("paper.pdf"):
            return httpx.Response(200, content=b"%PDF-1.7 body")
        return httpx.Response(
            200,
            json={
                "results": [
                    _openalex_work(
                        [
                            {
                                "pdf_url": "https://example.test/paper.pdf",
                                "license": "cc-by",
                                "landing_page_url": "https://example.test/paper",
                            }
                        ]
                    )
                ],
                "meta": {"next_cursor": None},
            },
        )

    source = OpenAlexCorpusSource(
        base_url="https://example.test",
        transport=httpx.MockTransport(handler),
        contact="ops@example.test",
    )
    records = _harvest(source)
    source.fetch_pdf(records[0])

    assert seen, "no request was made"
    assert all(agent.startswith("DocSuri/") for agent in seen), seen
    assert all("ops@example.test" in agent for agent in seen), seen


def test_a_landing_page_served_as_a_pdf_is_a_permanent_failure() -> None:
    """A 200 carrying HTML used to be handed to GROBID, whose 500 is RETRIABLE — so the job went
    round the retry loop into the DLQ instead of being rejected once."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<!DOCTYPE html><html>not a paper</html>")

    record = SourcePaperRecord(
        source_name=SourceName.OPENALEX,
        source_id="W1",
        title="Paper",
        pdf_url="https://example.test/paper.pdf",
    )
    source = _openalex_source(handler)
    with pytest.raises(PermanentIngestionError):
        source.fetch_pdf(record)


def test_a_refused_copy_falls_through_to_the_next_one() -> None:
    tried: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tried.append(str(request.url))
        if "repo" in str(request.url):
            return httpx.Response(200, content=b"%PDF-1.7 body")
        return httpx.Response(403)

    record = SourcePaperRecord(
        source_name=SourceName.OPENALEX,
        source_id="W1",
        title="Paper",
        pdf_url="https://example.test/publisher.pdf",
        alternate_pdf_urls=("https://example.test/repo.pdf",),
    )
    assert _openalex_source(handler).fetch_pdf(record) == b"%PDF-1.7 body"
    assert len(tried) == 2


def test_a_transient_failure_is_not_walked_past() -> None:
    """429/5xx mean "ask again later". Moving to another copy would turn a blip into a permanent
    choice of a worse source, so the retriable error propagates and the fallback stays unused."""
    tried: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tried.append(str(request.url))
        return httpx.Response(503)

    record = SourcePaperRecord(
        source_name=SourceName.OPENALEX,
        source_id="W1",
        title="Paper",
        pdf_url="https://example.test/publisher.pdf",
        alternate_pdf_urls=("https://example.test/repo.pdf",),
    )
    with pytest.raises(RetriableIngestionError):
        _openalex_source(handler).fetch_pdf(record)
    assert tried == ["https://example.test/publisher.pdf"]


def test_only_copies_that_pass_the_licence_gate_become_candidates() -> None:
    """Each OpenAlex location carries its own licence. Pairing one location's URL with another's
    licence would record a paper as CC-BY on the strength of a copy we never fetched."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    _openalex_work(
                        [
                            {"pdf_url": "https://example.test/a.pdf", "license": "cc-by"},
                            {"pdf_url": "https://example.test/nc.pdf", "license": "cc-by-nc"},
                            {"pdf_url": "https://example.test/none.pdf", "license": None},
                            {"pdf_url": "https://example.test/b.pdf", "license": "cc-by-sa"},
                        ]
                    )
                ],
                "meta": {"next_cursor": None},
            },
        )

    record = _harvest(_openalex_source(handler))[0]
    assert record.pdf_url == "https://example.test/a.pdf"
    assert record.alternate_pdf_urls == ("https://example.test/b.pdf",)


def test_the_candidate_walk_is_bounded() -> None:
    tried: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tried.append(str(request.url))
        return httpx.Response(403)

    record = SourcePaperRecord(
        source_name=SourceName.OPENALEX,
        source_id="W1",
        title="Paper",
        pdf_url="https://example.test/0.pdf",
        alternate_pdf_urls=tuple(f"https://example.test/{i}.pdf" for i in range(1, 9)),
    )
    with pytest.raises(PermanentIngestionError):
        _openalex_source(handler).fetch_pdf(record)
    assert len(tried) == 3


def test_alternate_copies_survive_the_queue_round_trip() -> None:
    record = SourcePaperRecord(
        source_name=SourceName.OPENALEX,
        source_id="W1",
        title="Paper",
        pdf_url="https://example.test/a.pdf",
        alternate_pdf_urls=("https://example.test/b.pdf",),
    )
    assert SourcePaperRecord.from_payload(record.to_payload()) == record


def test_the_harvest_asks_for_alternatives_not_a_conjunction() -> None:
    """Space-joining the slice's phrases is read by both APIs as "must contain all of these" —
    measured, that cost Semantic Scholar 306 results where the disjunction returns 22,039."""
    from docsuri_ingestion.adapters.corpus_http import _query

    assert _query(("cs.LG", "cs.CV"), joiner="|") == "computer vision | machine learning"
    assert _query(("cs.LG", "cs.CV"), joiner="OR") == "computer vision OR machine learning"


def test_openalex_harvests_computer_science_not_everything_that_says_machine_learning() -> None:
    """Semantic Scholar is asked for `fieldsOfStudy=Computer Science`; OpenAlex had no field
    filter at all, so a real week came back as intensive-care medicine and water management."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("filter", ""))
        return httpx.Response(200, json={"results": [], "meta": {"next_cursor": None}})

    _harvest(_openalex_source(handler))
    assert seen and "primary_topic.field.id:fields/17" in seen[0]
