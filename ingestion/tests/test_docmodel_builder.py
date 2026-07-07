"""DocModelBuilder (BR-30/D6): lazy build, (paperId, version) cache, source_unavailable."""

from __future__ import annotations

from datetime import UTC, datetime

from docsuri_shared.docmodel_contract import DOCMODEL_PARSER_VERSION, DOCMODEL_SCHEMA_VERSION
from docsuri_shared.dtos import DocModel, DocModelResultDTO, SourceTier, SourceUnavailableDTO

from docsuri_ingestion.adapters.local import sample_metadata
from docsuri_ingestion.docmodel.builder import DocModelBuilder
from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel

# A body long enough (non-abstract text ≥ the builder's completeness floor) to represent a
# COMPLETE conversion — a truncated ar5iv conversion is exercised separately by _TRUNCATED_HTML.
_BODY_PARAGRAPH = "This is a full paragraph of body prose. " * 20  # ~800 chars
_HTML = (
    '<article class="ltx_document"><section class="ltx_section" id="S1">'
    '<h2 class="ltx_title ltx_title_section">Intro</h2>'
    f'<div class="ltx_para"><p class="ltx_p">{_BODY_PARAGRAPH}</p></div></section></article>'
)

# A COMPLETE paper whose body prose lives entirely in a SUBSECTION (nested section tree). The
# top-level section has no direct blocks — the completeness gate must recurse into child sections.
_NESTED_BODY_HTML = (
    '<article class="ltx_document"><section class="ltx_section" id="S1">'
    '<h2 class="ltx_title ltx_title_section">Intro</h2>'
    '<section class="ltx_subsection" id="S1.SS1">'
    '<h3 class="ltx_title ltx_title_subsection">Sub</h3>'
    f'<div class="ltx_para"><p class="ltx_p">{_BODY_PARAGRAPH}</p></div>'
    '</section></section></article>'
)


# ar5iv (LaTeXML) conversion failed: HTTP 200 but the body is a single sentence (abstract-only).
_TRUNCATED_HTML = (
    '<article class="ltx_document"><section class="ltx_section" id="S1">'
    '<h2 class="ltx_title ltx_title_section">Preliminaries</h2>'
    '<div class="ltx_para"><p class="ltx_p">Let us start.</p></div></section></article>'
)


def _doc(
    paper_id: str = "2401.00001",
    version: int = 1,
    *,
    parser_version: str = DOCMODEL_PARSER_VERSION,
    schema_version: str = DOCMODEL_SCHEMA_VERSION,
    source_tier: SourceTier = SourceTier.ar5iv,
) -> DocModel:
    return parse_html_to_docmodel(
        _HTML,
        paper_id=paper_id,
        version=version,
        title="t",
        abstract=None,
        source_tier=source_tier,
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


_TEI = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
    "<div><head>Method</head><p>Body text.</p></div>"
    "</body></text></TEI>"
)
_EMPTY_BODY_TEI = '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body /></text></TEI>'


def test_build_from_tei_produces_structured_sections() -> None:
    store = _FakeStore()
    builder = _builder(_FakeSource(None), store)
    result = builder.build_from_tei("src-1", 1, "Title", "Abs", _TEI, "fallback text")
    assert result.cached is False
    titles = [s.title for s in result.docModel.sections]
    assert "Method" in titles
    assert store.put_calls  # cached for reuse


def test_build_from_tei_falls_back_to_flat_text_on_bad_tei() -> None:
    store = _FakeStore()
    builder = _builder(_FakeSource(None), store)
    result = builder.build_from_tei("src-2", 1, "Title", "Abs", "<TEI", "flat fallback body")
    # malformed TEI -> flat-text doc-model carrying the fallback text as a single paragraph
    assert "flat fallback body" in result.docModel.fullText


def test_build_from_tei_falls_back_to_flat_text_on_empty_body_tei() -> None:
    store = _FakeStore()
    builder = _builder(_FakeSource(None), store)
    result = builder.build_from_tei(
        "src-3", 1, "Title", "Abs", _EMPTY_BODY_TEI, "flat fallback body"
    )

    assert "flat fallback body" in result.docModel.fullText
    assert store.put_calls[-1].fullText == result.docModel.fullText


_TEI_FORMULA = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div><head>M</head>'
    '<formula coords="1,5,6,30,12"><label>(2)</label>x=y</formula>'
    "</div></body></text></TEI>"
)


