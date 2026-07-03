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
                    for line in page.extract_text_lines() or []:
                        parsed = caption_kind_and_number(line.get("text", ""))
                        if parsed is None:
                            continue
                        kind, number = parsed
                        if (kind is AssetType.FIGURE and not figures) or (
                            kind is AssetType.TABLE and not tables
                        ):
                            continue
                        bbox = _caption_region(page, line, kind)
                        image = _render_bbox_to_png(pdfium_doc, page_no, bbox, plumber_page=page)
                        image = self._normalizer.normalize(image) if image else None
                        if image is None:
                            continue
                        hits.append(
                            _CropHit(
                                kind=kind,
                                number=number,
                                image=image,
                                page=page_no,
                                y=float(line.get("top", 0.0)),
                                x=float(line.get("x0", 0.0)),
                                bbox=bbox,
                                caption=line.get("text", "").strip(),
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


def _caption_region(page, line, kind) -> tuple[float, float, float, float]:
    """Heuristic region for a captioned figure/table: the band above the caption for a
    figure, below it for a table (tables typically sit under their caption)."""
    top = float(line.get("top", 0.0))
    page_h = float(page.height)
    if kind is AssetType.TABLE:
        return (0.0, top, float(page.width), min(page_h, top + page_h * 0.4))
    return (0.0, max(0.0, top - page_h * 0.4), float(page.width), top)


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


