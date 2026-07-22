"""Repair the table cells GROBID reconstructs wrongly, from a second reading of the PDF.

GROBID gives real table structure most of the time, and where it does the TEI rows stay the
primary representation (D8). Where it does not, it merges a whole data row into a single cell
("0.696 ± 0.015 0.011 ± 0.000 0.697 ± 0.018") — and that is worse than no data at all, because
U7's grounding then reads those glued numbers as the paper's own.

So a table whose rows look merged is re-read from the PDF region GROBID gave coordinates for, and
the cells are replaced only when the new grid can be VERIFIED against THE PAGE ITSELF: every number
it puts in a cell must actually be printed in that region, and it must not read fewer numbers than
GROBID managed. The TEI cannot be the yardstick here — it is the thing being repaired, and it drops
rows as well as merging them — but the page can. A rebuild that fails the check is refused and the
TEI cells stand: being wrong in a new way is not an improvement.

Pure: given a doc-model and the tables an extractor read, the outcome is the same every time (P7).
"""

from __future__ import annotations

import io
import re
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from docsuri_ingestion.docmodel.parser import iter_blocks
from docsuri_ingestion.domain.assets import AssetCropSpec, ExtractedTable

# A number as a table reports one — never the digit inside an identifier like "HbA1c", which
# would otherwise have to be found on the page for the rebuild to verify.
_NUMBER_RE = re.compile(r"(?<![A-Za-z\d.])-?\d+(?:\.\d+)?(?![A-Za-z\d])")
# A space that splits a DECIMAL, e.g. "4. 69%" — healed before reading a cell. Only around the
# point: joining any digit-space-digit would fuse the neighbouring values of "0.771 0.775".
_INNER_SPACE_RE = re.compile(r"(?<=\.)\s+(?=\d)|(?<=\d)\s+(?=\.)")
# Reads the numbers printed in one page region: (page, bbox) -> numbers.
PrintedNumbers = Callable[[int, tuple[float, float, float, float]], "tuple[str, ...]"]
# A cell holding several numbers is the tell-tale of a merged row ("0.696 ± 0.015 0.011 ± 0.000").
_MERGED_CELL_NUMBERS = 3


def tables_needing_repair(doc: dict, crops: Sequence[AssetCropSpec]) -> list[AssetCropSpec]:
    """The crop specs of tables whose TEI cells look merged — the pages worth re-reading."""
    by_asset = {spec.asset_id: spec for spec in crops}
    out: list[AssetCropSpec] = []
    for block in iter_blocks(doc, "table"):
        ref = block.get("assetRef") or {}
        spec = by_asset.get(ref.get("assetId", ""))
        if spec is not None and _looks_merged(block.get("rows") or []):
            out.append(spec)
    return out


def apply_repairs(
    doc: dict,
    crops: Sequence[AssetCropSpec],
    tables: Sequence[ExtractedTable],
    printed: PrintedNumbers,
) -> int:
    """Replace merged TEI cells with a verified rebuild. Returns how many tables were repaired.

    ``printed`` reads the numbers actually printed in a region of the PDF — the ground truth a
    rebuild is checked against."""
    by_asset = {spec.asset_id: spec for spec in crops}
    repaired = 0
    for block in iter_blocks(doc, "table"):
        rows = block.get("rows") or []
        ref = block.get("assetRef") or {}
        spec = by_asset.get(ref.get("assetId", ""))
        if spec is None or not _looks_merged(rows):
            continue
        rebuilt = _best_match(spec, tables)
        if rebuilt is None:
            continue
        # Verify against the region the rebuilt rows were actually READ from — the extractor's own
        # table box. That box already covers every row it produced, so it is both complete and
        # tight. Widening it (e.g. unioning GROBID's box, which often shrinks to the caption strip)
        # would let a number printed just outside the table pass as "on the page" — the one thing
        # verification must refuse (C-2).
        if not _verified(rows, rebuilt.rows, printed(spec.page, rebuilt.bbox)):
            continue
        block["rows"] = [
            {"cells": [{"text": cell} for cell in row]} for row in rebuilt.rows if any(row)
        ]
        repaired += 1
    return repaired


def _looks_merged(rows: Sequence[Any]) -> bool:
    """Whether the reconstructed cells read as glued-together rows rather than real columns."""
    cells = [
        str(cell.get("text") or "")
        for row in rows
        if isinstance(row, dict)
        for cell in (row.get("cells") or [])
    ]
    if not cells:
        return False
    return any(len(_cell_numbers(cell)) >= _MERGED_CELL_NUMBERS for cell in cells)


def _best_match(spec: AssetCropSpec, tables: Sequence[ExtractedTable]) -> ExtractedTable | None:
    """The re-read table that overlaps this block's region most, if any does."""
    best, best_area = None, 0.0
    for table in tables:
        if table.page != spec.page:
            continue
        area = _overlap(spec.bbox, table.bbox)
        if area > best_area:
            best, best_area = table, area
    return best


def _cell_numbers(text: str) -> list[str]:
    """Numbers in a cell, healing a decimal an extractor split across a space ("4. 69%")."""
    return _NUMBER_RE.findall(_INNER_SPACE_RE.sub("", text))


def _overlap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    return width * height if width > 0 and height > 0 else 0.0


def _verified(
    rows: Sequence[Any], rebuilt: Sequence[Sequence[str]], printed: Sequence[str]
) -> bool:
    """Whether a rebuilt grid may replace the TEI cells.

    Two conditions, and they are the whole safety argument. Every number the rebuild places in a
    cell must be PRINTED in the table's region — so a second reader cannot introduce a figure the
    paper does not contain. And the rebuild must not read fewer numbers than GROBID did, so a
    repair never trades merged-but-complete data for tidy-but-partial data.
    """
    if not printed:
        return False
    old = Counter(
        n
        for row in rows
        for cell in (row.get("cells") or [])
        for n in _cell_numbers(str(cell.get("text") or ""))
    )
    new = Counter(n for row in rebuilt for cell in row for n in _cell_numbers(cell))
    if not new or sum(new.values()) < sum(old.values()):
        return False
    available = Counter(printed)
    return all(available[value] >= count for value, count in new.items())


def printed_numbers(pdf: bytes) -> PrintedNumbers:
    """A reader of the numbers actually printed in a region of the PDF.

    This is the yardstick a rebuild is checked against, read straight off the page with the same
    library the crop pipeline already uses. An unreadable page yields no numbers, which the
    verification treats as "cannot be checked" and therefore refuses to repair.
    """

    # The PDF is opened once, lazily, and reused across every table on the page — apply_repairs
    # calls this per candidate table, and re-parsing the whole PDF each time is the one place this
    # module does real repeated I/O. pdfplumber over BytesIO holds no OS handle, so the document is
    # released with the closure when the repair pass ends.
    pages: list = []

    def read(page_no: int, bbox: tuple[float, float, float, float]) -> tuple[str, ...]:
        try:
            if not pages:
                import pdfplumber

                pages.extend(pdfplumber.open(io.BytesIO(pdf)).pages)
            if not 1 <= page_no <= len(pages):
                return ()
            page = pages[page_no - 1]
            region = (
                max(0.0, bbox[0]),
                max(0.0, bbox[1]),
                min(float(page.width), bbox[2]),
                min(float(page.height), bbox[3]),
            )
            return tuple(_NUMBER_RE.findall(page.crop(region).extract_text() or ""))
        except Exception:  # noqa: BLE001 - unreadable page -> no yardstick -> no repair
            return ()

    return read