def test_build_from_tei_collects_crop_specs_in_one_parse() -> None:
    # The asset step reuses the crop specs gathered during this single TEI parse (out-param)
    # instead of re-parsing via tei_crop_specs. assetIds match the doc-model blocks (same walk).
    store = _FakeStore()
    builder = _builder(_FakeSource(None), store)
    crops: list = []
    result = builder.build_from_tei("src-9", 1, "T", "A", _TEI_FORMULA, "fb", crops=crops)
    assert result.cached is False
    assert [c.asset_id for c in crops] == ["src-9:v1:formula:0"]


def test_build_from_tei_skips_crop_collection_on_cache_hit() -> None:
    # A cache hit does not parse the TEI, so crops stays empty — the caller relies on this
    # (via result.cached) to fall back to deriving the specs from the TEI itself.
    store = _FakeStore(cached=_doc())
    builder = _builder(_FakeSource(None), store)
    crops: list = []
    result = builder.build_from_tei("src-1", 1, "T", "A", _TEI_FORMULA, "fb", crops=crops)
    assert result.cached is True
    assert crops == []


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


def test_native_html_cache_is_never_fresh_and_rebuilds() -> None:
    # A native_html doc-model at the CURRENT parser/schema is still refused by the U7 reader, so it
    # must NOT count as a cache hit here — otherwise the reader-triggered rebuild short-circuits on
    # the cache and never replaces it, and the paper is re-enqueued forever. The build must re-fetch
    # (now ar5iv) and overwrite the native_html object.
    store = _FakeStore(cached=_doc(source_tier=SourceTier.native_html))
    source = _FakeSource((_HTML, SourceTier.ar5iv))
    result = _builder(source, store).build(sample_metadata("2401.00001v1"))
    assert isinstance(result, DocModelResultDTO)
    assert result.cached is False
    assert source.calls == ["2401.00001v1"]  # re-fetched, not served from the native_html cache
    assert len(store.put_calls) == 1
    assert store.put_calls[0].meta.provenance.sourceTier is SourceTier.ar5iv  # replaced


def test_get_cached_rejects_native_html_even_at_current_version() -> None:
    store = _FakeStore(cached=_doc(source_tier=SourceTier.native_html))
    assert _builder(_FakeSource(None), store).get_cached("2401.00001", 1) is None


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


def test_build_degrades_to_source_unavailable_when_conversion_is_truncated() -> None:
    # A broken ar5iv conversion returns HTML 200 but only a sentence of body (the rest of the
    # LaTeX failed to convert). It must NOT be cached as a complete doc-model — degrade to
    # source_unavailable (arXiv link-out) instead of shipping a fragment as the full text.
    store = _FakeStore(cached=None)
    source = _FakeSource((_TRUNCATED_HTML, SourceTier.ar5iv))
    result = _builder(source, store).build(sample_metadata("2401.00001v1"))
    assert isinstance(result, SourceUnavailableDTO)
    assert store.put_calls == []  # nothing cached


def test_build_counts_body_in_nested_subsections() -> None:
    # Regression: a complete paper's body prose can live entirely in a subsection. The
    # completeness gate must recurse into child sections — otherwise the top-level section has no
    # direct blocks, body length reads 0, and the paper is wrongly degraded to source_unavailable
    # (throwing away a valid structured HTML doc-model for the flat PDF fallback).
    store = _FakeStore(cached=None)
    source = _FakeSource((_NESTED_BODY_HTML, SourceTier.ar5iv))
    result = _builder(source, store).build(sample_metadata("2401.00001v1"))
    assert isinstance(result, DocModelResultDTO)  # NOT degraded
    assert len(store.put_calls) == 1


