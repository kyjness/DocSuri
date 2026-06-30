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
  - ``<figure type="table"><table>``     -> TableBlock as DATA (rows/cells) — GROBID gives real
        table structure, so the structured rows stay the PRIMARY representation (D8). When the
        table also carries coordinates we ALSO attach a page-crop ``assetRef`` as a last-resort
        fallback (schema-sanctioned), so a later vision reader can re-read numbers GROBID's cell
        reconstruction may have garbled — the image never displaces the searchable data.
  - ``<figure>``                         -> FigureBlock (assetRef image, FR-17)

Figure/table position: GROBID groups ``<figure>`` elements (typically at body end), so their
exact inline position is not in TEI order. Figures nested inside a ``<div>`` keep that section;
body-level figures are appended in coordinate order (page, y) — approximate but deterministic.

Deterministic: same TEI -> same DocModel, ids included (P7). No LLM (D1). Built as dicts and
validated through the generated ``DocModel`` binding, so drift from the schema fails loudly.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from docsuri_shared.dtos import DocModel, SourceTier

from docsuri_ingestion.docmodel.parser import (
    _DocCtx,
    _project_full_text,
    _SectionCtx,
    _with_abstract_section,
)
from docsuri_ingestion.domain.assets import AssetCropSpec, asset_id
from docsuri_ingestion.domain.enums import AssetType
from docsuri_ingestion.xmlsafe import safe_fromstring

_WS_RE = re.compile(r"\s+")


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
    if body is not None:
        idx = 0
        for child in list(body):
            name = _local(child.tag)
            if name == "div":
                idx += 1
                sections.append(_parse_div(child, f"s{idx}", doc_ctx))
            elif name == "figure":
                trailing_figures.append(child)

    figure_section = _trailing_figure_section(trailing_figures, len(sections) + 1, doc_ctx)
    if figure_section is not None:
        sections.append(figure_section)

    sections = _with_abstract_section(sections, abstract)
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


def _parse_div(div: ET.Element, section_id: str, doc_ctx: _DocCtx) -> dict:
    """A ``<div>`` -> Section: ``<head>`` title + ``<p>``/``<formula>``/nested ``<figure>``."""
    sec_ctx = _SectionCtx(section_id=section_id)
    title = ""
    blocks: list[dict] = []
    for child in list(div):
        name = _local(child.tag)
        if name == "head" and not title:
            title = _text(child)
        elif name == "p":
            block = _paragraph_block(child, sec_ctx)
            if block:
                blocks.append(block)
        elif name == "formula":
            blocks.append(_formula_block(child, sec_ctx, doc_ctx))
        elif name == "figure":
            block = _figure_or_table_block(child, sec_ctx, doc_ctx)
            if block:
                blocks.append(block)
    return {"id": section_id, "title": title, "blocks": blocks}


def _trailing_figure_section(
    figures: list[ET.Element], section_index: int, doc_ctx: _DocCtx
) -> dict | None:
    """Group body-level figures/tables into a trailing section, ordered by page/y coordinates."""
    if not figures:
        return None
    ordered = sorted(figures, key=_coord_sort_key)
    section_id = f"s{section_index}"
    sec_ctx = _SectionCtx(section_id=section_id)
    blocks: list[dict] = []
    for fig in ordered:
        block = _figure_or_table_block(fig, sec_ctx, doc_ctx)
        if block:
            blocks.append(block)
    if not blocks:
        return None
    return {"id": section_id, "title": "그림 및 표", "blocks": blocks}


# --------------------------------------------------------------------------- blocks


def _paragraph_block(p: ET.Element, sec_ctx: _SectionCtx) -> dict | None:
    text = _text(p)
    if not text:
        return None
    return {"id": sec_ctx.next_id("paragraph"), "type": "paragraph", "text": text}


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
    if (figure_el.get("type") or "").lower() == "table":
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
    if not rows:
        return None
    ordinal = doc_ctx.table_ordinal
    doc_ctx.table_ordinal += 1
    label, caption = _figure_label_caption(figure_el)
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
    parsed = _parse_coords(el)
    if parsed is None:
        return False  # no coordinates -> no crop possible (the block still renders its caption)
    if doc_ctx.crops is not None:
        page, bbox = parsed
        doc_ctx.crops.append(
            AssetCropSpec(
                asset_id=aid,
                type=asset_type,
                ordinal=ordinal,
                page=page,
                bbox=bbox,
                caption=caption,
            )
        )
    return True


def _parse_coords(el: ET.Element) -> tuple[int, tuple[float, float, float, float]] | None:
    """GROBID ``coords`` ("page,x,y,w,h;..." possibly multi-region) -> (page, bbox) bounding box.

    Multiple regions (a figure spanning columns) are unioned into one bbox on the first page."""
    coords = el.get("coords")
    if not coords:
        return None
    page: int | None = None
    x0 = y0 = float("inf")
    x1 = y1 = float("-inf")
    for region in coords.split(";"):
        parts = region.split(",")
        if len(parts) < 5:
            continue
        try:
            pg = int(float(parts[0]))
            x, y, w, h = (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]))
        except ValueError:
            continue
        if page is None:
            page = pg
        elif pg != page:
            continue  # keep the bbox on the first region's page (deterministic)
        x0, y0 = min(x0, x), min(y0, y)
        x1, y1 = max(x1, x + w), max(y1, y + h)
    if page is None or x1 <= x0 or y1 <= y0:
        return None
    return page, (x0, y0, x1, y1)


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


def _coord_sort_key(figure_el: ET.Element) -> tuple[float, float]:
    """Sort key from the GROBID ``coords`` attribute ("page,x,y,w,h;...") -> (page, y).

    Missing/unparseable coords sort last but stably (document order is the tie-break upstream)."""
    coords = figure_el.get("coords")
    if not coords:
        return (float("inf"), float("inf"))
    first = coords.split(";", 1)[0].split(",")
    try:
        page = float(first[0])
        y = float(first[2]) if len(first) > 2 else 0.0
    except (ValueError, IndexError):
        return (float("inf"), float("inf"))
    return (page, y)


def _find_descendant(root: ET.Element, local_name: str) -> ET.Element | None:
    for el in root.iter():
        if _local(el.tag) == local_name:
            return el
    return None
