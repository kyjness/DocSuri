from __future__ import annotations

import string
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from docsuri_shared.dtos import DocModel
from docsuri_shared.vector_spec import DIMENSIONS
from hypothesis import given, settings
from hypothesis import strategies as st

from docsuri_ingestion.adapters.local import InMemoryControlPlaneStore, sample_metadata
from docsuri_ingestion.domain.enums import DedupDecision, DedupStateKind, SourceName
from docsuri_ingestion.domain.errors import LicenseRejectedError
from docsuri_ingestion.domain.ids import content_fingerprint, normalize_arxiv_ref
from docsuri_ingestion.domain.models import (
    Chunk,
    ChunkSet,
    EmbeddingBatch,
    ParsedPaper,
    RawDocument,
    Watermark,
)
from docsuri_ingestion.processors import (
    Chunker,
    FetchParseProcessor,
    IndexRecordAssembler,
    detect_withdrawal,
)

_HOST_LABEL = st.text(
    alphabet=string.ascii_lowercase + string.digits,
    min_size=1,
    max_size=20,
)


def test_arxiv_id_normalization_and_version_parsing() -> None:
    parsed = normalize_arxiv_ref("https://arxiv.org/pdf/2401.12345v7.pdf")
    assert parsed.paper_id == "2401.12345"
    assert parsed.version == 7
    assert parsed.arxiv_id == "2401.12345v7"


def test_content_fingerprint_is_paper_version_derived() -> None:
    assert content_fingerprint("2401.00001", 1) == content_fingerprint("2401.00001", 1)
    assert content_fingerprint("2401.00001", 1) != content_fingerprint("2401.00001", 2)


def test_oa_license_validation_rejects_missing_and_unknown_allows_arxiv_and_cc() -> None:
    processor = FetchParseProcessor()
    # Missing/empty and unknown (non-allowlisted) licenses are still rejected.
    with pytest.raises(LicenseRejectedError):
        processor.validate_open_access(None)
    with pytest.raises(LicenseRejectedError):
        processor.validate_open_access("https://example.com/proprietary-eula")
    with pytest.raises(LicenseRejectedError):
        processor.validate_open_access(
            "https://example.com/?next=https://creativecommons.org/licenses/by/4.0/"
        )
    # Relaxed beyond CC: arXiv's default non-exclusive distribution license now passes.
    processor.validate_open_access("http://arxiv.org/licenses/nonexclusive-distrib/1.0/")
    processor.validate_open_access("https://creativecommons.org/licenses/by/4.0/")


@settings(max_examples=50)
@given(label=_HOST_LABEL)
def test_oa_license_validation_rejects_cc_substring_spoofs(label: str) -> None:
    processor = FetchParseProcessor()
    spoofed_host = f"{label}.creativecommons.org.evil.test"

    with pytest.raises(LicenseRejectedError):
        processor.validate_open_access(f"https://{spoofed_host}/licenses/by/4.0/")
    with pytest.raises(LicenseRejectedError):
        processor.validate_open_access(
            f"https://evil.test/?next=https://creativecommons.org/licenses/by/4.0/{label}"
        )


def test_withdrawal_detection_uses_metadata_and_full_text() -> None:
    metadata = sample_metadata()
    assert detect_withdrawal(metadata, "This paper has been withdrawn by the authors.")


def test_chunker_produces_abstract_plus_body_chunks() -> None:
    processor = FetchParseProcessor()
    metadata = sample_metadata()
    raw = RawDocument(
        metadata=metadata,
        text="INTRODUCTION\n" + "alpha " * 1000 + "\nMETHOD\n" + "beta " * 1000,
        source_url="local://paper",
    )
    paper = processor.parse(raw)
    chunker = Chunker()
    first = chunker.chunk(paper)
    second = chunker.chunk(paper)
    assert first == second  # deterministic
    # full-body chunking: many chunks per paper, not a single abstract chunk
    assert len(first.chunks) > 1
    assert first.chunks[0].section == "abstract"
    assert first.chunks[0].ordinal == 0
    # ordinals are dense 0..N-1
    assert [c.ordinal for c in first.chunks] == list(range(len(first.chunks)))
    # body chunks exist beyond the abstract
    assert {c.section for c in first.chunks} > {"abstract"}


