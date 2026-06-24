"""SqsDocModelBuildQueue — real ``DocModelBuildQueuePort`` (BR-30/D6, boundary B).

On a doc-model read miss the orchestrator enqueues a ``BUILD_DOC_MODEL`` job onto U1's
ingestion queue; the U1 worker fetches the source and produces ``doc-model/{id}/v{ver}.json``.
The read side never imports the builder — it only sends a message in the shape U1's
``job_from_payload`` expects (``jobId``/``kind``/``arxivRef``).

Duplicate enqueues are bounded two ways: (1) a best-effort in-process TTL guard collapses the
rapid repeat polls a single warm instance sees, and (2) the producer is idempotent — a cache
hit short-circuits the build — so a cross-instance duplicate only costs a cheap no-op build.
Enqueue is best-effort: any failure is swallowed (logged) so the read path degrades to
``source_unavailable`` rather than 500 (the client simply retries).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

_DEFAULT_DEDUP_TTL_SECONDS = 120  # ~ expected build window; bounds rapid re-enqueues.


class SqsDocModelBuildQueue:
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
        # (paper_id, version) -> monotonic expiry. Best-effort, per-instance.
        self._inflight: dict[tuple[str, int], float] = {}

    def enqueue_build(self, paper_id: str, version: int) -> None:
        now = time.monotonic()
        self._prune(now)
        key = (paper_id, version)
        expiry = self._inflight.get(key)
        if expiry is not None and expiry > now:
            return  # already enqueued recently on this instance — skip (dedup)
        body = json.dumps(
            {
                "jobId": f"docmodel-{paper_id}-v{version}-{uuid4().hex[:8]}",
                "kind": "BUILD_DOC_MODEL",
                # U1 normalizes/validates this ref (rejects malformed → DLQ), so it is the
                # only field that carries the external paper_id, and only into a JSON body.
                "arxivRef": f"{paper_id}v{version}",
                "eventId": None,
                "correlationId": None,
            }
        )
        try:
            self._sqs.send_message(QueueUrl=self._queue_url, MessageBody=body)
        except Exception:  # noqa: BLE001 — enqueue is best-effort; never 500 the read path.
            logger.warning("doc-model build enqueue failed for %sv%s", paper_id, version)
            return
        self._inflight[key] = now + self._ttl

    def _prune(self, now: float) -> None:
        if len(self._inflight) < 256:
            return
        self._inflight = {k: v for k, v in self._inflight.items() if v > now}
