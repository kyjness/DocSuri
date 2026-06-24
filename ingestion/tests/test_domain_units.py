from __future__ import annotations

from datetime import UTC, datetime

import pytest

from docsuri_ingestion.adapters.local import InMemoryControlPlaneStore, sample_metadata
from docsuri_ingestion.domain.enums import DedupDecision, DedupStateKind
from docsuri_ingestion.domain.errors import LicenseRejectedError
from docsuri_ingestion.domain.ids import content_fingerprint, normalize_arxiv_ref
from docsuri_ingestion.domain.models import RawDocument, Watermark
from docsuri_ingestion.processors import Chunker, FetchParseProcessor, detect_withdrawal


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
    # Relaxed beyond CC: arXiv's default non-exclusive distribution license now passes.
    processor.validate_open_access("http://arxiv.org/licenses/nonexclusive-distrib/1.0/")
    processor.validate_open_access("https://creativecommons.org/licenses/by/4.0/")


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
