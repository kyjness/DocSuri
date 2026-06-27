from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from docsuri_shared.vector_spec import DIMENSIONS, IndexRecord

from .enums import DedupDecision, DedupStateKind, JobKind, SourceName
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
    doi: str = ""
    source_arxiv_id: str = ""
    source_name: SourceName = SourceName.ARXIV
    source_id: str = ""
    source_tier: str = ""
    source_url: str = ""
    display_arxiv_id: str = ""

    @property
    def arxiv_id(self) -> str:
        return f"{self.paper_id}v{self.version}"

    @property
    def card_arxiv_id(self) -> str:
        if self.display_arxiv_id:
            return self.display_arxiv_id
        if self.source_arxiv_id:
            return self.source_arxiv_id
        return "" if self.paper_id.startswith("src-") else self.arxiv_id

    @property
    def fingerprint(self) -> str:
        try:
            return content_fingerprint(self.paper_id, self.version)
        except ValueError:
            payload = f"{self.paper_id}:v{self.version}".encode()
            return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ChunkBlockRef:
    section_id: str
    block_id: str
    block_type: str


@dataclass(frozen=True, slots=True)
class Chunk:
    paper_id: str
    ordinal: int
    section: str
    text: str
    chunk_id: str
    block_refs: tuple[ChunkBlockRef, ...] = ()


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
    source_name: SourceName | None = None
    failure_stage: str | None = None
    canonical_key: str | None = None
    paper_id: str | None = None
    version: int | None = None
    source_record: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "jobId": self.job_id,
            "kind": self.kind.value,
            "arxivRef": self.arxiv_ref,
            "eventId": self.event_id,
            "correlationId": self.correlation_id,
        }
        optional = {
            "sourceName": self.source_name.value if self.source_name else None,
            "failureStage": self.failure_stage,
            "canonicalKey": self.canonical_key,
            "paperId": self.paper_id,
            "version": self.version,
            "sourceRecord": self.source_record,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})
        return payload


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
class CanonicalDedupState:
    canonical_key: str
    paper_id: str
    winning_source_tier: str
    winning_version: int
    fingerprint: str
    seen_sources: tuple[SourceName, ...] = ()


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