def test_completeness_gate_counts_non_paragraph_body_blocks() -> None:
    # Regression: body prose can live in list items / table cells, not only paragraphs. The gate
    # summed only block["text"], so a complete paper whose non-abstract body is mostly a list/table
    # (little direct paragraph text) read ~0 and was wrongly degraded. Every text-bearing block
    # type must contribute to the length signal.
    from docsuri_ingestion.docmodel.builder import _non_abstract_body_len

    item = {"text": "A substantial bulleted contribution describing the method in detail. "}
    doc = DocModel.model_validate(
        {
            "meta": {
                "paperId": "2401.00001",
                "version": 1,
                "title": "T",
                "provenance": {
                    "sourceTier": "ar5iv",
                    "parserVersion": DOCMODEL_PARSER_VERSION,
                    "schemaVersion": DOCMODEL_SCHEMA_VERSION,
                    "generatedAt": "1970-01-01T00:00:00Z",
                },
            },
            "fullText": "x",
            "sections": [
                {  # abstract excluded from the body signal
                    "id": "s0",
                    "title": "Abstract",
                    "blocks": [{"id": "s0.p1", "type": "paragraph", "text": "Short abstract."}],
                },
                {  # body carried entirely by a list — no direct paragraph text
                    "id": "s1",
                    "title": "Method",
                    "blocks": [
                        {"id": "s1.l1", "type": "list", "ordered": False, "items": [item] * 10}
                    ],
                },
            ],
        }
    )
    # 10 items × ~68 chars ≈ 680 > the 500 floor; the old paragraph-only count would read 0.
    assert _non_abstract_body_len(doc) >= 500


def test_invalidate_drops_cached_versions() -> None:
    store = _FakeStore()
    _builder(_FakeSource(None), store).invalidate("2401.00001")
    assert store.removed == ["2401.00001"]


class _FakeEprintSource:
    def __init__(self, eprint: bytes | None, *, raises: bool = False) -> None:
        self._eprint = eprint
        self._raises = raises
        self.calls: list[str] = []

    def fetch_eprint(self, metadata) -> bytes | None:
        self.calls.append(metadata.paper_id)
        if self._raises:
            raise RuntimeError("network down")
        return self._eprint


def _eprint_tar(tex: str) -> bytes:
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = tex.encode("utf-8")
        info = tarfile.TarInfo("main.tex")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_build_attaches_eprint_macros_to_meta() -> None:
    store = _FakeStore(cached=None)
    source = _FakeSource((_HTML, SourceTier.native_html))
    eprint = _FakeEprintSource(_eprint_tar(r"\newcommand{\R}{\mathbb{R}}"))
    builder = DocModelBuilder(
        source=source, store=store, eprint_source=eprint, clock=_FixedClock()
    )
    result = builder.build(sample_metadata("2401.00001v1"))
    assert isinstance(result, DocModelResultDTO)
    assert result.docModel.meta.macros == {"\\R": "\\mathbb{R}"}
    assert eprint.calls == ["2401.00001"]


def test_build_without_eprint_source_omits_macros() -> None:
    store = _FakeStore(cached=None)
    source = _FakeSource((_HTML, SourceTier.native_html))
    result = _builder(source, store).build(sample_metadata("2401.00001v1"))
    assert isinstance(result, DocModelResultDTO)
    assert result.docModel.meta.macros is None  # optional field omitted


def test_build_survives_eprint_fetch_failure() -> None:
    store = _FakeStore(cached=None)
    source = _FakeSource((_HTML, SourceTier.native_html))
    eprint = _FakeEprintSource(None, raises=True)
    builder = DocModelBuilder(
        source=source, store=store, eprint_source=eprint, clock=_FixedClock()
    )
    result = builder.build(sample_metadata("2401.00001v1"))
    assert isinstance(result, DocModelResultDTO)  # build still succeeds
    assert result.docModel.meta.macros is None


class _CapturingMetrics:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, float]] = []

    def emit_metric(self, name: str, value: float, tags: object = None) -> None:
        self.metrics.append((name, value))


def test_build_emits_macro_count_metric() -> None:
    obs = _CapturingMetrics()
    eprint = _FakeEprintSource(_eprint_tar(r"\newcommand{\R}{\mathbb{R}}"))
    builder = DocModelBuilder(
        source=_FakeSource((_HTML, SourceTier.native_html)),
        store=_FakeStore(cached=None),
        eprint_source=eprint,
        observability=obs,
        clock=_FixedClock(),
    )
    builder.build(sample_metadata("2401.00001v1"))
    assert ("ingestion.docmodel.macros", 1.0) in obs.metrics


def test_build_emits_failure_metric_on_eprint_error() -> None:
    obs = _CapturingMetrics()
    builder = DocModelBuilder(
        source=_FakeSource((_HTML, SourceTier.native_html)),
        store=_FakeStore(cached=None),
        eprint_source=_FakeEprintSource(None, raises=True),
        observability=obs,
        clock=_FixedClock(),
    )
    builder.build(sample_metadata("2401.00001v1"))
    assert ("ingestion.docmodel.macros_failed", 1.0) in obs.metrics
