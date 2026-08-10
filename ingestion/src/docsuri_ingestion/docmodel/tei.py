"""Deterministic GROBID TEI -> doc-model parser (BR-30, D1) — the PDF/GROBID structured path.

Non-arXiv sources (Semantic Scholar / OpenAlex) have no rich HTML; GROBID's
``processFulltextDocument`` returns TEI that *does* carry structure — ``<div>`` sections with
``<head>`` titles, ``<p>`` paragraphs, ``<formula>`` equations, and ``<figure>`` /
``<figure type="table">`` blocks. The old path flattened all of that into a single paragraph
(``parse_text_to_docmodel``); this parser preserves it, mirroring the HTML parser's output
shape so the viewer/chunker treat both identically.

What each TEI node maps to (and the honest fidelity limits of the PDF path):
  - ``<div><head>…</head><p>…</p>``      -> Section + ParagraphBlock (reading order preserved)
  - ``<formula>`` (block-level)          -> FormulaBlock as an IMAGE (assetRef, type=formula):
        GROBID emits OCR'd formula text, not reliable LaTeX, so we do NOT store garbled LaTeX
        — the equation degrades to a page-crop image (TD-12, our 3a decision). Image bytes are
        populated by the coordinate crop pipeline; the parser only assigns the deterministic id.
        When a formula reader is configured the builder later fills ``latexOcr`` from that crop —
        searchable, never rendered (docmodel/formula_ocr.py).
  - ``<figure type="table"><table>``     -> TableBlock as DATA (rows/cells) — GROBID gives real
        table structure, so the structured rows stay the PRIMARY representation (D8). When the
        table also carries coordinates we ALSO attach a page-crop ``assetRef`` as a last-resort
        fallback (schema-sanctioned), so a later vision reader can re-read numbers GROBID's cell
        reconstruction may have garbled — the image never displaces the searchable data.
  - ``<figure>``                         -> FigureBlock (assetRef image, FR-17)
  - an algorithm float                   -> CodeBlock with text AND its page crop: GROBID has no
        algorithm concept, so it files a listing under ``<formula>`` (sometimes promoting the
        float's heading to the section title). Unlike equation glyphs, listing text survives
        extraction well enough to index, so the listing is searchable while the crop keeps a
        faithful rendering.

Figure/table position: GROBID groups ``<figure>`` elements (typically at body end), so their
exact inline position is not in TEI order. Figures nested inside a ``<div>`` keep that section;
a body-level one is put back by ``_place_floats`` on the first of three signals — the paragraph
that cites its number, else the section its page coordinates fall in, else a trailing section.
TEI predating the ``head`` coordinate request keeps only the first signal, so every float its body
never names lands in that trailing section; ``ingestion.docmodel.floats_trailing`` counts them
rather than letting a stale cache degrade the corpus unseen.

Deterministic: same TEI -> same DocModel, ids included (P7). No LLM (D1). Built as dicts and
validated through the generated ``DocModel`` binding, so drift from the schema fails loudly.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import MutableSequence, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import NamedTuple

from docsuri_shared.dtos import DocModel, SourceTier

from docsuri_ingestion.asset_extraction import caption_kind, caption_number
from docsuri_ingestion.docmodel.parser import (
    _DocCtx,
    _finish_docmodel,
    _SectionCtx,
    _with_abstract_section,
)
from docsuri_ingestion.domain.assets import AssetCropSpec, asset_id
from docsuri_ingestion.domain.enums import AssetType, FailureReason
from docsuri_ingestion.domain.errors import PermanentIngestionError
from docsuri_ingestion.xmlsafe import safe_fromstring

_WS_RE = re.compile(r"\s+")
# The section holding floats ``_place_floats`` found no home for. Named rather than spelled at the
# one site that builds it, because the builder counts what lands here: this is the shape the whole
# path degrades to when GROBID stops coordinating <head>, and it degrades silently otherwise.
TRAILING_FLOAT_SECTION_TITLE = "그림 및 표"
# An algorithm float's heading is CAPITALISED — "Algorithm 1", or "ALGORITHM 1" where IEEE styling
# puts the whole float head in caps. Spelled out rather than matched with re.IGNORECASE, because
# the split below runs UNANCHORED over a formula's whole text and a lowercase "algorithm 2"
# mid-sentence is a cross-reference, not a heading: ignoring case there tore a real listing in half
# at exactly such a mention (2607.16138, where the second listing's body became its own block).
# The anchored uses further down can afford to ignore case; this one cannot.
_ALGORITHM_HEAD_TEXT = r"(?:ALGORITHM|Algorithm)\s+\d+"
# Capturing keeps the heading with the listing it opens, and splitting on every occurrence
# separates two listings GROBID ran together.
_ALGORITHM_SPLIT_RE = re.compile(rf"({_ALGORITHM_HEAD_TEXT})")
# A listing numbers its steps ("1:", "2:"); a sentence that merely cites an algorithm does not.
_ALGORITHM_STEP_RE = re.compile(r"(?<!\d)\d+\s*:")
_ALGORITHM_MIN_STEPS = 2
_ALGORITHM_HEAD_RE = re.compile(rf"^\s*{_ALGORITHM_HEAD_TEXT}")
# Without a heading, numbered steps alone would also match a numbered derivation, so the listing
# has to speak pseudocode as well — and show more steps than the headed case needs.
_HEADLESS_MIN_STEPS = 3
# The colon-terminated keywords are matched separately: a trailing \b after ``Input\s*:`` demands a
# word character right after the colon, so the ordinary "Input: x" spelling failed to match while
# "Input:x" did. Only the alternatives that end in a word character can carry that boundary.
#
# Two strengths, because the two callers stand on different ground. A phrase like "end for" or a
# "Require:" line is pseudocode notation and essentially never appears in a sentence; "repeat",
# "until" and "procedure" are ordinary English that any paper describing an iterative method will
# use. Where the vocabulary is only corroborating evidence — a headless <formula> that already
# shows three or more numbered steps — the wide set is safe and catches more. Where it is the SOLE
# evidence, as on the <p> path, the wide set would retype a real paragraph as code: "Algorithm 1
# proceeds in rounds until the loss stops improving …" opens like a listing and says "until".
_STRUCTURAL_PSEUDOCODE = (
    r"\b(?:end\s+(?:for|while|if|procedure|function)|for\s+each|Require|Ensure)\b"
    r"|\b(?:Input|Output)\s*:"
)
_STRUCTURAL_PSEUDOCODE_RE = re.compile(_STRUCTURAL_PSEUDOCODE, re.IGNORECASE)
_PSEUDOCODE_RE = re.compile(
    rf"{_STRUCTURAL_PSEUDOCODE}|\b(?:repeat|until|procedure)\b",
    re.IGNORECASE,
)
# A listing that opens a <p> rather than a <formula>. GROBID classifies a float as <formula> only
# when it reads as maths; a pseudocode or verbatim listing usually looks like prose to it and lands
# in <p> instead — measured across the audit sample, 43 listings arrived that way against 1 as a
# formula, so inspecting formulas alone left nearly every listing typed as a paragraph.
#
# Wider vocabulary than the <formula> patterns above, and deliberately so: swept over the same
# 50-paper sample the <formula> path has ZERO candidates for Listing/Procedure/Pseudocode (0 as a
# section head, 0 inside a formula), while "Procedure" is an ordinary English word that would newly
# match prose there. Anchored at the paragraph start, so it can afford to ignore case.
_LISTING_HEAD_RE = re.compile(
    r"^\s*(?:Algorithm|Listing|Procedure|Pseudocode)\s+\d+", re.IGNORECASE
)
# "Listing 3: ..." is LaTeX's lstlisting caption — verbatim code, which carries neither numbered
# steps nor pseudocode vocabulary, so the heading has to stand on its own for that family.
_VERBATIM_HEAD_RE = re.compile(r"^\s*Listing\s+\d+\s*[:.]", re.IGNORECASE)
# Below this a "listing" is a caption GROBID split from its body, not a float. Swept over the audit
# sample: at 150 exactly one more block promotes (a four-triple RDF listing) and nothing further
# appears down to 100, so the gate is not what bounds recall here.
_LISTING_MIN_CHARS = 150
# How a float is numbered, in both spellings a paper uses: arabic, or the uppercase roman IEEE
# styling runs on ("TABLE III"). Roman is uppercase-only — under IGNORECASE the letter class sits
# inside ordinary lowercase words ("in", "vi", "mix") — and both spellings are keyword-anchored
# wherever this is used, so a string that merely contains letters cannot be read as a numeral.
_FLOAT_NUMERAL = r"(\d+|(?-i:[IVXLCDM]+)\b)"
# A body reference to a float ("Figure 7", "Fig.3", "Tab. XII"), scanned over every paragraph ONCE
# to index which float each one cites. One combined pattern rather than one per float per number:
# the numeral is captured instead of spelled into the pattern, so the whole document's citations
# come out of a single pass. ``\d+`` is greedy, which is what keeps "Figure 15" from reading as a
# citation of Figure 1 — a shorter number is never matched inside a longer one.
_FLOAT_MENTION_RE = re.compile(
    rf"\b(Fig(?:ure)?|Tab(?:le)?)\.?\s*{_FLOAT_NUMERAL}", re.IGNORECASE
)
# The same grammar anchored for reading a float's OWN number off its label or caption, one per
# kind so the keyword is fixed: a table must not claim a number only "Figure" carries.
_FLOAT_NUM_RE = {
    False: re.compile(rf"\s*(?:Figure|Fig)\.?\s*{_FLOAT_NUMERAL}", re.IGNORECASE),
    True: re.compile(rf"\s*(?:Table|Tab)\.?\s*{_FLOAT_NUMERAL}", re.IGNORECASE),
}
# A label GROBID reduced to the bare numeral, the keyword having stayed with the caption.
_BARE_NUMBER_LABEL_RE = re.compile(r"^\s*(\d+)\s*$")
# The bullet glyphs LaTeX's itemize renders and pdfalto carries through into GROBID's text.
_BULLET_CHARS = "•▪‣◦"
# Anchored at the paragraph start, leading whitespace folded into the pattern: this is tested
# against every <p> in the corpus, and ``.lstrip()`` first would copy the whole paragraph to look
# at one character.
_BULLET_START_RE = re.compile(rf"\s*[{_BULLET_CHARS}]")
# A glyph that OPENS AN ITEM: at the start or after whitespace, and FOLLOWED BY whitespace. The
# same glyph is also mathematical notation that papers put mid-item — "r ∼ p(•)", "Ψ(•, •)",
# "[•] denotes the truncated SVD" — and splitting on every occurrence shredded a real item into
# fragments beginning with a bracket. The trailing-space rule separates the two cleanly: swept over
# the audit sample, all 464 glyphs followed by a space are list markers and all 125 that are not
# are maths (every one inside brackets — "β(•)", "ϕ(•)", "P n (•)"), with no list marker among them.
_ITEM_BULLET_RE = re.compile(rf"(?:(?<=\s)|^)[{_BULLET_CHARS}]\s")


def _local(tag: object) -> str:
    """Local element name without the TEI namespace ('{...}div' -> 'div')."""
    return str(tag).rsplit("}", 1)[-1]


def parse_tei_to_docmodel(
    tei: str,
    *,
    paper_id: str,
    version: int,
    title: str,
    abstract: str | None,
    source_tier: SourceTier,
    parser_version: str,
    schema_version: str,
    generated_at: datetime,
    crops: list[AssetCropSpec] | None = None,
) -> DocModel:
    """Parse GROBID TEI into a validated structured ``DocModel`` (pure given its inputs).

    When ``crops`` is supplied, figure/formula page-crop specs (with their block assetIds) are
    appended to it during the walk — used by the asset pipeline to render aligned images.

    Raises ``ET.ParseError`` on malformed TEI — the builder catches it and falls back to the
    flat-text doc-model so a parser hiccup never blocks ingestion.
    """
    root = safe_fromstring(tei)
    body = _find_descendant(root, "body")
    doc_ctx = _DocCtx(paper_id=paper_id, version=version, crops=crops)

    sections: list[dict] = []
    trailing_figures: list[ET.Element] = []
    # Bound before the branch: a TEI carrying no <body> at all still reaches the trailing-section
    # call below, and reading the layout off an unbound name there crashed a parse that used to
    # degrade quietly to an empty doc-model.
    layout = _PageLayout({}, two_column=False)
    if body is not None:
        divs = [c for c in body if _local(c.tag) == "div"]
        floats = [c for c in body if _local(c.tag) == "figure"]
        layout = _page_layout(root, divs)
        placement = _place_floats(divs, floats, layout)
        trailing_figures = placement.leftover
        for idx, div in enumerate(divs, start=1):
            sections.append(_parse_div(div, f"s{idx}", doc_ctx, placement))

    figure_section = _trailing_figure_section(
        trailing_figures, len(sections) + 1, doc_ctx, layout
    )
    if figure_section is not None:
        sections.append(figure_section)

    sections = _with_abstract_section(sections, abstract)
    return _finish_docmodel(
        sections,
        paper_id=paper_id,
        version=version,
        title=title,
        abstract=abstract,
        source_tier=source_tier,
        parser_version=parser_version,
        schema_version=schema_version,
        generated_at=generated_at,
    )


# --------------------------------------------------------------------------- sections


def _parse_div(
    div: ET.Element, section_id: str, doc_ctx: _DocCtx, placement: _FloatPlacement
) -> dict:
    """A ``<div>`` -> Section: ``<head>`` title + ``<p>``/``<formula>``/nested ``<figure>``.

    ``placement`` carries the body-level floats ``_place_floats`` assigned here — opening the
    section, following the paragraph that cites them, or closing it. They are built with this
    section's own ``_SectionCtx`` so their block ids belong to the section they read in, which is
    also why placement is decided before the walk rather than after it.
    """
    sec_ctx = _SectionCtx(section_id=section_id)
    title = ""
    opening = placement.at_section_start.get(id(div), ())
    blocks: list[dict] = _float_blocks(opening, sec_ctx, doc_ctx)
    for child in list(div):
        name = _local(child.tag)
        if name == "head" and not title:
            title = _text(child)
        elif name == "p":
            blocks.extend(_paragraph_blocks(placement.text_of(child), sec_ctx, blocks))
            blocks.extend(_float_blocks(placement.after_para.get(id(child), ()), sec_ctx, doc_ctx))
        elif name == "formula":
            blocks.extend(
                _formula_or_algorithm_blocks(
                    child,
                    sec_ctx,
                    doc_ctx,
                    blocks,
                    # GROBID sometimes promotes an algorithm float's heading to the section title
                    # ("Algorithm 3 Improved step 4 of IKPLS"), leaving its steps in headless
                    # formulas. Inside such a section a stepped formula IS the listing.
                    in_algorithm_section=bool(_ALGORITHM_HEAD_RE.match(title)),
                )
            )
        elif name == "figure":
            blocks.extend(_float_blocks((child,), sec_ctx, doc_ctx))
    blocks.extend(_float_blocks(placement.at_section_end.get(id(div), ()), sec_ctx, doc_ctx))
    return {"id": section_id, "title": title, "blocks": blocks}


def _float_blocks(
    floats: Sequence[ET.Element], sec_ctx: _SectionCtx, doc_ctx: _DocCtx
) -> list[dict]:
    """Blocks for floats reading here, dropping any that turns out to carry nothing to show.

    One helper for all four positions a float can reach a section from (opening it, after the
    paragraph citing it, nested in the TEI already, closing it) — the ar5iv path has just had to
    teach one float to yield two blocks, and four hand-written copies of this loop is four places
    that change would have to land."""
    return [b for el in floats if (b := _figure_or_table_block(el, sec_ctx, doc_ctx))]


class _FloatPlacement(NamedTuple):
    """Where each body-level float goes, keyed by ``id()`` of its host element.

    Identity keys, not the elements themselves: ``ElementTree`` nodes hash by identity anyway and
    comparing them by value would be wrong for two floats with the same markup.

    ``para_text`` carries the paragraph text placement already had to build. Deciding placement
    needs every paragraph's text and so does the walk that follows, and ``_text`` joins
    ``itertext()`` then whitespace-substitutes the result — computing it twice walked the whole
    body twice for nothing.
    """

    after_para: dict[int, list[ET.Element]]
    at_section_start: dict[int, list[ET.Element]]
    at_section_end: dict[int, list[ET.Element]]
    leftover: list[ET.Element]
    para_text: dict[int, str]
    layout: _PageLayout

    def text_of(self, p: ET.Element) -> str:
        """This paragraph's text, from the placement pass when it ran, else read now.

        The fallback is the float-less paper: placement returns early there, so nothing has read
        the body yet and this is the first (and only) read.
        """
        cached = self.para_text.get(id(p))
        return cached if cached is not None else _text(p)


def _place_floats(
    divs: list[ET.Element], floats: list[ET.Element], layout: _PageLayout
) -> _FloatPlacement:
    """Decide where each body-level float belongs.

    GROBID files every ``<figure>`` after every ``<div>``, so TEI order carries no position and
    reading the body left every float stranded in a trailing dump — measured at 616 of 616 floats
    across 50 papers, i.e. a reader saw no figure anywhere in the text. Two signals put them back:

    1. **The text that cites it.** A float goes right after the first paragraph naming its number,
       which is where a reader wants it and what the ar5iv path effectively gives.
    2. **Its coordinates.** With no citation, the section whose ``<head>`` last precedes the float
       on the page owns it. Coarser than (1) — the float lands at the section's end — but it still
       reads inside the matter it belongs to.

    A float printed ABOVE the first heading is the teaser authors put on the title page, and it
    opens the first section rather than closing it — the same hoist the ar5iv path already does
    for a float that precedes every section there.

    Anything with neither signal is returned for the trailing section. TEI predating the ``head``
    coordinate request keeps signal (1) — citations are read from paragraph text and need no
    coordinates — so an older cache stays parseable and loses only its uncited floats.
    """
    if not floats:
        # Nothing to place, so nothing to read the body for. Without this a float-less paper pays
        # a full ``_text`` pass over every paragraph and an anchor sort to decide nothing.
        return _FloatPlacement({}, {}, {}, [], {}, layout)

    after_para: defaultdict[int, list[ET.Element]] = defaultdict(list)
    at_section_start: defaultdict[int, list[ET.Element]] = defaultdict(list)
    at_section_end: defaultdict[int, list[ET.Element]] = defaultdict(list)
    leftover: list[ET.Element] = []

    paragraphs = [p for div in divs for p in div if _local(p.tag) == "p"]
    para_text = {id(p): _text(p) for p in paragraphs}
    first_mention = _first_mentions(paragraphs, para_text)
    div_anchors = sorted(
        ((key, div) for div in divs if (key := _head_coord(div, layout)) is not None),
        key=lambda pair: pair[0],
    )

    for figure_el in sorted(floats, key=lambda el: _coord_sort_key(el, layout)):
        cite = _citing_paragraph(figure_el, paragraphs, first_mention)
        if cite is not None:
            after_para[id(cite)].append(figure_el)
            continue
        owner = _section_by_coords(figure_el, div_anchors, layout)
        if owner is not None:
            at_section_end[id(owner)].append(figure_el)
            continue
        if div_anchors and _coord_sort_key(figure_el, layout) < div_anchors[0][0]:
            at_section_start[id(div_anchors[0][1])].append(figure_el)
            continue
        leftover.append(figure_el)
    return _FloatPlacement(
        after_para, at_section_start, at_section_end, leftover, para_text, layout
    )


def _head_coord(div: ET.Element, layout: _PageLayout) -> tuple[float, float, float] | None:
    """Sort key of the div's own ``<head>`` when it carries coordinates — never a figure's."""
    for child in div:
        if _local(child.tag) == "head":
            return _coord_sort_key(child, layout) if child.get("coords") else None
    return None


def _first_mentions(
    paragraphs: list[ET.Element], para_text: dict[int, str]
) -> dict[tuple[bool, int], int]:
    """``(is_table, number)`` -> index of the FIRST paragraph citing it. One pass over the body.

    Built once for the whole document rather than asking each float to find itself. Searching per
    float re-read every paragraph once per float per number it claims, which on a 13-float paper
    was a third of the entire TEI parse — and the floats that most need the answer, the uncited
    ones the coordinate fallback exists for, paid the full scan to learn nothing.
    """
    first: dict[tuple[bool, int], int] = {}
    for index, p in enumerate(paragraphs):
        for match in _FLOAT_MENTION_RE.finditer(para_text[id(p)]):
            number = caption_number(match.group(2))
            if number is not None:
                first.setdefault((match.group(1).lower().startswith("tab"), number), index)
    return first


def _citing_paragraph(
    figure_el: ET.Element,
    paragraphs: list[ET.Element],
    first_mention: dict[tuple[bool, int], int],
) -> ET.Element | None:
    """The first paragraph naming this float's number, or None when the body never cites it."""
    is_table = _is_table_float(figure_el)
    hits = [
        first_mention[(is_table, number)]
        for number in _float_numbers(figure_el, is_table)
        if (is_table, number) in first_mention
    ]
    return paragraphs[min(hits)] if hits else None


