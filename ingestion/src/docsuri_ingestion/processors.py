from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from docsuri_shared.dtos import DocModel
from docsuri_shared.ids import chunk_id
from docsuri_shared.vector_spec import EMBEDDING_SPEC, IndexRecord

from .config import OPEN_ACCESS_LICENSE_ALLOWLIST, WITHDRAWAL_MARKERS
from .domain.canonical import arxiv_tier_label
from .domain.enums import SourceName
from .domain.errors import LicenseRejectedError, ValidationViolationError
from .domain.ids import year_from_paper_id
from .domain.models import (
    Chunk,
    ChunkBlockRef,
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
# A single space, not a blank line: ``split_text`` runs ``normalize_text`` over every chunk, so
# chunk text is single-line by contract and any richer separator is collapsed a step later.
# Chunk text is embedding/BM25 input only — the read path renders doc-model blocks, not this.
_BLOCK_JOIN = " "


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
        # year drives the search year-filter facet — take it from the arXiv id's YYMM prefix
        # (authoritative submission year) and fall back to the metadata date only for old-style /
        # external ids the scheme can't decode (#436). The date fallback used ``updated_at``, which
        # a bulk OAI metadata re-touch can bump to a later year, mis-bucketing ~12% of papers.
        year = year_from_paper_id(identifier.paper_id) or published.year
        return ParsedPaper(
            paper_id=identifier.paper_id,
            version=identifier.version,
            title=normalize_text(metadata.title),
            authors=tuple(normalize_text(author) for author in metadata.authors),
            abstract=normalize_text(metadata.abstract),
            categories=metadata.categories,
            updated_at=metadata.updated_at,
            year=year,
            arxiv_url=identifier.abs_url,
            full_text=text,
            license_url=metadata.license_url or "",
            withdrawal_detected=withdrawal_detected,
            source_name=SourceName.ARXIV,
            source_id=identifier.arxiv_id,
            source_tier=arxiv_tier_label(raw.source_tier),
            source_url=raw.source_url,
            source_arxiv_id=identifier.arxiv_id,
            display_arxiv_id=identifier.arxiv_id,
        )

    def validate_open_access(self, license_url: str | None) -> None:
        if not _is_allowed_license_url(license_url):
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
    # Doc-model chunking is per block, and ``max_chunk_chars`` only ever SPLITS a long block — it
    # never packs short ones, so for two months every paragraph became its own chunk whatever its
    # length. Measured over 80 indexed papers (8,455 blocks): median 372 chars, 29% under 200,
    # p10 57 — a retrieval unit too short to carry the antecedent of its own "this method".
    # Packing consecutive blocks of the SAME section up to this target moves the median to 862
    # chars and 88 -> 56 chunks per paper, the band conventional hybrid-search sizing asks for.
    # Section-bounded because a chunk carries one ``section`` label and its anchors are read per
    # section; a chunk spanning two sections breaks both. See GQ1 in
    # aidlc-docs/construction/plans/docmodel-fulltext-index-pivot-plan.md — this is the granularity
    # that plan left open, and block-dense was its named cost lever.
    chunk_pack_chars: int = 1200
    # Kept in step with IngestionSettings.max_chunks_per_paper — see the rationale there. Both
    # matter: the worker passes the setting in, but tools and tests that build a Chunker directly
    # take this default, so a single-sided change silently keeps the old cap for them.
    max_chunks_per_paper: int = 2048

    def _fill(
        self,
        chunks: list[Chunk],
        paper_id: str,
        section: str,
        text: str,
        refs: tuple[ChunkBlockRef, ...] = (),
    ) -> bool:
        """Split ``text`` and append chunks in ordinal order until the per-paper cap is reached.

        Returns True only when a part was actually DROPPED — that is the truncation signal the
        callers turn into ``ChunkSet.truncated``. A paper that fills the cap exactly, with nothing
        left over, is complete, not cut; reporting it as cut would over-count the corpus-level
        signal, and with the cap (512) close to the measured maximum (487) an exact fit is not a
        corner case. An exact fill followed by MORE text is still caught: the next section's call
        finds no room for its first part and returns True. Callers stop feeding on True.
        """
        for part in split_text(text, self.max_chunk_chars, self.overlap_chars):
            if len(chunks) >= self.max_chunks_per_paper:
                return True
            ordinal = len(chunks)
            chunks.append(
                Chunk(
                    paper_id=paper_id,
                    ordinal=ordinal,
                    section=section,
                    text=part,
                    chunk_id=chunk_id(paper_id, ordinal),
                    block_refs=refs,
                )
            )
        return False

    def _pack(
        self, entries: list[tuple[str, str, str, tuple[ChunkBlockRef, ...]]]
    ) -> list[tuple[str, str, str, tuple[ChunkBlockRef, ...]]]:
        """Merge consecutive same-section blocks up to ``chunk_pack_chars``.

        Document order is preserved and nothing is dropped: a block that does not fit starts the
        next chunk rather than being split here, so the only splitting stays in ``_fill`` against
        ``max_chunk_chars``. A single block already over the target is emitted alone — packing
        must never make a chunk longer than leaving it be would.

        The merged chunk keeps EVERY constituent block's ref, in order. That is what makes this
        safe to do at all: ``blockRefs`` is declared as "block refs covered by this chunk", so a
        packed chunk is still traceable to the exact paragraphs it came from and DF-5's block
        locator stays expressible.
        """
        packed: list[tuple[str, str, str, tuple[ChunkBlockRef, ...]]] = []
        for section_id, label, text, refs in entries:
            if packed:
                prev_id, prev_label, prev_text, prev_refs = packed[-1]
                joined = len(prev_text) + len(_BLOCK_JOIN) + len(text)
                if prev_id == section_id and joined <= self.chunk_pack_chars:
                    packed[-1] = (
                        section_id,
                        prev_label,
                        f"{prev_text}{_BLOCK_JOIN}{text}",
                        prev_refs + refs,
                    )
                    continue
            packed.append((section_id, label, text, refs))
        return packed

    def chunk(self, paper: ParsedPaper) -> ChunkSet:
        sections = [("abstract", paper.abstract), *split_sections(paper.full_text)]
        chunks: list[Chunk] = []
        truncated = False
        for section, section_text in sections:
            # No early exit on an exact fill: if the cap filled on this section's LAST part, the
            # next section's ``_fill`` is what notices — it finds no room for its first part and
            # returns True — and a paper with nothing after this section correctly stays uncut.
            if self._fill(chunks, paper.paper_id, section, section_text):
                truncated = True
                break
        if not chunks:
            raise ValidationViolationError("paper produced no chunks", stage="chunk")
        return ChunkSet(
            paper_id=paper.paper_id,
            version=paper.version,
            chunks=tuple(chunks),
            truncated=truncated,
        )

    def chunk_doc_model(self, doc: DocModel) -> ChunkSet:
        """Chunk structured doc-model blocks while preserving block id refs internally."""
        block_ids: set[tuple[str, str, str]] = set()
        # section_id rides along only so packing can tell two sections apart: the label is the
        # section TITLE, and a paper with an "Appendix"/"References" heading at two different
        # depths would otherwise have their blocks merged into one chunk across the boundary.
        entries: list[tuple[str, str, str, tuple[ChunkBlockRef, ...]]] = []
        fallback_refs: tuple[ChunkBlockRef, ...] = ()

        def walk(section) -> None:
            nonlocal fallback_refs
            section_id = getattr(section, "id", "")
            section_label = normalize_text(section.title or section.id)
            for block in section.blocks:
                b = block.root
                block_id = getattr(b, "id", "")
                block_type = getattr(b, "type", "")
                if block_id:
                    block_ids.add((section_id, block_id, block_type))
                text = _docmodel_block_text(b)
                if text:
                    refs = (
                        (
                            ChunkBlockRef(
                                section_id=section_id,
                                block_id=block_id,
                                block_type=block_type,
                            ),
                        )
                        if block_id
                        else ()
                    )
                    if refs and not fallback_refs:
                        fallback_refs = refs
                    entries.append((section_id, section_label, text, refs))
                elif block_id and not fallback_refs:
                    fallback_refs = (
                        ChunkBlockRef(
                            section_id=section_id,
                            block_id=block_id,
                            block_type=block_type,
                        ),
                    )
            for child in section.sections or []:
                walk(child)

        for section in doc.sections:
            walk(section)

        chunks: list[Chunk] = []
        truncated = False
        for _, section, text, refs in self._pack(entries):
            if self._fill(chunks, doc.meta.paperId, section or "body", text, refs):
                truncated = True
                break

        if not chunks and doc.fullText and fallback_refs:
            truncated = self._fill(
                chunks, doc.meta.paperId, "body", doc.fullText, fallback_refs
            )

        referenced = {
            (ref.section_id, ref.block_id, ref.block_type)
            for chunk in chunks
            for ref in chunk.block_refs
        }
        if not referenced.issubset(block_ids):
            raise ValidationViolationError(
                "chunk references unknown doc-model block", stage="chunk"
            )
        if not chunks:
            raise ValidationViolationError("doc-model produced no chunks", stage="chunk")
        return ChunkSet(
            paper_id=doc.meta.paperId,
            version=doc.meta.version,
            chunks=tuple(chunks),
            truncated=truncated,
        )


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
        is_abstract = normalize_text(chunk.section).lower() == "abstract"
        lexical_terms = "" if is_abstract else normalize_text(chunk.text)
        # Canonicalize the abstract chunk's section to a stable lowercase keyword so readers can
        # term-filter it (U2 lite scope restricts k-NN to ``section=abstract``). The docmodel
        # path labels it "Abstract" (heading title); body sections keep their human label.
        section = "abstract" if is_abstract else chunk.section
        return IndexRecord(
            chunkId=chunk.chunk_id,
            paperId=paper.paper_id,
            version=paper.version,
            vector=list(vector),
            section=section,
            lexicalTerms=lexical_terms,
            blockRefs=[
                {
                    "paperId": paper.paper_id,
                    "version": paper.version,
                    "sectionId": ref.section_id,
                    "blockId": ref.block_id,
                    "blockType": ref.block_type,
                }
                for ref in chunk.block_refs
            ],
            title=paper.title,
            authors=list(paper.authors),
            year=paper.year,
            arxivId=paper.card_arxiv_id,
            abstract=paper.abstract,
            abstractSnippet=snippet(paper.abstract),
            arxivUrl=paper.arxiv_url,
            categories=list(paper.categories),
            doi=paper.doi or None,
            sourceArxivId=paper.source_arxiv_id or None,
            sourceProvenance={
                "sourceName": paper.source_name.value,
                "sourceId": paper.source_id or paper.paper_id,
                "sourceTier": paper.source_tier or paper.source_name.value,
                "sourceUrl": paper.source_url or paper.arxiv_url,
                "doi": paper.doi,
                "arxivId": paper.source_arxiv_id or paper.card_arxiv_id,
            },
        )


def normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _is_allowed_license_url(license_url: str | None) -> bool:
    raw = (license_url or "").strip()
    if not raw:
        return False
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    return any(
        host == allowed_host and path.startswith(allowed_path)
        for allowed_host, allowed_path in _OPEN_ACCESS_LICENSE_RULES
    )


_OPEN_ACCESS_LICENSE_RULES = tuple(
    ((parts.hostname or "").lower(), parts.path.lower())
    for parts in (urlsplit(f"https://{allowed}") for allowed in OPEN_ACCESS_LICENSE_ALLOWLIST)
)


def _docmodel_block_text(block) -> str:
    kind = getattr(block, "type", "")
    if kind == "paragraph":
        return normalize_text(block.text)
    if kind == "formula":
        # Source LaTeX first; failing that, the approximation an OCR reader recovered from the
        # page crop (PDF path). An image-only formula with neither carries no text at all.
        latex = getattr(block, "latex", None) or getattr(block, "latexOcr", None)
        return normalize_text(latex) if latex else ""
    if kind == "table":
        lines: list[str] = []
        label = getattr(block, "anchorLabel", "") or ""
        caption = getattr(block, "caption", "") or ""
        if label or caption:
            lines.append(" ".join(v for v in (label, caption) if v))
        for row in block.rows:
            lines.append(" | ".join(cell.text for cell in row.cells))
        return normalize_text(" ".join(lines))
    if kind == "figure":
        figure_text = " ".join(v for v in (block.anchorLabel or "", block.caption or "") if v)
        return normalize_text(figure_text)
    if kind == "list":
        return normalize_text(" ".join(item.text for item in block.items))
    if kind == "code":
        return normalize_text(block.text)
    return ""


def detect_withdrawal_text(title: str, abstract: str, text: str) -> bool:
    """Withdrawal-marker scan over the raw strings — for callers that hold no MetadataRecord
    (the corpus source path builds a ParsedPaper straight from a SourcePaperRecord)."""
    haystack = f"{title} {abstract} {text}".lower()
    return any(marker in haystack for marker in WITHDRAWAL_MARKERS)


def detect_withdrawal(metadata: MetadataRecord, text: str) -> bool:
    return detect_withdrawal_text(metadata.title, metadata.abstract, text)


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


def assert_writer_embedding_role() -> None:
    if EMBEDDING_SPEC.input_type_writer != "search_document":
        raise RuntimeError("U1 writer embedding role must be search_document")
