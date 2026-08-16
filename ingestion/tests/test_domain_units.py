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
from docsuri_ingestion.domain.ids import (
    content_fingerprint,
    normalize_arxiv_ref,
    year_from_paper_id,
)
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
    normalize_text,
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


def test_year_from_paper_id_decodes_yymm_and_falls_back_to_none() -> None:
    # #436: new-style YYMM.NNNNN → 20YY (authoritative submission year).
    assert year_from_paper_id("2506.09280") == 2025
    assert year_from_paper_id("2401.12345") == 2024
    # Old-style and non-arXiv (external) ids are undecodable → None (caller keeps the date year).
    assert year_from_paper_id("math/0309136") is None
    assert year_from_paper_id("src-abc123") is None


def test_parse_year_uses_arxiv_id_not_retouched_date() -> None:
    # #436 facet-leak repro: a 2025 submission (id 2506.*) whose only date is a re-touched 2026
    # ``updated_at`` (published_at absent). Old code stamped year=2026; the id says 2025.
    metadata = replace(
        sample_metadata("2506.09280v1"),
        published_at=None,
        updated_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    paper = FetchParseProcessor().parse(
        RawDocument(metadata=metadata, text="body", source_url="local://paper")
    )
    assert paper.year == 2025


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


def test_reaching_the_chunk_cap_is_reported_on_the_chunk_set() -> None:
    """The cap cuts a paper's body short, and it used to do so in silence.

    At 128 it removed a median 9.7% — up to 64.6% — of the body from 217 of 827 indexed papers
    and nothing said so; the papers it hit were the surveys with the most paragraphs, which is
    what the foundational list exists to include. The cap is 512 now against a measured sample
    maximum of 487 blocks, so the next paper to cross it is not far off. ``truncated`` is what
    lets the pipeline count it.
    """
    processor = FetchParseProcessor()
    raw = RawDocument(
        metadata=sample_metadata(),
        text="INTRODUCTION\n" + "alpha " * 4000,
        source_url="local://paper",
    )
    paper = processor.parse(raw)

    cut = Chunker(max_chunk_chars=200, overlap_chars=0, max_chunks_per_paper=3).chunk(paper)
    whole = Chunker(max_chunk_chars=200, overlap_chars=0).chunk(paper)

    assert cut.truncated is True
    assert len(cut.chunks) == 3
    assert whole.truncated is False
    assert len(whole.chunks) > 3


def test_a_paper_that_fills_the_cap_exactly_is_not_reported_as_cut() -> None:
    """The cap is a ceiling, not a tripwire. A body that produces exactly ``max_chunks_per_paper``
    chunks with nothing left over is complete — reporting it as cut over-counts the corpus-level
    signal, and with the cap (512) close to the measured maximum (487) an exact fit is realistic.
    """
    whole = Chunker(max_chunk_chars=200, overlap_chars=0).chunk(_paper_of("alpha " * 4000))
    exact = len(whole.chunks)

    fitted = Chunker(
        max_chunk_chars=200, overlap_chars=0, max_chunks_per_paper=exact
    ).chunk(_paper_of("alpha " * 4000))

    assert len(fitted.chunks) == exact
    assert fitted.truncated is False


def test_an_exact_fill_with_a_later_section_still_counts_as_cut() -> None:
    """The counterpart of the exact-fit case: the cap fills on the last part of section N and
    section N+1 still carries text. Nothing was skipped INSIDE a split, but a whole section is
    about to be — that is truncation, and it must not hide behind the exact fit.

    Pinned because it is exactly what a naive "exact fit is never cut" fix would get wrong. It
    holds without a special seam check: the loop does not stop on an exact fill, so the NEXT
    section's ``_fill`` finds no room for its first part and reports the cut itself.
    """
    # An abstract that splits into EXACTLY three full parts with no remainder, so its own
    # ``_fill`` places all three, fills a cap of 3 to the brim, and returns False — it skipped
    # nothing. The body behind it is what has to make this read as cut.
    abstract = " ".join(["x" * 99] * 3)
    paper = replace(_paper_of("alpha " * 800), abstract=abstract)
    chunker = Chunker(max_chunk_chars=100, overlap_chars=0, max_chunks_per_paper=3)

    fitted = chunker.chunk(paper)

    assert [c.section for c in fitted.chunks] == ["abstract"] * 3  # the body got none
    assert fitted.truncated is True  # the body was never reached — that IS a cut


def _paper_of(body: str):
    return FetchParseProcessor().parse(
        RawDocument(metadata=sample_metadata(), text="INTRODUCTION\n" + body, source_url="local://p")
    )


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


def test_arxiv_tier_label_reads_the_fetch_tier_not_the_url() -> None:
    # The stored winning_source_tier drives canonical dedup precedence, so it must come from the
    # rung the fetch adapter actually used. Consumers used to infer it by looking for "/pdf/" in
    # the source URL, which the raw-content cache ("cache://<tier>") does not carry and the
    # configurable PDF base URL is not required to contain.
    from docsuri_shared.dtos import SourceTier

    from docsuri_ingestion.domain.canonical import (
        ARXIV_HTML_TIER,
        ARXIV_PDF_TIER,
        arxiv_tier_label,
        grobid_tier_label,
        source_priority_from_tier,
    )

    assert arxiv_tier_label(SourceTier.pdf) == ARXIV_PDF_TIER
    assert arxiv_tier_label(SourceTier.ar5iv) == ARXIV_HTML_TIER
    assert arxiv_tier_label(SourceTier.native_html) == ARXIV_HTML_TIER
    # An untagged RawDocument stays on the HTML label, as the URL sniff did for a non-PDF URL.
    assert arxiv_tier_label(None) == ARXIV_HTML_TIER

    assert grobid_tier_label(SourceName.SEMANTIC_SCHOLAR) == "SEMANTIC_SCHOLAR_GROBID"
    assert grobid_tier_label(SourceName.OPENALEX) == "OPENALEX_GROBID"

    # Every label this vocabulary emits must be readable by the precedence rule that consumes it.
    assert source_priority_from_tier(ARXIV_PDF_TIER) == 0
    assert source_priority_from_tier(ARXIV_HTML_TIER) == 0
    assert source_priority_from_tier(grobid_tier_label(SourceName.SEMANTIC_SCHOLAR)) == 1
    assert source_priority_from_tier(grobid_tier_label(SourceName.OPENALEX)) == 2


def test_reembed_recovers_the_embed_text_the_writer_used() -> None:
    """The re-embed runner reconstructs each stored doc's embed text from the indexed fields,
    because the exact chunk text is not stored. That reconstruction reads ``section``,
    ``abstract``, ``lexicalTerms`` and ``title`` — all owned by IndexRecordAssembler — so a change
    there silently re-embeds the wrong text. Pin the contract here.
    """
    from docsuri_ingestion.reembed import _embed_text_for_source

    metadata = replace(
        sample_metadata(), title="Recover Title", abstract="Recover the abstract text."
    )
    paper = FetchParseProcessor().parse(
        RawDocument(
            metadata=metadata,
            text="INTRODUCTION\nRecover the body text",
            source_url="local://paper",
        )
    )
    chunks = Chunker(max_chunk_chars=200, overlap_chars=0).chunk(paper)
    embedding_batch = EmbeddingBatch(
        chunk_ids=tuple(chunk.chunk_id for chunk in chunks.chunks),
        vectors=tuple(tuple([0.0] * DIMENSIONS) for _ in chunks.chunks),
    )
    records = IndexRecordAssembler().assemble(paper, chunks, embedding_batch).records

    by_chunk = {chunk.chunk_id: chunk for chunk in chunks.chunks}
    for record in records:
        source = record.model_dump(mode="json")
        recovered = _embed_text_for_source(source)
        assert recovered, f"no embed text recovered for {record.chunkId}"
        chunk = by_chunk[record.chunkId]
        if record.section == "abstract":
            # lexicalTerms is blanked for abstract chunks, so the reconstruction falls back to the
            # stored abstract. It matches only while the abstract fits a single chunk.
            assert recovered == paper.abstract
            assert recovered == chunk.text
        else:
            assert recovered == normalize_text(chunk.text)


def test_reembed_abstract_reconstruction_is_exact_at_the_default_chunk_size() -> None:
    """The abstract branch of the re-embed reconstruction is exact only while the abstract fits
    one chunk. Pin both sides of that bound so the safe default is guaranteed and the failure
    mode under a lowered DOCSURI_MAX_CHUNK_CHARS is visible rather than silent.
    """
    from docsuri_ingestion.reembed import _embed_text_for_source

    # arXiv caps submitted abstracts well under the 2400-char default, so one chunk is the real
    # operating point — the reconstruction returns exactly what the writer embedded.
    long_abstract = "Sentence about the method. " * 60  # ~1620 chars, a realistic upper end
    metadata = replace(sample_metadata(), title="Bound Title", abstract=long_abstract)
    paper = FetchParseProcessor().parse(
        RawDocument(
            metadata=metadata, text="INTRODUCTION\nBody", source_url="local://paper"
        )
    )
    default_chunks = Chunker().chunk(paper)
    abstract_chunks = [c for c in default_chunks.chunks if c.section == "abstract"]
    assert len(abstract_chunks) == 1
    assert _embed_text_for_source({"section": "abstract", "abstract": paper.abstract}) == (
        abstract_chunks[0].text
    )

    # Lower the cap below the abstract length and it splits. Every one of those chunks would
    # re-embed the whole abstract, so the paper gets duplicate vectors in the abstract space.
    # Fixing that needs the embedded text stored per document, not a re-split in the runner.
    split_chunks = Chunker(max_chunk_chars=400, overlap_chars=0).chunk(paper)
    split_abstract_chunks = [c for c in split_chunks.chunks if c.section == "abstract"]
    assert len(split_abstract_chunks) > 1
    recovered = _embed_text_for_source({"section": "abstract", "abstract": paper.abstract})
    assert all(recovered != chunk.text for chunk in split_abstract_chunks)


def test_chunk_cap_does_not_truncate_a_survey_sized_paper() -> None:
    """The cap counts BLOCKS, not 2,400-char windows — a survey with hundreds of paragraphs must
    still be indexed whole.

    At 128 this silently cut the body of 217 of the 827 papers in the ⑧-2 deploy corpus (26%):
    a median 9.7% of their text and up to 64.6%. Nothing failed and nothing was logged; the
    paper simply stopped partway and the rest was unsearchable. The papers it cut were the
    surveys and reviews — the ones with the most paragraphs, and the ones the foundational list
    was assembled to include.
    """
    from docsuri_ingestion.processors import Chunker

    blocks = [
        {"id": f"s1.p{i}", "type": "paragraph", "text": f"Paragraph {i} of a long survey."}
        for i in range(300)
    ]
    doc = DocModel.model_validate(
        {
            "meta": {
                "paperId": "2401.00002",
                "version": 1,
                "title": "A Survey",
                "provenance": {
                    "sourceTier": "pdf",
                    "parserVersion": "test",
                    "schemaVersion": "1",
                    "generatedAt": "1970-01-01T00:00:00Z",
                },
            },
            "fullText": "body",
            "sections": [{"id": "s1", "title": "Body", "blocks": blocks}],
        }
    )

    chunks = Chunker().chunk_doc_model(doc).chunks

    assert len(chunks) == 300, "the survey lost paragraphs to the per-paper cap"
