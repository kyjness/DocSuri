"""FR-17 figure/table extraction + image normalization (display-only, best-effort).

Hybrid extraction (BR-23, Q2=C): arXiv e-print (LaTeX) graphics when available, else a
PDF page-crop fallback. Permissive licenses only (TD-11/13 amended away from PyMuPDF/AGPL):
``pypdfium2`` (render), ``pdfplumber`` (layout/captions), ``Pillow`` (WebP normalize).

Pure helpers (``caption_kind``, ``finalize_assets``) are deterministic and unit/PBT tested
(P7). PDF/e-print parsing is import-guarded and exercised in Build & Test (env-gated).
"""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .domain.assets import (
    AssetCropSpec,
    ExtractedAsset,
    FigureSpec,
    FigureTableAsset,
    RawAssetCandidate,
    asset_id,
)
from .domain.enums import AssetSourceMode, AssetType

# Caption detection — a line that STARTS with "Figure 3:", "Fig. 2.", "Table 1 —", or, in the
# journal styles that punctuate nothing, "Fig. 1 The configuration of …". What must be rejected is
# the body sentence that merely opens with a label ("Table 6 shows that …") — the bug that produced
# bogus table crops. So the number is followed by either:
#   - a delimiter (":" / "." / em dash), which also admits the no-space text extractions
#     pdfplumber often returns ("Figure1:Our…"), or
#   - whitespace and a CAPITAL, which is how a caption sentence opens. Measured over 24 real
#     papers: of 59 delimiter-less label lines, all 18 capitalised ones are captions and all 41
#     lowercase ones are cross-references ("Figure 5 shows …"), so the split is clean, or
#   - nothing at all — the label IS the whole line/column segment, which happens when the caption
#     text wraps to the next line. A cross-reference never ends there: its sentence continues.
# The captured number drives label-matching of an unmatched figure to its page-crop.
#
# The same body is compiled anchored (the caption rule) and unanchored (a cheap page-level probe
# for a caption that a two-column merge buried mid-line) so the two can never drift apart.
# ``(?-i:…)`` because the whole pattern is IGNORECASE, under which a bare [A-Z] also matches
# lowercase — which would have let every "Table 6 shows that …" back in.
#
# The number is arabic OR an uppercase roman numeral — IEEE style numbers its tables "TABLE IV"
# (measured on arXiv:2510.23156, where digit-only matching produced zero table crops for the whole
# paper). Roman is uppercase-only (``(?-i:…)`` again): under IGNORECASE the letter class would sit
# inside ordinary lowercase words ("in", "vi", "mix"). The follower guard applies unchanged, so
# "Table I shows …" stays a cross-reference and "TABLE IV RESULTS …" is still a caption.
_CAPTION_BODY = (
    r"(figure|fig\.?|table)\s*(\d+|(?-i:[IVXLCDM]+))(?:\s*[:.—]|\s+(?=(?-i:[A-Z]))|\s*$)"
)
_CAPTION_RE = re.compile(r"^\s*" + _CAPTION_BODY, re.IGNORECASE)
_CAPTION_ANYWHERE_RE = re.compile(_CAPTION_BODY, re.IGNORECASE)
_LABEL_NUM_RE = re.compile(r"(\d+)")
# Roman fallback for anchor labels ("TABLE III") — keyword-prefixed so a roman-lettered word in a
# label can never be misread as a number.
_LABEL_ROMAN_RE = re.compile(r"(?:figure|fig\.?|table)\s*((?-i:[IVXLCDM]+))\b", re.IGNORECASE)

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

_ASSETS_EXTRA_MISSING = "multimodal assets extra not installed (pip install .[assets])"

# Decompression-bomb guards for e-print image members (TD-15): cap per-image and per-tarball
# decoded bytes so a hostile tar member can't inflate unbounded before the pixel guard runs.
_MAX_IMAGE_BYTES = 20_000_000
_MAX_EPRINT_IMAGE_TOTAL = 200_000_000


def _member_stem(name: str) -> str:
    """Lowercased basename without its extension ('a/b/Fig1.PNG' -> 'fig1'), for figure matching.

    Stem (not full basename) so an HTML ``<img src>`` that points at LaTeXML's converted graphic
    can still match the e-print source under a different extension. Pure."""
    base = name.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[0].lower()


def _roman_to_int(token: str) -> int | None:
    """Value of an uppercase roman numeral ('IV' -> 4), or None. Pure.

    Lenient about canonical form ('IIII' -> 4): both call sites reach here only through a
    keyword-prefixed regex ("TABLE …"), so a non-canonical token is a styling quirk, not noise."""
    total = 0
    prev = 0
    for char in reversed(token):
        value = _ROMAN_VALUES.get(char)
        if value is None:
            return None
        total += value if value >= prev else -value
        prev = max(prev, value)
    return total or None


def _caption_number(token: str) -> int | None:
    """The number a caption regex captured — arabic ('3') or roman ('IV'). Pure."""
    return int(token) if token.isdigit() else _roman_to_int(token)


def _label_number(label: str) -> int | None:
    """First number in a figure anchor label ('Figure 3' / 'TABLE III' -> 3), or None. Pure.

    Digits take priority — every label observed until roman support was added is digit-styled, so
    those keep resolving exactly as before ('Figure 12b' -> 12)."""
    match = _LABEL_NUM_RE.search(label or "")
    if match:
        return int(match.group(1))
    roman = _LABEL_ROMAN_RE.search(label or "")
    return _roman_to_int(roman.group(1)) if roman else None


def caption_kind(text: str) -> AssetType | None:
    """Classify a text line as a figure/table caption, or None. Pure (P7)."""
    result = caption_kind_and_number(text)
    return result[0] if result else None


def caption_kind_and_number(text: str) -> tuple[AssetType, int] | None:
    """Caption ``(kind, number)`` for a line — "Figure 3:" -> (FIGURE, 3) — or None. Pure (P7)."""
    match = _CAPTION_RE.match(text or "")
    if not match:
        return None
    kind = AssetType.TABLE if match.group(1).lower().startswith("table") else AssetType.FIGURE
    number = _caption_number(match.group(2))
    if number is None:
        return None
    return kind, number


