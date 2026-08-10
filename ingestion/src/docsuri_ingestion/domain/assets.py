"""FR-17 multimodal figure/table asset domain types (display-only).

Assets are extracted/stored best-effort and are NOT part of the search index
(IndexRecord). They never gate paper indexing (BR-27). See FD §10 / business-rules §7.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import AssetSourceMode, AssetType


def asset_id(paper_id: str, version: int, asset_type: AssetType, ordinal: int) -> str:
    """Deterministic asset identifier (BR-28, P7). Stable for re-processing."""
    return f"{paper_id}:v{version}:{asset_type.value}:{ordinal}"


@dataclass(frozen=True, slots=True)
class FigureSpec:
    """A doc-model FigureBlock's image-resolution hints, in document order (index == ordinal).

    ``src`` is the HTML ``<img src>`` (matched to an e-print graphic by filename stem for the
    original-quality structured image). ``label`` is the visible anchor label, e.g. "Figure 3"
    (its number maps an unmatched figure to a PDF page-crop caption when the e-print has no raster
    for it). Both are best-effort hints; an empty value just skips that resolution path.
    """

    src: str = ""
    label: str = ""


@dataclass(frozen=True, slots=True)
class RawAssetCandidate:
    """Transient extractor output before ordering/normalization.

    ``image`` holds the (already normalized) WebP bytes. ``page``/``y``/``x`` drive the
    deterministic (page, y, x) ordering that assigns per-type ordinals (P7).

    ``ordinal`` pins the per-type ordinal explicitly: the e-print figure path matches each
    doc-model FigureBlock (in document order) to its graphic and carries that block's ordinal
    so the resulting ``assetId`` lands on the block referencing it. When ``None`` the ordinal is
    assigned positionally by ``finalize_assets`` (the caption page-crop path).
    """

    type: AssetType
    image: bytes
    source_mode: AssetSourceMode
    caption: str = ""
    section_ref: str | None = None
    page: int = 0
    y: float = 0.0
    x: float = 0.0
    bbox: tuple[float, float, float, float] | None = None
    ordinal: int | None = None


@dataclass(frozen=True, slots=True)
class AssetCropSpec:
    """A coordinate page-crop request emitted by the TEI parser (PDF/GROBID path).

    Carries the SAME ``asset_id``/``ordinal`` the doc-model block references, so the rendered
    image lands on the exact FormulaBlock/FigureBlock that points at it (ordinal alignment is
    guaranteed because spec and block are minted in one TEI walk). ``page`` is 1-based (GROBID);
    ``bbox`` is (x0, y0, x1, y1) in PDF points, top-left origin.

    ``content_coords`` records whether the bbox came from the float's CONTENT element (a figure's
    ``<graphic>``, a table's ``<table>``) or merely from the float's own coordinates. Only the
    latter can turn out to be a strip of caption text with no picture in it, so the renderer uses
    this to decide which crops still have to be checked against the PDF before being stored.

    ``float_bbox`` is the whole float's own box on the same page, when it has one. It is the OUTER
    bound for anything the renderer recovers: GROBID's ``<table>`` box sometimes collapses onto a
    fragment of the header row, and growing that back over the rows below it must not run past
    where the float itself ended.
    """

    asset_id: str
    type: AssetType
    ordinal: int
    page: int
    bbox: tuple[float, float, float, float]
    caption: str = ""
    content_coords: bool = False
    float_bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True, slots=True)
class FigureTableAsset:
    """Persisted asset metadata (manifest row). ``object_ref`` is set after S3 put."""

    asset_id: str
    paper_id: str
    version: int
    type: AssetType
    ordinal: int
    source_mode: AssetSourceMode
    caption: str = ""
    section_ref: str | None = None
    object_ref: str | None = None
    page_ref: int | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True, slots=True)
class ExtractedAsset:
    """An asset ready to store: normalized image bytes + metadata (object_ref unset)."""

    meta: FigureTableAsset
    image: bytes


@dataclass(frozen=True, slots=True)
class AssetManifest:
    """Per-paper list of stored assets — the display source of truth (P8)."""

    paper_id: str
    version: int
    assets: tuple[FigureTableAsset, ...]


@dataclass(frozen=True, slots=True)
class ExtractedTable:
    """A table re-read from the PDF: its page, region, and cell text row by row.

    ``page`` is 1-based (as GROBID's coordinates are) and ``bbox`` is (x0, y0, x1, y1) in PDF
    points, top-left origin — the same frame the TEI crop specs use, so a rebuilt grid can be
    matched to the doc-model table that occupies that region.

    ``caption`` is the second way to make that match, and the only one left when GROBID's own box
    collapses to the caption strip — a region that overlaps no table at all. Empty when the reader
    could not attribute one.
    """

    page: int
    bbox: tuple[float, float, float, float]
    rows: tuple[tuple[str, ...], ...]
    caption: str = ""
