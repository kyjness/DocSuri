"""DocModelBuilder — deterministic doc-model production with a (paperId, version) cache.

Corpus phase-1 builds doc-models eagerly during ingestion; the same builder also serves the
legacy lazy BUILD_DOC_MODEL path for misses, rebuilds, and phase-1 gaps. In both cases it
serves the cached artifact or builds, caches, and returns it.

The build is deterministic (D1) — the only non-deterministic input is ``provenance.generatedAt``
(a clock read), which is metadata, not content. The fetch follows the Q6 fallback ladder
(native HTML → ar5iv today; e-print/PDF are an additive rung behind the same port).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from docsuri_shared.docmodel_contract import DOCMODEL_PARSER_VERSION, DOCMODEL_SCHEMA_VERSION
from docsuri_shared.dtos import DocModel, DocModelResultDTO, SourceTier, SourceUnavailableDTO

from docsuri_ingestion.docmodel.macros import extract_macros
from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel, parse_text_to_docmodel
from docsuri_ingestion.docmodel.tei import parse_tei_to_docmodel
from docsuri_ingestion.domain.assets import AssetCropSpec, FigureSpec
from docsuri_ingestion.domain.models import MetadataRecord
from docsuri_ingestion.ports import DocModelSourcePort, DocModelStorePort, EprintSourcePort

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


def _block_text_len(block: dict) -> int:
    """Length of a block's renderable text, per block type. Paragraph/code carry ``text``, but
    body prose also lives in list items, table cells, and figure/table captions — counting only
    ``block['text']`` reads 0 for a paper whose body is mostly lists/tables and wrongly degrades a
    complete conversion. Mirror the full-text projection so every text-bearing block contributes."""
    kind = block.get("type")
    if kind in ("paragraph", "code"):
        return len(block.get("text") or "")
    if kind == "formula":
        return len(block.get("latex") or "")
    if kind == "list":
        return sum(len(item.get("text") or "") for item in block.get("items") or [])
    if kind in ("figure", "table"):
        total = len(block.get("caption") or "")
        if kind == "table":
            for row in block.get("rows") or []:
                for cell in row.get("cells") or []:
                    total += len(str(cell.get("text") or ""))
        return total
    return len(block.get("text") or "")


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
class ClockPort(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class MetricSink(Protocol):
    def emit_metric(self, name: str, value: float, tags: object = None) -> None: ...


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class DocModelBuilder:
    """Produce and cache the structured doc-model for a paper version (BR-30, BLM §7)."""

    def __init__(
        self,
        *,
        source: DocModelSourcePort,
        store: DocModelStorePort,
        eprint_source: EprintSourcePort | None = None,
        observability: MetricSink | None = None,
        clock: ClockPort | None = None,
        parser_version: str = PARSER_VERSION,
        schema_version: str = SCHEMA_VERSION,
    ) -> None:
        self._source = source
        self._store = store
        self._eprint_source = eprint_source
        self._observability = observability
        self._clock = clock or _SystemClock()
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
            self._emit("ingestion.docmodel.truncated_source", 1.0)
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
            self._emit("ingestion.docmodel.macros", float(len(macros)))
            return macros
        except Exception:  # noqa: BLE001 - macros are a display refinement, never blocking
            self._emit("ingestion.docmodel.macros_failed", 1.0)
            return {}

    def _emit(self, name: str, value: float) -> None:
        if self._observability is not None:
            self._observability.emit_metric(name, value, {})

    def build_from_text(
        self,
        metadata: MetadataRecord,
        text: str,
        *,
        source_tier: SourceTier = SourceTier.pdf,
    ) -> DocModelResultDTO:
        """Return/cache a minimal doc-model from already-fetched PDF/GROBID text."""
        paper_id = metadata.paper_id
        version = metadata.version
        cached = self._fresh_cached(paper_id, version)
        if cached is not None:
            return DocModelResultDTO(status="ok", cached=True, docModel=cached)
        doc = parse_text_to_docmodel(
            text,
            paper_id=paper_id,
            version=version,
            title=metadata.title,
            abstract=metadata.abstract or None,
            source_tier=source_tier,
            parser_version=self._parser_version,
            schema_version=self._schema_version,
            generated_at=self._clock.now(),
        )
        self._store.put(doc)
        return DocModelResultDTO(status="ok", cached=False, docModel=doc)

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
                    self._emit("ingestion.docmodel.tei_fallback", 1.0)
                    doc = None
            except Exception:  # noqa: BLE001 - any TEI parse fault degrades to flat text
                self._emit("ingestion.docmodel.tei_fallback", 1.0)
                doc = None
        if doc is None:
            return self.build_from_paper(
                paper_id, version, title, abstract, fallback_text, source_tier=source_tier
            )
        self._store.put(doc)
        return DocModelResultDTO(status="ok", cached=False, docModel=doc)

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
