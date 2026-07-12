"""Deterministic arXiv/ar5iv (LaTeXML) HTML -> doc-model parser (BR-30, TD-16, D1).

arXiv native HTML and ar5iv are both LaTeXML output, so a single parser keyed on the
``ltx_*`` class vocabulary covers both source tiers. The parse is **deterministic** — same
source HTML yields the same doc-model, identical block ids included (P7) — and contains **no
LLM extraction** (D1, to keep table numbers and formulas faithful).

Output is built as plain dicts and validated through the generated pydantic ``DocModel``
binding, so a parser that drifts from ``shared/dtos/docmodel.schema.json`` fails loudly.

Mapping (LaTeXML -> doc-model):
  - ``section.ltx_section`` / ``ltx_subsection`` / ``ltx_appendix`` / ...  -> nested Section tree
  - ``div.ltx_para`` > ``p.ltx_p``                       -> ParagraphBlock (inline math -> \\( \\))
  - ``table.ltx_equation`` / ``div.ltx_equationgroup``   -> FormulaBlock (MathML -> LaTeX)
  - ``figure.ltx_table`` > ``table.ltx_tabular``         -> TableBlock (rows/cols data, D8)
  - ``figure.ltx_figure``                                -> FigureBlock (webp assetId ref, FR-17)
  - ``ul.ltx_itemize`` / ``ol.ltx_enumerate``            -> ListBlock
  - ``div.ltx_listing`` / ``pre.ltx_verbatim``           -> CodeBlock

Figures link to the existing FR-17 webp assets by the deterministic ``asset_id`` keyed on
the document-order ordinal per type — no pixels are re-extracted (re-extraction = 0).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from bs4 import BeautifulSoup, NavigableString, Tag
from docsuri_shared.dtos import DocModel, SourceTier

from docsuri_ingestion.docmodel.mathml import mathml_to_latex
from docsuri_ingestion.domain.assets import FigureSpec, asset_id
from docsuri_ingestion.domain.enums import AssetType

_WS_RE = re.compile(r"\s+")

# A colour box LaTeXML could not expand (e.g. arXiv:2410.14706's ``\cybertron`` →
# ``\Colorbox{colour}{\lstinline{…}}``). It surfaces as an ``ltx_ERROR`` node holding the bare
# command token (possibly with a trailing ``[opt]``), and its leading colour argument(s) leak as
# loose text right after. Group 1 == "f" marks two-argument ``\fcolorbox`` (frame + bg); plain
# ``\Colorbox``/``\colorbox`` leak one. ``\b`` (not ``\Z``) so ``\Colorbox[rgb]`` still matches.
_BOXCMD_RE = re.compile(r"\\(f?)[Cc]olorbox\b")
# A leaked colour-name argument is a single bare token ("mygrayInline", "red", "gray!50") — never a
# sentence. Requiring that shape means a box command with no following colour never eats body text.
_COLOUR_ARG_RE = re.compile(r"^[A-Za-z][\w!.]*$")

# LaTeXML section-level wrappers, all rendered as <section>. ``ltx_appendix`` is included
# (FD Q2=B: appendices are preserved) — without it LaTeXML appendix subsections lose their
# nearest section ancestor and flatten up into the top level, dropping the "Appendix A"
# container title and the section hierarchy.
_SECTION_CLASSES = {
    "ltx_section",
    "ltx_subsection",
    "ltx_subsubsection",
    "ltx_paragraph",
    "ltx_appendix",
}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# Block-id type abbreviations (1-based ordinals per section): s3.p2, s3.tbl1, s3.eq2, ...
_ABBREV = {
    "paragraph": "p",
    "table": "tbl",
    "formula": "eq",
    "figure": "fig",
    "list": "list",
    "code": "code",
}


@dataclass
class _DocCtx:
    """Mutable per-document counters: figure/table asset ordinals are doc-global (per type),
    matching the FR-17 extractor's per-type ordinal so doc-model figures link to webp assets."""

    paper_id: str
    version: int
    figure_ordinal: int = 0
    table_ordinal: int = 0
    formula_ordinal: int = 0
    # Optional collector for coordinate crop specs (TEI/PDF path). When a list is supplied, the
    # TEI figure/formula builders append the page-crop request they mint alongside the block, so
    # the rendered image's asset_id matches the block's assetRef exactly (ordinal alignment).
    crops: list | None = None
    # Optional collector for figure image-resolution hints (HTML path). When a list is supplied,
    # each FigureBlock appends a FigureSpec(<img src>, anchorLabel) in document order (index ==
    # ordinal) so the asset extractor can match each figure to its e-print graphic (by src) or a
    # PDF page-crop (by label number) and keep the assetId aligned to the block.
    figure_specs: list | None = None


