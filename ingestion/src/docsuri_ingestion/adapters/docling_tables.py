"""Docling table extractor — a second reading of the tables GROBID reconstructs wrongly.

Import-guarded and optional (``pip install .[tables]``): the model stack is heavy, so a
deployment that does not want it simply configures no extractor and the TEI cells stand as GROBID
produced them. Only the pages that carry a suspect table are converted, since each page costs
seconds of CPU inference.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Sequence

from docsuri_ingestion.domain.assets import ExtractedTable

log = logging.getLogger("docsuri.ingestion.tables")

_DOCLING_MISSING = "docling table extractor not installed (pip install .[tables])"


class DoclingTableExtractor:
    """Re-read tables from a PDF with Docling's TableFormer model."""

    def __init__(self, *, max_pages: int = 12) -> None:
        # A page costs seconds; a pathological paper must not stall the pipeline behind a
        # best-effort repair, so only the first N suspect pages are re-read.
        self._max_pages = max_pages
        self._converter: object | None = None

    def extract_tables(self, pdf: bytes, pages: Sequence[int]) -> Sequence[ExtractedTable]:
        try:
            from docling.datamodel.base_models import DocumentStream
            from docling.document_converter import DocumentConverter
        except ImportError as exc:  # pragma: no cover - optional extra
            raise RuntimeError(_DOCLING_MISSING) from exc

        suspect = sorted({int(p) for p in pages if p and p > 0})
        wanted = suspect[: self._max_pages]
        if len(suspect) > len(wanted):
            # The cap is a budget device, but it used to be INVISIBLE: a candidate on a dropped
            # page is never re-read, and downstream that is indistinguishable from "the extractor
            # found nothing there". Measured over 50 papers, one paper spread its candidates over
            # 14 pages and lost 5 of them (4% of all candidates) this way, counted as match
            # failures. Say what was dropped so the batch can price raising the cap.
            log.warning(
                "docling page cap: re-reading %d of %d suspect pages, skipping %s",
                len(wanted), len(suspect), suspect[self._max_pages :],
            )
        if not wanted:
            return ()
        # Built once and reused for the life of this extractor. Constructing it loads the
        # TableFormer model stack, which is seconds of work that does not depend on the document.
        # Building one per call meant paying that per PAPER — tolerable while only merged-cell
        # tables were routed here, but empty tables are routed too now and they are far more
        # common (52% of papers against 25% in the audit sample), so a corpus-scale reparse would
        # spend most of this path's time re-loading the same weights. Still lazy: nothing is
        # imported or loaded until a paper actually has a suspect page.
        if self._converter is None:
            self._converter = DocumentConverter()
        converter = self._converter
        out: list[ExtractedTable] = []
        for page in wanted:
            try:
                result = converter.convert(
                    DocumentStream(name="paper.pdf", stream=io.BytesIO(pdf)),
                    page_range=(page, page),
                )
            except Exception:  # noqa: BLE001 - best-effort repair; a bad page keeps TEI cells
                log.warning("docling failed on page %d", page, exc_info=True)
                continue
            out.extend(_tables_of(result.document, page))
        return tuple(out)


def _tables_of(document: object, page: int) -> list[ExtractedTable]:
    tables: list[ExtractedTable] = []
    for table in getattr(document, "tables", ()) or ():
        grid = getattr(getattr(table, "data", None), "grid", None) or ()
        rows = tuple(tuple(str(cell.text or "").strip() for cell in row) for row in grid)
        if not rows:
            continue
        bbox = _bbox_of(table, document, page)
        if bbox is None:
            continue
        tables.append(
            ExtractedTable(page=page, bbox=bbox, rows=rows, caption=_caption_of(table, document))
        )
    return tables


def _caption_of(table: object, document: object) -> str:
    """The caption Docling attributed to this table, or "" — best-effort, never fatal."""
    try:
        return str(table.caption_text(document) or "").strip()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - a missing caption only costs the fallback match
        return ""


def _bbox_of(
    table: object, document: object, page: int
) -> tuple[float, float, float, float] | None:
    """The table's region in TEI's frame: PDF points, top-left origin.

    Docling reports a bottom-left origin box per provenance item, so it is flipped against the
    page height the same conversion carries.
    """
    for prov in getattr(table, "prov", ()) or ():
        box = getattr(prov, "bbox", None)
        if box is None:
            continue
        size = (getattr(document, "pages", {}) or {}).get(getattr(prov, "page_no", page))
        height = float(getattr(getattr(size, "size", None), "height", 0.0) or 0.0)
        if not height:
            return None
        return (float(box.l), height - float(box.t), float(box.r), height - float(box.b))
    return None
