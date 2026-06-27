"""DocModelBuilder (BR-30/D6): lazy build, (paperId, version) cache, source_unavailable."""

from __future__ import annotations

from datetime import UTC, datetime

from docsuri_shared.docmodel_contract import DOCMODEL_PARSER_VERSION, DOCMODEL_SCHEMA_VERSION
from docsuri_shared.dtos import DocModel, DocModelResultDTO, SourceTier, SourceUnavailableDTO

from docsuri_ingestion.adapters.local import sample_metadata
from docsuri_ingestion.docmodel.builder import DocModelBuilder
from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel

_HTML = (
    '<article class="ltx_document"><section class="ltx_section" id="S1">'
    '<h2 class="ltx_title ltx_title_section">Intro</h2>'
    '<div class="ltx_para"><p class="ltx_p">Body.</p></div></section></article>'
)


def _doc(
    paper_id: str = "2401.00001",
    version: int = 1,
    *,
    parser_version: str = DOCMODEL_PARSER_VERSION,
    schema_version: str = DOCMODEL_SCHEMA_VERSION,
) -> DocModel:
    return parse_html_to_docmodel(
        _HTML,
        paper_id=paper_id,
        version=version,
        title="t",
        abstract=None,
        source_tier=SourceTier.native_html,
        parser_version=parser_version,
        schema_version=schema_version,
        generated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )


class _FakeSource:
    def __init__(self, result: tuple[str, SourceTier] | None) -> None:
        self._result = result
        self.calls: list[str] = []

    def fetch_html_source(self, arxiv_id: str) -> tuple[str, SourceTier] | None:
        self.calls.append(arxiv_id)
        return self._result


class _FakeStore:
    def __init__(self, cached: DocModel | None = None) -> None:
        self._cached = cached
        self.put_calls: list[DocModel] = []
        self.removed: list[str] = []

    def get(self, paper_id: str, version: int) -> DocModel | None:
        return self._cached

    def put(self, doc: DocModel) -> str:
        self.put_calls.append(doc)
        return "s3://bucket/doc-model/x.json"

    def remove(self, paper_id: str) -> None:
        self.removed.append(paper_id)


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 6, 23, tzinfo=UTC)


def _builder(
    source: _FakeSource,
    store: _FakeStore,
    *,
    parser_version: str = DOCMODEL_PARSER_VERSION,
    schema_version: str = DOCMODEL_SCHEMA_VERSION,
) -> DocModelBuilder:
    return DocModelBuilder(
        source=source,
        store=store,
        clock=_FixedClock(),
        parser_version=parser_version,
        schema_version=schema_version,
    )


def test_cache_hit_returns_cached_without_fetching() -> None:
    store = _FakeStore(cached=_doc())
    source = _FakeSource((_HTML, SourceTier.native_html))
    result = _builder(source, store).build(sample_metadata("2401.00001v1"))
    assert isinstance(result, DocModelResultDTO)
    assert result.cached is True
    assert source.calls == []  # never touched the network
    assert store.put_calls == []


def test_cache_miss_builds_caches_and_returns_fresh() -> None:
    store = _FakeStore(cached=None)
    source = _FakeSource((_HTML, SourceTier.ar5iv))
    result = _builder(source, store).build(sample_metadata("2401.00001v1"))
    assert isinstance(result, DocModelResultDTO)
    assert result.cached is False
    assert result.docModel.meta.paperId == "2401.00001"
    assert result.docModel.meta.provenance.sourceTier is SourceTier.ar5iv
    assert source.calls == ["2401.00001v1"]
    assert len(store.put_calls) == 1  # cached for next consumer


def test_stale_parser_cache_hit_rebuilds_and_overwrites() -> None:
    store = _FakeStore(cached=_doc(parser_version="docmodel-parser@0"))
    source = _FakeSource((_HTML, SourceTier.native_html))
    result = _builder(source, store).build(sample_metadata("2401.00001v1"))
    assert isinstance(result, DocModelResultDTO)
    assert result.cached is False
    assert source.calls == ["2401.00001v1"]
    assert len(store.put_calls) == 1
    assert store.put_calls[0].meta.provenance.parserVersion == DOCMODEL_PARSER_VERSION


def test_stale_schema_cache_hit_rebuilds_text_doc_model() -> None:
    store = _FakeStore(cached=_doc(schema_version="0.9.0"))
    result = _builder(_FakeSource(None), store).build_from_text(
        sample_metadata("2401.00001v1"), "PDF fallback text."
    )
    assert result.cached is False
    assert len(store.put_calls) == 1
    assert store.put_calls[0].meta.provenance.schemaVersion == DOCMODEL_SCHEMA_VERSION


def test_stale_source_record_cache_hit_rebuilds_from_paper_text() -> None:
    store = _FakeStore(cached=_doc(parser_version="docmodel-parser@0"))
    result = _builder(_FakeSource(None), store).build_from_paper(
        "src-record",
        1,
        "Source Record",
        "Abstract",
        "GROBID text.",
    )
    assert result.cached is False
    assert len(store.put_calls) == 1
    assert store.put_calls[0].meta.paperId == "src-record"


def test_get_cached_filters_stale_cache_entries() -> None:
    store = _FakeStore(cached=_doc(parser_version="docmodel-parser@0"))
    assert _builder(_FakeSource(None), store).get_cached("2401.00001", 1) is None


def test_source_unavailable_when_no_html() -> None:
    store = _FakeStore(cached=None)
    source = _FakeSource(None)
    result = _builder(source, store).build(sample_metadata("2401.00001v1"))
    assert isinstance(result, SourceUnavailableDTO)
    assert result.status == "source_unavailable"
    assert store.put_calls == []


def test_invalidate_drops_cached_versions() -> None:
    store = _FakeStore()
    _builder(_FakeSource(None), store).invalidate("2401.00001")
    assert store.removed == ["2401.00001"]
