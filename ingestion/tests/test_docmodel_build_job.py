"""BUILD_DOC_MODEL queue job (slice 2, BR-30/D6): the worker dispatches a doc-model build
(enqueued by U7 on a cache miss) to ``IngestionPipelineService.build_doc_model``, which
fetches metadata and drives the cached builder. The same builder is also used eagerly by the
phase-1 Corpus ingest path.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from docsuri_shared.dtos import DocModel, SourceTier

import docsuri_ingestion.application as application_module
from docsuri_ingestion.adapters.local import FakeArxivSource, sample_metadata
from docsuri_ingestion.docmodel.builder import DocModelBuilder
from docsuri_ingestion.domain.enums import DedupDecision, FailureReason, JobKind
from docsuri_ingestion.domain.errors import PermanentIngestionError
from docsuri_ingestion.domain.models import IngestionJob
from docsuri_ingestion.full_text_extraction import FullTextExtractionError
from docsuri_ingestion.worker import job_from_payload, process_message

from .conftest import build_test_pipeline

_BODY = "A full paragraph of body prose for the completeness floor. " * 12  # ~700 chars
_HTML = (
    '<article class="ltx_document"><section class="ltx_section" id="S1">'
    '<h2 class="ltx_title ltx_title_section">Intro</h2>'
    f'<div class="ltx_para"><p class="ltx_p">{_BODY}</p></div></section></article>'
)
_USERDOC_TEI = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
    "<div><head>Method</head><p>Structured body from GROBID.</p></div>"
    "</body></text></TEI>"
)
_USERDOC_EMPTY_BODY_TEI = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body /></text></TEI>'
)
_USERDOC_UUID = "5a96a314-0fb9-45d6-96b8-2da8750120d8"
_USERDOC_PAPER_ID = f"userdoc:{_USERDOC_UUID}"
_USERDOC_JOB_UUID = "3e9d6b7d-24d9-4a21-8049-6ac132f5499f"
_USERDOC_JOB_ID = f"userdoc-{_USERDOC_JOB_UUID}"
_OTHER_USERDOC_JOB_ID = "userdoc-1f977735-652f-49b3-a281-c93f2bc17430"
_USERDOC_RECORD_REF = f"upload:acct-1:{_USERDOC_JOB_ID}:attachment-1"


class _FakeGrobid:
    """GROBID sidecar double for the arXiv PDF→GROBID rung."""

    def __init__(self, tei: str) -> None:
        self._tei = tei
        self.seen_pdf: bytes | None = None
        self.calls = 0

    def extract_tei(self, pdf: bytes) -> str:
        self.seen_pdf = pdf
        self.calls += 1
        return self._tei


_ARXIV_GROBID_TEI = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body>'
    "<div><head>Method</head><p>Structured body recovered from the PDF via GROBID.</p></div>"
    "</body></text></TEI>"
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


class _FakeUserDocumentSource:
    def __init__(self, payload: bytes = b"%PDF") -> None:
        self.payload = payload
        self.keys: list[str] = []

    def fetch_pdf(self, object_key: str) -> bytes:
        self.keys.append(object_key)
        return self.payload


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
    source = _FakeSource((_HTML, SourceTier.ar5iv))
    store = _FakeStore(cached=None)
    pipeline, _, _, _, _ = build_test_pipeline(doc_model_builder=_builder(source, store))

    result = pipeline.build_doc_model(
        IngestionJob(job_id="b-1", kind=JobKind.BUILD_DOC_MODEL, arxiv_ref="2401.00001v1")
    )

    assert result.status == "ok"
    assert result.cached is False
    assert len(store.put_calls) == 1  # built + cached
    assert source.calls  # builder fetched the HTML source


def test_build_doc_model_stays_unavailable_without_grobid() -> None:
    # BR-30 2026-08-10: below ar5iv the ladder is PDF→GROBID — never a flat-text doc-model.
    # With the rung unwired the lazy job keeps source_unavailable (viewer links out).
    store = _FakeStore()
    pipeline, _, _, _, observability = build_test_pipeline(
        doc_model_builder=_builder(_FakeSource(None), store)
    )
    result = pipeline.build_doc_model(
        IngestionJob(job_id="b-2", kind=JobKind.BUILD_DOC_MODEL, arxiv_ref="2401.00001v1")
    )
    assert result.status == "source_unavailable"
    assert store.put_calls == []  # no flat-text doc-model was cached
    assert any(
        m[0] == "ingestion.docmodel.grobid_rung_unwired" for m in observability.metrics
    )


def test_build_doc_model_recovers_via_grobid_rung() -> None:
    # ar5iv missing → arXiv PDF → GROBID → structured doc-model (BR-30 2026-08-10). The rung
    # needs the grobid sidecar AND a PDF source wired; both are faked here.
    metadata = sample_metadata()
    store = _FakeStore()
    pipeline, _, _, _, observability = build_test_pipeline(
        arxiv=FakeArxivSource([metadata], pdf=b"%PDF-fake"),
        doc_model_builder=_builder(_FakeSource(None), store),  # ar5iv miss → SourceUnavailable
        grobid=_FakeGrobid(_ARXIV_GROBID_TEI),
    )

    result = pipeline.build_doc_model(
        IngestionJob(job_id="b-gr", kind=JobKind.BUILD_DOC_MODEL, arxiv_ref=metadata.arxiv_ref)
    )

    assert result.status == "ok"
    assert result.docModel.meta.provenance.sourceTier is SourceTier.pdf
    assert [s.title for s in result.docModel.sections if s.title] != []  # structured, not flat
    assert len(store.put_calls) == 1
    assert any(
        # Same rung name the eager path reports — one ladder, one vocabulary.
        metric[0] == "ingestion.docmodel.build" and metric[2]["status"] == "grobid"
        for metric in observability.metrics
    )


def test_build_doc_model_stays_unavailable_when_grobid_rejects_the_pdf() -> None:
    # GROBID 4xx-rejects the PDF (malformed/unsupported): a PERMANENT verdict about this paper,
    # not a worker fault. The lazy job's contract says the result STAYS source_unavailable
    # (viewer links out); letting the error escape turned every such already-indexed paper into
    # an endless DLQ + failure-signal loop while the viewer polled forever.
    class _RejectingGrobid:
        def extract_tei(self, pdf: bytes) -> str:
            raise PermanentIngestionError(
                "GROBID rejected PDF", reason=FailureReason.PARSE_FAILURE, stage="grobid"
            )

    metadata = sample_metadata()
    store = _FakeStore()
    pipeline, _, _, _, observability = build_test_pipeline(
        arxiv=FakeArxivSource([metadata], pdf=b"%PDF-fake"),
        doc_model_builder=_builder(_FakeSource(None), store),
        grobid=_RejectingGrobid(),
    )

    result = pipeline.build_doc_model(
        IngestionJob(job_id="b-rej", kind=JobKind.BUILD_DOC_MODEL, arxiv_ref=metadata.arxiv_ref)
    )

    assert result.status == "source_unavailable"  # NOT an exception
    assert store.put_calls == []
    assert any(
        m[0] == "ingestion.docmodel.grobid_rung_rejected" for m in observability.metrics
    )


def test_grobid_rung_asset_context_tristate() -> None:
    # The rung's asset context distinguishes three situations _index_paper must not confuse:
    #   fresh build WITH coords  → context carrying the crops (crop branch renders them);
    #   fresh build, NO coords   → None: fall back to the e-print extractor branch (the path this
    #                              population used before the rung existed) + a metric — a silent
    #                              no-op left the doc-model's figure assetIds dangling invisibly;
    #   cache hit                → EMPTY context: stay on the crop branch and do nothing, the
    #                              build that filled the cache already stored the crops (None here
    #                              would re-download the tarball AND PDF via the e-print branch).
    class _AssetStore:
        def store_assets(self, *a):  # pragma: no cover - must not be reached
            raise AssertionError("this test never renders/stores")

        def remove_assets(self, paper_id):  # pragma: no cover - not exercised
            pass

    coords_tei = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div><head>M</head>'
        "<p>Prose body.</p>"
        '<figure coords="1,5,6,30,12"><head>Figure 1</head><figDesc>d</figDesc></figure>'
        "</div></body></text></TEI>"
    )
    metadata = sample_metadata()

    # Fresh build with coordinates: crops travel in the context.
    store = _FakeStore()
    pipeline, _, _, _, _ = build_test_pipeline(
        arxiv=FakeArxivSource([metadata], pdf=b"%PDF-fake"),
        doc_model_builder=_builder(_FakeSource(None), store),
        grobid=_FakeGrobid(coords_tei),
        asset_store=_AssetStore(),
    )
    fresh = pipeline._grobid_doc_model(metadata)
    assert fresh is not None
    fresh_result, fresh_ctx = fresh
    assert fresh_result.cached is False
    assert fresh_ctx is not None and len(fresh_ctx.crops) == 1

    # Cache hit: EMPTY context, not None.
    store._cached = store.put_calls[0]
    cached = pipeline._grobid_doc_model(metadata)
    assert cached is not None
    cached_result, cached_ctx = cached
    assert cached_result.cached is True
    assert cached_ctx is not None and cached_ctx.crops == ()

    # Fresh build with NO coordinates: None (e-print fallback) + the visibility metric.
    store2 = _FakeStore()
    pipeline2, _, _, _, observability2 = build_test_pipeline(
        arxiv=FakeArxivSource([metadata], pdf=b"%PDF-fake"),
        doc_model_builder=_builder(_FakeSource(None), store2),
        grobid=_FakeGrobid(_ARXIV_GROBID_TEI),  # no coords anywhere
        asset_store=_AssetStore(),
    )
    no_coords = pipeline2._grobid_doc_model(metadata)
    assert no_coords is not None
    _result, no_coords_ctx = no_coords
    assert no_coords_ctx is None
    assert any(
        m[0] == "ingestion.docmodel.grobid_rung_no_coords" for m in observability2.metrics
    )


def test_lazy_build_doc_model_stores_the_grobid_crops(monkeypatch) -> None:
    # The lazy BUILD_DOC_MODEL path caches the doc-model it builds — so a fresh GROBID build here
    # must ALSO store its crops. Discarding them left a cached doc-model whose figure blocks
    # reference assets never rendered, and every later eager pass hit the cache and stored
    # nothing: the gap was permanent.
    def fake_crops(pdf, specs, *, paper_id, version, refusals=None):
        # ``refusals`` accepted and ignored: this double renders everything, so there is nothing to
        # refuse. It must still take the argument — the caller passes it, and the asset path
        # swallows every exception by design (BR-27), so a stale double reads as "no assets"
        # rather than as the TypeError it is.
        return [
            SimpleNamespace(meta=SimpleNamespace(asset_id=spec.asset_id), image=b"img")
            for spec in specs
        ]

    monkeypatch.setattr(application_module, "crop_assets_from_specs", fake_crops)

    class _RecordingAssetStore:
        def __init__(self) -> None:
            self.stored: list[tuple[str, int, int]] = []

        def store_assets(self, paper_id, version, assets):
            self.stored.append((paper_id, version, len(assets)))

        def remove_assets(self, paper_id):  # pragma: no cover - not exercised
            pass

    coords_tei = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div><head>M</head>'
        "<p>Prose body.</p>"
        '<figure coords="1,5,6,30,12"><head>Figure 1</head><figDesc>d</figDesc></figure>'
        "</div></body></text></TEI>"
    )
    metadata = sample_metadata()
    asset_store = _RecordingAssetStore()
    pipeline, _, _, _, _ = build_test_pipeline(
        arxiv=FakeArxivSource([metadata], pdf=b"%PDF-fake"),
        doc_model_builder=_builder(_FakeSource(None), _FakeStore()),
        grobid=_FakeGrobid(coords_tei),
        asset_store=asset_store,
    )

    result = pipeline.build_doc_model(
        IngestionJob(job_id="b-lc", kind=JobKind.BUILD_DOC_MODEL, arxiv_ref=metadata.arxiv_ref)
    )

    assert result.status == "ok"
    assert asset_store.stored == [(metadata.paper_id, metadata.version, 1)]


def test_build_doc_model_stays_unavailable_when_tei_has_no_body() -> None:
    # GROBID answered but the TEI parses to nothing — a flat-text doc-model is exactly what the
    # 2026-08-10 revision removed, so the result stays source_unavailable.
    metadata = sample_metadata()
    store = _FakeStore()
    pipeline, _, _, _, _ = build_test_pipeline(
        arxiv=FakeArxivSource([metadata], pdf=b"%PDF-fake"),
        doc_model_builder=_builder(_FakeSource(None), store),
        grobid=_FakeGrobid(_USERDOC_EMPTY_BODY_TEI),
    )

    result = pipeline.build_doc_model(
        IngestionJob(job_id="b-nb", kind=JobKind.BUILD_DOC_MODEL, arxiv_ref=metadata.arxiv_ref)
    )

    assert result.status == "source_unavailable"
    assert store.put_calls == []


def test_build_doc_model_requires_arxiv_ref() -> None:
    pipeline, _, _, _, _ = build_test_pipeline(
        doc_model_builder=_builder(_FakeSource((_HTML, SourceTier.ar5iv)), _FakeStore())
    )
    with pytest.raises(PermanentIngestionError):
        pipeline.build_doc_model(
            IngestionJob(job_id="b-3", kind=JobKind.BUILD_DOC_MODEL, arxiv_ref=None)
        )


def test_user_docmodel_payload_accepts_s3_source_without_arxiv_ref() -> None:
    payload = {
        "jobId": _USERDOC_JOB_ID,
        "kind": "BUILD_USER_DOC_MODEL",
        "paperId": _USERDOC_PAPER_ID,
        "version": 1,
        "objectKey": "uploads/owner/job/attachment.pdf",
        "module": "novelty",
        "ownerId": "acct-1",
        "recordRef": _USERDOC_RECORD_REF,
    }

    job = job_from_payload(payload)

    assert job.kind is JobKind.BUILD_USER_DOC_MODEL
    assert job.arxiv_ref is None
    assert job.job_id == _USERDOC_JOB_ID
    assert job.paper_id == _USERDOC_PAPER_ID
    assert job.version == 1
    assert job.object_key == "uploads/owner/job/attachment.pdf"
    assert job.module == "novelty"
    assert job.owner_id == "acct-1"
    assert job.record_ref == _USERDOC_RECORD_REF


@pytest.mark.parametrize(
    "override",
    [
        {"arxivRef": "2401.00001v1"},
        {
            "jobId": "userdoc-not-a-uuid",
            "recordRef": "upload:acct-1:userdoc-not-a-uuid:attachment-1",
        },
        {"paperId": "2401.00001"},
        {"paperId": "userdoc:not-a-uuid"},
        {"version": 0},
        {"version": 2},
        {"objectKey": ""},
        {"module": "summary"},
        {"recordRef": f"upload:other:{_USERDOC_JOB_ID}:attachment-1"},
        {"recordRef": f"upload:acct-1:{_OTHER_USERDOC_JOB_ID}:attachment-1"},
        {"recordRef": f"upload:acct-1:{_USERDOC_JOB_ID}"},
        {"recordRef": f"upload:acct-1:{_USERDOC_JOB_ID}:"},
    ],
)
def test_user_docmodel_payload_rejects_contract_drift(override: dict) -> None:
    payload = {
        "jobId": _USERDOC_JOB_ID,
        "kind": "BUILD_USER_DOC_MODEL",
        "paperId": _USERDOC_PAPER_ID,
        "version": 1,
        "objectKey": "uploads/owner/job/attachment.pdf",
        "module": "evidence",
        "ownerId": "acct-1",
        "recordRef": _USERDOC_RECORD_REF,
        **override,
    }

    with pytest.raises(PermanentIngestionError):
        job_from_payload(payload)


def test_worker_dispatches_build_job_and_acks() -> None:
    source = _FakeSource((_HTML, SourceTier.ar5iv))
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


def test_worker_dispatches_user_docmodel_job_and_acks(monkeypatch) -> None:
    monkeypatch.setattr(
        application_module,
        "pdf_to_text",
        lambda pdf: "INTRODUCTION\nUser PDF body recovered from pdfplumber.",
    )
    store = _FakeStore(cached=None)
    user_source = _FakeUserDocumentSource()
    pipeline, _, _, queue, observability = build_test_pipeline(
        doc_model_builder=_builder(_FakeSource(None), store),
        user_document_source=user_source,
    )
    queue.send_job(
        IngestionJob(
            job_id=_USERDOC_JOB_ID,
            kind=JobKind.BUILD_USER_DOC_MODEL,
            paper_id=_USERDOC_PAPER_ID,
            version=1,
            object_key="uploads/acct-1/job-1/attachment.pdf",
            module="evidence",
            owner_id="acct-1",
            record_ref=_USERDOC_RECORD_REF,
        )
    )
    message = queue.receive_messages(max_messages=1)[0]
    runtime = SimpleNamespace(pipeline=pipeline, queue=queue, observability=observability)

    process_message(runtime, message)

    assert "arxivRef" not in message.body
    assert queue.acked == [message.message_id]
    assert queue.dlq == []
    assert user_source.keys == ["uploads/acct-1/job-1/attachment.pdf"]
    assert len(store.put_calls) == 1
    doc = store.put_calls[0]
    assert doc.meta.paperId == _USERDOC_PAPER_ID
    assert doc.meta.version == 1
    assert doc.meta.provenance.sourceTier is SourceTier.pdf
    assert "User PDF body" in doc.fullText
    assert any(
        metric[0] == "ingestion.docmodel.user_build"
        and metric[2]["module"] == "evidence"
        and metric[2]["cached"] == "false"
        for metric in observability.metrics
    )


def test_worker_dlqs_unparseable_user_docmodel_pdf(monkeypatch) -> None:
    def _raise_parse_error(pdf: bytes) -> str:
        del pdf
        raise FullTextExtractionError("bad pdf")

    monkeypatch.setattr(application_module, "pdf_to_text", _raise_parse_error)
    pipeline, _, _, queue, observability = build_test_pipeline(
        doc_model_builder=_builder(_FakeSource(None), _FakeStore()),
        user_document_source=_FakeUserDocumentSource(b"not a pdf"),
    )
    queue.send_job(
        IngestionJob(
            job_id=_OTHER_USERDOC_JOB_ID,
            kind=JobKind.BUILD_USER_DOC_MODEL,
            paper_id=_USERDOC_PAPER_ID,
            version=1,
            object_key="uploads/acct-1/job-1/bad.pdf",
            module="novelty",
            owner_id="acct-1",
            record_ref=f"upload:acct-1:{_OTHER_USERDOC_JOB_ID}:attachment-1",
        )
    )
    message = queue.receive_messages(max_messages=1)[0]
    runtime = SimpleNamespace(pipeline=pipeline, queue=queue, observability=observability)

    process_message(runtime, message)

    assert queue.acked == [message.message_id]
    assert queue.dlq[-1]["reason"] == "PARSE_FAILURE"
    assert observability.failures[-1] == {
        "job_id": _OTHER_USERDOC_JOB_ID,
        "stage": "parse",
        "error": "PARSE_FAILURE",
    }


def test_build_user_doc_model_uses_grobid_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(application_module, "pdf_to_text", lambda pdf: "INTRODUCTION\nBody text.")
    store = _FakeStore(cached=None)

    grobid = _FakeGrobid(_USERDOC_TEI)
    pipeline, _, _, _, _ = build_test_pipeline(
        doc_model_builder=_builder(_FakeSource(None), store),
        user_document_source=_FakeUserDocumentSource(),
        grobid=grobid,
    )
    job = IngestionJob(
        job_id=_USERDOC_JOB_ID,
        kind=JobKind.BUILD_USER_DOC_MODEL,
        paper_id=_USERDOC_PAPER_ID,
        version=1,
        object_key="uploads/acct-1/job-1/scan.pdf",
        module="novelty",
        owner_id="acct-1",
        record_ref=_USERDOC_RECORD_REF,
    )

    result = pipeline.build_user_doc_model(job)

    assert grobid.calls == 1  # GROBID was consulted when configured
    assert result.docModel.meta.provenance.sourceTier is SourceTier.pdf
    assert "Structured body from GROBID" in result.docModel.fullText
    assert "Body text" not in result.docModel.fullText
    assert any(section.title == "Method" for section in result.docModel.sections)


def test_build_user_doc_model_passes_the_crop_channel(monkeypatch) -> None:
    """Table repair and formula OCR map blocks to page regions through the crop-spec list; a
    caller that omits it silently turns both second readers off. The upload path must supply it
    along with the PDF — it is the only PDF path a user document ever takes."""
    monkeypatch.setattr(application_module, "pdf_to_text", lambda pdf: "INTRODUCTION\nBody text.")
    inner = _builder(_FakeSource(None), _FakeStore(cached=None))
    seen: dict = {}

    class _RecordingBuilder:
        def build_from_tei(self, *args, **kwargs):
            seen.update(kwargs)
            return inner.build_from_tei(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(inner, name)

    pipeline, _, _, _, _ = build_test_pipeline(
        doc_model_builder=_RecordingBuilder(),
        user_document_source=_FakeUserDocumentSource(),
        grobid=_FakeGrobid(_USERDOC_TEI),
    )
    job = IngestionJob(
        job_id=_USERDOC_JOB_ID,
        kind=JobKind.BUILD_USER_DOC_MODEL,
        paper_id=_USERDOC_PAPER_ID,
        version=1,
        object_key="uploads/acct-1/job-1/scan.pdf",
        module="novelty",
        owner_id="acct-1",
        record_ref=_USERDOC_RECORD_REF,
    )

    pipeline.build_user_doc_model(job)

    assert isinstance(seen.get("crops"), list)  # the repair/OCR passes receive the channel
    assert seen.get("pdf")  # and the same bytes GROBID read


def test_build_user_doc_model_degrades_when_grobid_returns_empty_body(
    monkeypatch,
) -> None:
    monkeypatch.setattr(application_module, "pdf_to_text", lambda pdf: "INTRODUCTION\nBody text.")
    store = _FakeStore(cached=None)

    class _EmptyBodyGrobid:
        def extract_tei(self, pdf: bytes) -> str:
            return _USERDOC_EMPTY_BODY_TEI

    pipeline, _, _, _, observability = build_test_pipeline(
        doc_model_builder=_builder(_FakeSource(None), store),
        user_document_source=_FakeUserDocumentSource(),
        grobid=_EmptyBodyGrobid(),
    )
    job = IngestionJob(
        job_id=_USERDOC_JOB_ID,
        kind=JobKind.BUILD_USER_DOC_MODEL,
        paper_id=_USERDOC_PAPER_ID,
        version=1,
        object_key="uploads/acct-1/job-1/scan.pdf",
        module="evidence",
        owner_id="acct-1",
        record_ref=_USERDOC_RECORD_REF,
    )

    result = pipeline.build_user_doc_model(job)

    assert "Body text" in result.docModel.fullText
    assert "Structured body from GROBID" not in result.docModel.fullText
    # The metric reports what the user RECEIVED: flat pdfplumber text, even though GROBID
    # answered — labeling this "grobid" hid a systematic empty-TEI regression at 100% grobid.
    assert any(
        m[0] == "ingestion.docmodel.user_build" and m[2]["status"] == "pdf_fallback"
        for m in observability.metrics
    )


def test_build_user_doc_model_degrades_when_grobid_faults(monkeypatch) -> None:
    monkeypatch.setattr(application_module, "pdf_to_text", lambda pdf: "INTRODUCTION\nBody text.")
    store = _FakeStore(cached=None)

    class _RaisingGrobid:
        def extract_tei(self, pdf: bytes) -> str:
            raise RuntimeError("grobid unavailable")

    pipeline, _, _, _, observability = build_test_pipeline(
        doc_model_builder=_builder(_FakeSource(None), store),
        user_document_source=_FakeUserDocumentSource(),
        grobid=_RaisingGrobid(),
    )
    job = IngestionJob(
        job_id=_USERDOC_JOB_ID,
        kind=JobKind.BUILD_USER_DOC_MODEL,
        paper_id=_USERDOC_PAPER_ID,
        version=1,
        object_key="uploads/acct-1/job-1/scan.pdf",
        module="evidence",
        owner_id="acct-1",
        record_ref=_USERDOC_RECORD_REF,
    )

    result = pipeline.build_user_doc_model(job)

    # A GROBID fault degrades to the pdfplumber flat-text doc-model — the build still succeeds.
    assert result.docModel.meta.provenance.sourceTier is SourceTier.pdf
    assert "Body text" in result.docModel.fullText
    assert any(
        m[0] == "ingestion.docmodel.user_grobid_unavailable" for m in observability.metrics
    )


def test_ingest_one_eagerly_builds_doc_model_before_index() -> None:
    source = _FakeSource((_HTML, SourceTier.ar5iv))
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
    source = _FakeSource((_HTML, SourceTier.ar5iv))
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


def test_ingest_one_excludes_the_paper_when_every_rung_fails() -> None:
    # BR-30 2026-08-10: no rung produced a structured doc-model → the paper does NOT enter the
    # corpus. Nothing is indexed, and no full text is written — the build runs BEFORE the store,
    # so the exclusion path costs zero S3 round trips instead of a write followed by a delete.
    store = _FakeStore()
    pipeline, _, index, _, observability = build_test_pipeline(
        doc_model_builder=_builder(_FakeSource(None), store)
    )

    with pytest.raises(PermanentIngestionError):
        pipeline.ingest_one(
            IngestionJob(job_id="i-2", kind=JobKind.INCREMENTAL, arxiv_ref="2401.00001v1")
        )

    assert index.bulk_calls == 0  # nothing reached the index
    assert pipeline._full_text_store.objects == {}  # never written, not written-then-deleted
    assert any(m[0] == "ingestion.paper.excluded" for m in observability.metrics)
    assert any(
        metric[0] == "ingestion.docmodel.eager_build" and metric[2]["status"] == "excluded"
        for metric in observability.metrics
    )
    # The begin_upsert claim committed its version bump before the build — the ledger must not
    # keep claiming INDEXED for a version that has no chunks, no doc-model, and no full text.
    from docsuri_ingestion.domain.enums import DedupStateKind

    ledger = pipeline._control_plane._dedup["2401.00001"]
    assert ledger.state is DedupStateKind.EXCLUDED
    assert ledger.fingerprint is None  # still the half-open claim, retriable as CHANGED


def test_ingest_one_recovers_via_grobid_rung_and_indexes() -> None:
    # ar5iv missing but GROBID wired: the paper lands with a STRUCTURED doc-model and its index
    # records reference that doc-model's blocks.
    store = _FakeStore()
    arxiv = FakeArxivSource([sample_metadata()], pdf=b"%PDF-fake")
    pipeline, _, index, _, observability = build_test_pipeline(
        arxiv=arxiv,
        doc_model_builder=_builder(_FakeSource(None), store),
        grobid=_FakeGrobid(_ARXIV_GROBID_TEI),
    )

    result = pipeline.ingest_one(
        IngestionJob(job_id="i-gr", kind=JobKind.INCREMENTAL, arxiv_ref="2401.00001v1")
    )

    assert result is DedupDecision.NEW
    assert index.bulk_calls == 1
    _assert_index_refs_doc_model(index, store.put_calls[0])
    assert any(
        metric[0] == "ingestion.docmodel.eager_build" and metric[2]["status"] == "grobid"
        for metric in observability.metrics
    )
    # The plain-text rung and the GROBID rung want the SAME bytes. Routing both through the arXiv
    # source (memoized) makes that one download; reaching for the FR-17 asset source instead
    # fetched the PDF a second time on exactly the papers this rung exists for.
    assert len(arxiv.pdf_calls) == 1, arxiv.pdf_calls


def test_ingest_one_swaps_discredited_ar5iv_text_for_pdf_text(monkeypatch) -> None:
    # The doc-model gate rejects the ar5iv page, GROBID recovers the structure — but the FULL
    # TEXT was extracted from that same rejected page and clears its own length-only floor. It
    # must NOT become the stored .txt (U7 summaries read it with no quality signal): the pipeline
    # re-derives the text from the PDF rung, and the canonical winner is labeled ARXIV_PDF.
    from docsuri_ingestion.domain.canonical import ARXIV_PDF_TIER
    from docsuri_ingestion.domain.models import RawDocument

    metadata = sample_metadata()

    class _Ar5ivTextSource(FakeArxivSource):
        """Full text extracted from the (broken) ar5iv page — over the 3,000-char floor."""

        def fetch_full_text(self, md):
            return RawDocument(
                metadata=md,
                text="Leaked TeX prose includegraphics thefigure. " * 100,
                source_url="html://x",
                source_tier=SourceTier.ar5iv,
            )

    # The page the gate rejects: clears the 500-char absolute floor, fails relative coverage.
    dead_html = (
        '<article class="ltx_document"><section class="ltx_section" id="S1">'
        '<h2 class="ltx_title ltx_title_section">Intro</h2>'
        + "".join(
            f'<div class="ltx_para"><p class="ltx_p">Surviving prose {i}. {"x" * 200}</p></div>'
            for i in range(5)
        )
        + "</section>"
        + "".join(f"<span>Stranded text {i}. {'z' * 400}</span>" for i in range(40))
        + "</article>"
    )
    monkeypatch.setattr(application_module, "pdf_to_text", lambda pdf: "Clean PDF body. " * 60)
    arxiv = _Ar5ivTextSource([metadata], pdf=b"%PDF-fake")
    store = _FakeStore()
    pipeline, control, index, _, _ = build_test_pipeline(
        arxiv=arxiv,
        doc_model_builder=_builder(_FakeSource((dead_html, SourceTier.ar5iv)), store),
        grobid=_FakeGrobid(_ARXIV_GROBID_TEI),
    )

    result = pipeline.ingest_one(
        IngestionJob(job_id="i-sw", kind=JobKind.INCREMENTAL, arxiv_ref=metadata.arxiv_ref)
    )

    assert result is DedupDecision.NEW
    [stored_text] = pipeline._full_text_store.objects.values()
    assert "Clean PDF body." in stored_text  # the PDF rung's text, not the rejected page's
    assert "includegraphics" not in stored_text
    winners = list(control._canonical.values())
    assert winners and all(w.winning_source_tier == ARXIV_PDF_TIER for w in winners)