def _is_table_float(figure_el: ET.Element) -> bool:
    """Whether GROBID typed this ``<figure>`` as a table — which block it becomes, and which
    keyword the body cites it by."""
    return (figure_el.get("type") or "").lower() == "table"


def _float_numbers(figure_el: ET.Element, is_table: bool) -> set[int]:
    """The float numbers this element claims ({7} for "Figure 7"), read off its own label.

    Numbers come from the label the block itself will carry, so the caption rules live in one
    place. A merged head ("Figure 4 :Figure 5 :") legitimately claims several.

    Every read here is KEYWORD-ANCHORED, and the bare-numeral fallback demands the label be
    nothing but the numeral. GROBID files a paper's theorem furniture under ``<figure>`` too —
    "Challenge 1 .", "Proposition 3 ." — so a rule that took the first number it found in a head
    handed those elements the numbers of Figure 1 and Figure 3 and printed them at those figures'
    citations. Anything not named as a float falls through to the coordinate signal instead.
    """
    label, caption = _figure_label_caption(figure_el)
    numbered = _FLOAT_NUM_RE[is_table]
    numbers = {n for n in map(caption_number, numbered.findall(label)) if n is not None}
    if not numbers:
        # No numbered head — GROBID files the whole caption into figDesc instead. Only a LEADING
        # number names this float; later ones are the caption citing other floats.
        lead = numbered.match(caption)
        value = caption_number(lead.group(1)) if lead else None
        if value is not None:
            numbers = {value}
    if not numbers:
        numbers = {int(n) for n in _BARE_NUMBER_LABEL_RE.findall(label)}
    return numbers


