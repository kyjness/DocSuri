from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass

from docsuri_ops.domain.models import BudgetState, TelemetryEvent
from docsuri_ops.incidents import (
    AiIncidentDetectorSuite,
    IncidentEventPublisher,
    PublishOutcome,
)
from docsuri_ops.ports import TelemetrySource


@dataclass(slots=True)
class WorkerResult:
    processed: int
    published: int


def run_once(
    events: Iterable[TelemetryEvent],
    suite: AiIncidentDetectorSuite,
    publisher: IncidentEventPublisher,
    *,
    budget_state: BudgetState | None = None,
) -> WorkerResult:
    processed = 0
    published = 0
    for event in events:
        processed += 1
        candidate = suite.evaluate(event, budget_state)
        if candidate is not None and (
            publisher.publish_candidate(candidate) is PublishOutcome.PUBLISHED
        ):
            published += 1
    return WorkerResult(processed=processed, published=published)


def run_polling_loop(
    source: TelemetrySource,
    suite: AiIncidentDetectorSuite,
    publisher: IncidentEventPublisher,
    *,
    max_messages: int = 10,
    interval_seconds: float = 1.0,
    stop_after: int | None = None,
) -> WorkerResult:
    total = WorkerResult(processed=0, published=0)
    iterations = 0
    while stop_after is None or iterations < stop_after:
        events = tuple(source.receive(max_messages=max_messages))
        processed = 0
        published = 0
        for event in events:
            processed += 1
            candidate = suite.evaluate(event)
            if candidate is None:
                source.ack(event)  # no incident — handled, safe to ack
                continue
            outcome = publisher.publish_candidate(candidate)
            if outcome is PublishOutcome.PUBLISHED:
                published += 1
                source.ack(event)  # newly published — ack
            elif outcome is PublishOutcome.DUPLICATE:
                source.ack(event)  # already recorded (idempotent) — ack, don't redeliver-loop
            # else FAILED: leave UN-acked so the source redelivers instead of silently dropping
            # the incident. Publish-before-commit (IncidentEventPublisher) makes this safe: nothing
            # was committed, so redelivery re-attempts cleanly. (PR #45 review + Finding 1)
        total = WorkerResult(
            processed=total.processed + processed,
            published=total.published + published,
        )
        iterations += 1
        if stop_after is None or iterations < stop_after:
            time.sleep(interval_seconds)
    return total


def main() -> int:
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
