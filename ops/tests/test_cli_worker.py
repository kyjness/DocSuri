from __future__ import annotations

import json

from docsuri_ops.adapters.local import (
    CapturingAlertPublisher,
    InMemoryIncidentStore,
    InMemoryTelemetrySource,
)
from docsuri_ops.cli import main
from docsuri_ops.domain.enums import SignalKind
from docsuri_ops.domain.models import TelemetryEvent
from docsuri_ops.incidents import AiIncidentDetectorSuite, IncidentEventPublisher
from docsuri_ops.worker import run_once, run_polling_loop


def test_worker_run_once_publishes_detected_incidents() -> None:
    store = InMemoryIncidentStore()
    sink = CapturingAlertPublisher()
    publisher = IncidentEventPublisher(store, sink)
    event = TelemetryEvent(
        event_id="partial-cli",
        kind=SignalKind.PARTIAL_RESULT,
        request_id="req-partial",
        payload={"status": "success", "resultCount": 0, "cards": []},
    )

    result = run_once([event], AiIncidentDetectorSuite(), publisher)

    assert result.processed == 1
    assert result.published == 1
    assert len(sink.incidents) == 1


def test_polling_loop_uses_telemetry_source_receive_and_ack_contract() -> None:
    store = InMemoryIncidentStore()
    sink = CapturingAlertPublisher()
    publisher = IncidentEventPublisher(store, sink)
    event = TelemetryEvent(
        event_id="partial-source",
        kind=SignalKind.PARTIAL_RESULT,
        request_id="req-source",
        payload={"status": "success", "resultCount": 0, "cards": []},
    )
    source = InMemoryTelemetrySource()
    source.queued.append(event)

    result = run_polling_loop(
        source,
        AiIncidentDetectorSuite(),
        publisher,
        max_messages=1,
        stop_after=1,
    )

    assert result.processed == 1
    assert result.published == 1
    assert source.acked == ["partial-source"]


def test_polling_loop_does_not_ack_events_whose_publish_fails() -> None:
    # PR #45 review: a publish failure must NOT be acked, else the incident is silently lost.
    store = InMemoryIncidentStore()
    sink = CapturingAlertPublisher(fail=True)  # publish_incident/alert return False
    publisher = IncidentEventPublisher(store, sink)
    event = TelemetryEvent(
        event_id="partial-fail",
        kind=SignalKind.PARTIAL_RESULT,
        request_id="req-fail",
        payload={"status": "success", "resultCount": 0, "cards": []},
    )
    source = InMemoryTelemetrySource()
    source.queued.append(event)

    result = run_polling_loop(
        source,
        AiIncidentDetectorSuite(),
        publisher,
        max_messages=1,
        stop_after=1,
    )

    assert result.published == 0
    assert source.acked == []  # left un-acked for redelivery


def test_polling_loop_acks_duplicate_redelivery_instead_of_looping() -> None:
    # Finding 1: a redelivered duplicate (same incident, new message id) must be acked, not left
    # un-acked like a transient failure — else a real redelivering source loops forever (poison).
    store = InMemoryIncidentStore()
    sink = CapturingAlertPublisher()
    publisher = IncidentEventPublisher(store, sink)
    payload = {"status": "success", "resultCount": 0, "cards": []}
    first = TelemetryEvent(
        event_id="dup-1",
        kind=SignalKind.PARTIAL_RESULT,
        request_id="req-dup",
        payload=payload,
    )
    # New event_id so the detector's own dedup doesn't short-circuit it to "no incident", but the
    # SAME request_id + reason → same incident dedup key → the publisher sees it as a duplicate.
    redelivered = TelemetryEvent(
        event_id="dup-2",
        kind=SignalKind.PARTIAL_RESULT,
        request_id="req-dup",
        payload=payload,
    )
    source = InMemoryTelemetrySource()
    source.queued.extend([first, redelivered])

    result = run_polling_loop(
        source,
        AiIncidentDetectorSuite(),
        publisher,
        max_messages=2,
        stop_after=1,
    )

    assert result.published == 1  # only the first is a NEW incident
    assert source.acked == ["dup-1", "dup-2"]  # BOTH acked — the duplicate isn't retried forever
    assert len(store.incidents) == 1


def test_cli_reliability_eval_outputs_json(capsys) -> None:
    assert main(["run-reliability-eval"]) == 0

    payload = json.loads(capsys.readouterr().out)

    assert payload == {"caseCount": 2, "degradedBehaviorOk": True}