def finalize_assets(
    paper_id: str,
    version: int,
    candidates: Sequence[RawAssetCandidate],
) -> tuple[ExtractedAsset, ...]:
    """Order candidates deterministically and assign per-type ordinals + asset ids (P7).

    Ordering is (page, y, x); ordinals are independent per AssetType. A candidate carrying an
    explicit ``ordinal`` (e-print figure matched to a doc-model block) keeps it verbatim so its
    ``assetId`` aligns with the FigureBlock that references it; the positional counter is used
    only for candidates that leave it ``None`` (page-crop path). Pure — given the same candidates
    it always yields the same assets/ids (PBT P7).
    """
    ordered = sorted(candidates, key=lambda c: (c.page, c.y, c.x, c.type.value))
    counters: dict[AssetType, int] = {AssetType.FIGURE: 0, AssetType.TABLE: 0}
    out: list[ExtractedAsset] = []
    for cand in ordered:
        if cand.ordinal is not None:
            ordinal = cand.ordinal
        else:
            ordinal = counters[cand.type]
            counters[cand.type] = ordinal + 1
        meta = FigureTableAsset(
            asset_id=asset_id(paper_id, version, cand.type, ordinal),
            paper_id=paper_id,
            version=version,
            type=cand.type,
            ordinal=ordinal,
            source_mode=cand.source_mode,
            caption=cand.caption,
            section_ref=cand.section_ref,
            page_ref=cand.page,
            bbox=cand.bbox,
        )
        out.append(ExtractedAsset(meta=meta, image=cand.image))
    return tuple(out)


class ImageNormalizer:
    """Re-encode external images to WebP with bomb/size guards (TD-13/15, BR-24).

    Always re-decodes through a trusted decoder and re-encodes — original bytes are never
    stored or served. Returns None for undecodable / oversized images (asset is skipped).
    """

    def __init__(
        self,
        *,
        max_longest_side: int = 2048,
        max_pixels: int = 30_000_000,
        webp_quality: int = 80,
    ) -> None:
        self._max_side = max_longest_side
        self._max_pixels = max_pixels
        self._quality = webp_quality

    def normalize(self, raw: bytes) -> bytes | None:
        if not raw:
            return None
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - assets extra not installed
            raise RuntimeError(_ASSETS_EXTRA_MISSING) from exc
        try:
            with Image.open(io.BytesIO(raw)) as img:
                width, height = img.size
                if width * height > self._max_pixels:  # decompression-bomb guard
                    return None
                # Transparency is flattened onto WHITE, the page a paper figure is set on. A bare
                # convert("RGB") leaves transparent pixels at their (usually black) RGB values, so
                # a plot saved with a transparent background rendered as solid black around its
                # axes — with its own black labels invisible inside it.
                if img.mode in ("RGBA", "LA") or (
                    img.mode == "P" and "transparency" in img.info
                ):
                    rgba = img.convert("RGBA")
                    img = Image.new("RGB", rgba.size, (255, 255, 255))
                    img.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    img = img.convert("RGB")
                longest = max(width, height)
                if longest > self._max_side:
                    scale = self._max_side / longest
                    img = img.resize((max(1, int(width * scale)), max(1, int(height * scale))))
                out = io.BytesIO()
                img.save(out, format="WEBP", quality=self._quality)  # strips metadata
                return out.getvalue()
        except Exception:  # noqa: BLE001 - any decode/encode failure → skip this asset
            return None


@dataclass(frozen=True, slots=True)
class _CropHit:
    """One caption-anchored PDF crop: its kind, caption number, WebP image, and page position."""

    kind: AssetType
    number: int
    image: bytes
    page: int
    y: float
    x: float
    bbox: tuple[float, float, float, float]
    caption: str


