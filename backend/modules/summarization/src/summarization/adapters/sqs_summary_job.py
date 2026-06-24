"""SqsSummaryJobQueue — real ``SummaryJobQueuePort`` (BR-S6/BR-S8, #135).

On the MAP_REDUCE band the orchestrator enqueues a summary job here and returns ``pending``
instead of running the 3-5 map-reduce LLM calls inline (which would blow the request/gateway
timeout). The summarization worker consumes the job, runs the summary inline, and write-throughs
the result to the shared store — so the client's next poll hits the cache.

The job payload carries the whole ``SummaryRequest`` plus the owner ``userId`` (needed to
resolve the personal glossary + cache key) so the worker can faithfully reconstruct the request.
Duplicate enqueues from rapid polling are collapsed by a best-effort in-process TTL guard;
the cache write-through is the real idempotency backstop. Enqueue is best-effort: any failure
is swallowed (logged) so the request path never 500s.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import uuid4

from ..domain.models import SummaryRequest

logger = logging.getLogger(__name__)

_DEFAULT_DEDUP_TTL_SECONDS = 90  # ~ expected map-reduce job window; bounds rapid re-enqueues.


class SqsSummaryJobQueue:
    def __init__(
        self,
        *,
        queue_url: str,
        region_name: str | None = None,
        client: Any | None = None,
        dedup_ttl_seconds: int = _DEFAULT_DEDUP_TTL_SECONDS,
    ) -> None:
        if client is None:
            import boto3  # lazy

            client = boto3.client("sqs", region_name=region_name)
        self._sqs = client
        self._queue_url = queue_url
        self._ttl = dedup_ttl_seconds
        self._inflight: dict[str, float] = {}

    def enqueue(self, request: SummaryRequest, user_id: str) -> None:
        now = time.monotonic()
        self._prune(now)
        key = self._dedup_key(request, user_id)
        expiry = self._inflight.get(key)
        if expiry is not None and expiry > now:
            return  # already enqueued recently on this instance — skip (dedup)
        body = json.dumps(self._payload(request, user_id))
        try:
            self._sqs.send_message(QueueUrl=self._queue_url, MessageBody=body)
        except Exception:  # noqa: BLE001 — enqueue is best-effort; never 500 the request path.
            logger.warning("summary job enqueue failed for %s/%s", request.paper_id, user_id)
            return
        self._inflight[key] = now + self._ttl

    @staticmethod
    def _payload(request: SummaryRequest, user_id: str) -> dict:
        return {
            "jobId": f"summary-{request.paper_id}-v{request.version}-{uuid4().hex[:8]}",
            "userId": user_id,
            "paperId": request.paper_id,
            "version": request.version,
            "task": request.task.value,
            "targetLang": request.target_lang.value,
            "persona": request.persona.value,
            "scope": request.scope.value,
            "abstract": request.abstract,
        }

    @staticmethod
    def _dedup_key(request: SummaryRequest, user_id: str) -> str:
        return "|".join(
            [
                user_id,
                request.paper_id,
                str(request.version),
                request.task.value,
                request.persona.value,
                request.scope.value,
                request.target_lang.value,
            ]
        )

    def _prune(self, now: float) -> None:
        if len(self._inflight) < 256:
            return
        self._inflight = {k: v for k, v in self._inflight.items() if v > now}
