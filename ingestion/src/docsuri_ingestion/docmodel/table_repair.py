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
import logging
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from docsuri_ingestion.docmodel.parser import iter_blocks
from docsuri_ingestion.domain.assets import AssetCropSpec, ExtractedTable
from docsuri_ingestion.text_keys import alnum_key

log = logging.getLogger("docsuri.ingestion.tables")


@dataclass(frozen=True, slots=True)
class PrintedRegion:
    """What the page draws inside one region: its text, and which of those words are ROTATED.

    The two are kept apart on purpose. ``text`` is the yardstick a rebuild is measured against, so
    it has to stay literally what the reader reported — nothing may be added to it to make a match
    easier. ``rotated`` records the words whose reading DIRECTION a geometric reader cannot settle,
    and it is the verifier's business alone what allowance, if any, that earns (see ``_proven``).
    """

    text: str
    rotated: tuple[str, ...] = ()


# Reads what a page region prints: (page, bbox) -> PrintedRegion.
PrintedText = Callable[[int, tuple[float, float, float, float]], PrintedRegion]

# A number as a table reports one — never the digit inside an identifier like "HbA1c", which
# would otherwise have to be found on the page for the rebuild to verify.
_NUMBER_RE = re.compile(r"(?<![A-Za-z\d.])-?\d+(?:\.\d+)?(?![A-Za-z\d])")
# A space that splits a DECIMAL, e.g. "4. 69%" — healed before reading a CELL, where an extractor
# has already decided where the value ends. Only around the point: joining any digit-space-digit
# would fuse the neighbouring values of "0.771 0.775". This is never applied to the printed pool:
# there the spacing is the page's own, and rewriting it invents values the page does not print.
_INNER_SPACE_RE = re.compile(r"(?<=\.)\s+(?=\d)|(?<=\d)\s+(?=\.)")
# Papers set a minus as U+2212 (or a dash from the same family), while a table extractor's cell
# uses ASCII "-". Read literally, the two sides disagree about the SAME value: a cell's "-5" was
# looked for among page numbers that only ever held "5", and one verified rebuild was refused over
# exactly that ("-5 -4 -3 -2" on arXiv:2409.08036). Normalised identically on both sides, because a
# one-sided rewrite would replace this asymmetry with another.
_MINUS_SIGNS = str.maketrans({"−": "-", "–": "-", "‐": "-", "‑": "-"})
# Word-gap tolerance as a fraction of font size, for reading the printed pool. pdfplumber's own
# default is an absolute 3pt, which is wider than the space of a 9-10pt paper and glued whole
# regions into one token; a space is proportional to the font, so the threshold should be too.
_GAP_RATIO = 0.15
# Tokens a word-level check compares. One-character cells ("N", "-") carry no evidence either way.
_WORD_RE = re.compile(r"[0-9a-z]{2,}", re.IGNORECASE)
# A cell holding several numbers is the tell-tale of a merged row ("0.696 ± 0.015 0.011 ± 0.000").
_MERGED_CELL_NUMBERS = 3
# The label each reader renders its own way ("Table 2 :" against "Table 2:"), dropped before the
# two captions are compared — what identifies the table is the sentence after it.
_CAPTION_LABEL_RE = re.compile(r"^\s*(?:table|tab\.?)\s*[IVXLC\d]+\s*[:.]?\s*", re.IGNORECASE)
# Under this a caption is too generic to identify a table on its own ("Results", "Ablation",
# "Ablation study on the two components" is 33 and does identify one).
_CAPTION_MIN_CHARS = 30
# How much of two captions must AGREE before the match is accepted. A separate number from the one
# above even where they coincide today, because they answer different questions and move for
# different reasons: raising the generic-caption floor to keep "Results" out would, if this were
# the same constant, silently drop real repairs whose readers part company early. Measured on the
# sweep's own case, the shortest caption that identified its table alone normalises to 56
# characters, and the sibling pair that had to be told apart diverged at 71.
_CAPTION_MIN_AGREEMENT_CHARS = 30


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

    "Empty" is judged on cell TEXT, not on whether rows exist. GROBID fails these two ways too:
    it emits no rows at all, or it recovers the grid's shape and none of its contents, leaving
    ``<row><cell/><cell/></row>``. The second carries exactly as little as the first — a reader
    gets a blank grid — but a structure-only check reads it as healthy and skips the re-read.

    Sending an empty table through is safe for the same reason a merged one is: the rebuild still
    has to place only numbers printed in the region (C-2), and a table with genuinely no data
    finds no overlapping re-read and is left alone.
    """
    cells = [cell for cell in _cells_of(rows) if cell.strip()]
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
    """The re-read table that overlaps this block's region most, if any does.

    Any overlap wins, with no minimum. That looks unsafe — geometry always beating the caption
    fallback means a GROBID box clipping a NEIGHBOURING grid would file that neighbour's rows under
    this table's caption, and ``_verified`` cannot catch it because it checks against the matched
    table's own region, where those numbers genuinely are printed. Measured on 89 repair candidates
    across the 50-paper sample, the shape does not occur: overlap is bimodal, never marginal.

        geometric match found         39 / 89     no match at all   50 / 89
        cover (overlap / GROBID box)  min 0.114   median 0.648      max 1.000
        cover < 0.10                  0 / 39

    The collapsed-caption-strip failure ``_caption_match`` exists for produces ZERO overlap, not a
    sliver — which is why the fallback is reachable and in fact decides the majority (50 of 89).
    Only 3 candidates had geometry and caption disagree, all at cover 0.63-0.79 where geometry is
    the better witness. A minimum-cover threshold would therefore change 0 of 89 decisions at any
    value the data supports, while costing recall if set higher. Left as it is, on evidence.

    Those figures describe ``spec.bbox`` as it was BEFORE the crop-framing change: the box is now
    the ``<table>`` content region and its page comes from that element too, so the cover
    distribution above has not been re-measured against today's input. Re-run the repair census
    before quoting them again. Note also that the box this overlaps is GROBID's, not the regrown
    one the renderer draws — regrowth is applied at render time and this matcher does not see it."""
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

    The table is the one whose caption AGREES WITH THIS BLOCK'S FOR LONGEST, and it has to win
    alone. A fixed-length probe cannot do this job, because the two readers disagree about where a
    caption ends in both directions at once:

    * GROBID runs a caption into what follows it, so the block's version carries a tail the page
      never gave this table — "…of the GINN-based detector. rithm 2 (Λ min …", where "rithm 2" is
      the NEXT table's "Algorithm 2". A 60-character probe reaches into that tail and matches
      nothing, although the real caption (56 characters normalised) is quoted exactly.
    * Sibling tables share an opening — "Accuracy (%) under different experimental conditions. The
      values are averaged for each …" is the start of BOTH Table 5 and Table 6, which parted only
      at "backbone" against "dataset". A short probe matches both and the page reads as ambiguous.

    Longest agreement settles both: the contaminated tail simply ends the agreement, and the
    siblings are separated by the character where they diverge. Ambiguity is still refused — a tie
    for longest means the captions do not identify a table — and a winner still has to agree over
    ``_CAPTION_MIN_AGREEMENT_CHARS``. What is matched is never trusted on its own: ``_verified``
    judges the rebuilt grid against the page either way.

    The agreement is measured by ``_agreement_len``, which tolerates leading text on the re-read
    side and demands the agreed stretch reach an end — see there for why either alone fails.

    The caption comes off the crop spec rather than the block: they are the same string, written
    from the same variable in the same walk (``tei._table_block`` hands it to ``_record_crop``),
    and taking it here keeps both matchers to one ``(spec, tables)`` shape.
    """
    caption = _normalise(spec.caption)
    if len(caption) < _CAPTION_MIN_CHARS:
        return None
    scored = [
        (_agreement_len(caption, _normalise(table.caption)), table)
        for table in tables
        if table.page == spec.page
    ]
    best = max((length for length, _ in scored), default=0)
    if best < _CAPTION_MIN_AGREEMENT_CHARS:
        return None
    winners = [table for length, table in scored if length == best]
    return winners[0] if len(winners) == 1 else None


