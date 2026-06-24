"""Summarization async worker + queue (slice 5b, BR-S6/BR-S8): the API enqueues a long-summary
job, the worker reconstructs the request and runs map-reduce inline (allow_enqueue=False), and
the result write-throughs to the store. Covers payload round-trip, inline dispatch, the poll
loop, and the SqsSummaryJobQueue adapter (payload shape, dedup, best-effort)."""

from __future__ import annotations

from summarization.adapters.sqs_summary_job import SqsSummaryJobQueue
from summarization.domain.models import Persona, Scope, SummaryRequest, Task
from summarization.worker import process_job, request_from_payload, run_worker

_PAYLOAD = {
    "userId": "u1",
    "paperId": "2401.1",
    "version": 2,
    "task": "summary",
    "targetLang": "ko",
    "persona": "expert",
    "scope": "abstract",
    "abstract": None,
}


def test_request_from_payload_roundtrip() -> None:
    request, user_id = request_from_payload(_PAYLOAD)
    assert user_id == "u1"
    assert request.paper_id == "2401.1"
    assert request.version == 2
    assert request.task is Task.SUMMARY


class _Orch:
    def __init__(self) -> None:
        self.runs: list[tuple[str, str, bool]] = []

    def run(self, request, ctx, *, allow_enqueue=True):
        self.runs.append((request.paper_id, ctx.auth_session.user_id, allow_enqueue))


def test_process_job_runs_inline_no_reenqueue() -> None:
    orch = _Orch()
    process_job(orch, _PAYLOAD)
    assert orch.runs == [("2401.1", "u1", False)]  # worker path: allow_enqueue=False


class _Msg:
    def __init__(self, body: dict) -> None:
        self.body = body


def test_run_worker_processes_then_acks() -> None:
    orch = _Orch()
    acked: list[_Msg] = []
    state = {"polls": 0}

    def receive():
        state["polls"] += 1
        return [_Msg(_PAYLOAD), _Msg(_PAYLOAD)] if state["polls"] == 1 else []

    run_worker(
        orch,
        receive=receive,
        ack=acked.append,
        should_stop=lambda: state["polls"] >= 2,
    )
    assert len(orch.runs) == 2
    assert len(acked) == 2  # both processed jobs acked


def test_run_worker_leaves_failed_job_unacked() -> None:
    class _Boom(_Orch):
        def run(self, request, ctx, *, allow_enqueue=True):
            raise RuntimeError("llm down")

    acked: list[_Msg] = []
    state = {"polls": 0}

    def receive():
        state["polls"] += 1
        return [_Msg(_PAYLOAD)] if state["polls"] == 1 else []

    run_worker(_Boom(), receive=receive, ack=acked.append, should_stop=lambda: state["polls"] >= 2)
    assert acked == []  # failed job is NOT acked → redelivery


# --- SqsSummaryJobQueue adapter -------------------------------------------


class _FakeSqs:
    def __init__(self, *, raises: bool = False) -> None:
        self.sent: list[dict] = []
        self._raises = raises

    def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict:
        if self._raises:
            raise RuntimeError("sqs down")
        import json

        self.sent.append(json.loads(MessageBody))
        return {"MessageId": "m1"}


def _req(version: int = 1) -> SummaryRequest:
    return SummaryRequest(
        paper_id="2401.1", version=version, task=Task.SUMMARY, persona=Persona.EXPERT,
        scope=Scope.ABSTRACT,
    )


def test_queue_sends_job_with_user_and_request() -> None:
    sqs = _FakeSqs()
    q = SqsSummaryJobQueue(queue_url="https://q", client=sqs)
    q.enqueue(_req(version=2), "u1")
    assert len(sqs.sent) == 1
    body = sqs.sent[0]
    assert body["userId"] == "u1"
    assert body["paperId"] == "2401.1"
    assert body["version"] == 2
    assert body["task"] == "summary"


def test_queue_dedups_rapid_repeat_for_same_request() -> None:
    sqs = _FakeSqs()
    q = SqsSummaryJobQueue(queue_url="https://q", client=sqs)
    q.enqueue(_req(), "u1")
    q.enqueue(_req(), "u1")  # same (user, request) within TTL → skipped
    q.enqueue(_req(), "u2")  # different user → sent
    assert [b["userId"] for b in sqs.sent] == ["u1", "u2"]


def test_queue_enqueue_is_best_effort() -> None:
    q = SqsSummaryJobQueue(queue_url="https://q", client=_FakeSqs(raises=True))
    q.enqueue(_req(), "u1")  # must not raise (request path stays up)