@dataclass
class _SectionCtx:
    """Per-section block-id counters (reset for each section)."""

    section_id: str
    counters: dict[str, int] = field(default_factory=dict)

    def next_id(self, block_type: str) -> str:
        n = self.counters.get(block_type, 0) + 1
        self.counters[block_type] = n
        return f"{self.section_id}.{_ABBREV[block_type]}{n}"


def parse_html_to_docmodel(
    html: str,
    *,
    paper_id: str,
    version: int,
    title: str,
    abstract: str | None,
    source_tier: SourceTier,
    parser_version: str,
    schema_version: str,
    generated_at: datetime,
    macros: dict[str, str] | None = None,
    figure_specs: list[FigureSpec] | None = None,
) -> DocModel:
    """Parse LaTeXML HTML into a validated ``DocModel`` (pure given its inputs).

    ``macros`` is an optional KaTeX macro map from the e-print preamble (see
    ``docmodel.macros``); it is carried on ``meta.macros`` so the renderer can resolve
    author-defined commands that LaTeXML left verbatim in the formula LaTeX.

    ``figure_specs`` is an optional out-param: when supplied it is filled with a FigureSpec per
    FigureBlock in document order (index == figure ordinal), so the asset extractor can resolve
    each figure's image (e-print graphic by src, else PDF page-crop by label) aligned to its block.
    """
    soup = BeautifulSoup(html or "", "lxml")
    root = soup.find(class_="ltx_document") or soup.body or soup
    doc_ctx = _DocCtx(paper_id=paper_id, version=version, figure_specs=figure_specs)

    top_sections = _top_level_sections(root)
    if top_sections:
        top_sections = _drop_duplicate_abstract_elements(top_sections, abstract)
        sections = [
            _parse_section(el, f"s{i}", doc_ctx) for i, el in enumerate(top_sections, start=1)
        ]
    else:
        # No LaTeXML sectioning (e.g. a short note): fold all body content into one
        # span-only section so the doc-model is still well-formed (BR-S3 fallback).
        sections = [_span_only_section(root, doc_ctx)]
    sections = _with_abstract_section(sections, abstract)

    data = {
        "meta": {
            "paperId": paper_id,
            "version": version,
            "title": title,
            **({"abstract": abstract} if abstract else {}),
            **({"macros": macros} if macros else {}),
            "provenance": {
                "sourceTier": source_tier.value,
                "parserVersion": parser_version,
                "schemaVersion": schema_version,
                "generatedAt": generated_at,
            },
        },
        "fullText": _project_full_text(sections),
        "sections": sections,
    }
    return DocModel.model_validate(data)


def parse_text_to_docmodel(
    text: str,
    *,
    paper_id: str,
    version: int,
    title: str,
    abstract: str | None,
    source_tier: SourceTier,
    parser_version: str,
    schema_version: str,
    generated_at: datetime,
) -> DocModel:
    """Build a minimal validated DocModel from normalized full text.

    This is the last-rung PDF/GROBID fallback: it preserves the DocModel contract and stable
    block refs even when no rich HTML source exists. It intentionally produces a single
    paragraph block rather than inventing structure the source did not provide.
    """
    body = _WS_RE.sub(" ", text or "").strip()
    sections = _with_abstract_section([], abstract)
    section = {
        "id": "s1",
        "title": "",
        "blocks": ([{"id": "s1.p1", "type": "paragraph", "text": body}] if body else []),
    }
    sections.append(section)
    data = {
        "meta": {
            "paperId": paper_id,
            "version": version,
            "title": title,
            **({"abstract": abstract} if abstract else {}),
            "provenance": {
                "sourceTier": source_tier.value,
                "parserVersion": parser_version,
                "schemaVersion": schema_version,
                "generatedAt": generated_at,
            },
        },
        "fullText": _project_full_text(sections),
        "sections": sections,
    }
    return DocModel.model_validate(data)


# --------------------------------------------------------------------------- sections


def _is_section(node: object) -> bool:
    return (
        isinstance(node, Tag)
        and node.name == "section"
        and bool(_SECTION_CLASSES & set(node.get("class", [])))
    )


def _nearest_section_ancestor(node: Tag) -> Tag | None:
    parent = node.parent
    while isinstance(parent, Tag):
        if _is_section(parent):
            return parent
        parent = parent.parent
    return None


