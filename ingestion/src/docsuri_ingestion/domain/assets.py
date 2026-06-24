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
class RawAssetCandidate:
    """Transient extractor output before ordering/normalization.

    ``image`` holds the (already normalized) WebP bytes. ``page``/``y``/``x`` drive the
    deterministic (page, y, x) ordering that assigns per-type ordinals (P7).
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
