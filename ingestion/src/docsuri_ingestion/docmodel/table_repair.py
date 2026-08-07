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
# Glue pdfplumber's region text leaves at word seams, healed before reading the pool. Both
# directions occur: "30-60 meters" comes back "30-60meters" (digit->letter, the unit) and
# "Giannacopoulos 2022" comes back "Giannacopoulos2022" (letter->digit, the citation year) — in
# each case a value the page plainly prints fails the number pattern's boundary and a rebuild's
# perfectly-spaced copy reads as "not printed". The letter->digit split demands two digits or
# more so identifiers stay protected: "HbA1c" keeps its single digit glued and vouches for
# nothing.
_UNIT_GLUE_RE = re.compile(r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d{2,})")
# Reads the text printed in one page region: (page, bbox) -> text.
PrintedText = Callable[[int, tuple[float, float, float, float]], str]
# Tokens a word-level check compares. One-character cells ("N", "-") carry no evidence either way.
_WORD_RE = re.compile(r"[0-9a-z]{2,}", re.IGNORECASE)
# A cell holding several numbers is the tell-tale of a merged row ("0.696 ± 0.015 0.011 ± 0.000").
_MERGED_CELL_NUMBERS = 3
# The label each reader renders its own way ("Table 2 :" against "Table 2:"), dropped before the
# two captions are compared — what identifies the table is the sentence after it.
_CAPTION_LABEL_RE = re.compile(r"^\s*(?:table|tab\.?)\s*[IVXLC\d]+\s*[:.]?\s*", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+", re.IGNORECASE)
# Under this a caption is too generic to identify a table on its own ("Results", "Ablation").
_CAPTION_MIN_CHARS = 30
# Compare an OPENING stretch, not the whole caption: the two readers agree on where a caption
# starts but not where it ends — one truncates a long one, the other runs it into the following
# paragraph — so demanding the whole of it made a matching caption look like a mismatch.
_CAPTION_PROBE_CHARS = 60


def tables_needing_repair(doc: dict, crops: Sequence[AssetCropSpec]) -> list[AssetCropSpec]:
    """The crop specs of tables worth re-reading — merged cells, or no cells at all."""
    by_asset = {spec.asset_id: spec for spec in crops}
    out: list[AssetCropSpec] = []
    for block in iter_blocks(doc, "table"):
        ref = block.get("assetRef") or {}
        spec = by_asset.get(ref.get("assetId", ""))
        if spec is not None and _needs_repair(block.get("rows") or []):
            out.append(spec)
    return out


def _needs_repair(rows: Sequence[Any]) -> bool:
    """Whether a re-read could improve this table.

    Two distinct GROBID failures, and only the second was ever routed here. Cells can come out
    EMPTY, when reconstruction fails outright and the block keeps its caption with no rows at all
    (the case ``test_a_table_grobid_could_not_reconstruct_keeps_its_caption`` pins). Or they come
    out GLUED — several columns run into one, which a cell holding several numbers gives away.
    The empty case is the worse of the two — the whole grid is gone, not merely mis-split — yet
    the merged-cell test alone reads it as healthy, so the repair never ran on exactly the tables
    that needed it most.

    Sending an empty table through is safe for the same reason a merged one is: the rebuild still
    has to place only numbers printed in the region (C-2), and a table with genuinely no data
    finds no overlapping re-read and is left alone.
    """
    cells = _cells_of(rows)
    return not cells or any(len(_cell_numbers(cell)) >= _MERGED_CELL_NUMBERS for cell in cells)


def apply_repairs(
    doc: dict,
    crops: Sequence[AssetCropSpec],
    tables: Sequence[ExtractedTable],
    printed: PrintedText,
) -> int:
    """Replace merged TEI cells with a verified rebuild. Returns how many tables were repaired.

    ``printed`` reads the text actually printed in a region of the PDF — the ground truth a
    rebuild is checked against."""
    by_asset = {spec.asset_id: spec for spec in crops}
    repaired = 0
    for block in iter_blocks(doc, "table"):
        rows = block.get("rows") or []
        ref = block.get("assetRef") or {}
        spec = by_asset.get(ref.get("assetId", ""))
        if spec is None or not _needs_repair(rows):
            continue
        rebuilt = _best_match(spec, tables) or _caption_match(spec, tables)
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


def _cells_of(rows: Sequence[Any]) -> list[str]:
    return [
        str(cell.get("text") or "")
        for row in rows
        if isinstance(row, dict)
        for cell in (row.get("cells") or [])
    ]


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


def _caption_match(spec: AssetCropSpec, tables: Sequence[ExtractedTable]) -> ExtractedTable | None:
    """The re-read table this block's CAPTION names, when its region names none.

    The failure that empties a table's cells also collapses GROBID's box onto the caption strip,
    and that strip lies BETWEEN the tables it sits among — overlapping neither. Observed on
    ``1909.03716`` page 5: an 21pt box at y 258-279 against real tables at y 62-247 and y 291-393,
    11pt above and 12pt below. Distance cannot choose there, and choosing wrong would file one
    table's numbers under another's caption — numbers that ARE printed on the page, so the C-2
    check downstream would not catch the misattribution. The caption does choose: it matched
    "Table 2 ..." exactly and separated it from the "Table 3 ..." grid 12pt away.

    Demanded strictly, because this runs precisely where geometry has already failed: the block's
    whole caption must appear in the candidate's, and exactly one candidate on the page may match.
    An ambiguous page is left unrepaired.

    The caption comes off the crop spec rather than the block: they are the same string, written
    from the same variable in the same walk (``tei._table_block`` hands it to ``_record_crop``),
    and taking it here keeps both matchers to one ``(spec, tables)`` shape.
    """
    caption = _normalise(spec.caption)[:_CAPTION_PROBE_CHARS]
    if len(caption) < _CAPTION_MIN_CHARS:
        return None
    hits = [
        table
        for table in tables
        if table.page == spec.page and caption in _normalise(table.caption)
    ]
    return hits[0] if len(hits) == 1 else None


def _normalise(text: object) -> str:
    """Caption text reduced to what two readers can agree on.

    Letters and digits only. The two readers render the same caption with different punctuation —
    GROBID gave `"bounded by m " means … r ∼ p(•` where the re-read gave `'bounded by m ' means …
    r ∼ p (` — so quotes, spacing and brackets have to go before the comparison, not just case and
    the label each spells its own way ("Table 2 :" against "Table 2:").
    """
    stripped = _CAPTION_LABEL_RE.sub("", str(text or ""), count=1)
    return _NON_ALNUM_RE.sub("", stripped).lower()


def _cell_numbers(text: str) -> list[str]:
    """Numbers in a cell, healing a decimal an extractor split across a space ("4. 69%")."""
    return _NUMBER_RE.findall(_INNER_SPACE_RE.sub("", text))


def _overlap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    return width * height if width > 0 and height > 0 else 0.0


def _verified(rows: Sequence[Any], rebuilt: Sequence[Sequence[str]], printed: str) -> bool:
    """Whether a rebuilt grid may replace the TEI cells.

    Two conditions, and they are the whole safety argument. Everything the rebuild places in a cell
    must be PRINTED in the table's region — so a second reader cannot introduce content the paper
    does not contain. And the rebuild must not read LESS than GROBID did, so a repair never trades
    merged-but-complete data for tidy-but-partial data.

    What gets compared depends on what the table holds. Numbers are the sharper evidence and stay
    the test wherever there are any. But judging on numbers ALONE meant a table without them could
    never be verified and so was never repaired — and plenty of tables in these papers are text
    ("Attack Type | Example", ablation descriptions, dataset overviews). Those are compared on
    words instead, under the same two conditions — this function chooses between them, and
    ``_proven`` holds the conditions themselves so a future tightening cannot reach one and miss
    the other.

    The two paths heal the printed text differently, and the asymmetry is deliberate. The numeric
    pool needs ``_INNER_SPACE_RE`` first, to rejoin a decimal the extractor split across a space
    ("4. 69%") before any number can be read out of it; doing that to the word pool would fuse
    neighbouring words instead of repairing anything. Both then get ``_UNIT_GLUE_RE``, which
    re-cuts the seams pdfplumber closes ("30-60meters", "Giannacopoulos2022").
    """
    if not printed.strip():
        return False
    if any(_cell_numbers(cell) for row in rebuilt for cell in row):
        healed = _UNIT_GLUE_RE.sub(" ", _INNER_SPACE_RE.sub("", printed))
        return _proven(rows, rebuilt, _cell_numbers, set(_NUMBER_RE.findall(healed)))
    return _proven(rows, rebuilt, _words, set(_words(_UNIT_GLUE_RE.sub(" ", printed))))


def _proven(
    rows: Sequence[Any],
    rebuilt: Sequence[Sequence[str]],
    tokens: Callable[[str], list[str]],
    available: set[str],
) -> bool:
    """The two conditions of ``_verified``, over whichever tokens that path compares.

    A rebuild with nothing to compare is refused rather than waved through — verifying against an
    empty set would let any grid pass, which is the one outcome this check exists to prevent.
    """
    new = Counter(t for row in rebuilt for cell in row for t in tokens(cell))
    if not new:
        return False
    old = Counter(t for cell in _cells_of(rows) for t in tokens(cell))
    if sum(new.values()) < sum(old.values()):
        return False
    # Containment, not multiplicity: a cell spanning seven columns is printed ONCE but lands in
    # the grid seven times ("1.12 (210)" across every header column), and demanding seven printed
    # copies refused real tables wholesale. Fabrication is still impossible — a value the region
    # never prints stays refused — and replication of a printed value is colspan flattening, not
    # invented content.
    return all(token in available for token in new)


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def printed_text(pdf: bytes) -> PrintedText:
    """A reader of the text actually printed in a region of the PDF.

    This is the yardstick a rebuild is checked against, read straight off the page with the same
    library the crop pipeline already uses. An unreadable page yields nothing, which the
    verification treats as "cannot be checked" and therefore refuses to repair.

    The region's whole text is returned rather than just its numbers: the numbers were always
    derived from it, and a table that holds none still has to be checkable against something.
    """

    # The PDF is opened once, lazily, and reused across every table on the page — apply_repairs
    # calls this per candidate table, and re-parsing the whole PDF each time is the one place this
    # module does real repeated I/O. pdfplumber over BytesIO holds no OS handle, so the document is
    # released with the closure when the repair pass ends.
    pages: list = []
    # Two suspect blocks can resolve to the SAME re-read table — GROBID tends to fail on every
    # table of a page at once, and the caption fallback is a second route to a table the region
    # match may also find — so the same (page, box) is cropped and extracted twice. The reading is
    # a pure function of those two, and this memo dies with the closure exactly as ``pages`` does.
    seen: dict[tuple[int, tuple[float, float, float, float]], str] = {}

    def read(page_no: int, bbox: tuple[float, float, float, float]) -> str:
        if (page_no, bbox) in seen:
            return seen[(page_no, bbox)]
        text = ""
        try:
            if not pages:
                import pdfplumber

                pages.extend(pdfplumber.open(io.BytesIO(pdf)).pages)
            if 1 <= page_no <= len(pages):
                page = pages[page_no - 1]
                region = (
                    max(0.0, bbox[0]),
                    max(0.0, bbox[1]),
                    min(float(page.width), bbox[2]),
                    min(float(page.height), bbox[3]),
                )
                text = page.crop(region).extract_text() or ""
        except Exception:  # noqa: BLE001 - unreadable page -> no yardstick -> no repair
            text = ""
        seen[(page_no, bbox)] = text
        return text

    return read
