"""DocModelBuilder — deterministic doc-model production with a (paperId, version) cache.

Corpus phase-1 builds doc-models eagerly during ingestion; the same builder also serves the
legacy lazy BUILD_DOC_MODEL path for misses, rebuilds, and phase-1 gaps. In both cases it
serves the cached artifact or builds, caches, and returns it.

The build is deterministic (D1) — the only non-deterministic input is ``provenance.generatedAt``
(a clock read), which is metadata, not content. The fetch follows the Q6 fallback ladder
(native HTML → ar5iv today; e-print/PDF are an additive rung behind the same port).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol, runtime_checkable

from docsuri_shared.docmodel_contract import DOCMODEL_PARSER_VERSION, DOCMODEL_SCHEMA_VERSION
from docsuri_shared.dtos import DocModel, DocModelResultDTO, SourceTier, SourceUnavailableDTO
from docsuri_shared.observability import emit_metric

from docsuri_ingestion.docmodel.formula_ocr import apply_ocr, formula_crops
from docsuri_ingestion.docmodel.macros import extract_macros
from docsuri_ingestion.docmodel.parser import (
    _project_full_text,
    block_text_parts,
    parse_html_to_docmodel,
    parse_text_to_docmodel,
)
from docsuri_ingestion.docmodel.table_repair import (
    apply_repairs,
    printed_text,
    tables_needing_repair,
)
from docsuri_ingestion.docmodel.tei import TRAILING_FLOAT_SECTION_TITLE, parse_tei_to_docmodel
from docsuri_ingestion.domain.assets import AssetCropSpec, FigureSpec
from docsuri_ingestion.domain.models import MetadataRecord
from docsuri_ingestion.ports import (
    ClockPort,
    DocModelSourcePort,
    DocModelStorePort,
    EprintSourcePort,
    FormulaReaderPort,
    SystemClock,
    TableExtractorPort,
)

# Bumping PARSER_VERSION invalidates cached doc-models (provenance.parserVersion, BR-30/TD-16).
PARSER_VERSION = DOCMODEL_PARSER_VERSION
# Mirrors the doc-model schema contract version (additive evolution; shared/README Versioning).
SCHEMA_VERSION = DOCMODEL_SCHEMA_VERSION

_SOURCE_UNAVAILABLE_REASON = (
    "We could not find a rich-renderable source (arXiv HTML) for this paper version."
)

# Source tiers that must never satisfy a cache hit, regardless of parser/schema version. The U7
# reader refuses a native_html doc-model outright (its raw TeX/pgf leaks into fullText), so treating
# such a cached object as "fresh" here would let a rebuild short-circuit on the cache hit and never
# replace it — the reader keeps rejecting it and re-enqueues the paper forever. Mirror the reader's
# rejection so a rebuild always re-fetches and overwrites these. Kept in lockstep with the reader's
# refused tiers (summarization s3_docmodel adapter).
_REBUILD_SOURCE_TIERS = frozenset({SourceTier.native_html})

# Some arXiv papers have a broken ar5iv (LaTeXML) conversion — the HTML returns 200 but the body
# is truncated to the abstract + a sentence or two (the rest of the LaTeX failed to convert). The
# parser faithfully extracts the little that is there, so a truncated conversion would otherwise be
# stored as a "complete" doc-model. Gate on the non-abstract body length: a real paper has
# thousands of characters of body prose, so a floor this low never trips a genuinely complete paper
# but reliably catches the abstract-only truncations. A tripped gate degrades to source_unavailable
# (arXiv link-out) — honest — rather than shipping a fragment as the full text. (A PDF→GROBID
# fallback that actually recovers the body is a separate follow-up.)
_MIN_BODY_TEXT_CHARS = 500

# A LaTeXML run that died mid-conversion stamps `ltx_ERROR` nodes where content should be and
# dumps raw TeX into what body it does emit. The length floor above misses this failure mode —
# the observed break (2502.10208) still carried 8,905 chars of body and sailed through. Errors
# are judged RELATIVE to paragraph count, not absolutely: a long paper accumulates sporadic
# recoverable errors (corpus max measured 10 on a 322-paragraph paper) without being broken.
# Measured on 39 corpus papers + the broken control (2026-08-10): normal error/paragraph ratio
# tops out at 0.14 (8 errors / 59 paras), the broken conversion sits at 8.8 (167 / 19) — a
# threshold of 1.0 ("an error marker per paragraph") has ~7x margin to both sides. Raw-TeX
# leak counting was evaluated as a second signal and REJECTED: it does not separate (a normal
# paper measured 6 pgfsys fragments inside legit math — a sanitizer gap, not a dead conversion —
# while the broken control measured 2).
_LATEXML_ERROR_MARKER = "ltx_ERROR"
_LATEXML_PARA_MARKER = "ltx_para"
_BROKEN_ERRORS_PER_PARA = 1.0


def _conversion_is_broken(html: str) -> bool:
    """Whether a LaTeXML build failed hard enough that its output must not become a doc-model.

    Substring counts, not a DOM walk — `ltx_para` also matches longer class names
    (`ltx_paragraph`), which only INFLATES the denominator; with an order-of-magnitude margin on
    both sides of the threshold that imprecision cannot flip a verdict."""
    errors = html.count(_LATEXML_ERROR_MARKER)
    return errors >= _BROKEN_ERRORS_PER_PARA * max(html.count(_LATEXML_PARA_MARKER), 1)


def _block_text_len(block: dict) -> int:
    """Length of a block's renderable text. Body prose lives in list items, table cells, and
    figure/table captions as well as paragraphs, so counting only ``block['text']`` would read 0
    for a paper whose body is mostly lists/tables and wrongly degrade a complete conversion.
    Measures exactly the fragments the fullText projection emits, so the gate cannot drift from
    what the doc-model actually carries."""
    return sum(len(part) for part in block_text_parts(block))


def _walk_sections(sections: object) -> Iterator[Any]:
    """Every section depth-first, on the MODEL form. ``parser.iter_blocks`` answers the same
    question on the dict form; using it here would mean dumping the doc-model to JSON first, which
    is exactly the cost the one caller is avoiding."""
    for section in sections or []:
        yield section
        yield from _walk_sections(section.sections)


def _non_abstract_body_len(doc: DocModel) -> int:
    """Character count of the doc-model body EXCLUDING the abstract section — the signal that
    separates a complete conversion from an abstract-only truncation.

    Recurses into nested subsections: the parser builds a nested section tree (ltx_section →
    ltx_subsection → …) and a normal paper's body prose often lives entirely in subsections, so
    counting only the top-level sections' direct blocks would read 0 and wrongly degrade a
    complete paper. Counts every text-bearing block type (not just paragraphs) for the same
    reason — see ``_block_text_len``."""

    def _count(sections: object) -> int:
        total = 0
        for section in sections or []:
            label = str(section.get("title") or section.get("heading") or "").strip().lower()
            if label == "abstract":
                continue  # skip the abstract subtree at any depth
            for block in section.get("blocks") or []:
                if isinstance(block, dict):
                    total += _block_text_len(block)
            total += _count(section.get("sections"))
        return total

    return _count(doc.model_dump(mode="json").get("sections"))


@runtime_checkable
class MetricSink(Protocol):
    def emit_metric(self, name: str, value: float, tags: object = None) -> None: ...


class DocModelBuilder:
    """Produce and cache the structured doc-model for a paper version (BR-30, BLM §7)."""

    def __init__(
        self,
        *,
        source: DocModelSourcePort,
        store: DocModelStorePort,
        eprint_source: EprintSourcePort | None = None,
        table_extractor: TableExtractorPort | None = None,
        formula_reader: FormulaReaderPort | None = None,
        observability: MetricSink | None = None,
        clock: ClockPort | None = None,
        parser_version: str = PARSER_VERSION,
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self._source = source
        self._store = store
        self._eprint_source = eprint_source
        self._table_extractor = table_extractor
        self._formula_reader = formula_reader
        self._observability = observability
        self._clock = clock or SystemClock()
        self._parser_version = parser_version
        self._schema_version = schema_version

    def build(
        self,
        metadata: MetadataRecord,
        *,
        figure_specs: list[FigureSpec] | None = None,
    ) -> DocModelResultDTO | SourceUnavailableDTO:
        """Return the doc-model for ``metadata`` — cached, freshly built, or unavailable.

        ``figure_specs`` is an optional out-param threaded to the HTML parser: on a fresh build it
        is filled with a FigureSpec per FigureBlock (document order) so the eager asset step can
        resolve each figure's image aligned to its block. On a cache hit the parser does not run,
        so it stays untouched and the extractor falls back to its legacy scan.
        """
        paper_id = metadata.paper_id
        version = metadata.version

        cached = self._fresh_cached(paper_id, version)
        if cached is not None:
            return DocModelResultDTO(status="ok", cached=True, docModel=cached)

        fetched = self._source.fetch_html_source(metadata.identifier.arxiv_id)
        if fetched is None:
            return SourceUnavailableDTO(
                status="source_unavailable", reason=_SOURCE_UNAVAILABLE_REASON
            )
        html, source_tier = fetched
        if _conversion_is_broken(html):
            # Dead LaTeXML build (see _BROKEN_ERRORS_PER_PARA) — degrade BEFORE parsing so the
            # next ladder rung takes over, and count it separately from truncations so the two
            # failure modes stay distinguishable in metrics.
            emit_metric(self._observability, "ingestion.docmodel.broken_conversion", 1.0)
            return SourceUnavailableDTO(
                status="source_unavailable", reason=_SOURCE_UNAVAILABLE_REASON
            )

        doc = parse_html_to_docmodel(
            html,
            paper_id=paper_id,
            version=version,
            title=metadata.title,
            abstract=metadata.abstract or None,
            source_tier=source_tier,
            parser_version=self._parser_version,
            schema_version=self._schema_version,
            generated_at=self._clock.now(),
            macros=self._extract_macros(metadata),
            figure_specs=figure_specs,
        )
        if _non_abstract_body_len(doc) < _MIN_BODY_TEXT_CHARS:
            # Broken ar5iv conversion (HTML 200 but abstract-only) — do NOT cache a truncated
            # doc-model as "complete"; degrade to source_unavailable so the viewer links out to
            # arXiv instead of showing a fragment. Observed so the truncation rate is trackable.
            emit_metric(self._observability, "ingestion.docmodel.truncated_source", 1.0)
            return SourceUnavailableDTO(
                status="source_unavailable", reason=_SOURCE_UNAVAILABLE_REASON
            )
        self._store.put(doc)
        return DocModelResultDTO(status="ok", cached=False, docModel=doc)

    def _extract_macros(self, metadata: MetadataRecord) -> dict[str, str]:
        """Best-effort KaTeX macro map from the e-print preamble (never blocks the build).

        Emits a count metric (and a failure counter) so a regression that drops macros entirely
        — a broken e-print source, a tokenizer fault — is visible instead of silently swallowed.
        """
        if self._eprint_source is None:
            return {}
        try:
            macros = extract_macros(self._eprint_source.fetch_eprint(metadata))
            emit_metric(self._observability, "ingestion.docmodel.macros", float(len(macros)))
            return macros
        except Exception:  # noqa: BLE001 - macros are a display refinement, never blocking
            emit_metric(self._observability, "ingestion.docmodel.macros_failed", 1.0)
            return {}

    def build_from_text(
        self,
        metadata: MetadataRecord,
        text: str,
        *,
        source_tier: SourceTier = SourceTier.pdf,
    ) -> DocModelResultDTO:
        """Return/cache a minimal doc-model from already-fetched PDF/GROBID text."""
        return self.build_from_paper(
            metadata.paper_id,
            metadata.version,
            metadata.title,
            metadata.abstract or "",
            text,
            source_tier=source_tier,
        )

    def build_from_paper(
        self,
        paper_id: str,
        version: int,
        title: str,
        abstract: str,
        text: str,
        *,
        source_tier: SourceTier = SourceTier.pdf,
    ) -> DocModelResultDTO:
        """Return/cache a minimal doc-model for non-arXiv source records."""
        cached = self._fresh_cached(paper_id, version)
        if cached is not None:
            return DocModelResultDTO(status="ok", cached=True, docModel=cached)
        doc = parse_text_to_docmodel(
            text,
            paper_id=paper_id,
            version=version,
            title=title,
            abstract=abstract or None,
            source_tier=source_tier,
            parser_version=self._parser_version,
            schema_version=self._schema_version,
            generated_at=self._clock.now(),
        )
        self._store.put(doc)
        return DocModelResultDTO(status="ok", cached=False, docModel=doc)

    def build_from_tei(
        self,
        paper_id: str,
        version: int,
        title: str,
        abstract: str,
        tei: str,
        fallback_text: str,
        *,
        source_tier: SourceTier = SourceTier.pdf,
        crops: list[AssetCropSpec] | None = None,
        pdf: bytes | None = None,
    ) -> DocModelResultDTO:
        """Structured doc-model from GROBID TEI for non-arXiv sources (sections/tables/figures).

        Falls back to the flat-text doc-model when TEI is missing or unparseable, so a GROBID
        quirk never blocks ingestion (best-effort, BR-27-style). The fallback emits a metric so
        a systematic TEI regression is visible rather than silently degrading every paper.

        When ``crops`` is supplied, the figure/formula page-crop specs are collected during this
        single TEI parse (the parser's out-param) so the asset step need not re-parse the TEI.
        On a cache hit the TEI is not parsed, so ``crops`` stays empty — the caller distinguishes
        that via the returned ``cached`` flag.
        """
        cached = self._fresh_cached(paper_id, version)
        if cached is not None:
            return DocModelResultDTO(status="ok", cached=True, docModel=cached)
        doc = None
        if tei and tei.strip():
            try:
                doc = parse_tei_to_docmodel(
                    tei,
                    paper_id=paper_id,
                    version=version,
                    title=title,
                    abstract=abstract or None,
                    source_tier=source_tier,
                    parser_version=self._parser_version,
                    schema_version=self._schema_version,
                    generated_at=self._clock.now(),
                    crops=crops,
                )
                if _non_abstract_body_len(doc) <= 0:
                    emit_metric(self._observability, "ingestion.docmodel.tei_fallback", 1.0)
                    doc = None
            except Exception:  # noqa: BLE001 - any TEI parse fault degrades to flat text
                emit_metric(self._observability, "ingestion.docmodel.tei_fallback", 1.0)
                doc = None
        if doc is None:
            return self.build_from_paper(
                paper_id, version, title, abstract, fallback_text, source_tier=source_tier
            )
        self._emit_float_placement(doc)
        doc = self._repair_tables(doc, pdf, crops)
        doc = self._read_formulas(doc, pdf, crops)
        self._store.put(doc)
        return DocModelResultDTO(status="ok", cached=False, docModel=doc)

    def _emit_float_placement(self, doc: DocModel) -> None:
        """Count the floats that read inline against those left in the trailing dump.

        The coordinate signal rests on GROBID coordinating ``<head>``; lose it and every float the
        body never names by number is stranded in the dump, where a reader browsing the text never
        meets it. That fallback is deliberately silent so an older TEI cache stays parseable, which
        means a GROBID upgrade, a proxy dropping the ``teiCoordinates`` form field, or a run
        against a stale cache would all degrade the whole corpus while every existing signal
        stayed green. These two counters are how that shows up, and they sit beside
        ``tei_fallback`` for the same reason it exists.

        Guarded and dump-free, because this is pure observability standing in front of the two
        recovery stages: a fault here must not cost a paper that parsed cleanly, and a second full
        ``model_dump`` of every doc-model is real cost on a corpus-scale reparse for two counters.
        """
        try:
            placed = dumped = 0
            for section in _walk_sections(doc.sections):
                trailing = section.title == TRAILING_FLOAT_SECTION_TITLE
                for block in section.blocks:
                    if block.root.type in ("figure", "table"):
                        if trailing:
                            dumped += 1
                        else:
                            placed += 1
            emit_metric(self._observability, "ingestion.docmodel.floats_placed", float(placed))
            emit_metric(self._observability, "ingestion.docmodel.floats_trailing", float(dumped))
        except Exception:  # noqa: BLE001 - a counter must never cost us the doc-model we have
            emit_metric(self._observability, "ingestion.docmodel.float_census_failed", 1.0)

    def _repair_tables(
        self, doc: DocModel, pdf: bytes | None, crops: list[AssetCropSpec] | None
    ) -> DocModel:
        """Re-read the tables GROBID merged into single cells, when an extractor is configured.

        Best-effort in the strict sense: any failure, and every table whose rebuild cannot be
        verified against the TEI numbers, leaves the doc-model exactly as parsed (BR-27).
        """
        if self._table_extractor is None or not pdf or not crops:
            return doc
        try:
            payload = doc.model_dump(mode="json")
            suspect = tables_needing_repair(payload, crops)
            if not suspect:
                return doc
            tables = self._table_extractor.extract_tables(pdf, [s.page for s in suspect])
            repaired = apply_repairs(payload, crops, tables, printed_text(pdf))
            if not repaired:
                return doc
            # Rows changed, so the fullText projection made at parse time no longer matches the
            # blocks — re-project it, or the root text would still carry GROBID's merged cells.
            payload["fullText"] = _project_full_text(payload["sections"])
            emit_metric(self._observability, "ingestion.docmodel.tables_repaired", float(repaired))
            return DocModel.model_validate(payload)
        except Exception:  # noqa: BLE001 - a repair must never cost us the doc-model we have
            emit_metric(self._observability, "ingestion.docmodel.table_repair_failed", 1.0)
            return doc

    def _read_formulas(
        self, doc: DocModel, pdf: bytes | None, crops: list[AssetCropSpec] | None
    ) -> DocModel:
        """Recover searchable LaTeX from the formula crops, when a reader is configured.

        The crops are rendered here rather than waited for: the asset step runs later and may not
        run at all. Best-effort — any failure leaves the image-only formulas untouched (BR-27).
        """
        if self._formula_reader is None or not pdf or not crops:
            return doc
        try:
            from docsuri_ingestion.asset_extraction import crop_assets_from_specs

            specs = formula_crops(crops)
            if not specs:
                return doc
            images = {
                asset.meta.asset_id: asset.image
                for asset in crop_assets_from_specs(
                    pdf, specs, paper_id=doc.meta.paperId, version=doc.meta.version
                )
            }
            payload = doc.model_dump(mode="json")
            filled = apply_ocr(payload, images, self._formula_reader.read_latex)
            if not filled:
                return doc
            # ``latexOcr`` is projected into fullText (it exists to be searchable), so the parse
            # -time projection is stale the moment a formula is filled — re-project.
            payload["fullText"] = _project_full_text(payload["sections"])
            emit_metric(self._observability, "ingestion.docmodel.formulas_read", float(filled))
            return DocModel.model_validate(payload)
        except Exception:  # noqa: BLE001 - a failed read must never cost us the doc-model
            emit_metric(self._observability, "ingestion.docmodel.formula_read_failed", 1.0)
            return doc

    def invalidate(self, paper_id: str) -> None:
        """Drop every cached doc-model version for a paper (version change / tombstone)."""
        self._store.remove(paper_id)

    def get_cached(self, paper_id: str, version: int) -> DocModel | None:
        return self._fresh_cached(paper_id, version)

    def _fresh_cached(self, paper_id: str, version: int) -> DocModel | None:
        cached = self._store.get(paper_id, version)
        if cached is None:
            return None
        provenance = cached.meta.provenance
        # A refused source tier (native_html) is never fresh even at the current parser/schema — the
        # reader rejects it, so a cache hit here would trap the rebuild in a no-op and the object
        # would never be replaced. Force a rebuild (re-fetch → ar5iv/PDF) instead.
        if provenance.sourceTier in _REBUILD_SOURCE_TIERS:
            return None
        if (
            provenance.parserVersion == self._parser_version
            and provenance.schemaVersion == self._schema_version
        ):
            return cached
        return None
