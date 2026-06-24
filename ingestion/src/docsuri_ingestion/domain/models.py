from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from docsuri_shared.vector_spec import DIMENSIONS, IndexRecord

from .enums import DedupDecision, DedupStateKind, JobKind
from .ids import ArxivIdentifier, content_fingerprint, normalize_arxiv_ref


@dataclass(frozen=True, slots=True)
class CategoryFilter:
    categories: tuple[str, ...]
    updated_after: datetime
    updated_before: datetime

    def __post_init__(self) -> None:
        if not self.categories:
            raise ValueError("at least one category is required")
        if self.updated_after >= self.updated_before:
            raise ValueError("updated_after must be before updated_before")


@dataclass(frozen=True, slots=True)
class MetadataRecord:
    arxiv_ref: str
    title: str
    authors: tuple[str, ...]
    abstract: str
    categories: tuple[str, ...]
    updated_at: datetime
    published_at: datetime | None = None
    license_url: str | None = None
    primary_category: str | None = None

    @property
    def identifier(self) -> ArxivIdentifier:
        return normalize_arxiv_ref(self.arxiv_ref)

    @property
    def paper_id(self) -> str:
        return self.identifier.paper_id

    @property
    def version(self) -> int:
        return self.identifier.version


@dataclass(frozen=True, slots=True)
class RawDocument:
    metadata: MetadataRecord
    text: str  # normalized plain text (BR-29: from HTML-preferred source, PDF fallback)
    source_url: str
    content_type: str = "text/plain"


@dataclass(frozen=True, slots=True)
class ParsedPaper:
    paper_id: str
    version: int
    title: str
    authors: tuple[str, ...]
    abstract: str
    categories: tuple[str, ...]
    updated_at: datetime
    year: int
    arxiv_url: str
    full_text: str  # normalized plain text (BR-29)
    license_url: str
    withdrawal_detected: bool = False
    stored_full_text_ref: str | None = None

    @property
    def arxiv_id(self) -> str:
        return f"{self.paper_id}v{self.version}"

    @property
    def fingerprint(self) -> str:
        return content_fingerprint(self.paper_id, self.version)


@dataclass(frozen=True, slots=True)
class Chunk:
    paper_id: str
    ordinal: int
    section: str
    text: str
    chunk_id: str


@dataclass(frozen=True, slots=True)
class ChunkSet:
    paper_id: str
    version: int
    chunks: tuple[Chunk, ...]

    def __post_init__(self) -> None:
        if not self.chunks:
            raise ValueError("chunk set must not be empty")
        ordinals = [chunk.ordinal for chunk in self.chunks]
        if ordinals != list(range(len(self.chunks))):
            raise ValueError("chunk ordinals must be contiguous from zero")


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    chunk_ids: tuple[str, ...]
    vectors: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if len(self.chunk_ids) != len(self.vectors):
            raise ValueError("embedding count must match chunk ids")
        for vector in self.vectors:
            if len(vector) != DIMENSIONS:
                raise ValueError(f"embedding vector must be {DIMENSIONS} dimensions")


@dataclass(frozen=True, slots=True)
class IndexRecordBatch:
    paper_id: str
    version: int
    records: tuple[IndexRecord, ...]

    def __post_init__(self) -> None:
        if not self.records:
            raise ValueError("index record batch must not be empty")
        for record in self.records:
            if record.paperId != self.paper_id or record.version != self.version:
                raise ValueError("index record batch contains mismatched paper/version")


@dataclass(frozen=True, slots=True)
class IngestionJob:
    job_id: str
    kind: JobKind
    arxiv_ref: str | None = None
    category_filter: CategoryFilter | None = None
    event_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class Watermark:
    name: str
    updated_at: datetime

    def advance(self, candidate: datetime) -> Watermark:
        return Watermark(name=self.name, updated_at=max(self.updated_at, candidate))

    @classmethod
    def epoch(cls, name: str = "arxiv") -> Watermark:
        return cls(name=name, updated_at=datetime(1970, 1, 1, tzinfo=UTC))


@dataclass(frozen=True, slots=True)
class DedupState:
    paper_id: str
    current_version: int
    fingerprint: str | None
    state: DedupStateKind
    ingested_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DedupResult:
    decision: DedupDecision
    current_state: DedupState | None = None


@dataclass(frozen=True, slots=True)
class Tombstone:
    paper_id: str
    version: int
    reason: str = "WITHDRAWN"
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class IndexStats:
    status: str
    timestamp: datetime
    index_name: str
    total_documents: int
    vector_count: int
    last_write_timestamp: datetime | None
    dependencies: dict[str, str]

    def to_public_internal_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "index_name": self.index_name,
            "metrics": {
                "total_documents": self.total_documents,
                "vector_count": self.vector_count,
                "last_write_timestamp": (
                    self.last_write_timestamp.isoformat()
                    if self.last_write_timestamp is not None
                    else None
                ),
            },
            "dependencies": dict(self.dependencies),
        }
