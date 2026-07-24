"""LocalSummaryJobQueue — the in-process SummaryJobQueuePort (no SQS).

Mirrors the SqsSummaryJobQueue contracts in test_summary_worker.py: a job actually runs, rapid
repeats of the same (user, request) collapse, and enqueue never raises at the caller. The two
extras here come from running the job in-process rather than handing it to a queue — the job must
be run with ``allow_enqueue=False`` (or it would enqueue itself forever), and a failed job must
release its dedup claim so the still-polling client can trigger another attempt.
"""

from __future__ import annotations

import threading
import time

from summarization.adapters.local_summary_job import LocalSummaryJobQueue
from summarization.domain.models import Persona, Scope, SummaryRequest, Task


class _Orch:
    """Records runs; optionally blocks or fails, to exercise the claim lifecycle."""

    def __init__(self, *, raises: bool = False) -> None:
        self.runs: list[tuple[str, str, bool]] = []
        self.done = threading.Event()
        self.release = threading.Event()
        self._raises = raises

    def run(self, request, ctx, *, allow_enqueue=True):
        self.release.wait(timeout=2)
        self.runs.append((request.paper_id, ctx.auth_session.user_id, allow_enqueue))
        self.done.set()
        if self._raises:
            raise RuntimeError("generation failed")


def _req(version: int = 1) -> SummaryRequest:
    return SummaryRequest(
        paper_id="2401.1",
        version=version,
        task=Task.SUMMARY,
        persona=Persona.EXPERT,
        scope=Scope.ABSTRACT,
    )


def _queue(orch: _Orch) -> LocalSummaryJobQueue:
    q = LocalSummaryJobQueue()
    q.bind(orch)
    return q


def test_job_runs_on_the_worker_path_not_the_request_path() -> None:
    # allow_enqueue=False is what makes this a job: left on, the orchestrator would see the same
    # long input and enqueue it again, forever.
    orch = _Orch()
    q = _queue(orch)
    orch.release.set()
    q.enqueue(_req(version=2), "u1")
    assert orch.done.wait(timeout=2)
    assert orch.runs == [("2401.1", "u1", False)]


def test_repeat_while_running_collapses_but_another_user_still_runs() -> None:
    # A polling client re-sends the same request every few seconds; each poll reaches enqueue.
    # Without the claim, every poll would start another billed generation of the same artifact.
    orch = _Orch()
    q = _queue(orch)
    q.enqueue(_req(), "u1")
    q.enqueue(_req(), "u1")  # still claimed → collapsed
    q.enqueue(_req(), "u2")  # different owner → its own job
    orch.release.set()
    q._executor.shutdown(wait=True)
    assert sorted(u for _, u, _ in orch.runs) == ["u1", "u2"]


def test_job_running_past_its_ttl_is_not_double_run() -> None:
    # A generation that outlives the dedup TTL keeps its claim via _running: a poll arriving while
    # it is still executing collapses instead of starting a SECOND billed generation. ttl=0 makes
    # the expiry lapse immediately, standing in for a job that ran longer than the backstop.
    orch = _Orch()  # blocks in run() until release is set
    q = LocalSummaryJobQueue(dedup_ttl_seconds=0)
    q.bind(orch)
    q.enqueue(_req(), "u1")
    # Wait until the job is actually executing (its key is in _running) — its TTL already lapsed.
    running = False
    for _ in range(200):
        with q._lock:
            running = bool(q._running)
        if running:
            break
        time.sleep(0.005)
    assert running, "job never started running"

    q.enqueue(_req(), "u1")  # same key, still running → must collapse despite the lapsed TTL
    orch.release.set()
    q._executor.shutdown(wait=True)
    assert len(orch.runs) == 1  # not double-run


def test_failed_job_releases_its_claim_so_the_client_can_retry() -> None:
    # Holding the claim after a failure would make a transient error look permanent for the whole
    # TTL — the client is still polling and would never get another attempt.
    orch = _Orch(raises=True)
    q = _queue(orch)
    orch.release.set()
    q.enqueue(_req(), "u1")
    q._executor.shutdown(wait=True)
    assert q._inflight == {}


def test_enqueue_never_raises_at_the_caller() -> None:
    # Best-effort port contract: a queue problem degrades the response, it does not 500 the
    # request. An unbound queue is the reachable case — wiring built it but never bound it.
    LocalSummaryJobQueue().enqueue(_req(), "u1")

    orch = _Orch()
    q = _queue(orch)
    q._executor.shutdown(wait=True)  # pool gone → submit raises RuntimeError internally
    q.enqueue(_req(), "u1")
    assert orch.runs == []
    assert q._inflight == {}  # claim released, not leaked