def _section_by_coords(
    figure_el: ET.Element,
    div_anchors: list[tuple[tuple[float, float, float], ET.Element]],
    layout: _PageLayout,
) -> ET.Element | None:
    """The div whose head last precedes the float in reading order, or None without coordinates."""
    position = _coord_sort_key(figure_el, layout)
    if position[0] == float("inf") or not div_anchors:
        return None
    owner = None
    for anchor, div in div_anchors:
        if anchor > position:
            break
        owner = div
    return owner


def _trailing_figure_section(
    figures: list[ET.Element], section_index: int, doc_ctx: _DocCtx, layout: _PageLayout
) -> dict | None:
    """Group body-level figures/tables into a trailing section, ordered by page/y coordinates."""
    if not figures:
        return None
    section_id = f"s{section_index}"
    sec_ctx = _SectionCtx(section_id=section_id)
    ordered = sorted(figures, key=lambda el: _coord_sort_key(el, layout))
    blocks = _float_blocks(ordered, sec_ctx, doc_ctx)
    if not blocks:
        return None
    return {"id": section_id, "title": TRAILING_FLOAT_SECTION_TITLE, "blocks": blocks}


# --------------------------------------------------------------------------- blocks


def _paragraph_blocks(
    text: str, sec_ctx: _SectionCtx, section_blocks: MutableSequence[dict]
) -> list[dict]:
    """A ``<p>`` -> paragraph, or the listing / bulleted list GROBID flattened into one.

    TEI has no list element on this path at all: GROBID emits neither ``<list>`` nor ``<item>``
    anywhere in the body, so a bulleted list arrives as prose carrying its bullet glyphs. Usually
    it arrives as one ``<p>`` PER ITEM (64 such paragraphs against 19 multi-bullet ones across the
    audit sample), which is why a run of them has to be rejoined rather than each split alone.
    """
    if not text:
        return []
    if _is_paragraph_listing(text):
        # Same text either way — what changes is that the listing stops being indistinguishable
        # from prose, so a reader sees it as code and an agent can tell it apart when quoting.
        return [_text_block(sec_ctx, "code", text)]
    items = _split_bullets(text)
    if not items:
        return [_text_block(sec_ctx, "paragraph", text)]
    # These items belong to whatever list is already running, regardless of how many arrived in
    # this one <p>. GROBID splits a single list both ways in the same document — one paragraph per
    # item, and a tail of several run together — so joining only the one-item case left a stray
    # bullet paragraph in front of a list holding the rest.
    host = _open_list(section_blocks)
    if host is not None:
        host["items"].extend({"text": item} for item in items)
        return []
    # No open list: start one by absorbing the bulleted paragraph immediately before. That first
    # item could not know a second was coming, so it landed as a paragraph and is reclaimed here.
    first = _trailing_bullet_items(section_blocks)
    if first is not None:
        section_blocks.pop()
        sec_ctx.release("paragraph")
        return [_list_block(sec_ctx, [*first, *items])]
    if len(items) == 1:
        # With neither neighbour a lone bullet is not a list, and inventing a one-item list where
        # the source had a sentence is the worse error — the paragraph stays verbatim.
        return [_text_block(sec_ctx, "paragraph", text)]
    return [_list_block(sec_ctx, items)]


