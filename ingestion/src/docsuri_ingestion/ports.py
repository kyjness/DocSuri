from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from docsuri_shared.dtos import DocModel, SourceTier
from docsuri_shared.events import NewArxivEvent

from .domain.assets import AssetManifest, ExtractedAsset
from .domain.enums import DedupDecision, JobKind
from .domain.models import (
    CanonicalDedupState,
    CategoryFilter,
    DedupResult,
    IndexRecordBatch,
    IndexStats,
    IngestionJob,
    MetadataRecord,
    ParsedPaper,
    RawDocument,
    Tombstone,
    Watermark,
)


@runtime_checkable
class ClockPort(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class ArxivSourcePort(Protocol):
    def harvest_seed(self, category_filter: CategoryFilter) -> Iterable[MetadataRecord]: ...

    def fetch_incremental(
        self, since: datetime, categories: Sequence[str]
    ) -> Iterable[MetadataRecord]: ...

    def fetch_metadata(self, arxiv_ref: str) -> MetadataRecord: ...

    def fetch_full_text(self, metadata: MetadataRecord) -> RawDocument: ...


@runtime_checkable
class FullTextStorePort(Protocol):
    def put_full_text(self, paper: ParsedPaper) -> str: ...


@runtime_checkable
class RawContentStorePort(Protocol):
    """B3 raw source-byte cache keyed (paperId, version, tier) — primes a full re-parse offline."""

    def put_raw(
        self, paper_id: str, version: int, tier: str, data: bytes, *, content_type: str = ...
    ) -> str: ...

    def get_raw(self, paper_id: str, version: int, tier: str) -> bytes | None: ...


@runtime_checkable
class EmbeddingPort(Protocol):
    def embed_documents(
        self, texts: Sequence[str], *, correlation_id: str | None = None
    ) -> list[list[float]]: ...


@runtime_checkable
class VectorIndexPort(Protocol):
    def bulk_upsert(self, batch: IndexRecordBatch) -> None: ...

    def tombstone_paper(self, tombstone: Tombstone) -> None: ...

    def delete_stale_chunks(self, paper_id: str, keep_chunk_ids: set[str]) -> None: ...

    def index_stats(self) -> IndexStats: ...


@runtime_checkable
class ControlPlaneStorePort(Protocol):
    def get_watermark(self, name: str = "arxiv") -> Watermark: ...

    def advance_watermark(self, name: str, candidate: datetime) -> Watermark: ...

    def reset_watermark_for_rebuild(self, name: str, value: datetime) -> Watermark: ...

    def evaluate_dedup(
        self,
        paper_id: str,
        version: int,
        fingerprint: str,
    ) -> DedupResult: ...

    def try_claim_upsert(self, paper_id: str, version: int, fingerprint: str) -> bool: ...

    def mark_ingested(self, paper_id: str, version: int, fingerprint: str) -> None: ...

    def try_claim_tombstone(self, paper_id: str, version: int) -> bool: ...

    def get_canonical_dedup_state(
        self, canonical_key: str
    ) -> CanonicalDedupState | None: ...

    def list_canonical_dedup_states_for_paper(
        self, paper_id: str
    ) -> tuple[CanonicalDedupState, ...]: ...

    def upsert_canonical_dedup_state(self, state: CanonicalDedupState) -> None: ...

    def delete_canonical_dedup_state_for_paper(self, paper_id: str) -> None: ...

    def acquire_rebuild_lock(self, owner: str) -> bool: ...

    def release_rebuild_lock(self, owner: str) -> None: ...

    def is_rebuild_active(self) -> bool: ...

    def record_job_started(self, job: IngestionJob) -> None: ...

    def record_job_finished(
        self, job_id: str, *, success: bool, detail: str | None = None
    ) -> None: ...


@runtime_checkable
class QueueMessage(Protocol):
    message_id: str
    receipt_handle: str
    body: Mapping[str, Any]


@runtime_checkable
class QueuePort(Protocol):
    def send_job(self, job: IngestionJob) -> None: ...

    def receive_messages(self, max_messages: int = 10) -> Sequence[QueueMessage]: ...

    def ack(self, message: QueueMessage) -> None: ...

    def send_to_dlq(self, payload: Mapping[str, Any], *, reason: str) -> None: ...

    def parse_new_arxiv_event(self, payload: Mapping[str, Any]) -> NewArxivEvent: ...


@runtime_checkable
class AssetSourcePort(Protocol):
    """FR-17 figure/table source bytes. Fetched lazily for NEW|CHANGED papers only."""

    def fetch_eprint(self, metadata: MetadataRecord) -> bytes | None: ...

    def fetch_pdf(self, metadata: MetadataRecord) -> bytes | None: ...


@runtime_checkable
class UserDocumentSourcePort(Protocol):
    """Uploaded user document bytes, addressed by the producer-owned S3 object key."""

    def fetch_pdf(self, object_key: str) -> bytes: ...


@runtime_checkable
class AssetStorePort(Protocol):
    """FR-17 asset persistence: binary→S3, manifest→RDS (write-order S3 then RDS, P8)."""

    def store_assets(
        self, paper_id: str, version: int, assets: Sequence[ExtractedAsset]
    ) -> AssetManifest: ...

    def remove_assets(self, paper_id: str) -> None: ...


@runtime_checkable
class DocModelSourcePort(Protocol):
    """BR-30 doc-model source: fetch deterministic-parseable HTML across the fallback ladder.

    Returns ``(html, source_tier)`` for the first rung that yields HTML (native arXiv HTML →
    ar5iv), or ``None`` when no rung produced HTML (→ source_unavailable). Q6's e-print/PDF
    rungs are an additive extension behind the same port.
    """

    def fetch_html_source(self, arxiv_id: str) -> tuple[str, SourceTier] | None: ...


@runtime_checkable
class EprintSourcePort(Protocol):
    """e-print tarball bytes for a paper version (BR-30 macro extraction).

    Structurally satisfied by ``AssetSourcePort`` — the doc-model builder uses it only to
    read the author's LaTeX preamble for KaTeX macros, best-effort and never blocking.
    """

    def fetch_eprint(self, metadata: MetadataRecord) -> bytes | None: ...


@runtime_checkable
class DocModelStorePort(Protocol):
    """BR-30 doc-model cache: lazy-built JSON keyed (paperId, version) at the doc-model/ prefix.

    ``put`` derives its key from ``doc.meta`` (paperId/version); ``remove`` drops every cached
    version for a paper (tombstone/version-change invalidation, BLM §7).
    """

    def get(self, paper_id: str, version: int) -> DocModel | None: ...

    def put(self, doc: DocModel) -> str: ...

    def remove(self, paper_id: str) -> None: ...


@runtime_checkable
class ObservabilityPort(Protocol):
    def emit_metric(
        self, name: str, value: float, tags: Mapping[str, str] | None = None
    ) -> None: ...

    def emit_log(self, entry: Mapping[str, Any]) -> None: ...

    def emit_failure_signal(self, job_id: str, *, stage: str, error: str) -> None: ...


def dedup_decision_applies_to_index(decision: DedupDecision) -> bool:
    return decision in {DedupDecision.NEW, DedupDecision.CHANGED}


def job_can_run_during_rebuild(kind: JobKind) -> bool:
    return kind is JobKind.SEED_REBUILD
