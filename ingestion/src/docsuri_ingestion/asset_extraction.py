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

from .domain.assets import (
    ExtractedAsset,
    FigureTableAsset,
    RawAssetCandidate,
    asset_id,
)
from .domain.enums import AssetSourceMode, AssetType

# Caption detection — "Figure 1", "Fig. 2", "Table 3" (case-insensitive, line start).
_CAPTION_RE = re.compile(r"^\s*(figure|fig\.?|table)\s+\d+", re.IGNORECASE)

_ASSETS_EXTRA_MISSING = "multimodal assets extra not installed (pip install .[assets])"


def caption_kind(text: str) -> AssetType | None:
    """Classify a text line as a figure/table caption, or None. Pure (P7)."""
    match = _CAPTION_RE.match(text or "")
    if not match:
        return None
    head = match.group(1).lower()
    return AssetType.TABLE if head.startswith("table") else AssetType.FIGURE


def finalize_assets(
    paper_id: str,
    version: int,
    candidates: Sequence[RawAssetCandidate],
) -> tuple[ExtractedAsset, ...]:
    """Order candidates deterministically and assign per-type ordinals + asset ids (P7).

    Ordering is (page, y, x); ordinals are independent per AssetType. Pure — given the same
    candidates it always yields the same assets/ids (PBT P7).
    """
    ordered = sorted(candidates, key=lambda c: (c.page, c.y, c.x, c.type.value))
    counters: dict[AssetType, int] = {AssetType.FIGURE: 0, AssetType.TABLE: 0}
    out: list[ExtractedAsset] = []
    for cand in ordered:
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


class AssetExtractor:
    """Extract figure/table assets for a paper (hybrid, best-effort).

    Returns an empty tuple on any failure — the caller treats assets as non-blocking
    (BR-27). The ``source`` port supplies PDF / e-print bytes lazily (only for NEW|CHANGED
    papers, per the application wiring), so DUPLICATE papers incur no asset fetch (BR-22).
    """

    def __init__(self, *, normalizer: ImageNormalizer | None = None) -> None:
        self._normalizer = normalizer or ImageNormalizer()

    def extract(self, *, paper_id: str, version: int, pdf: bytes | None, eprint: bytes | None
                ) -> tuple[ExtractedAsset, ...]:
        candidates: list[RawAssetCandidate] = []
        # Figures: prefer e-print structured graphics (original quality); fall back to crop.
        if eprint:
            candidates.extend(self._structured_figures(eprint))
        if pdf:
            # Tables always page-crop (TD-12); figures page-crop when e-print yielded none.
            want_figures = not candidates
            candidates.extend(self._page_crop(pdf, want_figures=want_figures))
        return finalize_assets(paper_id, version, candidates)

    # ---- hybrid paths (import-guarded; integration-tested in Build & Test) ----

    def _structured_figures(self, eprint: bytes) -> list[RawAssetCandidate]:
        """Extract raster graphics from an e-print tarball as figure candidates."""
        import tarfile

        out: list[RawAssetCandidate] = []
        try:
            with tarfile.open(fileobj=io.BytesIO(eprint), mode="r:*") as tar:
                members = sorted(
                    (m for m in tar.getmembers() if m.isfile()), key=lambda m: m.name
                )
                for member in members:
                    if not member.name.lower().endswith((".png", ".jpg", ".jpeg")):
                        continue
                    fh = tar.extractfile(member)
                    if fh is None:
                        continue
                    image = self._normalizer.normalize(fh.read())
                    if image is None:
                        continue
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

    def _page_crop(self, pdf: bytes, *, want_figures: bool) -> list[RawAssetCandidate]:
        """Render figure/table regions from a PDF, anchored to detected captions."""
        try:
            import pdfplumber
            import pypdfium2 as pdfium
        except ImportError as exc:  # pragma: no cover - assets extra not installed
            raise RuntimeError(_ASSETS_EXTRA_MISSING) from exc

        out: list[RawAssetCandidate] = []
        try:
            pdfium_doc = pdfium.PdfDocument(pdf)
            with pdfplumber.open(io.BytesIO(pdf)) as plumber:
                for page_no, page in enumerate(plumber.pages):
                    for line in page.extract_text_lines() or []:
                        kind = caption_kind(line.get("text", ""))
                        if kind is None or (kind is AssetType.FIGURE and not want_figures):
                            continue
                        bbox = _caption_region(page, line, kind)
                        image = _render_crop(pdfium_doc, page_no, page, bbox)
                        image = self._normalizer.normalize(image) if image else None
                        if image is None:
                            continue
                        out.append(
                            RawAssetCandidate(
                                type=kind,
                                image=image,
                                source_mode=AssetSourceMode.PAGE_CROP,
                                caption=line.get("text", "").strip(),
                                section_ref=None,
                                page=page_no,
                                y=float(line.get("top", 0.0)),
                                x=float(line.get("x0", 0.0)),
                                bbox=bbox,
                            )
                        )
        except Exception:  # noqa: BLE001 - best-effort; skip assets for this paper
            return []
        return out


def _caption_region(page, line, kind) -> tuple[float, float, float, float]:
    """Heuristic region for a captioned figure/table: the band above the caption for a
    figure, below it for a table (tables typically sit under their caption)."""
    top = float(line.get("top", 0.0))
    page_h = float(page.height)
    if kind is AssetType.TABLE:
        return (0.0, top, float(page.width), min(page_h, top + page_h * 0.4))
    return (0.0, max(0.0, top - page_h * 0.4), float(page.width), top)


def _render_crop(pdfium_doc, page_no: int, plumber_page, bbox) -> bytes | None:
    """Render the bbox region of a page to PNG bytes via pypdfium2."""
    try:
        page = pdfium_doc[page_no]
        bitmap = page.render(scale=2.0)
        pil = bitmap.to_pil()
        scale_x = pil.width / float(plumber_page.width)
        scale_y = pil.height / float(plumber_page.height)
        box = (
            int(bbox[0] * scale_x),
            int(bbox[1] * scale_y),
            int(bbox[2] * scale_x),
            int(bbox[3] * scale_y),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        out = io.BytesIO()
        pil.crop(box).save(out, format="PNG")
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None