def test_docmodel_chunker_uses_docmodel_blocks_only() -> None:
    doc = DocModel.model_validate(
        {
            "meta": {
                "paperId": "2401.00001",
                "version": 1,
                "title": "T",
                "provenance": {
                    "sourceTier": "native_html",
                    "parserVersion": "test",
                    "schemaVersion": "1",
                    "generatedAt": "1970-01-01T00:00:00Z",
                },
            },
            "fullText": "Body",
            "sections": [
                {
                    "id": "s1",
                    "title": "Body",
                    "blocks": [{"id": "s1.p1", "type": "paragraph", "text": "Body"}],
                }
            ],
        }
    )

    chunks = Chunker(
        max_chunk_chars=10,
        overlap_chars=0,
        max_chunks_per_paper=2,
    ).chunk_doc_model(doc)

    assert len(chunks.chunks) == 1
    assert chunks.chunks[0].section == "Body"
    assert chunks.chunks[0].block_refs[0].block_id == "s1.p1"


def test_docmodel_chunker_falls_back_to_full_text_for_textless_blocks() -> None:
    doc = DocModel.model_validate(
        {
            "meta": {
                "paperId": "2401.00001",
                "version": 1,
                "title": "T",
                "provenance": {
                    "sourceTier": "native_html",
                    "parserVersion": "test",
                    "schemaVersion": "1",
                    "generatedAt": "1970-01-01T00:00:00Z",
                },
            },
            "fullText": "Results",
            "sections": [
                {
                    "id": "s1",
                    "title": "Results",
                    "blocks": [{"id": "s1.tbl1", "type": "table", "rows": []}],
                }
            ],
        }
    )

    chunks = Chunker().chunk_doc_model(doc)

    assert chunks.chunks[0].text == "Results"
    assert chunks.chunks[0].block_refs[0].block_id == "s1.tbl1"


def test_index_record_lexical_terms_are_body_chunk_only() -> None:
    metadata = replace(
        sample_metadata(),
        title="Unique Title Only",
        abstract="Unique Abstract Only",
    )
    paper = FetchParseProcessor().parse(
        RawDocument(
            metadata=metadata,
            text="INTRODUCTION\nBody chunk only terms",
            source_url="local://paper",
        )
    )
    chunks = Chunker(max_chunk_chars=200, overlap_chars=0).chunk(paper)
    embedding_batch = EmbeddingBatch(
        chunk_ids=tuple(chunk.chunk_id for chunk in chunks.chunks),
        vectors=tuple(tuple([0.0] * DIMENSIONS) for _ in chunks.chunks),
    )

    records = IndexRecordAssembler().assemble(paper, chunks, embedding_batch).records
    abstract_record = next(record for record in records if record.section == "abstract")
    body_record = next(
        record for record in records if record.lexicalTerms == "INTRODUCTION Body chunk only terms"
    )

    assert abstract_record.lexicalTerms == ""
    assert abstract_record.abstract == "Unique Abstract Only"
    assert "Unique Title Only" not in body_record.lexicalTerms
    assert "Unique Abstract Only" not in body_record.lexicalTerms


def test_docmodel_abstract_chunk_has_empty_lexical_terms() -> None:
    metadata = replace(
        sample_metadata(),
        title="DocModel Title",
        abstract="DocModel Abstract Only",
    )
    paper = FetchParseProcessor().parse(
        RawDocument(
            metadata=metadata,
            text="INTRODUCTION\nDocModel body only terms",
            source_url="local://paper",
        )
    )
    doc = DocModel.model_validate(
        {
            "meta": {
                "paperId": paper.paper_id,
                "version": paper.version,
                "title": paper.title,
                "abstract": paper.abstract,
                "provenance": {
                    "sourceTier": "native_html",
                    "parserVersion": "test",
                    "schemaVersion": "1",
                    "generatedAt": "1970-01-01T00:00:00Z",
                },
            },
            "fullText": "Abstract\n\nDocModel Abstract Only\n\nBody\n\nDocModel body only terms",
            "sections": [
                {
                    "id": "s0",
                    "title": "Abstract",
                    "blocks": [
                        {"id": "s0.p1", "type": "paragraph", "text": "DocModel Abstract Only"}
                    ],
                },
                {
                    "id": "s1",
                    "title": "Body",
                    "blocks": [
                        {"id": "s1.p1", "type": "paragraph", "text": "DocModel body only terms"}
                    ],
                },
            ],
        }
    )
    chunks = Chunker(max_chunk_chars=200, overlap_chars=0).chunk_doc_model(doc)
    embedding_batch = EmbeddingBatch(
        chunk_ids=tuple(chunk.chunk_id for chunk in chunks.chunks),
        vectors=tuple(tuple([0.0] * DIMENSIONS) for _ in chunks.chunks),
    )

    records = IndexRecordAssembler().assemble(paper, chunks, embedding_batch).records
    abstract_record = next(record for record in records if record.section == "abstract")
    body_record = next(record for record in records if record.section == "Body")

    assert abstract_record.lexicalTerms == ""
    assert abstract_record.abstract == "DocModel Abstract Only"
    assert body_record.lexicalTerms == "DocModel body only terms"