def _top_level_sections(root: Tag) -> list[Tag]:
    """Sections under ``root`` with no section ancestor (LaTeXML may wrap them in divs)."""
    return [s for s in root.find_all(_is_section) if _nearest_section_ancestor(s) is None]


def _child_sections(section_el: Tag) -> list[Tag]:
    """Direct subsections of ``section_el`` (nearest section ancestor == section_el)."""
    return [
        s
        for s in section_el.find_all(_is_section)
        if _nearest_section_ancestor(s) is section_el
    ]


def _parse_section(section_el: Tag, section_id: str, doc_ctx: _DocCtx) -> dict:
    sec_ctx = _SectionCtx(section_id=section_id)
    blocks = _collect_blocks(section_el, sec_ctx, doc_ctx, skip_sections=True)
    subsections = [
        _parse_section(child, f"{section_id}.{i}", doc_ctx)
        for i, child in enumerate(_child_sections(section_el), start=1)
    ]
    section: dict = {"id": section_id, "title": _section_title(section_el), "blocks": blocks}
    if subsections:
        section["sections"] = subsections
    return section


def _span_only_section(root: Tag, doc_ctx: _DocCtx) -> dict:
    sec_ctx = _SectionCtx(section_id="s1")
    blocks = _collect_blocks(root, sec_ctx, doc_ctx, skip_sections=False)
    return {"id": "s1", "title": "", "blocks": blocks}


def _with_abstract_section(sections: list[dict], abstract: str | None) -> list[dict]:
    text = _WS_RE.sub(" ", abstract or "").strip()
    if not text:
        return sections
    return [
        {
            "id": "s0",
            "title": "Abstract",
            "blocks": [{"id": "s0.p1", "type": "paragraph", "text": text}],
        },
        *sections,
    ]


def _drop_duplicate_abstract_elements(sections: list[Tag], abstract: str | None) -> list[Tag]:
    text = _WS_RE.sub(" ", abstract or "").strip().lower()
    if not text or not sections:
        return sections
    first = sections[0]
    title = _WS_RE.sub(" ", _section_title(first)).strip().lower()
    if title != "abstract":
        return sections
    body = _WS_RE.sub(
        " ",
        " ".join(_inline_text(p) for p in first.find_all("p", class_="ltx_p")),
    ).strip().lower()
    return sections[1:] if body == text else sections


def _section_title(section_el: Tag) -> str:
    for child in section_el.children:
        if isinstance(child, Tag) and child.name in _HEADING_TAGS:
            return _inline_text(child)
    return ""


# --------------------------------------------------------------------------- blocks


def _collect_blocks(
    container: Tag, sec_ctx: _SectionCtx, doc_ctx: _DocCtx, *, skip_sections: bool
) -> list[dict]:
    """Walk a section's direct content in document order, dispatching to block builders.

    Recurses through layout wrappers (e.g. ``div.ltx_para``) but stops at nested sections so
    each block is attributed to the section that owns it.
    """
    blocks: list[dict] = []
    for child in container.children:
        if not isinstance(child, Tag):
            continue
        if _is_section(child):
            continue  # subsections handled by _parse_section
        if child.name in _HEADING_TAGS:
            continue
        blocks.extend(_blocks_from(child, sec_ctx, doc_ctx, skip_sections=skip_sections))
    return blocks


def _classes(node: Tag) -> set[str]:
    return set(node.get("class", []))


def _blocks_from(
    el: Tag, sec_ctx: _SectionCtx, doc_ctx: _DocCtx, *, skip_sections: bool
) -> list[dict]:
    classes = _classes(el)
    name = el.name

    if name == "figure" and "ltx_table" in classes:
        block = _table_block(el, sec_ctx)
        return [block] if block else []
    if name == "figure" and "ltx_figure" in classes:
        block = _figure_block(el, sec_ctx, doc_ctx)
        return [block] if block else []
    if "ltx_equation" in classes or "ltx_eqn_table" in classes or "ltx_equationgroup" in classes:
        return _formula_blocks(el, sec_ctx)
    if name in {"ul", "ol"} and ("ltx_itemize" in classes or "ltx_enumerate" in classes):
        block = _list_block(el, sec_ctx)
        return [block] if block else []
    if "ltx_listing" in classes or "ltx_verbatim" in classes:
        block = _code_block(el, sec_ctx)
        return [block] if block else []
    if name == "p" and "ltx_p" in classes:
        block = _paragraph_block(el, sec_ctx)
        return [block] if block else []
    if skip_sections and _is_section(el):
        return []
    # Layout wrapper (ltx_para, divs, ...): recurse to preserve in-order content.
    out: list[dict] = []
    for child in el.children:
        if isinstance(child, Tag):
            out.extend(_blocks_from(child, sec_ctx, doc_ctx, skip_sections=skip_sections))
    return out


