"""BUILD_DOC_MODEL queue job (slice 2, BR-30/D6): the worker dispatches a doc-model build
(enqueued by U7 on a cache miss) to ``IngestionPipelineService.build_doc_model``, which
fetches metadata and drives the cached builder. The same builder is also used eagerly by the
phase-1 Corpus ingest path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from docsuri_shared.dtos import DocModel, SourceTier

from docsuri_ingestion.adapters.local import FakeArxivSource, sample_metadata
from docsuri_ingestion.docmodel.builder import DocModelBuilder
from docsuri_ingestion.domain.enums import DedupDecision, JobKind
from docsuri_ingestion.domain.errors import PermanentIngestionError
from docsuri_ingestion.domain.models import IngestionJob
from docsuri_ingestion.worker import process_message

from .conftest import build_test_pipeline

_HTML = (
    '<article class="ltx_document"><section class="ltx_section" id="S1">'
    '<h2 class="ltx_title ltx_title_section">Intro</h2>'
    '<div class="ltx_para"><p class="ltx_p">Body.</p></div></section></article>'
)


class _FakeSource:
    """Builder source (HTML→tier). Separate from the pipeline's arXiv metadata port."""

    def __init__(self, result: tuple[str, SourceTier] | None) -> None:
        self._result = result
        self.calls: list[str] = []

    def fetch_html_source(self, arxiv_id: str) -> tuple[str, SourceTier] | None:
        self.calls.append(arxiv_id)
        return self._result


class _FakeStore:
    def __init__(self, cached: DocModel | None = None) -> None:
        self._cached = cached
        self.put_calls: list[DocModel] = []

    def get(self, paper_id: str, version: int) -> DocModel | None:
        return self._cached

    def put(self, doc: DocModel) -> str:
        self.put_calls.append(doc)
        return "s3://bucket/doc-model/x.json"

    def remove(self, paper_id: str) -> None:  # pragma: no cover - not exercised here
        pass


def _builder(source: _FakeSource, store: _FakeStore) -> DocModelBuilder:
    return DocModelBuilder(source=source, store=store)


def _doc_block_index(doc: DocModel) -> set[tuple[str, str, str]]:
    refs: set[tuple[str, str, str]] = set()

    def walk(section) -> None:
        for block in section.blocks:
            b = block.root
            refs.add((section.id, b.id, b.type))
        for child in section.sections or []:
            walk(child)

    for section in doc.sections:
        walk(section)
    return refs


def _assert_index_refs_doc_model(index, doc: DocModel) -> None:
    refs = _doc_block_index(doc)
    for record in index.records.values():
        assert record.blockRefs
        for ref in record.blockRefs:
            assert ref.paperId == doc.meta.paperId
            assert ref.version == doc.meta.version
            assert (ref.sectionId, ref.blockId, ref.blockType) in refs


def test_build_doc_model_builds_and_caches_on_miss() -> None:
    source = _FakeSource((_HTML, SourceTier.native_html))
    store = _FakeStore(cached=None)
    pipeline, _, _, _, _ = build_test_pipeline(doc_model_builder=_builder(source, store))

    result = pipeline.build_doc_model(
        IngestionJob(job_id="b-1", kind=JobKind.BUILD_DOC_MODEL, arxiv_ref="2401.00001v1")
    )

    assert result.status == "ok"
    assert result.cached is False
    assert len(store.put_calls) == 1  # built + cached
    assert source.calls  # builder fetched the HTML source


def test_build_doc_model_falls_back_to_text_when_html_unavailable() -> None:
    store = _FakeStore()
    pipeline, _, _, _, observability = build_test_pipeline(
        doc_model_builder=_builder(_FakeSource(None), store)
    )
    result = pipeline.build_doc_model(
        IngestionJob(job_id="b-2", kind=JobKind.BUILD_DOC_MODEL, arxiv_ref="2401.00001v1")
    )
    assert result.status == "ok"
    assert result.docModel.meta.provenance.sourceTier is SourceTier.pdf
    assert result.docModel.fullText
    assert len(store.put_calls) == 1
    assert any(
        metric[0] == "ingestion.docmodel.build" and metric[2]["status"] == "pdf_fallback"
        for metric in observability.metrics
    )