def _text_block(sec_ctx: _SectionCtx, kind: str, text: str) -> dict:
    """A paragraph or code block, minted the one way — the shape ``_list_block`` and
    ``_algorithm_block`` beside it already have, so a field added to text blocks later cannot land
    on some of the six call sites and not the others."""
    return {"id": sec_ctx.next_id(kind), "type": kind, "text": text}


def _list_block(sec_ctx: _SectionCtx, items: Sequence[str]) -> dict:
    """``ordered`` stays False: the glyph that survived is a bullet, and a numbered list keeps its
    numerals inside the item text where they are still readable."""
    return {
        "id": sec_ctx.next_id("list"),
        "type": "list",
        "ordered": False,
        "items": [{"text": item} for item in items],
    }


def _trailing_bullet_items(blocks: Sequence[dict]) -> list[str] | None:
    """The ITEMS of the bulleted paragraph a following bullet turns into a list, or None.

    Returns the split rather than the block it came from: the caller wants those items, and
    running the split once as a predicate and again for its value is how the two drift apart.
    """
    last = blocks[-1] if blocks else None
    if last is None or last.get("type") != "paragraph":
        return None
    return _split_bullets(last.get("text") or "") or None


def _open_list(blocks: Sequence[dict]) -> dict | None:
    """The list a following bulleted paragraph continues — only when it is the LAST block.

    Anything in between (a formula, a figure, a plain paragraph) ends the list; a later bullet
    then starts its own rather than reaching back across unrelated content.
    """
    last = blocks[-1] if blocks else None
    return last if last is not None and last.get("type") == "list" else None