def _agreement_len(spec_caption: str, read_caption: str) -> int:
    """How much of the block's caption the re-read caption quotes, or 0 when they disagree.

    Two rules, each carrying a measured failure:

    * The opening of ``spec_caption`` may sit at ANY offset in ``read_caption``, not only at the
      start. GROBID's caption is label-free by construction (the TEI walk files the label into
      ``<head>``) while the re-read caption is the caption as PRINTED — and ``_CAPTION_LABEL_RE``
      only knows arabic and roman numerals, so an appendix label ("Table A1:", "TABLE S2.") or a
      leading "(a)" survived normalisation and scored a strict prefix comparison 0 against a
      caption it quotes verbatim. Searching for the opening instead makes every leading spelling
      irrelevant without enumerating label grammars.
    * The agreed stretch must REACH AN END — the whole of the spec's caption, or the end of the
      re-read's. Truncation and a contaminated tail both pass (the intact side is consumed whole),
      but two captions that merely share an opening and then both go their own way agree nowhere
      that both speak: with the winner's own region as the verification yardstick, a sibling
      matched on a shared 30-character opening would verify against ITSELF, and the wrong table's
      rows would be written under this block's caption.

    Pure."""
    if spec_caption and spec_caption in read_caption:
        return len(spec_caption)  # the whole caption is quoted, wherever it sits
    ceiling = min(len(spec_caption), len(read_caption))
    for length in range(ceiling, _CAPTION_MIN_AGREEMENT_CHARS - 1, -1):
        if read_caption.endswith(spec_caption[:length]):
            return length  # the re-read caption ends inside the spec's — truncation, not sibling
    return 0