class AssetExtractor:
    """Extract figure/table assets for a paper (hybrid, best-effort).

    Returns an empty tuple on any failure — the caller treats assets as non-blocking
    (BR-27). The ``source`` port supplies PDF / e-print bytes lazily (only for NEW|CHANGED
    papers, per the application wiring), so DUPLICATE papers incur no asset fetch (BR-22).
    """

    def __init__(self, *, normalizer: ImageNormalizer | None = None) -> None:
        self._normalizer = normalizer or ImageNormalizer()

    def extract(
        self,
        *,
        paper_id: str,
        version: int,
        pdf: bytes | None,
        eprint: bytes | None,
        figure_specs: Sequence[FigureSpec] | None = None,
    ) -> tuple[ExtractedAsset, ...]:
        """Resolve a paper's figure/table images (hybrid, per-ordinal, best-effort).

        With ``figure_specs`` (the doc-model FigureBlocks in document order) each figure ordinal is
        resolved independently: the original-quality e-print graphic when its ``src`` matches a
        tarball member, otherwise a PDF page-crop matched to the figure by its caption NUMBER. So a
        paper mixing author rasters and LaTeXML-rendered vector figures still images every figure a
        source covers — instead of the old all-or-nothing where any structured hit disabled every
        page-crop figure. Tables always page-crop (TD-12). Without ``figure_specs`` the legacy
        whole-tarball / all-or-nothing path runs (backfill cache hit or a direct call).
        """
        candidates: list[RawAssetCandidate] = []
        if eprint:
            candidates.extend(self._structured_figures(eprint, figure_specs))
        if not pdf:
            return finalize_assets(paper_id, version, candidates)

        if figure_specs is None:
            # Legacy: no doc-model guidance — figures only if e-print yielded none (all-or-nothing).
            candidates.extend(self._page_crop(pdf, want_figures=not candidates))
            return finalize_assets(paper_id, version, candidates)

        matched = {c.ordinal for c in candidates if c.type is AssetType.FIGURE}
        unmatched = [(i, spec) for i, spec in enumerate(figure_specs) if i not in matched]
        hits = self._scan_caption_crops(pdf, figures=bool(unmatched), tables=True)
        if unmatched:
            crops_by_number: dict[int, bytes] = {}
            for hit in hits:
                if hit.kind is AssetType.FIGURE:
                    crops_by_number.setdefault(hit.number, hit.image)
            for ordinal, spec in unmatched:
                number = _label_number(spec.label)
                image = crops_by_number.get(number) if number is not None else None
                if image is not None:
                    candidates.append(
                        RawAssetCandidate(
                            type=AssetType.FIGURE,
                            image=image,
                            source_mode=AssetSourceMode.PAGE_CROP,
                            caption=spec.label,
                            ordinal=ordinal,
                            x=float(ordinal),
                        )
                    )
        for hit in hits:
            if hit.kind is AssetType.TABLE:
                candidates.append(
                    RawAssetCandidate(
                        type=AssetType.TABLE,
                        image=hit.image,
                        source_mode=AssetSourceMode.PAGE_CROP,
                        caption=hit.caption,
                        page=hit.page,
                        y=hit.y,
                        x=hit.x,
                        bbox=hit.bbox,
                    )
                )
        return finalize_assets(paper_id, version, candidates)

    # ---- hybrid paths (import-guarded; integration-tested in Build & Test) ----

    def _structured_figures(
        self, eprint: bytes, figure_specs: Sequence[FigureSpec] | None = None
    ) -> list[RawAssetCandidate]:
        """Extract raster graphics from an e-print tarball as figure candidates.

        With ``figure_specs`` (the doc-model FigureBlocks, in document order) each figure's ``src``
        is matched to its tarball member by filename STEM and emitted with the block's
        document-order ordinal — so the ``assetId`` lands on the FigureBlock referencing it, and
        rasters no block points at (logos, sub-panels) are excluded. Stem matching lets an HTML
        ``<img src="x1.png">`` find a source ``x1.pdf``; an undecodable vector source then
        normalizes to ``None`` and is skipped, so the caller's page-crop fill takes over.

        Without ``figure_specs`` (no doc-model guidance — a backfill cache hit or a direct call)
        the legacy filename-ordered scan runs: every raster becomes a figure, positionally ordered.
        """
        import tarfile

        out: list[RawAssetCandidate] = []
        try:
            with tarfile.open(fileobj=io.BytesIO(eprint), mode="r:*") as tar:
                files = [m for m in tar.getmembers() if m.isfile()]
                budget = _MAX_EPRINT_IMAGE_TOTAL  # per-tarball decode budget (TD-15)
                if figure_specs is not None:
                    members_by_stem: dict[str, Any] = {}
                    for member in sorted(files, key=lambda m: m.name):
                        members_by_stem.setdefault(_member_stem(member.name), member)
                    for ordinal, spec in enumerate(figure_specs):
                        if not spec.src:
                            continue  # blanked src (e.g. multi-panel) → page-crop the whole figure
                        member = members_by_stem.get(_member_stem(spec.src))
                        if member is None:
                            continue  # unmatched figure → page-crop fill by caption number
                        if budget <= 0:
                            break  # per-tarball decode budget spent (TD-15)
                        image = self._read_and_normalize(tar, member)
                        if image is None:
                            continue
                        budget -= member.size
                        out.append(
                            RawAssetCandidate(
                                type=AssetType.FIGURE,
                                image=image,
                                source_mode=AssetSourceMode.STRUCTURED,
                                ordinal=ordinal,
                                x=float(ordinal),
                            )
                        )
                    return out
                for member in sorted(files, key=lambda m: m.name):
                    if not member.name.lower().endswith((".png", ".jpg", ".jpeg")):
                        continue
                    if budget <= 0:
                        break  # per-tarball decode budget spent (TD-15)
                    image = self._read_and_normalize(tar, member)
                    if image is None:
                        continue
                    budget -= member.size
                    out.append(
                        RawAssetCandidate(
                            type=AssetType.FIGURE,
                            image=image,
                            source_mode=AssetSourceMode.STRUCTURED,
                            x=float(len(out)),
                        )
                    )
        except Exception:  # noqa: BLE001 - best-effort; fall back to page-crop
            return []
        return out

    def _read_and_normalize(self, tar: Any, member: Any) -> bytes | None:
        # Per-image decompression-bomb cap (TD-15): reject an oversized declared size, and bound the
        # read so a lying tar header can't OOM us past the cap before the pixel guard runs.
        if member.size > _MAX_IMAGE_BYTES:
            return None
        fh = tar.extractfile(member)
        if fh is None:
            return None
        raw = fh.read(_MAX_IMAGE_BYTES + 1)
        if len(raw) > _MAX_IMAGE_BYTES:
            return None
        return self._normalizer.normalize(raw)

    def _scan_caption_crops(
        self, pdf: bytes, *, figures: bool, tables: bool
    ) -> list[_CropHit]:
        """Render caption-anchored figure/table crops from a PDF in one pass (page, caption order).

        Detects lines that open with a "Figure N"/"Table N" caption, crops the region the caption
        anchors, and normalizes it to WebP — returning the kind, caption NUMBER, image, and
        position so callers can map a crop to a doc-model figure by number (figures) or order them
        positionally (tables). Best-effort: any backend failure yields an empty list (BR-27)."""
        try:
            import pdfplumber
            import pypdfium2 as pdfium
        except ImportError as exc:  # pragma: no cover - assets extra not installed
            raise RuntimeError(_ASSETS_EXTRA_MISSING) from exc

        hits: list[_CropHit] = []
        try:
            pdfium_doc = pdfium.PdfDocument(pdf)
            bitmaps = _PageBitmapCache()
            with pdfplumber.open(io.BytesIO(pdf)) as plumber:
                for page_no, page in enumerate(plumber.pages):
                    lines = page.extract_text_lines() or []
                    texts = [ln.get("text", "") or "" for ln in lines]
                    if not any(_CAPTION_ANYWHERE_RE.search(t) for t in texts):
                        continue  # no caption anywhere on the page — skip before paying for words
                    # Extract words ONCE (caption detection needs them for column starts, and the
                    # crop bbox grows to them) and assign the page's graphic primitives to captions
                    # ONCE — both are O(page), recomputing per caption was pure overhead.
                    words = page.extract_words() or []
                    captions = _page_captions(lines, words)
                    if not captions:
                        continue
                    buckets = _assign_graphics(page, captions, words)
                    for cap, prims in zip(captions, buckets, strict=True):
                        kind = cap["kind"]
                        if (kind is AssetType.FIGURE and not figures) or (
                            kind is AssetType.TABLE and not tables
                        ):
                            continue
                        bbox = _caption_bbox(page, prims, words, cap)
                        if bbox is None:
                            continue  # no graphic assigned → caption was a body cross-reference
                        image = _render_bbox_to_png(
                            pdfium_doc, page_no, bbox, plumber_page=page, bitmap_cache=bitmaps
                        )
                        image = self._normalizer.normalize(image) if image else None
                        if image is None:
                            continue
                        hits.append(
                            _CropHit(
                                kind=kind,
                                number=cap["number"],
                                image=image,
                                page=page_no,
                                y=cap["top"],
                                x=cap["x0"],
                                bbox=bbox,
                                caption=cap["text"],
                            )
                        )
        except Exception:  # noqa: BLE001 - best-effort; skip assets for this paper
            return []
        return hits

    def _page_crop(self, pdf: bytes, *, want_figures: bool) -> list[RawAssetCandidate]:
        """Legacy all-or-nothing page-crop (no doc-model guidance): positionally-ordered crops."""
        return [
            RawAssetCandidate(
                type=hit.kind,
                image=hit.image,
                source_mode=AssetSourceMode.PAGE_CROP,
                caption=hit.caption,
                section_ref=None,
                page=hit.page,
                y=hit.y,
                x=hit.x,
                bbox=hit.bbox,
            )
            for hit in self._scan_caption_crops(pdf, figures=want_figures, tables=True)
        ]


