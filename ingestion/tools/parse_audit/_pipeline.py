"""Ingestion wiring shared by the PDF-path audits — the parts that DO touch ``docsuri_ingestion``.

Kept apart from ``_common.py`` on purpose. That file is the yardstick for A/B sweeps and has to run
identically from two checkouts, so it imports nothing from the package under test. This one is the
opposite: it exists precisely to build the pipeline the way ingestion builds it, so a measurement
cannot silently diverge from what the service actually does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

TS = datetime(2026, 1, 1, tzinfo=UTC)


class _TeiSource(Protocol):
    def extract_tei(self, pdf: bytes) -> str: ...


def tei_for(key: str, cache: Path, client: _TeiSource | None) -> str:
    """Cached TEI, extracting it once when the cache has none and a GROBID is reachable.

    The cache is what makes the PDF sweeps repeatable without a container running: GROBID is hit
    at most once per paper, ever, and every later run reads the file.
    """
    path = cache / "tei" / f"{key}.tei.xml"
    if path.exists():
        return path.read_text(encoding="utf-8")
    if client is None:
        raise FileNotFoundError(f"no cached TEI for {key} and no --grobid-url given")
    path.parent.mkdir(parents=True, exist_ok=True)
    tei = client.extract_tei((cache / "pdf" / f"{key}.pdf").read_bytes())
    path.write_text(tei, encoding="utf-8")
    return tei


def build_doc(
    paper_id: str,
    version: int,
    tei: str,
    pdf: bytes,
    builder: Any | None,
    crops: list | None = None,
) -> Any:
    """The doc-model to judge: the parser's, or the whole builder's when a builder is given.

    They differ, and the difference has fooled this sweep twice. Table re-extraction and formula
    OCR run AFTER ``parse_tei_to_docmodel`` inside ``DocModelBuilder.build_from_tei``, so a
    parser-only reading reports their absence as parser defects (it counted six empty tables where
    the pipeline delivers four, and 0% formula characters where it delivers 80%). Both PDF audits
    ask this same question, so they ask it in one place — the audit sentinel versions and the
    positional ``build_from_tei`` call cannot drift between them.

    ``crops`` is the parser's out-param; both recovery stages page-crop through it, so passing a
    list is what makes them run at all.
    """
    from docsuri_shared.dtos import SourceTier

    from docsuri_ingestion.docmodel.tei import parse_tei_to_docmodel

    crops = [] if crops is None else crops
    if builder is None:
        return parse_tei_to_docmodel(
            tei,
            paper_id=paper_id, version=version, title="", abstract=None,
            source_tier=SourceTier.pdf, parser_version="audit", schema_version="audit",
            generated_at=TS, crops=crops,
        )
    return builder.build_from_tei(
        paper_id, version, "", "", tei, "",
        source_tier=SourceTier.pdf, crops=crops, pdf=pdf,
    ).docModel


def pipeline_builder() -> Any:
    """A ``DocModelBuilder`` wired exactly as ingestion wires it, writing nothing.

    The readers come from ``runtime``'s own resolvers so a missing optional extra degrades here the
    way it would in ingestion, and the store always misses so a cache hit cannot skip the very
    stages a pipeline measurement exists to see.
    """
    from docsuri_ingestion.docmodel.builder import DocModelBuilder
    from docsuri_ingestion.runtime import _formula_reader, _table_extractor
    from docsuri_ingestion.settings import IngestionSettings

    class _NoStore:
        def get(self, paper_id: str, version: int):  # noqa: ARG002
            return None

        def put(self, doc) -> None:
            """Drop it — an audit measures, it does not populate the corpus."""

        def remove(self, paper_id: str) -> None:
            """Never called; present so the object satisfies the store port."""

    class _FixedClock:
        def now(self):
            return TS

    # from_env(), the way the service builds it (cli.py). A bare IngestionSettings() ignores
    # DOCSURI_TABLE_EXTRACTOR / DOCSURI_FORMULA_READER, so an audit run in an environment that
    # switches a reader off would still resolve "auto", run it, and report a recovery rate the
    # real configuration never delivers — the divergence this module exists to prevent.
    settings = IngestionSettings.from_env()
    return DocModelBuilder(
        source=None,  # type: ignore[arg-type]  # build_from_tei never reaches the HTML ladder
        store=_NoStore(),
        table_extractor=_table_extractor(settings),
        formula_reader=_formula_reader(settings),
        clock=_FixedClock(),
        parser_version="audit",
        schema_version="audit",
    )