def _normalise(text: object) -> str:
    """Caption text reduced to what two readers can agree on.

    Letters and digits only. The two readers render the same caption with different punctuation —
    GROBID gave `"bounded by m " means … r ∼ p(•` where the re-read gave `'bounded by m ' means …
    r ∼ p (` — so quotes, spacing and brackets have to go before the comparison, not just case and
    the label each spells its own way ("Table 2 :" against "Table 2:").
    """
    return alnum_key(_CAPTION_LABEL_RE.sub("", str(text or ""), count=1))


def _cell_numbers(text: str) -> list[str]:
    """Numbers in a cell, healing a decimal an extractor split across a space ("4. 69%")."""
    return _NUMBER_RE.findall(_INNER_SPACE_RE.sub("", text.translate(_MINUS_SIGNS)))


def _page_numbers(text: str) -> list[str]:
    """Numbers a page region prints, read exactly as printed.

    The cell reader's decimal healing is deliberately absent. A cell is one value an extractor has
    already delimited, so rejoining "4. 69" there recovers what it meant; the region is running
    text where "avg. 0.85" and "4. 69 patients" are ordinary, and healing them either destroys a
    printed value or manufactures one that was never on the page.

    The MINUS normalisation is not that kind of rewrite and is applied to BOTH sides: it changes
    which character counts as a sign, not where a value begins or ends.
    """
    return _NUMBER_RE.findall(text.translate(_MINUS_SIGNS))


def _words(text: str) -> list[str]:
    """Word tokens, read the same way in a cell and on the page — neither side is rewritten."""
    return [w.lower() for w in _WORD_RE.findall(text)]


def _overlap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    # Same arithmetic as the audit's ``_assets._overlap_area`` — kept separate on purpose, since
    # this one pairs specs with Docling tables and that one measures delivered crops; neither
    # should move when the other's pairing rule is retuned.
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    return width * height if width > 0 and height > 0 else 0.0


def _verified(
    rows: Sequence[Any], rebuilt: Sequence[Sequence[str]], printed: PrintedRegion
) -> bool:
    """Whether a rebuilt grid may replace the TEI cells.

    Two conditions, and they are the whole safety argument. Everything the rebuild places in a cell
    must be PRINTED in the table's region — so a second reader cannot introduce content the paper
    does not contain. And the rebuild must not read LESS than GROBID did, so a repair never trades
    merged-but-complete data for tidy-but-partial data.

    EVERY kind of token the rebuild emits is checked, not just the sharpest one. Numbers used to
    be the whole test wherever the grid held any, which left two holes at once: a table with no
    numbers could never be verified and so was never repaired (and plenty of tables in these papers
    are text — "Attack Type | Example", ablation descriptions, dataset overviews), while a mostly-
    text grid carrying a single stray digit had all of its text waved through on the strength of
    that one number. Both are closed by running the check per token kind and requiring all of them,
    with ``_proven`` holding the conditions once so a future tightening cannot reach one kind and
    miss the other.

    Neither pool is rewritten before comparison. The reader hands back the page's own words
    (``printed_text``), so a seam this used to patch with regexes never forms — and patching it
    was worse than the seam: splitting "ResNet50" to heal a glued unit also minted a standalone
    "50" that the page never prints as a value, which is exactly the fabrication C-2 forbids.
    """
    if not printed.text.strip():
        return False
    # Each kind of token a rebuilt cell may claim, paired with how the same kind is read off the
    # page, and with the leniency that kind allows. Words are read identically on both sides;
    # numbers are not, because a cell and a page line disagree about what a numeral is glued to.
    reversible = frozenset(t for word in printed.rotated for t in _words(word))
    checks = [
        (in_cell, set(on_page(printed.text)), lenient)
        for in_cell, on_page, lenient in (
            (_cell_numbers, _page_numbers, frozenset()),
            (_words, _words, reversible),
        )
        if any(in_cell(cell) for row in rebuilt for cell in row)
    ]
    return bool(checks) and all(
        _proven(rows, rebuilt, in_cell, available, lenient)
        for in_cell, available, lenient in checks
    )


