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

# Caption detection — a line that STARTS with "Figure 3:", "Fig. 2.", or "Table 1 —". A delimiter
# (":" / "." / em dash) after the number is required, which:
#   - admits no-space PDF text extractions ("Figure1:Our…", common in pdfplumber output), and
#   - rejects body sentences that merely open with a number ("Table 6 shows that …") — the bug
#     that produced bogus table crops.
# The captured number drives label-matching of an unmatched figure to its page-crop.
_CAPTION_RE = re.compile(r"^\s*(figure|fig\.?|table)\s*(\d+)\s*[:.—]", re.IGNORECASE)
_LABEL_NUM_RE = re.compile(r"(\d+)")

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


def _label_number(label: str) -> int | None:
    """First integer in a figure anchor label ('Figure 3' -> 3), or None. Pure."""
    match = _LABEL_NUM_RE.search(label or "")
    return int(match.group(1)) if match else None


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
    return kind, int(match.group(2))


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
            budget = _MAX_EPRINT_IMAGE_TOTAL
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
            with pdfplumber.open(io.BytesIO(pdf)) as plumber:
                for page_no, page in enumerate(plumber.pages):
                    captions = _page_captions(page.extract_text_lines() or [])
                    if not captions:
                        continue
                    # Assign the page's graphic primitives to captions ONCE, then extract words ONCE
                    # (both are O(page) — recomputing per caption was pure overhead on dense pages).
                    buckets = _assign_graphics(page, captions)
                    words = page.extract_words() or []
                    for cap, prims in zip(captions, buckets, strict=True):
                        kind = cap["kind"]
                        if (kind is AssetType.FIGURE and not figures) or (
                            kind is AssetType.TABLE and not tables
                        ):
                            continue
                        bbox = _caption_bbox(page, prims, words)
                        if bbox is None:
                            continue  # no graphic assigned → caption was a body cross-reference
                        image = _render_bbox_to_png(pdfium_doc, page_no, bbox, plumber_page=page)
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


def _page_captions(lines: Sequence[dict]) -> list[dict]:
    """Every "Figure N"/"Table N" caption line on the page, as ``{kind, number, top, bottom, x0, x1,
    text}``. The x-span lets a two-column page keep each column's figure with its caption. Pure."""
    caps: list[dict] = []
    for ln in lines:
        parsed = caption_kind_and_number(ln.get("text", ""))
        if parsed is None:
            continue
        kind, number = parsed
        top = float(ln.get("top", 0.0))
        caps.append(
            {
                "kind": kind,
                "number": number,
                "top": top,
                "bottom": float(ln.get("bottom", top)),
                "x0": float(ln.get("x0", 0.0)),
                "x1": float(ln.get("x1", 0.0)),
                "text": (ln.get("text", "") or "").strip(),
            }
        )
    return caps


def _assign_graphics(page, captions: Sequence[dict]) -> list[dict[str, list]]:
    """Assign each graphic primitive to the caption whose content-side edge is NEAREST — a figure's
    content sits ABOVE its caption, a table's BELOW — restricted to captions its x-span overlaps.

    Nearest-edge assignment (not a vertical window) is what keeps a table's rules with the table
    even when a figure caption sits just after it. Among captions on the primitive's content side an
    x-overlapping caption is preferred (so a two-column page's left/right figures stay apart), but a
    primitive that overlaps no caption — a figure wider than its short caption — still falls back to
    the nearest same-side caption rather than being dropped. Returns a list parallel to
    ``captions`` of ``{"img": [...], "vec": [...]}`` boxes. Pure given the page."""
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
                # Signed distance from the primitive to this caption's content side; <0 means the
                # primitive is on the WRONG side (below a figure caption / above a table caption).
                dist = cap["top"] - cy if cap["kind"] is AssetType.FIGURE else cy - cap["bottom"]
                if dist < 0:
                    continue
                if any_d is None or dist < any_d:
                    any_d, any_i = dist, i
                overlaps_x = px1 >= cap["x0"] and px0 <= cap["x1"]
                if overlaps_x and (overlap_d is None or dist < overlap_d):
                    overlap_d, overlap_i = dist, i
            chosen = overlap_i if overlap_i is not None else any_i
            if chosen is not None:
                buckets[chosen][key].append((px0, ptop, px1, pbot))
    return buckets


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


def _caption_bbox(page, prims: dict[str, list], words: Sequence[dict]):
    """Tight crop bbox for one caption's assigned primitives, or None to skip.

    The bbox is the union of the assigned primitives grown to include the words that sit within the
    (FIXED) primitive span — axis labels, legends, table cells. Membership is tested against the
    frozen graphic span, never the growing bbox, so a word cannot chain the crop outward into
    neighbouring prose or the running header. Pure given the page."""
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
    return (
        max(0.0, x0 - _REGION_PAD),
        max(0.0, t0 - _REGION_PAD),
        min(float(page.width), x1 + _REGION_PAD),
        min(float(page.height), t1 + _REGION_PAD),
    )


def _render_bbox_to_png(
    pdfium_doc, page_no: int, bbox, *, plumber_page=None
) -> bytes | None:
    """Render the bbox region of a page to PNG bytes via pypdfium2 (points-space bbox -> pixels).

    The page size in PDF points comes from ``plumber_page`` when the caller has a pdfplumber page
    (HTML/caption-region path) and from ``page.get_size()`` otherwise (TEI/GROBID coords path) —
    the only thing that differs between the two callers. The bbox is clamped to the rendered
    bitmap so an over-range coordinate can't yield an empty/oversized crop."""
    try:
        page = pdfium_doc[page_no]
        bitmap = page.render(scale=2.0)
        pil = bitmap.to_pil()
        if plumber_page is not None:
            width_pt, height_pt = plumber_page.width, plumber_page.height
        else:
            width_pt, height_pt = page.get_size()
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
        for spec in specs:
            page_idx = spec.page - 1  # GROBID coords are 1-based
            if page_idx < 0 or page_idx >= page_count:
                continue
            raw = _render_bbox_to_png(doc, page_idx, spec.bbox)
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
                bbox=spec.bbox,
            )
            out.append(ExtractedAsset(meta=meta, image=image))
    except Exception:  # noqa: BLE001 - best-effort; skip assets for this paper
        return ()
    return tuple(out)