def _paragraph_block(p: Tag, sec_ctx: _SectionCtx) -> dict | None:
    text = _inline_text(p)
    if not text:
        return None
    return {"id": sec_ctx.next_id("paragraph"), "type": "paragraph", "text": text}


def _table_block(figure_el: Tag, sec_ctx: _SectionCtx) -> dict | None:
    table = figure_el.find("table", class_="ltx_tabular")
    if table is None:
        return None
    rows: list[dict] = []
    for tr in table.find_all("tr"):
        # A stacked/rotated column header can itself be a NESTED <table> (LaTeXML renders a
        # two-line "Name / ↑" header as a mini table inside the header cell). find_all("tr")
        # descends into those and would pull their rows up as phantom single-cell main rows
        # (the observed "column headers spill into the first column" breakage). Keep only rows
        # whose nearest ancestor table is THIS one — the nested content already lives in the
        # parent header cell's flattened text.
        if tr.find_parent("table") is not table:
            continue
        cells = []
        in_thead = tr.find_parent("thead") is not None
        for cell in tr.find_all(["td", "th"], recursive=False):
            cell_dict: dict = {"text": _inline_text(cell)}
            if cell.name == "th" or "ltx_th" in _classes(cell) or in_thead:
                cell_dict["isHeader"] = True
            colspan = _int_attr(cell, "colspan")
            rowspan = _int_attr(cell, "rowspan")
            if colspan > 1:
                cell_dict["colspan"] = colspan
            if rowspan > 1:
                cell_dict["rowspan"] = rowspan
            cells.append(cell_dict)
        rows.append({"cells": cells})
    if not rows:
        return None
    label, caption = _caption(figure_el)
    block: dict = {"id": sec_ctx.next_id("table"), "type": "table", "rows": rows}
    if caption:
        block["caption"] = caption
    if label:
        block["anchorLabel"] = label
    return block


def _figure_block(figure_el: Tag, sec_ctx: _SectionCtx, doc_ctx: _DocCtx) -> dict | None:
    imgs = figure_el.find_all("img")
    if not imgs:
        return None  # no graphic to reference
    ordinal = doc_ctx.figure_ordinal
    doc_ctx.figure_ordinal += 1
    label, caption = _caption(figure_el)
    # Record this figure's resolution hints at its ordinal so the asset extractor can align its
    # image to this block (the append order matches the ordinal increment, keeping
    # figure_specs[ordinal] == this block).
    if doc_ctx.figure_specs is not None:
        # A multi-panel figure (LaTeXML nests one <img> per sub-panel in the float) must NOT be
        # sourced from the first panel's e-print graphic — the stem-match would image only that
        # one panel and drop the rest (the observed "figure shows a single sub-panel" breakage).
        # Blank the src so the asset extractor falls back to a whole-figure PDF page-crop (matched
        # by caption number), which captures every panel as laid out. A single-image figure keeps
        # its src for the original-quality e-print graphic.
        first = imgs[0]
        src = first.get("src") if len(imgs) == 1 and isinstance(first, Tag) else None
        doc_ctx.figure_specs.append(
            FigureSpec(src=src if isinstance(src, str) else "", label=label)
        )
    asset_ref: dict = {
        "assetId": asset_id(doc_ctx.paper_id, doc_ctx.version, AssetType.FIGURE, ordinal),
        "type": "figure",
        "ordinal": ordinal,
    }
    if caption:
        asset_ref["caption"] = caption
    block: dict = {
        "id": sec_ctx.next_id("figure"),
        "type": "figure",
        "assetRef": asset_ref,
    }
    if caption:
        block["caption"] = caption
    if label:
        block["anchorLabel"] = label
    return block