def _split_bullets(text: str) -> list[str]:
    """Bullet items of a paragraph that IS a list, else empty. Pure.

    Anchored at the paragraph start, because a bullet glyph mid-sentence is maths, not a list:
    papers write "\\([\\bullet]\\) denotes the truncated SVD" and "\\((\\bullet)^+\\) denotes the
    pseudo inverse", which an unanchored split tore into fragments beginning with a bracket. Only
    a paragraph that OPENS with the glyph is an itemised one.
    """
    if not _BULLET_START_RE.match(text):
        return []
    parts = [part.strip(f" \t:;,{_BULLET_CHARS}") for part in _ITEM_BULLET_RE.split(text)]
    return [part for part in parts if part]


def _is_paragraph_listing(text: str) -> bool:
    """Whether a ``<p>`` is a listing float GROBID failed to recognise as one.

    Anchored at the paragraph start and gated on length, because the cost of a false positive is
    real prose retyped as code. "Algorithm 2 achieves a better bound" opens the same way, so a
    heading alone never suffices for the pseudocode family — the body has to show numbered steps
    or control-flow vocabulary too. Verbatim listings carry neither, so that family leans on the
    stricter captioned heading ("Listing 3:") instead.
    """
    if len(text) < _LISTING_MIN_CHARS or not _LISTING_HEAD_RE.match(text):
        return False
    if _VERBATIM_HEAD_RE.match(text):
        return True
    # Structural vocabulary only: here the words ARE the evidence, so "until" in a sentence
    # describing an iterative method must not be enough to retype the paragraph as code.
    return _is_listing(text) or _STRUCTURAL_PSEUDOCODE_RE.search(text) is not None


def _formula_or_algorithm_blocks(
    formula: ET.Element,
    sec_ctx: _SectionCtx,
    doc_ctx: _DocCtx,
    section_blocks: Sequence[dict] = (),
    *,
    in_algorithm_section: bool = False,
) -> list[dict]:
    """A ``<formula>`` -> formula image, or the algorithm listing(s) GROBID hid inside it.

    GROBID has no notion of an algorithm float: it classifies one as ``<formula>`` and often
    splits a single listing across several of them, so an algorithm was reachable only as a
    picture — readable, but absent from search and from anything an agent can quote. Unlike
    equation glyphs the listing's text survives extraction well enough to index ("Algorithm 1
    Step 2 of IKPLS 1: if M ..."), so it becomes a CodeBlock that KEEPS the page crop: the text
    is the searchable representation, the crop is what renders faithfully (TD-12).
    """
    text = _text(formula)
    parts = _ALGORITHM_SPLIT_RE.split(text)
    pairs = list(zip(parts[1::2], parts[2::2], strict=True))
    if not any(_is_listing(body) for _, body in pairs):
        # A standalone <formula> is really a listing in two cases, both handled the same way — join
        # the previous listing if one is open, else start a fresh block. (a) Headless: GROBID
        # promoted "Algorithm 1" out of the listing (into the section title, or a neighbouring
        # float's caption), leaving numbered steps with no heading to split on — measured on 40
        # PDFs, that is how every pseudocode listing but one arrived. (b) In-algorithm-section: the
        # whole section is one listing, so its fragments join one block.
        if _is_headless_listing(text) or (in_algorithm_section and _is_listing(text)):
            host = _last_listing(section_blocks)
            if host is not None:
                _append_to_listing(host, text, formula, doc_ctx)
                return []
            return [_algorithm_block(formula, text, sec_ctx, doc_ctx)]
        # No "Algorithm N" heading followed by numbered steps — an equation that merely cites one
        # still belongs on the formula path, where it stays an image.
        return [_formula_block(formula, sec_ctx, doc_ctx)]
    blocks: list[dict] = []
    lead = parts[0].strip()
    if lead:
        # GROBID splits one listing across several elements, so text before the first heading is
        # the previous listing's tail. It rejoins that listing rather than starting a new block —
        # the intervening fragments GROBID filed as paragraphs stay where they are.
        host = _last_listing(section_blocks)
        if host is not None and _ALGORITHM_STEP_RE.search(lead):
            _append_to_listing(host, lead)
        else:
            blocks.append(_text_block(sec_ctx, "code", lead))
    # Walk the headings in document order. A "Algorithm N" whose body is a real listing becomes a
    # code block; one that is only a cross-reference GROBID swept into the float ("Algorithm 2 for
    # details") is still text the paper contains, so it is kept — joined to the listing it follows
    # when there is one, else as its own block — rather than dropped.
    for label, body in pairs:
        segment = f"{label} {body.strip()}".strip()
        if _is_listing(body):
            blocks.append(_algorithm_block(formula, segment, sec_ctx, doc_ctx))
        elif segment:
            host = _last_listing(blocks) or _last_listing(section_blocks)
            if host is not None:
                _append_to_listing(host, segment)
            else:
                blocks.append(_text_block(sec_ctx, "code", segment))
    return blocks


def _append_to_listing(
    host: dict, text: str, formula: ET.Element | None = None, doc_ctx: _DocCtx | None = None
) -> None:
    """Append a split-off fragment to the listing it belongs to, single-spaced.

    The fragment's COORDINATES join the host's crop when ``formula`` is given. GROBID files one
    algorithm float as several ``<formula>`` elements, and keeping only the first one's box
    pictured a multi-line listing as its opening line — measured on 2607.16138, a 297-character
    listing whose crop was 223x21pt. The text was already being rejoined here; the region follows.

    The caller passes the element ONLY when the whole of it goes into this listing. An element
    whose text is split across several blocks has no region attributable to one of them, and
    unioning all of it made the first listing's crop swallow the next listing entirely (the same
    fixture: 84pt -> 339pt, overlapping the block below it). Those fragments keep their text
    merged and their coordinates behind, which is what they already did.
    """
    host["text"] = f"{host['text']} {text}".strip()
    if formula is not None and doc_ctx is not None:
        _widen_crop(doc_ctx, (host.get("assetRef") or {}).get("assetId"), formula)


