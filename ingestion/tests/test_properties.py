from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from docsuri_ingestion.adapters.local import (
    FakeEmbeddingPort,
    InMemoryControlPlaneStore,
    InMemoryVectorIndex,
)
from docsuri_ingestion.domain.models import EmbeddingBatch, Watermark
from docsuri_ingestion.processors import Chunker, IndexRecordAssembler

from .strategies import parsed_paper_strategy


@given(parsed_paper_strategy())
@settings(max_examples=25, derandomize=True)
def test_p2_chunking_is_deterministic(paper) -> None:
    chunker = Chunker()
    assert chunker.chunk(paper) == chunker.chunk(paper)


@given(parsed_paper_strategy())
@settings(max_examples=25, derandomize=True)
def test_p3_upsert_is_idempotent(paper) -> None:
    batch = assemble_batch(paper)
    index = InMemoryVectorIndex()
    index.bulk_upsert(batch)
    first_state = dict(index.records)
    index.bulk_upsert(batch)
    assert index.records == first_state


@given(parsed_paper_strategy())
@settings(max_examples=25, derandomize=True)
def test_p4_no_loss_no_duplicate_records(paper) -> None:
    chunk_set = Chunker().chunk(paper)
    batch = assemble_batch(paper)
    assert len(batch.records) == len(chunk_set.chunks)
    assert len({record.chunkId for record in batch.records}) == len(batch.records)


@given(parsed_paper_strategy())
@settings(max_examples=25, derandomize=True)
def test_p5_embedding_alignment_preserved(paper) -> None:
    chunk_set = Chunker().chunk(paper)
    vectors = FakeEmbeddingPort().embed_documents([chunk.text for chunk in chunk_set.chunks])
    embedding_batch = EmbeddingBatch(
        chunk_ids=tuple(chunk.chunk_id for chunk in chunk_set.chunks),
        vectors=tuple(tuple(vector) for vector in vectors),
    )
    batch = IndexRecordAssembler().assemble(paper, chunk_set, embedding_batch)
    assert [record.chunkId for record in batch.records] == list(embedding_batch.chunk_ids)


@given(st.lists(st.integers(min_value=-30, max_value=30), min_size=1, max_size=20))
@settings(max_examples=25, derandomize=True)
def test_p6_watermark_monotonic(offsets) -> None:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    watermark = Watermark.epoch()
    previous = watermark.updated_at
    for offset in offsets:
        watermark = watermark.advance(base + timedelta(days=offset))
        assert watermark.updated_at >= previous
        previous = watermark.updated_at


@given(
    st.lists(
        st.tuples(
            st.sampled_from(("arxiv", "semantic_scholar", "openalex")),
            st.integers(min_value=-30, max_value=30),
        ),
        min_size=1,
        max_size=30,
    )
)
@settings(max_examples=25, derandomize=True)
def test_source_watermarks_are_monotonic_and_independent(ops) -> None:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    store = InMemoryControlPlaneStore()
    names = ("arxiv", "semantic_scholar", "openalex")

    previous = {name: store.get_watermark(name).updated_at for name in names}
    for name, offset in ops:
        before_others = {
            other: store.get_watermark(other).updated_at for other in names if other != name
        }
        updated = store.advance_watermark(name, base + timedelta(days=offset))

        assert updated.updated_at >= previous[name]
        for other, value in before_others.items():
            assert store.get_watermark(other).updated_at == value
        previous[name] = updated.updated_at


def assemble_batch(paper):
    chunk_set = Chunker().chunk(paper)
    vectors = FakeEmbeddingPort().embed_documents([chunk.text for chunk in chunk_set.chunks])
    embedding_batch = EmbeddingBatch(
        chunk_ids=tuple(chunk.chunk_id for chunk in chunk_set.chunks),
        vectors=tuple(tuple(vector) for vector in vectors),
    )
    return IndexRecordAssembler().assemble(paper, chunk_set, embedding_batch)