def test_index_record_preserves_source_provenance_and_external_arxiv_alias() -> None:
    paper = ParsedPaper(
        paper_id="src-abc",
        version=1,
        title="External Paper",
        authors=("Ada Lovelace",),
        abstract="External abstract",
        categories=("cs.LG",),
        updated_at=datetime(2025, 1, 1, tzinfo=UTC),
        year=2025,
        arxiv_url="https://example.test/paper",
        full_text="External body",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        doi="10.1000/external",
        source_arxiv_id="2501.00001v2",
        source_name=SourceName.OPENALEX,
        source_id="oa-1",
        source_tier="OPENALEX_GROBID",
        source_url="https://example.test/paper.pdf",
        display_arxiv_id="2501.00001v2",
    )
    chunks = ChunkSet(
        paper_id=paper.paper_id,
        version=paper.version,
        chunks=(
            Chunk(
                paper_id=paper.paper_id,
                ordinal=0,
                section="body",
                text="External body",
                chunk_id="src-abc:0000",
            ),
        ),
    )
    embedding_batch = EmbeddingBatch(
        chunk_ids=("src-abc:0000",),
        vectors=(tuple([0.0] * DIMENSIONS),),
    )

    record = IndexRecordAssembler().assemble(paper, chunks, embedding_batch).records[0]

    assert record.arxivId == "2501.00001v2"
    assert record.doi == "10.1000/external"
    assert record.sourceArxivId == "2501.00001v2"
    assert record.sourceProvenance is not None
    assert record.sourceProvenance.sourceName == "OPENALEX"
    assert record.sourceProvenance.sourceId == "oa-1"
    assert record.sourceProvenance.sourceTier == "OPENALEX_GROBID"
    assert record.sourceProvenance.sourceUrl == "https://example.test/paper.pdf"


def test_dedup_guard_decisions_and_mark_ingested() -> None:
    store = InMemoryControlPlaneStore()
    metadata = sample_metadata()
    processor = FetchParseProcessor()
    paper = processor.parse(RawDocument(metadata=metadata, text="body", source_url="local://paper"))
    assert (
        store.evaluate_dedup(paper.paper_id, paper.version, paper.fingerprint).decision
        is DedupDecision.NEW
    )
    assert store.try_claim_upsert(paper.paper_id, paper.version, paper.fingerprint)
    store.mark_ingested(paper.paper_id, paper.version, paper.fingerprint)
    assert (
        store.evaluate_dedup(paper.paper_id, paper.version, paper.fingerprint).decision
        is DedupDecision.DUPLICATE
    )


def test_watermark_max_clamp() -> None:
    watermark = Watermark(name="arxiv", updated_at=datetime(2024, 1, 10, tzinfo=UTC))
    older = watermark.advance(datetime(2024, 1, 1, tzinfo=UTC))
    newer = watermark.advance(datetime(2024, 1, 20, tzinfo=UTC))
    assert older.updated_at == watermark.updated_at
    assert newer.updated_at == datetime(2024, 1, 20, tzinfo=UTC)


def test_tombstone_strictly_newer_version_wins() -> None:
    store = InMemoryControlPlaneStore()
    assert store.try_claim_tombstone("2401.00001", 2)
    assert store._dedup["2401.00001"].state is DedupStateKind.TOMBSTONED
    assert store.try_claim_upsert("2401.00001", 3, "fingerprint-v3")
    store.mark_ingested("2401.00001", 3, "fingerprint-v3")
    assert not store.try_claim_tombstone("2401.00001", 2)
    state = store._dedup["2401.00001"]
    assert state.current_version == 3
    assert state.state is DedupStateKind.INDEXED