def _widen_crop(doc_ctx: _DocCtx, aid: str | None, el: ET.Element) -> None:
    """Grow the recorded crop spec ``aid`` to also cover ``el``, when they share page and column.

    Regions on another page are ignored, the rule ``_union_regions`` already follows: a listing
    continuing overleaf has no single rectangle and inventing one would crop the pages between.
    Regions that do not overlap the spec HORIZONTALLY are ignored for the same reason one column
    down — in a two-column paper the continuation sits beside the host, and unioning across the
    gutter would drag the whole other column into the image.
    """
    if not aid or doc_ctx.crops is None:
        return
    for index in range(len(doc_ctx.crops) - 1, -1, -1):
        spec = doc_ctx.crops[index]
        if spec.asset_id != aid:
            continue
        x0, y0, x1, y1 = spec.bbox
        regions = [
            r
            for r in _coord_regions(el)
            if r.page == spec.page and r.x1 > x0 and r.x0 < x1
        ]
        if regions:
            doc_ctx.crops[index] = replace(
                spec,
                bbox=(
                    min([x0, *(r.x0 for r in regions)]),
                    min([y0, *(r.y0 for r in regions)]),
                    max([x1, *(r.x1 for r in regions)]),
                    max([y1, *(r.y1 for r in regions)]),
                ),
            )
        return


def _last_listing(blocks: Sequence[dict]) -> dict | None:
    """The most recent algorithm listing in this section, or None. Pure."""
    for block in reversed(blocks):
        if block.get("type") == "code":
            return block
    return None


def _is_listing(body: str) -> bool:
    """Whether text after an "Algorithm N" heading is a numbered listing rather than a mention."""
    return len(_ALGORITHM_STEP_RE.findall(body)) >= _ALGORITHM_MIN_STEPS


def _is_headless_listing(text: str) -> bool:
    """Whether a formula is pseudocode that lost its "Algorithm N" heading to GROBID.

    Numbered steps alone are too weak a signal without the heading — a multi-line derivation
    numbers its equations the same way — so control-flow vocabulary has to be there too, and more
    steps are required than the headed case asks for. Both together do not occur in an equation.
    """
    return (
        len(_ALGORITHM_STEP_RE.findall(text)) >= _HEADLESS_MIN_STEPS
        and _PSEUDOCODE_RE.search(text) is not None
    )


def _algorithm_block(
    formula: ET.Element, listing: str, sec_ctx: _SectionCtx, doc_ctx: _DocCtx
) -> dict:
    """One algorithm listing: searchable text plus the page crop of the float it came from."""
    ordinal = doc_ctx.formula_ordinal
    doc_ctx.formula_ordinal += 1
    aid = asset_id(doc_ctx.paper_id, doc_ctx.version, AssetType.FORMULA, ordinal)
    _record_crop(doc_ctx, formula, aid, AssetType.FORMULA, ordinal, "")
    return {
        "id": sec_ctx.next_id("code"),
        "type": "code",
        "text": listing,
        "assetRef": {
            "assetId": aid,
            "type": "formula",
            "ordinal": ordinal,
            "sourceMode": "page-crop",
        },
    }


def _formula_block(formula: ET.Element, sec_ctx: _SectionCtx, doc_ctx: _DocCtx) -> dict:
    """Block-level equation -> image fallback (no reliable LaTeX on the PDF path; TD-12/3a).

    The image bytes are page-cropped by the asset pipeline; here we only mint the deterministic
    assetId. A ``<label>`` (e.g. "(3)") becomes the anchor label.
    """
    ordinal = doc_ctx.formula_ordinal
    doc_ctx.formula_ordinal += 1
    aid = asset_id(doc_ctx.paper_id, doc_ctx.version, AssetType.FORMULA, ordinal)
    block: dict = {
        "id": sec_ctx.next_id("formula"),
        "type": "formula",
        "display": True,
        "assetRef": {
            "assetId": aid,
            "type": "formula",
            "ordinal": ordinal,
            "sourceMode": "page-crop",
        },
    }
    label = _child_text(formula, "label")
    if label:
        block["anchorLabel"] = label
    _record_crop(doc_ctx, formula, aid, AssetType.FORMULA, ordinal, "")
    return block


def _figure_or_table_block(
    figure_el: ET.Element, sec_ctx: _SectionCtx, doc_ctx: _DocCtx
) -> dict | None:
    if _is_table_float(figure_el):
        return _table_block(figure_el, sec_ctx, doc_ctx)
    return _figure_block(figure_el, sec_ctx, doc_ctx)


def _table_block(figure_el: ET.Element, sec_ctx: _SectionCtx, doc_ctx: _DocCtx) -> dict | None:
    """GROBID gives real table structure (``<table><row><cell>``) -> DATA TableBlock (D8)."""
    table = _find_descendant(figure_el, "table")
    rows: list[dict] = []
    if table is not None:
        for row in table:
            if _local(row.tag) != "row":
                continue
            cells = [
                {"text": _text(cell)}
                for cell in row
                if _local(cell.tag) == "cell"
            ]
            if cells:
                rows.append({"cells": cells})
    # Empty rows are kept, not dropped. GROBID emits a bare <table/> whenever its cell
    # reconstruction fails on a table that is plainly there, and discarding the block took the
    # CAPTION with it — text the paper really contains, that the schema preserves as a
    # results-number source (BR-S3), and the last handle on that table once its cells are gone.
    # The crop below still gives a reader the picture of it. Only a table with neither rows nor a
    # caption carries nothing and is still discarded.
    label, caption = _figure_label_caption(figure_el)
    if not rows and not caption:
        return None
    if not rows and not label and caption_kind(caption) is not AssetType.TABLE:
        # Neither cells nor a "Table N" head: GROBID did not identify a table here, it swept a
        # stretch of prose into a table element. Across the audit sample every one of these was
        # running text — a references tail, an acknowledgements paragraph, a bulleted item, a
        # sentence that merely cites Table 1 — and the reader got a phantom empty table whose
        # "caption" was that paragraph (523 chars at the median) plus a page crop picturing it.
        # Caption LENGTH cannot separate the two: real captioned tables run to 1,142 chars here.
        # The head can, so keep the text and drop the table typing rather than the other way round.
        #
        # Unless the caption names the float itself. GROBID does sometimes fail to split the label
        # out of the caption — ``table_repair._CAPTION_LABEL_RE`` exists because labels ride inside
        # captions — and demoting one of those would take a real table's rows, crop and repair
        # eligibility with it. No such shape occurs in the audit sample (0 of 210 table figures),
        # so this costs nothing here; it is a guard against an irreversible loss, not a fix.
        #
        # ``caption_kind`` is that guard rather than a pattern of our own, because the label-vs-
        # mention rule is exactly what it already decides for the ar5iv path: it demands a
        # delimiter, end-of-string, or a capitalised follower after the number, so "Table 1
        # displays the selected hyperparameters …" (the 2503.09504 paragraph GROBID swept into a
        # <figure type="table">) stays a mention. A private copy of that rule accepted only the
        # delimiter, which silently excluded the colon-less IEEE styling — "TABLE IV RESULTS OF
        # THE ABLATION STUDY" — and so disarmed the guard on the very captions it exists for.
        return _text_block(sec_ctx, "paragraph", caption)
    ordinal = doc_ctx.table_ordinal
    doc_ctx.table_ordinal += 1
    block: dict = {"id": sec_ctx.next_id("table"), "type": "table", "rows": rows}
    if caption:
        block["caption"] = caption
    if label:
        block["anchorLabel"] = label
    # Rows are the PRIMARY, searchable representation (D8). When GROBID supplies table coordinates
    # we ALSO mint a page-crop image as a last-resort fallback (schema allows assetRef on a table),
    # so a later vision reader can re-read numbers GROBID's cell reconstruction may have garbled —
    # without that image ever displacing the structured data. No coordinates -> data only.
    aid = asset_id(doc_ctx.paper_id, doc_ctx.version, AssetType.TABLE, ordinal)
    if _record_crop(doc_ctx, figure_el, aid, AssetType.TABLE, ordinal, caption):
        asset_ref: dict = {
            "assetId": aid,
            "type": "table",
            "ordinal": ordinal,
            "sourceMode": "page-crop",
        }
        if caption:
            asset_ref["caption"] = caption
        block["assetRef"] = asset_ref
    return block