def test_build_doc_model_requires_arxiv_ref() -> None:
    pipeline, _, _, _, _ = build_test_pipeline(
        doc_model_builder=_builder(_FakeSource((_HTML, SourceTier.native_html)), _FakeStore())
    )
    with pytest.raises(PermanentIngestionError):
        pipeline.build_doc_model(
            IngestionJob(job_id="b-3", kind=JobKind.BUILD_DOC_MODEL, arxiv_ref=None)
        )


def test_worker_dispatches_build_job_and_acks() -> None:
    source = _FakeSource((_HTML, SourceTier.native_html))
    store = _FakeStore(cached=None)
    pipeline, _, _, queue, observability = build_test_pipeline(
        doc_model_builder=_builder(source, store)
    )
    queue.send_job(
        IngestionJob(job_id="b-4", kind=JobKind.BUILD_DOC_MODEL, arxiv_ref="2401.00001v1")
    )
    message = queue.receive_messages(max_messages=1)[0]
    runtime = SimpleNamespace(pipeline=pipeline, queue=queue, observability=observability)

    process_message(runtime, message)

    assert queue.acked == [message.message_id]
    assert len(store.put_calls) == 1  # dispatched to build_doc_model, not ingest_one


def test_ingest_one_eagerly_builds_doc_model_before_index() -> None:
    source = _FakeSource((_HTML, SourceTier.native_html))
    store = _FakeStore(cached=None)
    pipeline, _, index, _, observability = build_test_pipeline(
        doc_model_builder=_builder(source, store)
    )

    result = pipeline.ingest_one(
        IngestionJob(job_id="i-1", kind=JobKind.INCREMENTAL, arxiv_ref="2401.00001v1")
    )

    assert result.name == "NEW"
    assert len(store.put_calls) == 1
    assert index.bulk_calls == 1  # index write happened after the doc-model build
    _assert_index_refs_doc_model(index, store.put_calls[0])
    assert any(m[0] == "ingestion.docmodel.eager_build" for m in observability.metrics)


def test_ingest_one_eager_doc_model_new_and_changed_smoke() -> None:
    v1_meta = sample_metadata("2401.00001v1")
    v2_meta = sample_metadata("2401.00001v2")
    arxiv = FakeArxivSource(
        [v1_meta, v2_meta],
        full_text={
            "2401.00001v1": "INTRODUCTION\nbody v1",
            "2401.00001v2": "INTRODUCTION\nbody v2",
        },
    )
    source = _FakeSource((_HTML, SourceTier.native_html))
    store = _FakeStore(cached=None)
    pipeline, _, index, _, _ = build_test_pipeline(
        arxiv=arxiv, doc_model_builder=_builder(source, store)
    )

    assert (
        pipeline.ingest_one(
            IngestionJob(job_id="i-new", kind=JobKind.INCREMENTAL, arxiv_ref="2401.00001v1")
        )
        is DedupDecision.NEW
    )
    assert (
        pipeline.ingest_one(
            IngestionJob(job_id="i-changed", kind=JobKind.INCREMENTAL, arxiv_ref="2401.00001v2")
        )
        is DedupDecision.CHANGED
    )

    assert len(store.put_calls) == 2
    assert all(record.version == 2 for record in index.records.values())
    _assert_index_refs_doc_model(index, store.put_calls[-1])
    assert index.index_stats().total_documents == len(index.records)


def test_ingest_one_falls_back_to_text_doc_model_when_html_unavailable() -> None:
    store = _FakeStore()
    pipeline, _, index, _, observability = build_test_pipeline(
        doc_model_builder=_builder(_FakeSource(None), store)
    )

    result = pipeline.ingest_one(
        IngestionJob(job_id="i-2", kind=JobKind.INCREMENTAL, arxiv_ref="2401.00001v1")
    )

    assert result is DedupDecision.NEW
    assert index.bulk_calls == 1
    _assert_index_refs_doc_model(index, store.put_calls[0])
    assert any(
        metric[0] == "ingestion.docmodel.eager_build"
        and metric[2]["status"] == "pdf_fallback"
        for metric in observability.metrics
    )