def _formula_blocks(el: Tag, sec_ctx: _SectionCtx) -> list[dict]:
    rows = el.find_all("tr")
    targets = rows if rows else [el]
    blocks: list[dict] = []
    for target in targets:
        # An aligned/eqnarray line splits its LHS/RHS across sibling <td><math> cells, so
        # concatenate every math in the row (in order) into one formula (e.g. "x=y+z").
        maths = target.find_all("math")
        if not maths:
            continue
        latex = "".join(mathml_to_latex(m) for m in maths).strip()
        if not latex:
            continue
        block: dict = {
            "id": sec_ctx.next_id("formula"),
            "type": "formula",
            "latex": latex,
            "display": True,
        }
        label = _equation_label(target)
        if label:
            block["anchorLabel"] = label
        if any(not m.get("alttext") for m in maths):
            block["mathmlSource"] = "".join(str(m) for m in maths)
        blocks.append(block)
    return blocks


def _list_block(el: Tag, sec_ctx: _SectionCtx) -> dict | None:
    items = []
    for li in el.find_all("li", recursive=False):
        text = _inline_text(li)
        if text:
            items.append({"text": text})
    if not items:
        return None
    ordered = el.name == "ol" or "ltx_enumerate" in _classes(el)
    return {
        "id": sec_ctx.next_id("list"),
        "type": "list",
        "ordered": ordered,
        "items": items,
    }


def _code_block(el: Tag, sec_ctx: _SectionCtx) -> dict | None:
    # A <math> inside a listing/algorithm line carries its presentation MathML (rendered as unicode
    # glyphs) PLUS two annotations LaTeXML attaches: <annotation encoding="application/x-tex"> (the
    # LaTeX source) and <annotation-xml encoding="MathML-Content"> (content MathML). A raw
    # get_text() emits ALL of them, so each symbol triples — e.g. ``η_m`` renders as
    # "ηm" + "subscript" + "𝜂𝑚" (presentation glyphs, the content <csymbol>subscript</csymbol>
    # name, and the italic-unicode content <ci>s). Code blocks are shown verbatim (no KaTeX), so
    # drop BOTH annotation kinds and keep only the readable unicode presentation. ``annotation-xml``
    # is a distinct tag name from ``annotation``, so it must be listed explicitly.
    for annotation in el.find_all(["annotation", "annotation-xml"]):
        annotation.decompose()
    lines = el.find_all(class_="ltx_listingline")
    if lines:
        text = "\n".join(_listing_line_text(line) for line in lines)
    else:
        text = el.get_text("\n")
    text = text.strip("\n")
    if not text.strip():
        return None
    return {"id": sec_ctx.next_id("code"), "type": "code", "text": text}


def _listing_line_text(line: Tag) -> str:
    """One listing/algorithm line as ``"<num>: <body>"`` (or just the body for plain code).

    Algorithm floats carry a per-line number in a ``ltx_tag_listingline`` span that LaTeXML
    renders with NO separator, so a raw ``get_text`` glues it to the step ("1:Flow…"). Pull the
    number out and re-join it with a space. LaTeXML also keeps the author's soft line-wrap inside
    a single numbered step (the Require line splits across source lines); fold those internal
    newlines back so one step stays on one line. Leading indentation (em-spaces marking nesting,
    or a plain-code indent) is preserved — only newlines are collapsed."""
    tag = line.find(class_="ltx_tag_listingline")
    number = ""
    if tag is not None:
        number = tag.get_text().strip()
        tag.extract()  # so it isn't duplicated in the body text below
    body = line.get_text().strip("\n").replace("\r", " ").replace("\n", " ")
    return f"{number} {body}" if number else body


# --------------------------------------------------------------------------- text


def _inline_text(el: Tag) -> str:
    """Visible text of an element with inline math rendered as ``\\( latex \\)``.

    Skips LaTeXML marker tags (``ltx_tag`` — section numbers, list bullets, eq numbers) and
    footnotes/notes (``ltx_note`` — out-of-flow annotations) so neither leaks into body text.
    U1 Corpus freezes footnotes out of DocModel v1; Citation Graph owns reference structure.
    Also drops ``ltx_ERROR`` nodes (undefined commands LaTeXML could not expand) so raw command
    tokens do not leak; for a ``\\Colorbox``/``\\fcolorbox`` box the leaked colour argument(s) that
    follow as loose text are dropped too (see ``_BOXCMD_RE``/``_COLOUR_ARG_RE``).
    """
    parts: list[str] = []
    drop_boxargs = 0  # leaked colour tokens still to drop after a \Colorbox/\fcolorbox error node
    for node in el.children:
        if isinstance(node, NavigableString):
            text = str(node)
            if drop_boxargs > 0:
                if not text.strip():
                    continue  # whitespace between the error node and the colour arg — stay armed
                if _COLOUR_ARG_RE.match(text.strip()):
                    drop_boxargs -= 1
                    continue  # drop this leaked colour name
                drop_boxargs = 0  # not a colour token → real body text; keep it and disarm
            parts.append(text)
        elif isinstance(node, Tag):
            drop_boxargs = 0
            if node.name == "math":
                latex = mathml_to_latex(node)
                if latex:
                    parts.append(f"\\({latex}\\)")
            elif "ltx_tag" in _classes(node) or "ltx_note" in _classes(node):
                continue
            elif "ltx_ERROR" in _classes(node):
                box = _BOXCMD_RE.match(node.get_text().strip())
                if box:
                    drop_boxargs = 2 if box.group(1) == "f" else 1
                continue
            else:
                parts.append(_inline_text(node))
    return _WS_RE.sub(" ", "".join(parts)).strip()


