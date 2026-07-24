"""LocalSummaryJobQueue — in-process ``SummaryJobQueuePort`` for a single-process deployment.

The orchestrator only returns ``pending`` when a job queue is wired; otherwise it runs the long
generation inline on the request thread. Deployed, that queue was SQS with its own worker process,
so a full-paper summary or translation went to the background and the client polled. With no SQS
there is nothing to enqueue to, so the same work ran inline and blew the client's deadline — the
request was reported as failed while the backend kept going and cached the result, making the
retry look instant. Nothing signalled the fallback.

This adapter closes that gap without SQS: it runs the job on a small thread pool in the same
process, against the same orchestrator and therefore the same store. That is all the poll needs —
``PendingDTO`` carries no job id, so the client simply re-reads the cache key until the write-
through lands. It mirrors ``_DirectHistoryPublisher`` in ``backend/wiring.py``, the in-process
stand-in for EventBridge, and is the same shape: fire-and-forget submit, failures logged, never
raised at the caller.

Not a substitute for the deployed worker: a restart loses in-flight jobs (the next poll re-queues
them) and the pool is per-process, so this is for a single-process local/dev run.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from ..domain.models import SummaryRequest
from .summary_job_dedup import prune_inflight, summary_job_dedup_key

if TYPE_CHECKING:  # pragma: no cover — import cycle: the orchestrator constructs this adapter.
    from ..service.orchestrator import SummarizationOrchestrationService

logger = logging.getLogger(__name__)

# Backstop only. A job releases its key the moment it finishes, so this bounds the entry left
# behind by a process that dies mid-job — long enough to outlast a real generation, short enough
# that the user is not locked out of retrying for the rest of the session.
_DEFAULT_DEDUP_TTL_SECONDS = 900


class LocalSummaryJobQueue:
    def __init__(self, *, dedup_ttl_seconds: int = _DEFAULT_DEDUP_TTL_SECONDS) -> None:
        # A single worker thread. The queue exists to lift the long generation OFF the request
        # thread (so the API can answer ``pending``), not to run generations in parallel — one
        # background thread does that. Running several at once would call the one shared
        # orchestrator concurrently from multiple pool threads, a concurrency the deployed
        # separate-process worker never exercised and whose safety is unaudited; so it stays 1.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="summary-job")
        self._ttl = dedup_ttl_seconds
        # Both request threads (enqueue) and pool threads (release) touch these, unlike the SQS
        # adapter where only the request path does — hence the lock.
        self._lock = threading.Lock()
        self._inflight: dict[str, float] = {}
        # Keys whose job is currently executing. Treated as claimed by enqueue regardless of the
        # expiry backstop, so a generation that outlives the TTL is not double-run by a concurrent
        # poll (the expiry alone would have lapsed).
        self._running: set[str] = set()
        self._orchestrator: SummarizationOrchestrationService | None = None

    def bind(self, orchestrator: SummarizationOrchestrationService) -> None:
        """Attach the orchestrator that runs the jobs.

        Late-bound because the orchestrator takes this queue as a constructor argument, so the
        queue has to exist first. Until it is called, ``enqueue`` degrades to a no-op rather than
        silently dropping work with no trace.
        """
        self._orchestrator = orchestrator

    def enqueue(self, request: SummaryRequest, user_id: str) -> None:
        orchestrator = self._orchestrator
        if orchestrator is None:
            logger.warning(
                "local summary job queue is unbound; dropped job for %s/%s",
                request.paper_id,
                user_id,
            )
            return
        key = summary_job_dedup_key(request, user_id)
        now = time.monotonic()
        # Claim the key before submitting: a poll arriving while the job is still queued must see
        # it as taken, or the pool would hold several generations of the same artifact. A job that
        # runs past its TTL backstop is still claimed via ``_running`` — the expiry alone would have
        # lapsed and let a concurrent poll double-run the same billed generation.
        with self._lock:
            self._inflight = prune_inflight(self._inflight, now)
            expiry = self._inflight.get(key)
            if key in self._running or (expiry is not None and expiry > now):
                return
            self._inflight[key] = now + self._ttl
        try:
            self._executor.submit(self._run, key, orchestrator, request, user_id)
        except RuntimeError:  # pool already shut down (interpreter teardown)
            self._release(key)
            logger.warning("local summary job executor unavailable; dropped %s", request.paper_id)

    def _run(
        self,
        key: str,
        orchestrator: SummarizationOrchestrationService,
        request: SummaryRequest,
        user_id: str,
    ) -> None:
        with self._lock:
            self._running.add(key)
        try:
            from ..worker import run_job  # local import — worker imports the orchestrator type

            run_job(orchestrator, request, user_id)
        except Exception:  # noqa: BLE001 — a failed job (or a failed import) must not kill the
            # pool thread, and the finally below must still release the claim either way.
            logger.exception("local summary job failed for %s/%s", request.paper_id, user_id)
        finally:
            # Release on failure too: the client is still polling, and holding the key would make
            # a transient failure look like a permanent one for the rest of the TTL.
            self._release(key)

    def _release(self, key: str) -> None:
        with self._lock:
            self._inflight.pop(key, None)
            self._running.discard(key)
