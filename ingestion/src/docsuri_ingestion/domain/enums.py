from __future__ import annotations

from enum import StrEnum


class SourceName(StrEnum):
    ARXIV = "ARXIV"
    SEMANTIC_SCHOLAR = "SEMANTIC_SCHOLAR"
    OPENALEX = "OPENALEX"


class DedupDecision(StrEnum):
    NEW = "NEW"
    CHANGED = "CHANGED"
    DUPLICATE = "DUPLICATE"
    STALE = "STALE"


class JobKind(StrEnum):
    SEED_REBUILD = "SEED_REBUILD"
    INCREMENTAL = "INCREMENTAL"
    EVENT = "EVENT"
    # Lazy on-demand doc-model build (BR-30/D6), enqueued by a consumer (U7 viewer/summary)
    # on a cache miss. Separate from the index pipeline — produces doc-model/{id}/v{ver}.json.
    BUILD_DOC_MODEL = "BUILD_DOC_MODEL"


class FailureClass(StrEnum):
    RETRIABLE = "RETRIABLE"
    PERMANENT = "PERMANENT"


class FailureReason(StrEnum):
    FETCH_FAILURE = "FETCH_FAILURE"
    PARSE_FAILURE = "PARSE_FAILURE"
    VALIDATION_VIOLATION = "VALIDATION_VIOLATION"
    NON_OA = "NON_OA"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    BULK_INDEX_PARTIAL_FAILURE = "BULK_INDEX_PARTIAL_FAILURE"
    POISON_EVENT = "POISON_EVENT"
    # FR-17 multimodal assets — best-effort, NON-blocking (BR-27): never fail a paper.
    ASSET_EXTRACT_FAILURE = "ASSET_EXTRACT_FAILURE"
    ASSET_STORE_FAILURE = "ASSET_STORE_FAILURE"


class DedupStateKind(StrEnum):
    INDEXED = "INDEXED"
    TOMBSTONED = "TOMBSTONED"


class AssetType(StrEnum):
    """FR-17 figure/table asset kind (display-only)."""

    FIGURE = "figure"
    TABLE = "table"


class AssetSourceMode(StrEnum):
    """How an asset was obtained (BR-23 hybrid extraction)."""

    STRUCTURED = "structured"  # arXiv e-print (LaTeX) graphic, original quality
    PAGE_CROP = "page-crop"  # rendered PDF region crop (fallback)
