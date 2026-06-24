"""BUILD_DOC_MODEL queue job (slice 2, BR-30/D6): the worker dispatches a lazy doc-model
build (enqueued by U7 on a cache miss) to ``IngestionPipelineService.build_doc_model``, which
fetches metadata and drives the cached builder. Boundary B: the read side enqueues, this worker
produces — the index hot path (ingest_one) never touches the builder.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from docsuri_shared.dtos import DocModel, SourceTier

from docsuri_ingestion.docmodel.builder import DocModelBuilder
from docsuri_ingestion.domain.enums import JobKind
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


def test_build_doc_model_source_unavailable_is_terminal() -> None:
    # Builder source returns None → SourceUnavailableDTO (ack, no redelivery).
    pipeline, _, _, _, _ = build_test_pipeline(
        doc_model_builder=_builder(_FakeSource(None), _FakeStore())
    )
    result = pipeline.build_doc_model(
        IngestionJob(job_id="b-2", kind=JobKind.BUILD_DOC_MODEL, arxiv_ref="2401.00001v1")
    )
    assert result.status == "source_unavailable"


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