def _is_figure_container(node: object) -> bool:
    return (
        isinstance(node, Tag)
        and node.name == "figure"
        and bool({"ltx_figure", "ltx_table"} & _classes(node))
    )


def _nearest_figure_ancestor(node: Tag) -> Tag | None:
    parent = node.parent
    while isinstance(parent, Tag):
        if _is_figure_container(parent):
            return parent
        parent = parent.parent
    return None


def _own_figcaption(figure_el: Tag) -> Tag | None:
    """The figure's OWN ``ltx_caption`` — not one belonging to a nested sub-figure panel.

    LaTeXML lays a subfigure group's panel captions ("(a)", "(b)", …) out BEFORE the figure's
    own "Figure N:" caption, so a plain descendant ``find`` grabs the first panel's "(a)" — which
    mislabels the figure and strips its number (breaking caption-number matching). Pick the
    figcaption whose nearest figure container is ``figure_el`` itself.
    """
    for figcaption in figure_el.find_all("figcaption", class_="ltx_caption"):
        if _nearest_figure_ancestor(figcaption) is figure_el:
            return figcaption
    return None


def _caption(figure_el: Tag) -> tuple[str, str]:
    """Return ``(anchorLabel, caption)`` from the figure's own ``ltx_caption`` figcaption.

    The leading ``ltx_tag`` span ("Figure 1: ") yields the anchor label; the remaining
    text is the caption. Nested sub-figure panel captions are ignored (see ``_own_figcaption``).
    """
    figcaption = _own_figcaption(figure_el)
    if figcaption is None:
        return "", ""
    tag = figcaption.find("span", class_="ltx_tag")
    label = ""
    if tag is not None:
        label = _WS_RE.sub(" ", tag.get_text()).strip().rstrip(":").strip()
        tag.extract()
    caption = _inline_text(figcaption)
    return label, caption


def _equation_label(target: Tag) -> str:
    tag = target.find("span", class_="ltx_tag")
    if tag is None:
        return ""
    return _WS_RE.sub(" ", tag.get_text()).strip()


def _int_attr(el: Tag, name: str) -> int:
    raw = el.get(name)
    try:
        return int(raw) if raw is not None else 1
    except (TypeError, ValueError):
        return 1


def _project_full_text(sections: list[dict]) -> str:
    """Reading-order text projection for DocModel.fullText.

    This is intentionally derived from the already-built block tree, so the contract stays in
    one place: tables contribute rows/cells, figures contribute captions, formulas contribute
    LaTeX, and AssetRef internals never enter the text projection.
    """
    parts: list[str] = []

    def add(text: str | None) -> None:
        cleaned = _WS_RE.sub(" ", text or "").strip()
        if cleaned:
            parts.append(cleaned)

    def walk_section(section: dict) -> None:
        add(section.get("title"))
        for block in section.get("blocks", []):
            kind = block.get("type")
            if kind == "paragraph":
                add(block.get("text"))
            elif kind == "table":
                label = block.get("anchorLabel")
                caption = block.get("caption")
                add(" ".join(v for v in (label, caption) if v))
                for row in block.get("rows", []):
                    add(" | ".join(cell.get("text", "") for cell in row.get("cells", [])))
            elif kind == "formula":
                add(block.get("latex"))
            elif kind == "figure":
                label = block.get("anchorLabel")
                caption = block.get("caption")
                add(" ".join(v for v in (label, caption) if v))
            elif kind == "list":
                for item in block.get("items", []):
                    add(item.get("text"))
            elif kind == "code":
                add(block.get("text"))
        for child in section.get("sections", []) or []:
            walk_section(child)

    for section in sections:
        walk_section(section)
    return "\n\n".join(parts)
