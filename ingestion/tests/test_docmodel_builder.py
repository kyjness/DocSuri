"""DocModelBuilder (BR-30/D6): lazy build, (paperId, version) cache, source_unavailable."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from docsuri_shared.docmodel_contract import DOCMODEL_PARSER_VERSION, DOCMODEL_SCHEMA_VERSION
from docsuri_shared.dtos import DocModel, DocModelResultDTO, SourceTier, SourceUnavailableDTO

from docsuri_ingestion.adapters.local import sample_metadata
from docsuri_ingestion.docmodel.builder import DocModelBuilder
from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel
from docsuri_ingestion.domain.assets import ExtractedTable

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
    table_extractor: object | None = None,
    formula_reader: object | None = None,
) -> DocModelBuilder:
    return DocModelBuilder(
        source=source,
        store=store,
        clock=_FixedClock(),
        parser_version=parser_version,
        schema_version=schema_version,
        table_extractor=table_extractor,
        formula_reader=formula_reader,
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
    result = builder.build_from_tei("src-1", 1, "Title", "Abs", _TEI)
    assert result.cached is False
    titles = [s.title for s in result.docModel.sections]
    assert "Method" in titles
    assert store.put_calls  # cached for reuse


def test_build_from_tei_reports_unavailable_on_bad_tei() -> None:
    # Malformed TEI yields NO doc-model, unconditionally (BR-30 2026-08-10). Leniency is not an
    # argument here — the one caller allowed to be lenient (user uploads) recovers on this result
    # at its own call site, so a corpus caller cannot re-admit flat text by forgetting a keyword.
    store = _FakeStore()
    builder = _builder(_FakeSource(None), store)
    result = builder.build_from_tei("src-2", 1, "Title", "Abs", "<TEI")
    assert isinstance(result, SourceUnavailableDTO)
    assert store.put_calls == []  # nothing cached


def test_build_from_tei_reports_unavailable_on_empty_body_tei() -> None:
    store = _FakeStore()
    builder = _builder(_FakeSource(None), store)
    result = builder.build_from_tei("src-3", 1, "Title", "Abs", _EMPTY_BODY_TEI)
    assert isinstance(result, SourceUnavailableDTO)
    assert store.put_calls == []


# Prose alongside the formula: a formula block carries no body text of its own, and a TEI with
# nothing else is (correctly) not a structured doc-model at all — see
# test_build_from_tei_reports_unavailable_on_empty_body_tei.
_TEI_FORMULA = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div><head>M</head>'
    "<p>Prose body.</p>"
    '<formula coords="1,5,6,30,12"><label>(2)</label>x=y</formula>'
    "</div></body></text></TEI>"
)


def test_build_from_tei_collects_crop_specs_in_one_parse() -> None:
    # The asset step reuses the crop specs gathered during this single TEI parse (out-param)
    # instead of re-parsing via tei_crop_specs. assetIds match the doc-model blocks (same walk).
    store = _FakeStore()
    builder = _builder(_FakeSource(None), store)
    crops: list = []
    result = builder.build_from_tei("src-9", 1, "T", "A", _TEI_FORMULA, crops=crops)
    assert result.cached is False
    assert [c.asset_id for c in crops] == ["src-9:v1:formula:0"]


def test_build_from_tei_skips_crop_collection_on_cache_hit() -> None:
    # A cache hit does not parse the TEI, so crops stays empty — the caller relies on this
    # (via result.cached) to fall back to deriving the specs from the TEI itself.
    store = _FakeStore(cached=_doc())
    builder = _builder(_FakeSource(None), store)
    crops: list = []
    result = builder.build_from_tei("src-1", 1, "T", "A", _TEI_FORMULA, crops=crops)
    assert result.cached is True
    assert crops == []


_MERGED_TABLE_TEI = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
    "<div><head>Results</head><p>Prose body.</p></div>"
    '<figure type="table" coords="3,100,100,300,100"><head>Table 1</head>'
    "<figDesc>Merged by GROBID.</figDesc><table>"
    "<row><cell>ADA</cell><cell>0.696 ± 0.015 0.011 ± 0.000</cell></row>"
    "</table></figure></body></text></TEI>"
)


class _FakeTableExtractor:
    def extract_tables(self, pdf: bytes, pages) -> list[ExtractedTable]:
        return [
            ExtractedTable(
                page=3,
                bbox=(100.0, 100.0, 400.0, 200.0),
                rows=(("ADA", "0.696 ± 0.015", "0.011 ± 0.000"),),
            )
        ]


def test_a_table_repair_reprojects_full_text(monkeypatch) -> None:
    """Repaired cells must reach every representation: the blocks AND the root fullText, which
    was projected before the repair ran and would otherwise keep the merged numbers."""
    monkeypatch.setattr(
        "docsuri_ingestion.docmodel.builder.printed_text",
        lambda pdf: lambda page, bbox: "ADA 0.696 ± 0.015 0.011 ± 0.000",
    )
    builder = _builder(_FakeSource(None), _FakeStore(), table_extractor=_FakeTableExtractor())

    result = builder.build_from_tei(
        "src-r", 1, "T", "A", _MERGED_TABLE_TEI, crops=[], pdf=b"%PDF-fake"
    )

    assert "ADA | 0.696 ± 0.015 | 0.011 ± 0.000" in result.docModel.fullText
    assert "0.696 ± 0.015 0.011 ± 0.000" not in result.docModel.fullText


def test_a_formula_ocr_read_reprojects_full_text(monkeypatch) -> None:
    """``latexOcr`` exists to be searchable, so a filled formula must show up in fullText — the
    parse-time projection predates the read and carries nothing for an image-only formula."""

    def fake_crops(pdf, specs, *, paper_id, version):
        return [
            SimpleNamespace(meta=SimpleNamespace(asset_id=spec.asset_id), image=b"img")
            for spec in specs
        ]

    monkeypatch.setattr("docsuri_ingestion.asset_extraction.crop_assets_from_specs", fake_crops)
    reader = SimpleNamespace(read_latex=lambda image: r"E = mc^{2}")
    builder = _builder(_FakeSource(None), _FakeStore(), formula_reader=reader)
    # Prose alongside the formula: an image-only formula carries no body text, and a TEI without
    # any would (correctly) degrade to the flat-text fallback before OCR could run.
    tei = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div><head>M</head>'
        "<p>Prose body.</p>"
        '<formula coords="1,5,6,30,12"><label>(2)</label>x=y</formula>'
        "</div></body></text></TEI>"
    )

    result = builder.build_from_tei("src-o", 1, "T", "A", tei, crops=[], pdf=b"%PDF-fake")

    assert r"E = mc^{2}" in result.docModel.fullText


def test_cache_hit_returns_cached_without_fetching() -> None:
    store = _FakeStore(cached=_doc())
    source = _FakeSource((_HTML, SourceTier.ar5iv))
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
    source = _FakeSource((_HTML, SourceTier.ar5iv))
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


def test_stale_schema_cache_hit_rebuilds_flat_doc_model() -> None:
    # build_from_paper is the surviving flat-text entry (user uploads via build_from_tei's
    # degrade); build_from_text was removed with the corpus flat-text fallback (BR-30 2026-08-10).
    store = _FakeStore(cached=_doc(schema_version="0.9.0"))
    result = _builder(_FakeSource(None), store).build_from_paper(
        "2401.00001", 1, "T", "A", "PDF fallback text."
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


# A LaTeXML build that died PART-WAY: 2,000+ chars of body survive (clearing the absolute floor),
# but the bulk of the page's readable text never became blocks — it sits in prose the parser
# cannot reach. Modeled on the measured break (2502.10208: 8,905 chars of body, ~0.08 coverage).
_DEAD_CONVERSION_HTML = (
    '<article class="ltx_document"><section class="ltx_section" id="S1">'
    '<h2 class="ltx_title ltx_title_section">Intro</h2>'
    + "".join(
        f'<div class="ltx_para"><p class="ltx_p">Surviving prose number {i}. {"x" * 200}</p></div>'
        for i in range(5)
    )
    + "</section>"
    # Unreachable remainder: readable text on the page that produced no block at all.
    + "".join(f"<span>Stranded body text {i}. {'z' * 400}</span>" for i in range(40))
    + "</article>"
)


def test_build_degrades_when_the_conversion_died_partway() -> None:
    # Enough chars survive to clear the absolute floor, so only the RELATIVE coverage check can
    # catch it: the parser recovered a small fraction of the text the page actually carries.
    obs = _CapturingMetrics()
    store = _FakeStore(cached=None)
    builder = DocModelBuilder(
        source=_FakeSource((_DEAD_CONVERSION_HTML, SourceTier.ar5iv)),
        store=store,
        observability=obs,
        clock=_FixedClock(),
    )
    result = builder.build(sample_metadata("2401.00001v1"))
    assert isinstance(result, SourceUnavailableDTO)
    assert store.put_calls == []  # nothing cached
    # Counted apart from truncations so the two failure modes stay distinguishable in metrics.
    assert ("ingestion.docmodel.broken_conversion", 1.0) in obs.metrics


def test_build_tolerates_a_macro_the_converter_could_not_resolve() -> None:
    # An unresolved macro emits one ltx_ERROR per USE, so a paper that names its own tool 74 times
    # carries 74 error nodes while staying entirely readable (measured: 2310.04047 — 36,770 chars,
    # 18 sections, 7 tables, zero TeX leak). Counting error nodes rejected papers like this one;
    # coverage must not. Guards the 2026-08-10 false-rejection finding.
    html = (
        '<article class="ltx_document"><section class="ltx_section" id="S1">'
        '<h2 class="ltx_title ltx_title_section">Intro</h2>'
        + "".join(
            '<div class="ltx_para"><p class="ltx_p">Body prose about '
            '<span class="ltx_ERROR undefined">\\ourtool</span> and its results. '
            f'{"y" * 200}</p></div>'
            for _ in range(8)
        )
        + "</section></article>"
    )
    store = _FakeStore(cached=None)
    result = _builder(_FakeSource((html, SourceTier.ar5iv)), store).build(
        sample_metadata("2401.00001v1")
    )
    assert isinstance(result, DocModelResultDTO)  # NOT degraded
    assert len(store.put_calls) == 1


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
    source = _FakeSource((_HTML, SourceTier.ar5iv))
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
    source = _FakeSource((_HTML, SourceTier.ar5iv))
    result = _builder(source, store).build(sample_metadata("2401.00001v1"))
    assert isinstance(result, DocModelResultDTO)
    assert result.docModel.meta.macros is None  # optional field omitted


def test_build_survives_eprint_fetch_failure() -> None:
    store = _FakeStore(cached=None)
    source = _FakeSource((_HTML, SourceTier.ar5iv))
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
        source=_FakeSource((_HTML, SourceTier.ar5iv)),
        store=_FakeStore(cached=None),
        eprint_source=eprint,
        observability=obs,
        clock=_FixedClock(),
    )
    builder.build(sample_metadata("2401.00001v1"))
    assert ("ingestion.docmodel.macros", 1.0) in obs.metrics


_TEI_WITH_COORDS = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
    '<div><head coords="1,10,100,300,10">Method</head>'
    "<p>The overview is given in Figure 1.</p></div>"
    '<figure coords="1,10,300,200,80"><head>Figure 1</head>'
    "<figDesc>Overview.</figDesc></figure>"
    "</body></text></TEI>"
)
# The same paper with the head coordinates stripped AND the citation removed — what GROBID
# returned before the parser asked for coordinates, on a float the body never names. Both have to
# go: the citation signal reads paragraph text and does not depend on coordinates at all, so
# losing them strands the uncited floats only, not every float.
_TEI_WITHOUT_COORDS = _TEI_WITH_COORDS.replace(
    ' coords="1,10,100,300,10"', ""
).replace("The overview is given in Figure 1.", "The overview is given below.")


def test_build_from_tei_counts_floats_that_read_inline() -> None:
    obs = _CapturingMetrics()
    builder = DocModelBuilder(
        source=_FakeSource(None), store=_FakeStore(), observability=obs, clock=_FixedClock()
    )
    builder.build_from_tei("src-p", 1, "T", "A", _TEI_WITH_COORDS)
    assert ("ingestion.docmodel.floats_placed", 1.0) in obs.metrics
    assert ("ingestion.docmodel.floats_trailing", 0.0) in obs.metrics


def test_build_from_tei_counts_floats_stranded_in_the_trailing_dump() -> None:
    """A float with neither signal falls back to the trailing section, where a reader browsing the
    body never meets it. That degradation is deliberately silent so an older TEI cache stays
    parseable — so it has to be counted, or losing the coordinates corpus-wide reads as clean."""
    obs = _CapturingMetrics()
    builder = DocModelBuilder(
        source=_FakeSource(None), store=_FakeStore(), observability=obs, clock=_FixedClock()
    )
    builder.build_from_tei("src-q", 1, "T", "A", _TEI_WITHOUT_COORDS)
    assert ("ingestion.docmodel.floats_trailing", 1.0) in obs.metrics
    assert ("ingestion.docmodel.floats_placed", 0.0) in obs.metrics


def test_build_emits_failure_metric_on_eprint_error() -> None:
    obs = _CapturingMetrics()
    builder = DocModelBuilder(
        source=_FakeSource((_HTML, SourceTier.ar5iv)),
        store=_FakeStore(cached=None),
        eprint_source=_FakeEprintSource(None, raises=True),
        observability=obs,
        clock=_FixedClock(),
    )
    builder.build(sample_metadata("2401.00001v1"))
    assert ("ingestion.docmodel.macros_failed", 1.0) in obs.metrics