# Region-detection tunables. A real figure/table is a cluster of vector/raster primitives; a lone
# stray line (a rule, an underline) is not, so require a minimum before accepting a crop — unless
# the single primitive is large enough to be a one-path diagram/plot. Padding gives breathing room.
_MIN_GRAPHIC_OBJS = 2
_REGION_PAD = 4.0
_SINGLE_PRIM_MIN_W_FRAC = 0.3  # a lone primitive counts only if it spans ≥30% width AND ≥10% height
_SINGLE_PRIM_MIN_H_FRAC = 0.1

# Column-start detection for a caption a two-column merge buried mid-line. Measured on a real
# two-column paper: a column-starting caption has this strip clear on 57-73% of the page's rows,
# an in-prose cross-reference on only 10-14% — so the threshold sits far from both.
_ROW_TOLERANCE_PT = 3.0  # pdfplumber's own line-clustering tolerance
_COLUMN_EDGE_PROBE_PT = 8.0
_COLUMN_EDGE_MAX_CROSSED_FRAC = 0.6
# Measured word gaps on real two-column papers: ordinary spaces 4-6pt, a column jump 10pt+.
_COLUMN_MIN_GAP_PT = 8.0
# How far a crop may reach across empty space before the next primitive counts as unrelated
# content rather than another panel/rule of the same figure or table (1 inch).
_CROP_PRIM_GAP_PT = 72.0
# Recognising a table's unruled body rows. Measured on a real table: its rows carry five word gaps
# of 12-28pt inside the table's width, while every prose row around it carries none.
_TABLE_COL_GAP_PT = 8.0
_TABLE_MIN_COL_GAPS = 2
# A two-column table's row has a single gap, so it must be far wider than the ~10pt a justified
# line can stretch a space to. Measured on a real two-column table: 28-103pt.
_TABLE_WIDE_GAP_PT = 20.0
_TABLE_ROW_MAX_GAP_PT = 20.0  # a row further than this has stopped being the next line of the table
_TABLE_ROW_PAD_PT = 12.0


def _page_captions(lines: Sequence[dict], words: Sequence[dict] = ()) -> list[dict]:
    """Every "Figure N"/"Table N" caption on the page, as ``{kind, number, top, bottom, x0, x1,
    text}``. The x-span lets a two-column page keep each column's figure with its caption.

    ``extract_text_lines`` merges the two columns of a two-column page into ONE line, so a line is
    read one COLUMN SEGMENT at a time: a segment starts at the line's own start or wherever a word
    begins a column, and ends where the next column begins. That matters twice over — the right
    column's caption is otherwise invisible to the "caption starts the line" rule (its figure then
    goes uncropped, or is swallowed by whatever caption does claim it), and a caption in the LEFT
    column otherwise absorbs the neighbouring column's text into its own text and x-span, which is
    how a table caption ended up spanning a whole page. A column start is recognised by the strip
    just left of it being clear on most of the page's rows; a body cross-reference ("… is provided
    in Figure 1.") sits inside running prose, so its strip is covered. Pure given lines and words.
    """
    caps: list[dict] = []
    rows = _text_rows(words)
    for ln in lines:
        text = (ln.get("text", "") or "").strip()
        line_words = _line_words(ln, words) if rows and _CAPTION_ANYWHERE_RE.search(text) else []
        if not line_words:
            parsed = caption_kind_and_number(text)
            if parsed is not None:
                x0, x1 = float(ln.get("x0", 0.0)), float(ln.get("x1", 0.0))
                caps.append(_caption_entry(ln, parsed, x0, x1, text))
            continue
        for start, end in _column_segments(line_words, rows):
            segment = line_words[start:end]
            seg_text = " ".join(str(w.get("text", "")) for w in segment)
            parsed = caption_kind_and_number(seg_text)
            if parsed is not None:
                caps.append(
                    _caption_entry(
                        ln,
                        parsed,
                        float(segment[0].get("x0", 0.0)),
                        float(segment[-1].get("x1", 0.0)),
                        seg_text,
                    )
                )
    return caps


def _column_segments(
    line_words: Sequence[dict], rows: Sequence[Sequence[dict]]
) -> list[tuple[int, int]]:
    """The line's words split into column segments as ``(start, end)`` index pairs.

    A split needs BOTH a real horizontal jump and a column edge. The gap alone cannot decide it
    (justified prose stretches word gaps to a column gutter's width), but without it the edge test
    can fire on an ordinary word space and cut a caption in half on a sparsely-set page. Pure."""
    starts = [0] + [
        i
        for i in range(1, len(line_words))
        if float(line_words[i].get("x0", 0.0)) - float(line_words[i - 1].get("x1", 0.0))
        >= _COLUMN_MIN_GAP_PT
        and _starts_a_column(float(line_words[i].get("x0", 0.0)), rows)
    ]
    return [(s, e) for s, e in zip(starts, [*starts[1:], len(line_words)], strict=True)]


