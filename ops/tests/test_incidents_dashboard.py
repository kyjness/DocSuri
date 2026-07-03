from __future__ import annotations

from datetime import timedelta

from docsuri_ops.adapters.local import CapturingAlertPublisher, InMemoryIncidentStore
from docsuri_ops.dashboard import OpsDashboardService
from docsuri_ops.domain.enums import IncidentClass, Severity, SignalKind
from docsuri_ops.domain.models import (
    AlertRecord,
    ClassifiedIncidentRecord,
    DashboardWindow,
    IncidentCandidate,
    TelemetryEvent,
    utc_now,
)
from docsuri_ops.incidents import (
    AiIncidentDetectorSuite,
    IncidentEventPublisher,
    PublishOutcome,
)


def test_incident_suite_classifies_three_res11_classes() -> None:
    suite = AiIncidentDetectorSuite()

    records = [
        suite.classify(
            IncidentCandidate(
                incident_class=IncidentClass.COST_EXPLOSION,
                severity=Severity.WARNING,
                request_id="req-cost",
                reason="cost",
                signal_id="sig-cost",
            )
        ),
        suite.classify(
            IncidentCandidate(
                incident_class=IncidentClass.HALLUCINATION,
                severity=Severity.CRITICAL,
                request_id="req-hallucination",
                reason="hallucination",
                signal_id="sig-hallucination",
            )
        ),
        suite.classify(
            IncidentCandidate(
                incident_class=IncidentClass.PARTIAL_RESULT,
                severity=Severity.WARNING,
                request_id="req-partial",
                reason="partial",
                signal_id="sig-partial",
            )
        ),
    ]

    assert [record.incident_class.value for record in records] == ["a", "b", "c"]


def test_incident_publisher_emits_shared_events_and_suppresses_duplicates() -> None:
    store = InMemoryIncidentStore()
    sink = CapturingAlertPublisher()
    publisher = IncidentEventPublisher(store, sink)
    candidate = IncidentCandidate(
        incident_class=IncidentClass.COST_EXPLOSION,
        severity=Severity.WARNING,
        request_id="req-cost",
        reason="monthly cost threshold exceeded",
        signal_id="sig-cost",
    )

    assert publisher.publish_candidate(candidate) is PublishOutcome.PUBLISHED
    # A redelivered duplicate is an idempotent success (ack-able), not a failure. (Finding 1)
    assert publisher.publish_candidate(candidate) is PublishOutcome.DUPLICATE

    assert len(store.incidents) == 1
    assert len(store.alerts) == 1
    assert len(sink.incidents) == 1
    assert sink.incidents[0].class_.value == "a"
    assert len(sink.alerts) == 1


def test_dashboard_aggregates_windowed_incidents_and_alerts() -> None:
    store = InMemoryIncidentStore()
    now = utc_now()
    store.append_incident(
        ClassifiedIncidentRecord(
            incident_class=IncidentClass.HALLUCINATION,
            severity=Severity.CRITICAL,
            request_id="req-1",
            reason="grounding",
            timestamp=now,
        )
    )
    store.append_alert(
        AlertRecord(
            severity=Severity.CRITICAL,
            request_id="req-1",
            reason="grounding",
            timestamp=now,
        )
    )
    dashboard = OpsDashboardService(store)

    view = dashboard.get_dashboard(
        DashboardWindow(now - timedelta(minutes=1), now + timedelta(minutes=1))
    )

    assert view.incident_count == 1
    assert view.alert_count == 1
    assert dashboard.summarize_by_class(view.window) == {"a": 0, "b": 1, "c": 0}


def test_dashboard_metrics_none_for_write_only_store() -> None:
    """A write-only event store (supports_readback=False, e.g. CloudWatch) can't be read back,
    so the dashboard reports None for event-derived metrics rather than fabricating zeros that
    read as 'healthy/quiet'. (US-R4)"""

    class _WriteOnly:
        supports_readback = False

        def list_events(self):
            return []

    now = utc_now()
    view = OpsDashboardService(InMemoryIncidentStore(), event_store=_WriteOnly()).get_dashboard(
        DashboardWindow(now - timedelta(hours=1), now)
    )

    assert view.latency_p95 is None
    assert view.error_rate is None
    assert view.throughput is None
    assert view.grounding_health is None


def test_grounding_event_without_verdict_raises_incident_fail_closed() -> None:
    # Finding 3: a malformed GROUNDING telemetry event (no verdict) must NOT be silently treated
    # as "pass" — it defaults to abstain, so a hallucination incident is raised (fail-closed).
    suite = AiIncidentDetectorSuite()
    event = TelemetryEvent(
        event_id="gnd-noverdict",
        kind=SignalKind.GROUNDING,
        request_id="req-gnd",
        payload={},  # no "verdict" key
    )

    candidate = suite.evaluate(event)

    assert candidate is not None
    assert candidate.incident_class == IncidentClass.HALLUCINATION


def test_usage_event_uses_zero_value_not_payload_fallback() -> None:
    # Finding 5: a real 0.0 usage value must be used as 0.0, not treated as falsy and replaced by
    # payload["amountUsd"]. A $0 event is below every threshold → no incident.
    suite = AiIncidentDetectorSuite()
    event = TelemetryEvent(
        event_id="usage-zero",
        kind=SignalKind.USAGE,
        request_id="req-usage",
        value=0.0,
        payload={"amountUsd": 999.0},  # would trip the spike threshold if wrongly used
    )

    assert suite.evaluate(event) is None