def _figure_block(figure_el: ET.Element, sec_ctx: _SectionCtx, doc_ctx: _DocCtx) -> dict:
    ordinal = doc_ctx.figure_ordinal
    doc_ctx.figure_ordinal += 1
    label, caption = _figure_label_caption(figure_el)
    aid = asset_id(doc_ctx.paper_id, doc_ctx.version, AssetType.FIGURE, ordinal)
    asset_ref: dict = {
        "assetId": aid,
        "type": "figure",
        "ordinal": ordinal,
        "sourceMode": "page-crop",
    }
    if caption:
        asset_ref["caption"] = caption
    block: dict = {"id": sec_ctx.next_id("figure"), "type": "figure", "assetRef": asset_ref}
    if caption:
        block["caption"] = caption
    if label:
        block["anchorLabel"] = label
    _record_crop(doc_ctx, figure_el, aid, AssetType.FIGURE, ordinal, caption)
    return block


# --------------------------------------------------------------------------- text / coords


def _text(el: ET.Element) -> str:
    """All descendant text of a TEI element, whitespace-collapsed (inline refs/formulas kept)."""
    return _WS_RE.sub(" ", "".join(el.itertext())).strip()


def _child_text(el: ET.Element, local_name: str) -> str:
    for child in el:
        if _local(child.tag) == local_name:
            return _text(child)
    return ""


def _figure_label_caption(figure_el: ET.Element) -> tuple[str, str]:
    """Return (anchorLabel, caption): label from head/label, caption from figDesc."""
    label = _child_text(figure_el, "head") or _child_text(figure_el, "label")
    caption = _child_text(figure_el, "figDesc")
    return label, caption


def _record_crop(
    doc_ctx: _DocCtx,
    el: ET.Element,
    aid: str,
    asset_type: AssetType,
    ordinal: int,
    caption: str,
) -> bool:
    """Report whether ``el`` can be page-cropped, appending its spec when a collector is active.

    Returns True when the element carries GROBID coordinates (a crop image is therefore possible),
    so a caller can decide whether to attach an ``assetRef`` independently of whether the crop
    collector is currently running — the doc-model build runs with no collector yet still needs
    the coords-present answer. The spec itself is appended only when ``doc_ctx.crops`` is active
    (the asset-pipeline walk in ``tei_crop_specs``)."""
    parsed = _crop_region(el, asset_type)
    if parsed is None:
        return False  # no coordinates -> no crop possible (the block still renders its caption)
    if doc_ctx.crops is not None:
        page, bbox, from_content = parsed
        doc_ctx.crops.append(
            AssetCropSpec(
                asset_id=aid,
                type=asset_type,
                ordinal=ordinal,
                page=page,
                bbox=bbox,
                caption=caption,
                content_coords=from_content,
            )
        )
    return True


class _Region(NamedTuple):
    """One rectangle of a GROBID ``coords`` attribute: 1-based page, top-left-origin PDF points."""

    page: int
    x0: float
    y0: float
    x1: float
    y1: float


def _coord_regions(el: ET.Element) -> list[_Region]:
    """Every rectangle in ``coords`` ("page,x,y,w,h;..."), malformed entries skipped. Pure."""
    out: list[_Region] = []
    for region in (el.get("coords") or "").split(";"):
        parts = region.split(",")
        if len(parts) < 5:
            continue
        try:
            page = int(float(parts[0]))
            x, y, w, h = (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]))
        except ValueError:
            continue
        out.append(_Region(page, x, y, x + w, y + h))
    return out


def _union_regions(
    regions: Sequence[_Region],
) -> tuple[int, tuple[float, float, float, float]] | None:
    """Bounding box of the regions lying on the FIRST one's page, or None if there is no area.

    Regions on later pages are dropped rather than merged: a float that spans a page break has no
    single rectangle, and picking the first page keeps the answer deterministic."""
    if not regions:
        return None
    page = regions[0].page
    same = [r for r in regions if r.page == page]
    bbox = (
        min(r.x0 for r in same),
        min(r.y0 for r in same),
        max(r.x1 for r in same),
        max(r.y1 for r in same),
    )
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return None
    return page, bbox


def _parse_coords(el: ET.Element) -> tuple[int, tuple[float, float, float, float]] | None:
    """GROBID ``coords`` -> (page, bbox) bounding box over everything the element covers."""
    return _union_regions(_coord_regions(el))


# Where a float's CONTENT is reported, per float kind. GROBID emits these as children of the
# ``<figure>`` and they carry their own coordinates; nothing else in the float does.
_CONTENT_TAG = {AssetType.FIGURE: "graphic", AssetType.TABLE: "table"}


