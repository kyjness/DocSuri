from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from docsuri_shared.ids import chunk_id
from docsuri_shared.vector_spec import EMBEDDING_SPEC, IndexRecord

from .config import OPEN_ACCESS_LICENSE_ALLOWLIST, WITHDRAWAL_MARKERS
from .domain.enums import DedupDecision
from .domain.errors import LicenseRejectedError, ValidationViolationError
from .domain.models import (
    Chunk,
    ChunkSet,
    DedupResult,
    EmbeddingBatch,
    IndexRecordBatch,
    MetadataRecord,
    ParsedPaper,
    RawDocument,
)
from .ports import ControlPlaneStorePort

_HEADING_RE = re.compile(r"^(?P<title>[A-Z][A-Za-z0-9 ,.()/_:-]{2,80})$", re.MULTILINE)
_WHITESPACE_RE = re.compile(r"\s+")


class FetchParseProcessor:
    """Validate source metadata/full text and convert it to a ParsedPaper."""

    def parse(self, raw: RawDocument) -> ParsedPaper:
        metadata = raw.metadata
        self.validate_open_access(metadata.license_url)
        self._validate_metadata(metadata)

        text = normalize_text(raw.text)
        if not text:
            raise ValidationViolationError("full text is empty", stage="parse")

        withdrawal_detected = detect_withdrawal(metadata, text)
        published = metadata.published_at or metadata.updated_at
        identifier = metadata.identifier
        return ParsedPaper(
            paper_id=identifier.paper_id,
            version=identifier.version,
            title=normalize_text(metadata.title),
            authors=tuple(normalize_text(author) for author in metadata.authors),
            abstract=normalize_text(metadata.abstract),
            categories=metadata.categories,
            updated_at=metadata.updated_at,
            year=published.year,
            arxiv_url=identifier.abs_url,
            full_text=text,
            license_url=metadata.license_url or "",
            withdrawal_detected=withdrawal_detected,
        )

    def validate_open_access(self, license_url: str | None) -> None:
        normalized = (license_url or "").strip().lower()
        if not normalized:
            raise LicenseRejectedError(license_url)
        if not any(allowed in normalized for allowed in OPEN_ACCESS_LICENSE_ALLOWLIST):
            raise LicenseRejectedError(license_url)

    def _validate_metadata(self, metadata: MetadataRecord) -> None:
        if not metadata.title.strip():
            raise ValidationViolationError("title is required")
        if not metadata.authors:
            raise ValidationViolationError("at least one author is required")
        if not metadata.abstract.strip():
            raise ValidationViolationError("abstract is required")
        if not metadata.categories:
            raise ValidationViolationError("at least one category is required")


@dataclass(frozen=True, slots=True)
class Chunker:
    """Full-text body chunking — abstract chunk + section-split body chunks (full-body search).

    Reverses the issue-#120 abstract-only rescoping now that body semantic search is in scope.
    """

    max_chunk_chars: int = 2400
    overlap_chars: int = 240
    max_chunks_per_paper: int = 128

    def chunk(self, paper: ParsedPaper) -> ChunkSet:
        sections = [("abstract", paper.abstract), *split_sections(paper.full_text)]
        chunks: list[Chunk] = []
        for section, section_text in sections:
            for text in split_text(section_text, self.max_chunk_chars, self.overlap_chars):
                if len(chunks) >= self.max_chunks_per_paper:
                    break
                ordinal = len(chunks)
                chunks.append(
                    Chunk(
                        paper_id=paper.paper_id,
                        ordinal=ordinal,
                        section=section,
                        text=text,
                        chunk_id=chunk_id(paper.paper_id, ordinal),
                    )
                )
            if len(chunks) >= self.max_chunks_per_paper:
                break
        if not chunks:
            raise ValidationViolationError("paper produced no chunks", stage="chunk")
        return ChunkSet(paper_id=paper.paper_id, version=paper.version, chunks=tuple(chunks))


class DeduplicationGuard:
    def __init__(self, store: ControlPlaneStorePort) -> None:
        self._store = store

    def evaluate(self, paper: ParsedPaper) -> DedupResult:
        return self._store.evaluate_dedup(paper.paper_id, paper.version, paper.fingerprint)

    def begin_upsert(self, paper: ParsedPaper) -> bool:
        return self._store.try_claim_upsert(paper.paper_id, paper.version, paper.fingerprint)

    def mark_ingested(self, paper: ParsedPaper) -> None:
        self._store.mark_ingested(paper.paper_id, paper.version, paper.fingerprint)

    def begin_tombstone(self, paper: ParsedPaper) -> bool:
        return self._store.try_claim_tombstone(paper.paper_id, paper.version)


class IndexRecordAssembler:
    def assemble(
        self,
        paper: ParsedPaper,
        chunk_set: ChunkSet,
        embedding_batch: EmbeddingBatch,
    ) -> IndexRecordBatch:
        if tuple(chunk.chunk_id for chunk in chunk_set.chunks) != embedding_batch.chunk_ids:
            raise ValidationViolationError(
                "embedding order does not match chunks", stage="assemble"
            )
        records = tuple(
            self._record_from_chunk(paper, chunk, vector)
            for chunk, vector in zip(chunk_set.chunks, embedding_batch.vectors, strict=True)
        )
        return IndexRecordBatch(paper_id=paper.paper_id, version=paper.version, records=records)

    def _record_from_chunk(
        self,
        paper: ParsedPaper,
        chunk: Chunk,
        vector: Sequence[float],
    ) -> IndexRecord:
        lexical_terms = normalize_text(f"{paper.title} {paper.abstract} {chunk.text}")
        return IndexRecord(
            chunkId=chunk.chunk_id,
            paperId=paper.paper_id,
            version=paper.version,
            vector=list(vector),
            section=chunk.section,
            lexicalTerms=lexical_terms,
            title=paper.title,
            authors=list(paper.authors),
            year=paper.year,
            arxivId=paper.arxiv_id,
            abstract=paper.abstract,
            abstractSnippet=snippet(paper.abstract),
            arxivUrl=paper.arxiv_url,
            categories=list(paper.categories),
        )


def normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def detect_withdrawal(metadata: MetadataRecord, text: str) -> bool:
    haystack = f"{metadata.title} {metadata.abstract} {text}".lower()
    return any(marker in haystack for marker in WITHDRAWAL_MARKERS)


def split_sections(text: str) -> list[tuple[str, str]]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("body", normalized)]

    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = normalize_text(match.group("title")).lower()
        section_text = normalize_text(text[start:end])
        if section_text:
            sections.append((title, section_text))
    return sections or [("body", normalized)]


def split_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than max_chars")
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    cursor = 0
    while cursor < len(normalized):
        end = min(cursor + max_chars, len(normalized))
        if end < len(normalized):
            split_at = normalized.rfind(" ", cursor, end)
            if split_at > cursor + max_chars // 2:
                end = split_at
        chunk = normalized[cursor:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(normalized):
            break
        cursor = max(0, end - overlap_chars)
    return chunks


def snippet(abstract: str, max_chars: int = 280) -> str:
    clean = normalize_text(abstract)
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "..."


def decision_from_state(result: DedupResult) -> DedupDecision:
    return result.decision


def assert_writer_embedding_role() -> None:
    if EMBEDDING_SPEC.input_type_writer != "search_document":
        raise RuntimeError("U1 writer embedding role must be search_document")