def _proven(
    rows: Sequence[Any],
    rebuilt: Sequence[Sequence[str]],
    tokens: Callable[[str], list[str]],
    available: set[str],
    reversible: frozenset[str] = frozenset(),
) -> bool:
    """The two conditions of ``_verified``, over whichever tokens that path compares.

    A rebuild with nothing to compare is refused rather than waved through — verifying against an
    empty set would let any grid pass, which is the one outcome this check exists to prevent.

    ``reversible`` is the only leniency, and it is decided HERE rather than by widening the page's
    text, so what the page prints stays literally what the reader reported. pdfplumber orders a run
    geometrically and a top-to-bottom label therefore comes out backwards: page 31 of
    arXiv:2409.08036 sets its row-group labels rotated and the reader returns ``elbmesnE``, ``DSN``,
    ``EN``, ``TN`` for "Ensemble", "NSD", "NE", "NT", which refused a correctly rebuilt 50-row table
    over four tokens out of 891. Which end such a run starts from is genuinely ambiguous, so a token
    that failed the exact test is given a second look against the reversed rotated words — and only
    those, so a page's ordinary horizontal text is compared exactly as before. Never offered for
    NUMBERS (the caller passes an empty set there): reversing "12.5" would mint "5.21", a value the
    page does not print, which is the one thing verification exists to refuse (C-2).
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
    return all(token in available or token[::-1] in reversible for token in new)


def _rotated_words(words: Sequence[Any]) -> tuple[str, ...]:
    """The words the page itself marks as drawn ROTATED, as the reader returned them.

    Carried beside the region's text rather than mixed into it, so a verifier can tell a word the
    page prints from one whose reading direction is merely ambiguous. Anything holding a digit is
    left out here rather than downstream: it can then never reach a reversal, whichever check asks.
    Measured on the page above, 7 of 410 words qualify. Pure.
    """
    out = []
    for word in words:
        text = str(word.get("text") or "")
        if text and not word.get("upright", True) and not any(ch.isdigit() for ch in text):
            out.append(text)
    return tuple(out)


def printed_text(pdf: bytes) -> PrintedText:
    """A reader of the text actually printed in a region of the PDF.

    This is the yardstick a rebuild is checked against, read straight off the page with the same
    library the crop pipeline already uses. An unreadable page yields nothing, which the
    verification treats as "cannot be checked" and therefore refuses to repair.

    The region's whole text is returned rather than just its numbers: the numbers were always
    derived from it, and a table that holds none still has to be checkable against something. It is
    returned EXACTLY as read, with the rotated words named separately (``PrintedRegion``) rather
    than folded in — a yardstick that quietly contains more than the page does is not one.

    Built from word boxes read at a FONT-RELATIVE gap tolerance, joined by single spaces. Both
    parts matter, and the second is the one that was wrong before.

    pdfplumber decides where a word ends by a horizontal gap, and its default 3pt is wider than the
    space of an ordinary paper: measured on 2410.04309 the inter-word gap is 2.24pt, so a whole
    page came back as "ComprehensiveMonitoringofAirPollution…" and a table region as "ValueRange",
    "30-60meters". That glue was previously patched afterwards by re-splitting the string at
    digit/letter boundaries — a cure worse than the disease, because splitting "ResNet50" to heal a
    glued unit also minted a standalone "50" the page never prints AS A VALUE, and a rebuild could
    place that "50" in a cell and still verify. ``x_tolerance_ratio`` scales the gap with the font
    size instead, which is the quantity a space is actually proportional to, so the words separate
    at the source and neither side of the comparison needs rewriting.
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
    seen: dict[tuple[int, tuple[float, float, float, float]], PrintedRegion] = {}

    def read(page_no: int, bbox: tuple[float, float, float, float]) -> PrintedRegion:
        if (page_no, bbox) in seen:
            return seen[(page_no, bbox)]
        region_text = PrintedRegion("")
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
                words = page.crop(region).extract_words(x_tolerance_ratio=_GAP_RATIO) or ()
                region_text = PrintedRegion(
                    " ".join(str(w.get("text") or "") for w in words), _rotated_words(words)
                )
        except TypeError:
            # Not an unreadable page — the extractor did not accept the call. ``x_tolerance_ratio``
            # arrived in pdfplumber 0.11.1, so an environment resolving lower raises here on EVERY
            # region. That failure is indistinguishable from "nothing needed repair" downstream:
            # empty printed text reads as "refuse", ``table_repair_failed`` only fires on a raised
            # exception, and ``tables_repaired`` simply never appears. Table repair would be a
            # silent no-op for the whole corpus. Logged loudly because it is an environment fault,
            # not a property of this paper. The dependency floor is pinned to match.
            log.error("pdfplumber rejected the word-extraction call — table repair is inert",
                      exc_info=True)
            region_text = PrintedRegion("")
        except Exception:  # noqa: BLE001 - unreadable page -> no yardstick -> no repair
            region_text = PrintedRegion("")
        seen[(page_no, bbox)] = region_text
        return region_text

    return read