def _crop_region(
    el: ET.Element, asset_type: AssetType
) -> tuple[int, tuple[float, float, float, float], bool] | None:
    """(page, bbox, from_content) for a float's page-crop: its content, caption lines trimmed off.

    A float's ``coords`` is the list of its caption's TEXT LINES plus its content region, and
    unioning all of it put the caption inside every crop — 10-69% of the rendered image on the TEI
    fixtures, duplicating text the viewer already renders as a ``<figcaption>`` beside it. The
    content region is exactly what ``<graphic>``/``<table>`` reports, so when one is present:

    * ``y`` spans only the regions that overlap the content — the caption lines above and/or below
      it are dropped;
    * ``x`` stays the float's own span, because a subfigure's ``<graphic>`` can be narrower than
      the column the float occupies and cropping to it alone cuts the neighbouring subfigure;
    * a float whose regions ALL overlap the content has no line identifiable as caption (GROBID
      gave it one region covering caption and body together), so the content box is taken as-is.

    The content element also decides the PAGE, which is how a table whose caption strip GROBID
    filed on the previous page stops being cropped from the wrong page entirely.

    ``from_content`` is False when GROBID reported no content region: the bbox is then the float's
    own coords, which may be a picture's surroundings or nothing but the caption — a difference
    only the PDF itself can settle, so the asset pipeline makes that call.
    """
    tag = _CONTENT_TAG.get(asset_type)
    content = (
        _union_regions(
            [
                region
                for child in el.iter()
                if _local(child.tag) == tag
                for region in _coord_regions(child)
            ]
        )
        if tag is not None
        else None
    )
    if content is None:
        parsed = _parse_coords(el)
        return None if parsed is None else (parsed[0], parsed[1], False)
    page, (cx0, cy0, cx1, cy1) = content
    regions = [r for r in _coord_regions(el) if r.page == page]
    body = [r for r in regions if r.y1 > cy0 and r.y0 < cy1]
    if len(body) == len(regions):
        return page, (cx0, cy0, cx1, cy1), True
    return (
        page,
        (
            min([r.x0 for r in regions] + [cx0]),
            min([r.y0 for r in body] + [cy0]),
            max([r.x1 for r in regions] + [cx1]),
            max([r.y1 for r in body] + [cy1]),
        ),
        True,
    )


def tei_crop_specs(tei: str, *, paper_id: str, version: int) -> list[AssetCropSpec]:
    """Figure/formula page-crop specs for a TEI document (PDF/GROBID asset path).

    Runs the SAME walk as ``parse_tei_to_docmodel`` (the doc-model is built and discarded), so
    every spec's ``asset_id`` matches the block that references it — there is no second, possibly
    divergent traversal. Returns ``[]`` on malformed TEI (assets are best-effort, never block).
    """
    crops: list[AssetCropSpec] = []
    try:
        parse_tei_to_docmodel(
            tei,
            paper_id=paper_id,
            version=version,
            title="",
            abstract=None,
            source_tier=SourceTier.pdf,
            parser_version="",
            schema_version="",
            generated_at=datetime.fromtimestamp(0, tz=UTC),
            crops=crops,
        )
    except ET.ParseError:
        return []
    return crops


class _PageLayout(NamedTuple):
    """Page widths by page number, and whether the paper is set in two columns.

    Only used to order elements on a page. ``two_column`` is read off where the section heads
    START: a single-column paper puts every head at the left margin, a two-column one puts roughly
    half of them past the middle of the page. Measured across 50 PDF-path papers, 27 are
    two-column — this is the majority layout on the path, not an edge case.

    No ``<facsimile>`` means no page widths, and then the layout is treated as single-column: that
    is exactly today's ordering, so a TEI without page geometry degrades to what it already did.
    """

    widths: dict[int, float]
    two_column: bool


_SPANNING_WIDTH_RATIO = 0.6


def _page_layout(root: ET.Element, divs: list[ET.Element]) -> _PageLayout:
    """Page geometry for ordering, from GROBID's ``<facsimile>`` surfaces and the head positions."""
    widths: dict[int, float] = {}
    for surface in root.iter():
        if _local(surface.tag) != "surface":
            continue
        try:
            widths[int(surface.get("n", ""))] = float(surface.get("lrx", ""))
        except ValueError:
            continue
    if not widths:
        return _PageLayout({}, two_column=False)
    starts = [
        (_coord_parts(head), widths.get(int(_coord_parts(head)[0]), 0.0))
        for div in divs
        for head in div
        if _local(head.tag) == "head" and _coord_parts(head) is not None
    ]
    two_column = any(parts[1] >= width / 2 for parts, width in starts if width)
    return _PageLayout(widths, two_column)


def _coord_parts(el: ET.Element) -> tuple[float, float, float, float] | None:
    """``(page, x, y, width)`` from GROBID's ``coords`` ("page,x,y,w,h;..."), or None."""
    coords = el.get("coords")
    if not coords:
        return None
    first = coords.split(";", 1)[0].split(",")
    try:
        return (float(first[0]), float(first[1]), float(first[2]), float(first[3]))
    except (ValueError, IndexError):
        return None


def _coord_sort_key(
    figure_el: ET.Element, layout: _PageLayout | None = None
) -> tuple[float, float, float]:
    """Reading-order sort key from the GROBID ``coords`` attribute -> ``(page, column, y)``.

    The column is what makes this reading order rather than merely page order. Ordering a
    two-column page by ``y`` alone puts a float at the top of the RIGHT column ahead of a heading
    at the bottom of the LEFT one, so the coordinate fallback hands the float to the section
    before the one it is printed in. Verified on arXiv:2502.11386 page 9: a left-column float at
    y=347 sits under "B. QoE Modeling" (left column, y=161), but "C. Algorithm Overview" opens the
    right column at y=186 and ``y``-only ordering gave the float to C.

    A float wider than 60% of the page spans both columns and takes column 0, which reads
    correctly for the page-top placement authors use for wide floats; one parked at the page FOOT
    is still ordered ahead of the right column, an imprecision this does not attempt to resolve.

    Without a layout — or on a single-column paper — every element takes column 0, which orders
    exactly as the old ``(page, y)`` key did. Missing/unparseable coords sort last but stably
    (document order is the tie-break upstream)."""
    parts = _coord_parts(figure_el)
    if parts is None:
        return (float("inf"), float("inf"), float("inf"))
    page, x, y, width = parts
    if layout is None or not layout.two_column:
        return (page, 0.0, y)
    page_width = layout.widths.get(int(page), 0.0)
    if not page_width or width > _SPANNING_WIDTH_RATIO * page_width:
        return (page, 0.0, y)
    return (page, float(x + width / 2 >= page_width / 2), y)


def _find_descendant(root: ET.Element, local_name: str) -> ET.Element | None:
    for el in root.iter():
        if _local(el.tag) == local_name:
            return el
    return None


def tei_to_text(tei: str) -> str:
    """Flat reading-order text of a TEI document — the projection used when GROBID structure is
    available but a doc-model is not being built (the corpus source's text candidate).

    Public sibling of ``parse_tei_to_docmodel`` so callers outside the GROBID adapter do not have
    to reach into it for a private helper. Invalid or empty TEI is a permanent parse failure:
    retrying the same bytes cannot produce text.
    """
    try:
        root = safe_fromstring(tei)
    except ET.ParseError as exc:
        raise PermanentIngestionError(
            "GROBID returned invalid TEI",
            reason=FailureReason.PARSE_FAILURE,
            stage="grobid",
        ) from exc
    text = " ".join(part.strip() for part in root.itertext() if part.strip())
    if not text:
        raise PermanentIngestionError(
            "GROBID returned empty TEI",
            reason=FailureReason.PARSE_FAILURE,
            stage="grobid",
        )
    return text
