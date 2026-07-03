"""Capability ports U7 depends on by injection (logical-components.md §2).

Dependency-isolation exceptions (RES-9 / NFR-R2 / Q1):
- ``LlmUnavailable`` — Bedrock generation failed/timed out → orchestrator abstains
  (after one retry) rather than emit ungrounded text (fail-closed, INV-4).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from docsuri_shared.dtos import DocModel

from ..domain.models import (
    Glossary,
    RefinedSource,
    StoredAsset,
    SummaryCacheKey,
    SummaryDraft,
    SummaryRequest,
    TermMapping,
    TranslationSegment,
    TranslationSegmentsResult,
)

__all__ = [
    "LlmUnavailable",
    "LlmGatewayPort",
    "SummaryStorePort",
    "FullTextSourcePort",
    "DocModelReadPort",
    "DocModelBuildQueuePort",
    "SummaryJobQueuePort",
    "GlossaryRepositoryPort",
    "AssetReadPort",
]


class LlmUnavailable(Exception):
    """LLM generation dependency (Bedrock) failed — abstain after one retry (Q1/BR-S7)."""


@runtime_checkable
class LlmGatewayPort(Protocol):
    """Summary/translation generation via the LLM gateway (Bedrock, U6-gateway-fronted).

    Implementations buffer the model stream and return a complete draft so the U7
    grounding gate can validate the whole structured output before exposure (Q5/BR-S8).
    """

    def summarize(
        self, refined: RefinedSource, request: SummaryRequest, glossary: Glossary
    ) -> SummaryDraft:
        """Generate a structured summary (§3). Raises ``LlmUnavailable`` on failure."""
        ...

    def translate_segments(
        self,
        segments: Sequence[TranslationSegment],
        request: SummaryRequest,
        glossary: Glossary,
    ) -> TranslationSegmentsResult:
        """Translate a batch of doc-model text segments to Korean, returning ``id → 번역텍스트``
        (BR-S18 — structured translation). Verbatim content (table numeric cells, formula LaTeX,
        code) is never sent here. Raises ``LlmUnavailable`` on failure."""
        ...


@runtime_checkable
class SummaryStorePort(Protocol):
    """Two-tier store: read-through (Redis hot → S3 permanent), write-through (§11 / BR-S1)."""

    def get(self, key: SummaryCacheKey) -> dict | None:
        """Return the cached payload (``SummaryResultDTO.to_dict``) or None on miss."""
        ...

    def put(self, key: SummaryCacheKey, payload: dict) -> None:
        """Write-through: S3 permanent + Redis hot (immutable key, INV-5)."""
        ...


@runtime_checkable
class FullTextSourcePort(Protocol):
    """U1 full-text read capability (S3 ``stored_full_text_ref``). Read-only."""

    def get_full_text(self, paper_id: str, version: int) -> str | None:
        """Return the stored full text, or None when absent / license-disallowed (Q1)."""
        ...


@runtime_checkable
class DocModelReadPort(Protocol):
    """U1 doc-model read capability (S3 ``doc-model/{paperId}/v{version}.json``). Read-only.

    U7 reads the lazily-built, cached structured doc-model (BR-30); building/caching is U1's
    role (the read side never builds). The returned ``DocModel`` is url-free (SEC-9) — figure
    signed URLs come from the parallel ``/assets`` manifest, joined by ``assetId`` on the client.
    """

    def get_doc_model(self, paper_id: str, version: int) -> DocModel | None:
        """Return the cached doc-model, or None when absent / not yet built / license-disallowed."""
        ...


@runtime_checkable
class DocModelBuildQueuePort(Protocol):
    """Trigger U1's lazy doc-model build (BR-30/D6) on a read miss. The read side only enqueues
    a ``BUILD_DOC_MODEL`` job onto U1's queue — it never imports/runs the builder (boundary B:
    consumer enqueues, ingestion worker produces). Idempotent at the producer (a cache hit
    short-circuits the build), so a duplicate enqueue is cheap.

    DEPRECATED (D6, Q5) — legacy backfill path only. The target is eager doc-model build at
    ingestion time, which degrades to flat-text on failure (never None), so "index ⊆ doc-model"
    holds and a read miss should not occur for newly-ingested papers. This lazy trigger is kept
    transitionally to backfill papers ingested before eager build shipped, and is slated for
    removal once the corpus is backfilled. Do not build new dependencies on it."""

    def enqueue_build(self, paper_id: str, version: int) -> None:
        """Best-effort enqueue of a doc-model build for ``(paper_id, version)``. MUST NOT raise
        on the read path — a failed enqueue degrades to ``source_unavailable``, not a 500."""
        ...


@runtime_checkable
class SummaryJobQueuePort(Protocol):
    """Enqueue a long-input summary as a background job (BR-S6/BR-S8). On the MAP_REDUCE band the
    API path enqueues and returns ``pending`` instead of running 3-5 LLM calls inline (a request
    that would blow the gateway timeout). A summarization worker consumes the job, runs the
    map-reduce summary inline, and write-throughs the result to the store — so the client's poll
    hits the cache. MUST NOT raise on the request path (a failed enqueue degrades, not 500s)."""

    def enqueue(self, request: SummaryRequest, user_id: str) -> None:
        """Best-effort enqueue of a summary job for ``request`` on behalf of ``user_id``."""
        ...


@runtime_checkable
class AssetReadPort(Protocol):
    """FR-17 read side: list a paper's figure/table manifest (paper_asset, RDS, read-only —
    U1 is the single writer) and presign its S3 object refs (BR-S15). Read capability only."""

    def list_assets(self, paper_id: str, version: int) -> Sequence[StoredAsset]:
        """Return stored asset metadata in display order (ordinal). Empty when none."""
        ...

    def presign(self, object_ref: str) -> str | None:
        """Return a short-lived signed GET URL for an S3 object ref, or ``None`` for a
        non-S3 ref so the caller skips it — the raw object_ref is never exposed (SEC-9)."""
        ...


@runtime_checkable
class GlossaryRepositoryPort(Protocol):
    """Personal glossary (P2) persistence — owner-scoped (SEC-8). RDS-backed."""

    def get_user_glossary(self, user_id: str) -> Sequence[TermMapping]:
        """Return the user's term overrides (owner-scoped)."""
        ...

    def upsert_term(
        self, user_id: str, term_from: str, term_to: str, *, prompt_enforced: bool
    ) -> int:
        """Add/override a personal term (owner-scoped); return the bumped ``glossary_ver``."""
        ...
