"""Lazy doc-model build trigger (slice 3, BR-30/D6, boundary B).

On a read miss the orchestrator enqueues a BUILD_DOC_MODEL job onto U1's queue and tells the
client to poll (``building``); the read side never runs the builder. Covers the orchestrator
lookup branches and the SqsDocModelBuildQueue adapter (dedup + best-effort enqueue).
"""

from __future__ import annotations

from docsuri_shared.dtos import DocModel

from summarization.adapters.sqs_docmodel_build import SqsDocModelBuildQueue
from summarization.domain.models import DocModelLookup
from tests.stubs import make_orchestrator


def _doc(paper_id: str = "2401.00001", version: int = 1) -> DocModel:
    return DocModel.model_validate(
        {
            "meta": {
                "paperId": paper_id,
                "version": version,
                "title": "A Paper",
                "provenance": {
                    "sourceTier": "ar5iv",
                    "parserVersion": "docmodel-parser@1",
                    "schemaVersion": "1.0.0",
                    "generatedAt": "2026-06-23T00:00:00Z",
                },
            },
            "sections": [
                {"id": "s1", "title": "Intro", "blocks": []},
            ],
        }
    )


class _FakeReader:
    def __init__(self, doc: DocModel | None) -> None:
        self._doc = doc

    def get_doc_model(self, paper_id: str, version: int) -> DocModel | None:
        return self._doc


class _SpyQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def enqueue_build(self, paper_id: str, version: int) -> None:
        self.calls.append((paper_id, version))


# --- orchestrator.doc_model lookup branches -------------------------------


def test_hit_returns_doc_without_enqueue() -> None:
    queue = _SpyQueue()
    orch = make_orchestrator(
        doc_model_reader=_FakeReader(_doc(version=2)), doc_model_build_queue=queue
    )
    result = orch.doc_model("2401.00001", 2)
    assert isinstance(result, DocModelLookup)
    assert result.doc is not None and result.building is False
    assert queue.calls == []  # cache hit → no build


def test_miss_with_queue_enqueues_and_signals_building() -> None:
    queue = _SpyQueue()
    orch = make_orchestrator(doc_model_reader=_FakeReader(None), doc_model_build_queue=queue)
    result = orch.doc_model("2401.00001", 4)
    assert result.doc is None
    assert result.building is True
    assert result.retry_after_ms is not None
    assert queue.calls == [("2401.00001", 4)]  # lazy build triggered


def test_miss_without_queue_stays_unavailable() -> None:
    orch = make_orchestrator(doc_model_reader=_FakeReader(None), doc_model_build_queue=None)
    result = orch.doc_model("2401.00001", 4)
    assert result.doc is None and result.building is False


def test_no_reader_returns_empty_lookup() -> None:
    result = make_orchestrator().doc_model("2401.00001", 1)
    assert result.doc is None and result.building is False


# --- SqsDocModelBuildQueue adapter ----------------------------------------


class _FakeSqs:
    def __init__(self, *, raises: bool = False) -> None:
        self.sent: list[dict] = []
        self._raises = raises

    def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict:
        if self._raises:
            raise RuntimeError("sqs down")
        import json

        self.sent.append({"url": QueueUrl, "body": json.loads(MessageBody)})
        return {"MessageId": "m1"}


def test_adapter_sends_build_job_in_u1_payload_shape() -> None:
    sqs = _FakeSqs()
    q = SqsDocModelBuildQueue(queue_url="https://q/url", client=sqs)
    q.enqueue_build("2401.00001", 2)
    assert len(sqs.sent) == 1
    body = sqs.sent[0]["body"]
    assert body["kind"] == "BUILD_DOC_MODEL"
    assert body["arxivRef"] == "2401.00001v2"
    assert body["jobId"].startswith("docmodel-2401.00001-v2-")


def test_adapter_dedups_rapid_repeat_enqueues() -> None:
    sqs = _FakeSqs()
    q = SqsDocModelBuildQueue(queue_url="https://q/url", client=sqs)
    q.enqueue_build("2401.00001", 2)
    q.enqueue_build("2401.00001", 2)  # within TTL → skipped
    q.enqueue_build("2401.00001", 3)  # different version → sent
    assert [b["body"]["arxivRef"] for b in sqs.sent] == ["2401.00001v2", "2401.00001v3"]


def test_adapter_enqueue_is_best_effort_on_send_failure() -> None:
    q = SqsDocModelBuildQueue(queue_url="https://q/url", client=_FakeSqs(raises=True))
    q.enqueue_build("2401.00001", 2)  # must not raise (read path stays up)


def test_adapter_strips_version_suffix_to_avoid_double_version_ref() -> None:
    # paper_id may already carry a version (2304.10557v1); the ref must not become
    # 2304.10557v1v1 — arXiv can't resolve a double-versioned ref, so the build never runs.
    sqs = _FakeSqs()
    q = SqsDocModelBuildQueue(queue_url="https://q/url", client=sqs)
    q.enqueue_build("2304.10557v1", 1)
    assert sqs.sent[0]["body"]["arxivRef"] == "2304.10557v1"


def test_adapter_dedups_across_raw_id_spellings_with_same_bare() -> None:
    # Two raw spellings that normalize to one ref (versioned vs bare, both v1) must share a
    # dedup bucket — the second is collapsed (dedup keys on the bare id, like the ref).
    sqs = _FakeSqs()
    q = SqsDocModelBuildQueue(queue_url="https://q/url", client=sqs)
    q.enqueue_build("2304.10557v1", 1)
    q.enqueue_build("2304.10557", 1)  # same bare+version → deduped, not re-sent
    assert [b["body"]["arxivRef"] for b in sqs.sent] == ["2304.10557v1"]