def _caption_entry(
    line: dict, parsed: tuple[AssetType, int], x0: float, x1: float, text: str
) -> dict:
    """One caption record: its kind/number, the line's vertical band, and its own x-span. Pure."""
    kind, number = parsed
    top = float(line.get("top", 0.0))
    return {
        "kind": kind,
        "number": number,
        "top": top,
        "bottom": float(line.get("bottom", top)),
        "x0": x0,
        "x1": x1,
        "text": text,
    }


def _text_rows(words: Sequence[dict]) -> list[list[dict]]:
    """The page's words grouped into rows by ``top`` (pdfplumber's line tolerance). Pure."""
    rows: dict[int, list[dict]] = {}
    for word in words:
        rows.setdefault(int(float(word.get("top", 0.0)) // _ROW_TOLERANCE_PT), []).append(word)
    return list(rows.values())


def _line_words(line: dict, words: Sequence[dict]) -> list[dict]:
    """The page words whose vertical centre falls inside ``line``, left to right. Pure."""
    top, bottom = float(line.get("top", 0.0)), float(line.get("bottom", 0.0))
    inside = []
    for w in words:
        cy = (float(w.get("top", 0.0)) + float(w.get("bottom", 0.0))) / 2.0
        if top - 1.0 <= cy <= bottom + 1.0:
            inside.append(w)
    return sorted(inside, key=lambda w: float(w.get("x0", 0.0)))


def _starts_a_column(x0: float, rows: Sequence[Sequence[dict]]) -> bool:
    """Whether ``x0`` looks like a column's left edge: the strip immediately left of it is clear of
    text on most of the page's rows. Prose flowing through that strip on nearly every row means the
    position is mid-sentence, not a column start. Pure."""
    left, right = x0 - _COLUMN_EDGE_PROBE_PT, x0 - 1.0
    crossed = sum(
        1
        for row in rows
        if any(float(w.get("x0", 0.0)) < right and float(w.get("x1", 0.0)) > left for w in row)
    )
    return crossed <= _COLUMN_EDGE_MAX_CROSSED_FRAC * len(rows)


def _assign_graphics(
    page, captions: Sequence[dict], words: Sequence[dict] = ()
) -> list[dict[str, list]]:
    """Assign each graphic primitive to the caption whose content-side edge is NEAREST — a figure's
    content sits ABOVE its caption, a table's on EITHER side — restricted to captions its x-span
    overlaps.

    A figure caption always follows its figure, but journals differ on tables: some print the
    caption above the table, some below it, and papers mix both. So a table caption takes the
    nearest primitives on whichever side they lie, and ``_one_sided`` then trims it back to a
    single side — a crop that straddles its own caption is wrong whichever way the paper prints it.

    Nearest-edge assignment (not a vertical window) is what keeps a table's rules with the table
    even when a figure caption sits just after it, and it is also what stops a table caption from
    stealing the figure above it: that figure's own caption is nearer. Among captions on the
    primitive's content side an x-overlapping caption is preferred (so a two-column page's
    left/right figures stay apart), but a primitive that overlaps no caption — a figure wider than
    its short caption — still falls back to the nearest same-side caption rather than being dropped.
    Returns a list parallel to ``captions`` of ``{"img": [...], "vec": [...]}`` boxes. Pure given
    the page."""
    buckets: list[dict[str, list]] = [{"img": [], "vec": []} for _ in captions]
    for name in ("curves", "lines", "rects", "images"):
        key = "img" if name == "images" else "vec"
        for o in getattr(page, name, None) or []:
            px0, ptop, px1, pbot = (
                float(o["x0"]),
                float(o["top"]),
                float(o["x1"]),
                float(o["bottom"]),
            )
            cy = (ptop + pbot) / 2.0
            overlap_i = overlap_d = any_i = any_d = None
            for i, cap in enumerate(captions):
                # Distance from the primitive to this caption's content side; None means the
                # primitive is on a side this caption's content cannot be on (below a figure
                # caption).
                dist = _content_distance(cap, cy)
                if dist is None:
                    continue
                if any_d is None or dist < any_d:
                    any_d, any_i = dist, i
                overlaps_x = px1 >= cap["x0"] and px0 <= cap["x1"]
                if overlaps_x and (overlap_d is None or dist < overlap_d):
                    overlap_d, overlap_i = dist, i
            chosen = overlap_i if overlap_i is not None else any_i
            if chosen is not None:
                buckets[chosen][key].append((px0, ptop, px1, pbot))
    return [
        _contiguous_with_caption(cap, _one_sided(cap, bucket), words)
        for cap, bucket in zip(captions, buckets, strict=True)
    ]


def _content_distance(caption: dict, cy: float) -> float | None:
    """Distance from a primitive's centre to the caption's content side, or None if it is on a side
    that caption's content cannot occupy. Pure."""
    if caption["kind"] is AssetType.FIGURE:
        above = caption["top"] - cy
        return above if above >= 0 else None
    if cy > caption["bottom"]:
        return cy - caption["bottom"]
    return max(0.0, caption["top"] - cy)  # 0 for a primitive overlapping the caption band itself


def _one_sided(caption: dict, bucket: dict[str, list]) -> dict[str, list]:
    """Drop the farther side when a (table) caption drew primitives from both — two tables sharing a
    caption line's neighbourhood must not merge into one crop spanning the caption. Pure."""
    centres = [(b[1] + b[3]) / 2.0 for b in bucket["img"] + bucket["vec"]]
    above = [cy for cy in centres if cy < caption["top"]]
    below = [cy for cy in centres if cy > caption["bottom"]]
    if not above or not below:
        return bucket
    # The kept bound is the caption's FAR edge, so a primitive overlapping the caption band (a rule
    # printed through it) stays with whichever side wins rather than being dropped by both.
    if (caption["top"] - max(above)) <= (min(below) - caption["bottom"]):
        lo, hi = float("-inf"), caption["bottom"]
    else:
        lo, hi = caption["top"], float("inf")
    return {
        key: [b for b in boxes if lo < (b[1] + b[3]) / 2.0 < hi] for key, boxes in bucket.items()
    }


def _contiguous_with_caption(
    caption: dict, bucket: dict[str, list], words: Sequence[dict]
) -> dict[str, list]:
    """Keep only the run of primitives that reaches the caption without an unfilled break.

    A caption is the nearest one for everything on its side of the page, including a rule at the
    very bottom that belongs to nothing near it. A figure or table is a contiguous band, so walk
    outward from the caption and stop at the first wide gap — unless the gap is FILLED by the
    table's own rows. Most journals rule only a table's header and its last row, leaving a body
    of unruled text between them that is otherwise indistinguishable from a page-sized break.
    Pure given the page's words."""
    boxes = sorted(
        bucket["img"] + bucket["vec"],
        key=lambda b: _content_distance(caption, (b[1] + b[3]) / 2.0) or 0.0,
    )
    if not boxes:
        return bucket
    top, bottom = boxes[0][1], boxes[0][3]
    for box in boxes[1:]:
        if max(top - box[3], box[1] - bottom) > _CROP_PRIM_GAP_PT and not _rows_bridge(
            caption, words, (top, bottom), box
        ):
            break
        top, bottom = min(top, box[1]), max(bottom, box[3])
    return {
        key: [b for b in boxes_of_kind if b[1] <= bottom and b[3] >= top]
        for key, boxes_of_kind in bucket.items()
    }


def _rows_bridge(
    caption: dict, words: Sequence[dict], span: tuple[float, float], box: tuple
) -> bool:
    """Whether a table's rows fill the gap between the kept band and the next primitive. Pure."""
    if caption["kind"] is not AssetType.TABLE or not words:
        return False
    top, bottom = _table_row_span(words, caption, (box[0], box[2]), span)
    return box[1] <= bottom + _CROP_PRIM_GAP_PT and box[3] >= top - _CROP_PRIM_GAP_PT


def _accept_graphics(img_boxes: list, vec_boxes: list, page) -> bool:
    """Whether the assigned primitives are a real figure/table (not a body cross-reference that
    merely opens with a caption-looking phrase). Any raster counts; so does a cluster of vector
    primitives, or a single LARGE one (a one-path diagram) — but not a lone thin rule/underline."""
    if img_boxes:
        return True
    if len(vec_boxes) >= _MIN_GRAPHIC_OBJS:
        return True
    if len(vec_boxes) == 1:
        x0, t0, x1, t1 = vec_boxes[0]
        return (x1 - x0) >= _SINGLE_PRIM_MIN_W_FRAC * float(page.width) and (
            t1 - t0
        ) >= _SINGLE_PRIM_MIN_H_FRAC * float(page.height)
    return False


def _caption_bbox(page, prims: dict[str, list], words: Sequence[dict], caption: dict | None = None):
    """Tight crop bbox for one caption's assigned primitives, or None to skip.

    The bbox is the union of the assigned primitives grown to include the words that sit within the
    (FIXED) primitive span — axis labels, legends, table cells. Membership is tested against the
    frozen graphic span, never the growing bbox, so a word cannot chain the crop outward into
    neighbouring prose or the running header.

    A table is the exception: most journals rule only the header and the last row, so the frozen
    span covers a couple of rules and the crop came out as a header strip with the table's body
    below it. For a table the box therefore also grows over the ROWS that continue from it (see
    ``_table_row_span``). Pure given the page."""
    img_boxes, vec_boxes = prims["img"], prims["vec"]
    if not _accept_graphics(img_boxes, vec_boxes, page):
        return None
    boxes = img_boxes + vec_boxes
    gx0 = min(b[0] for b in boxes)
    gt0 = min(b[1] for b in boxes)
    gx1 = max(b[2] for b in boxes)
    gt1 = max(b[3] for b in boxes)
    x0, t0, x1, t1 = gx0, gt0, gx1, gt1
    for w in words:
        cy = (float(w["top"]) + float(w["bottom"])) / 2.0
        if gt0 - 2.0 <= cy <= gt1 + 2.0 and float(w["x1"]) >= gx0 and float(w["x0"]) <= gx1:
            x0 = min(x0, float(w["x0"]))
            x1 = max(x1, float(w["x1"]))
            t0 = min(t0, float(w["top"]))
            t1 = max(t1, float(w["bottom"]))
    if caption is not None and caption["kind"] is AssetType.TABLE:
        t0, t1 = _table_row_span(words, caption, (gx0, gx1), (t0, t1))
    return (
        max(0.0, x0 - _REGION_PAD),
        max(0.0, t0 - _REGION_PAD),
        min(float(page.width), x1 + _REGION_PAD),
        min(float(page.height), t1 + _REGION_PAD),
    )


def _table_row_span(
    words: Sequence[dict],
    caption: dict,
    x_span: tuple[float, float],
    v_span: tuple[float, float],
) -> tuple[float, float]:
    """Grow a table's vertical span over the rows that continue from its ruled band.

    A ruled band is only where the journal drew lines — usually the header and the last row — so
    the rest of the body has to be recognised from the text itself. A table row is columnar: it
    carries several wide inter-word gaps within the table's width, which running prose never does.
    Rows are taken while they keep coming (line spacing) and never past the caption. Pure."""
    gx0, gx1 = x_span
    top, bottom = v_span
    rows = sorted(
        (
            (min(float(w["top"]) for w in row), max(float(w["bottom"]) for w in row), row)
            for row in _text_rows(
                [
                    w
                    for w in words
                    if float(w["x0"]) >= gx0 - _TABLE_ROW_PAD_PT
                    and float(w["x1"]) <= gx1 + _TABLE_ROW_PAD_PT
                ]
            )
        ),
        key=lambda r: r[0],
    )
    for direction in (1, -1):
        edge = bottom if direction == 1 else top
        for row_top, row_bottom, row in rows if direction == 1 else reversed(rows):
            near, far = (row_top, row_bottom) if direction == 1 else (row_bottom, row_top)
            if (near - edge) * direction <= 0:
                continue  # already inside the span
            if abs(near - edge) > _TABLE_ROW_MAX_GAP_PT or not _is_columnar(row):
                break
            if caption["top"] <= near <= caption["bottom"]:
                break  # reached the caption itself
            edge = far
        if direction == 1:
            bottom = max(bottom, edge)
        else:
            top = min(top, edge)
    return top, bottom


def _is_columnar(row: Sequence[dict]) -> bool:
    """Whether a text row reads as table columns rather than prose.

    A many-column row shows several moderate gaps; a two-column row shows exactly one, so that one
    has to be wide enough that justified prose could not have stretched a space to it. Pure."""
    ordered = sorted(row, key=lambda w: float(w["x0"]))
    gaps = [float(b["x0"]) - float(a["x1"]) for a, b in zip(ordered, ordered[1:], strict=False)]
    if sum(1 for g in gaps if g >= _TABLE_COL_GAP_PT) >= _TABLE_MIN_COL_GAPS:
        return True
    return any(g >= _TABLE_WIDE_GAP_PT for g in gaps)


class _PageBitmapCache:
    """The most recently rendered page, held as a single entry.

    Rendering a page at 2x costs tens of milliseconds and roughly 6 MB, and a page carrying five
    figures used to be rendered five times — once per crop. Both crop callers walk their specs in
    page order (the caption path iterates pages directly, the spec path receives them sorted by
    page), so one entry removes the repeats without letting a long paper pin every page in memory.
    """

    def __init__(self) -> None:
        self._page_no: int | None = None
        self._pil = None
        self._bitmap = None  # keeps the buffer the PIL image may be a view of — see page_image

    def page_image(self, pdfium_doc, page_no: int):
        if self._page_no != page_no or self._pil is None:
            bitmap = pdfium_doc[page_no].render(scale=2.0)
            # Hold the PdfBitmap for as long as the image: pypdfium2's to_pil() returns a view
            # over the bitmap buffer for RGBA/RGBX/L modes and deliberately attaches no keep-alive
            # finalizer, so dropping it would leave the cached image reading freed memory. Today's
            # render yields RGB, which copies — but the cache outlives the call that made it, and
            # that safety must not depend on a render flag nobody links back to here.
            self._pil = bitmap.to_pil()
            self._bitmap = bitmap
            self._page_no = page_no
        return self._pil


class _PageGraphicCache:
    """Bounding boxes of the graphic objects on the most recently inspected page.

    Same single-entry shape as ``_PageBitmapCache`` and for the same reason: specs arrive in page
    order, and a page can carry over a hundred objects that would otherwise be walked once per
    spec. Boxes are converted to the top-left origin the specs use, so callers never meet pdfium's
    bottom-up coordinates.
    """

    def __init__(self) -> None:
        self._page_no: int | None = None
        self._boxes: tuple[tuple[float, float, float, float], ...] = ()

    def boxes(self, pdfium_doc, page_no: int) -> tuple[tuple[float, float, float, float], ...]:
        if self._page_no != page_no:
            self._boxes = _graphic_boxes(pdfium_doc, page_no)
            self._page_no = page_no
        return self._boxes


def _graphic_boxes(pdfium_doc, page_no: int) -> tuple[tuple[float, float, float, float], ...]:
    """Top-left-origin boxes of the picture-bearing objects on a page.

    IMAGE covers raster figures; FORM covers the vector figures a plotting library emits as an
    XObject — the ones GROBID never reports, since it looks for embedded images. Bare PATH objects
    are deliberately excluded: page rules, table borders and underlines are all paths, so treating
    them as figures would make almost every page look like it had a graphic on it.
    """
    try:
        from pypdfium2 import raw
    except ImportError:  # pragma: no cover - assets extra not installed
        return ()
    try:
        page = pdfium_doc[page_no]
        page_height = page.get_size()[1]
        boxes = []
        for obj in page.get_objects(max_depth=1):
            if obj.type not in (raw.FPDF_PAGEOBJ_IMAGE, raw.FPDF_PAGEOBJ_FORM):
                continue
            x0, y0, x1, y1 = obj.get_pos()
            # pdfium measures y upward from the page bottom; specs measure it downward from the
            # top. Flipping BOTH edges swaps their roles, hence y1 -> top and y0 -> bottom.
            boxes.append((x0, page_height - y1, x1, page_height - y0))
        return tuple(boxes)
    except Exception:  # noqa: BLE001 - a page we cannot inspect simply offers no recovery
        return ()


# A figure caption sits directly beneath its graphic. Allowing an unbounded gap would let a crop
# reach up the page and swallow an unrelated figure, so the search stops half an inch above the
# caption — measured gaps on the fixture papers are 3.0, -2.2 and 15.1pt.
_CAPTION_GRAPHIC_GAP_PT = 36.0

# Not every vector object is a picture. A QED tombstone is four 0.5pt-thick FORM XObjects, and
# rules and underlines are similarly thin; latching onto one drags unrelated text into the crop.
# Real figure graphics on the fixture papers run 157-291pt per side (>= 25,000pt² of area), so a
# floor of roughly a 32pt square separates them by orders of magnitude rather than by a hair.
_MIN_GRAPHIC_AREA_PT2 = 1000.0


# A crop smaller than this holds a glyph fragment, not content. GROBID occasionally emits a
# formula element for a stray delimiter — a lone ")" 4.4pt wide — and rendering it stores an image
# of one bracket that a reader is then shown in place of the equation. Across the TEI fixtures the
# offenders measure 35-42pt² while the smallest genuine crop is over 600pt², so this separates them
# by an order of magnitude rather than by a hair.
_MIN_CROP_AREA_PT2 = 200.0


def crop_is_renderable(bbox: tuple[float, float, float, float]) -> bool:
    """Whether a crop region is big enough to carry anything — see ``_MIN_CROP_AREA_PT2``."""
    x0, y0, x1, y1 = bbox
    return (x1 - x0) * (y1 - y0) >= _MIN_CROP_AREA_PT2


def crop_bbox_for(
    spec: AssetCropSpec, graphics: Sequence[tuple[float, float, float, float]]
) -> tuple[float, float, float, float]:
    """The region to render for ``spec``, widened when a figure's graphic went unreported.

    Figures only. A table's coordinates are its body and a formula's are the formula, so neither
    has anything to recover and widening either would pull in surrounding page content.
    """
    if spec.type is not AssetType.FIGURE:
        return spec.bbox
    return _recover_figure_bbox(graphics, spec.bbox) or spec.bbox


def _recover_figure_bbox(
    graphics: Sequence[tuple[float, float, float, float]],
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    """Widen a caption-only figure bbox to include the graphic sitting above it, or None.

    GROBID emits a ``<graphic>`` for raster figures only, so a vector figure's coordinates cover
    just the caption's text lines and the crop shows a sentence where the figure should be. The
    picture is still in the PDF as a page object; this finds it.

    Returns None whenever the answer is not clear-cut, which keeps the existing crop:
    a bbox already overlapping a graphic is GROBID's own (correct) figure region, and a page with
    no graphic object above the caption offers nothing to recover — a text block mislabelled as a
    figure lands here and is left exactly as it was.
    """
    x0, y0, x1, y1 = bbox
    # Decorative vector objects are not pictures — see _MIN_GRAPHIC_AREA_PT2. Filtering here rather
    # than in _graphic_boxes keeps that helper an honest report of what is on the page.
    graphics = [g for g in graphics if (g[2] - g[0]) * (g[3] - g[1]) >= _MIN_GRAPHIC_AREA_PT2]
    # "Already covers a graphic" has to mean most of one, not a hairline touch: a caption's first
    # line routinely tucks a point or two under the plot above it, and treating that as coverage
    # would leave exactly the figures this exists to recover uncorrected.
    for g in graphics:
        overlap = max(0.0, min(x1, g[2]) - max(x0, g[0])) * max(0.0, min(y1, g[3]) - max(y0, g[1]))
        area = (g[2] - g[0]) * (g[3] - g[1])
        if area > 0 and overlap / area >= 0.5:
            return None  # GROBID's own figure region — nothing was missed
    above = [
        g
        for g in graphics
        # Horizontally overlapping, bottom above the caption's bottom, and close enough that the
        # caption plausibly belongs to it. The gap may be slightly negative (a caption whose first
        # line tucks under the graphic's box), which the upper bound alone still admits.
        if g[0] < x1 and g[2] > x0 and g[3] < y1 and (y0 - g[3]) <= _CAPTION_GRAPHIC_GAP_PT
    ]
    if not above:
        return None
    # Nearest one only. Unioning every candidate would merge stacked subfigures into one crop that
    # also swept up whatever text sat between them.
    nearest = max(above, key=lambda g: g[3])
    return (min(x0, nearest[0]), min(y0, nearest[1]), max(x1, nearest[2]), max(y1, nearest[3]))


def _render_bbox_to_png(
    pdfium_doc, page_no: int, bbox, *, plumber_page=None, bitmap_cache=None
) -> bytes | None:
    """Render the bbox region of a page to PNG bytes via pypdfium2 (points-space bbox -> pixels).

    The page size in PDF points comes from ``plumber_page`` when the caller has a pdfplumber page
    (HTML/caption-region path) and from ``page.get_size()`` otherwise (TEI/GROBID coords path) —
    the only thing that differs between the two callers. The bbox is clamped to the rendered
    bitmap so an over-range coordinate can't yield an empty/oversized crop."""
    try:
        cache = bitmap_cache if bitmap_cache is not None else _PageBitmapCache()
        # crop() copies, so successive crops of one cached page cannot disturb each other.
        pil = cache.page_image(pdfium_doc, page_no)
        if plumber_page is not None:
            width_pt, height_pt = plumber_page.width, plumber_page.height
        else:
            # Load the page only on the branch that needs it: the caption path supplies its own
            # page size, and loading it there was one FPDF_LoadPage per crop for nothing.
            width_pt, height_pt = pdfium_doc[page_no].get_size()
        scale_x = pil.width / float(width_pt)
        scale_y = pil.height / float(height_pt)
        box = (
            max(0, int(bbox[0] * scale_x)),
            max(0, int(bbox[1] * scale_y)),
            min(pil.width, int(bbox[2] * scale_x)),
            min(pil.height, int(bbox[3] * scale_y)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        out = io.BytesIO()
        pil.crop(box).save(out, format="PNG")
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


def crop_assets_from_specs(
    pdf: bytes,
    specs: Sequence[AssetCropSpec],
    *,
    paper_id: str,
    version: int,
    normalizer: ImageNormalizer | None = None,
) -> tuple[ExtractedAsset, ...]:
    """Render TEI-coordinate page-crops into stored assets (PDF/GROBID path, FR-17).

    Each spec's bbox (PDF points, top-left origin) is rendered from the PDF and normalized to
    WebP, keyed by the spec's ``asset_id`` — the SAME id the doc-model block references, so the
    image lands on the right FormulaBlock/FigureBlock (ordinal alignment guaranteed upstream).
    Best-effort: any failure yields an empty tuple (assets never block indexing, BR-27).
    """
    if not specs:
        return ()
    normalizer = normalizer or ImageNormalizer()
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - assets extra not installed
        raise RuntimeError(_ASSETS_EXTRA_MISSING) from exc

    out: list[ExtractedAsset] = []
    try:
        doc = pdfium.PdfDocument(pdf)
        page_count = len(doc)
        bitmaps = _PageBitmapCache()
        graphics = _PageGraphicCache()
        for spec in specs:
            page_idx = spec.page - 1  # GROBID coords are 1-based
            if page_idx < 0 or page_idx >= page_count:
                continue
            bbox = crop_bbox_for(spec, graphics.boxes(doc, page_idx))
            if not crop_is_renderable(bbox):
                continue
            raw = _render_bbox_to_png(doc, page_idx, bbox, bitmap_cache=bitmaps)
            image = normalizer.normalize(raw) if raw else None
            if image is None:
                continue
            meta = FigureTableAsset(
                asset_id=spec.asset_id,
                paper_id=paper_id,
                version=version,
                type=spec.type,
                ordinal=spec.ordinal,
                source_mode=AssetSourceMode.PAGE_CROP,
                caption=spec.caption,
                page_ref=spec.page,
                bbox=bbox,  # the rendered region, which recovery may have widened
            )
            out.append(ExtractedAsset(meta=meta, image=image))
    except Exception:  # noqa: BLE001 - best-effort; skip assets for this paper
        return ()
    return tuple(out)


