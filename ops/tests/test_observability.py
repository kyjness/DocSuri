from __future__ import annotations

from docsuri_ops.adapters.local import InMemoryEventStore
from docsuri_ops.domain.enums import SignalKind
from docsuri_ops.domain.models import TelemetryEvent
from docsuri_ops.observability import ObservabilityHub, redact


def test_redact_removes_sensitive_keys_and_emails() -> None:
    payload = {
        "email": "researcher@example.com",
        "nested": {"token": "secret-token", "message": "contact a@b.com"},
    }

    assert redact(payload) == {
        "email": "[REDACTED]",
        "nested": {"token": "[REDACTED]", "message": "contact [REDACTED_EMAIL]"},
    }


def test_redact_normalizes_sensitive_key_variants() -> None:
    # camelCase / snake_case / kebab variants collapse to the same normalized name, so a value
    # can't slip past by renaming the field. (US-R4 review: ownerId/owner_id were a redaction gap)
    payload = {
        "ownerId": "acct-1",
        "owner_id": "acct-2",
        "access_token": "abc",
        "apiKey": "k",
        "Session-Id": "s",
        "tokenCount": 7,  # NOT a secret — exact-after-normalize match must leave it intact
    }

    assert redact(payload) == {
        "ownerId": "[REDACTED]",
        "owner_id": "[REDACTED]",
        "access_token": "[REDACTED]",
        "apiKey": "[REDACTED]",
        "Session-Id": "[REDACTED]",
        "tokenCount": 7,
    }


def test_observability_log_preserves_request_id_and_redacts() -> None:
    store = InMemoryEventStore()
    hub = ObservabilityHub(store)

    hub.emit_log({"eventId": "log-1", "requestId": "req-1", "password": "nope"})

    assert len(store.events) == 1
    event = store.events[0]
    assert event.request_id == "req-1"
    assert event.payload["password"] == "[REDACTED]"


def test_audit_is_append_only() -> None:
    store = InMemoryEventStore()
    hub = ObservabilityHub(store)

    hub.audit_append({"eventId": "audit-1", "action": "authorize", "user_id": "u1"})
    hub.audit_append({"eventId": "audit-2", "action": "authorize", "user_id": "u1"})

    assert [event["eventId"] for event in store.audit_events] == ["audit-1", "audit-2"]
    assert all(event["user_id"] == "[REDACTED]" for event in store.audit_events)


def test_duplicate_event_id_is_idempotent() -> None:
    store = InMemoryEventStore()
    event = TelemetryEvent(event_id="same", kind=SignalKind.METRIC, name="x", value=1.0)

    assert store.append(event)
    assert not store.append(event)
    assert len(store.events) == 1


def test_dedup_window_is_bounded_lru(monkeypatch) -> None:
    """_seen is a bounded LRU — it never exceeds the window and only the OLDEST keys are evicted,
    so recent duplicates still dedup. Guards the per-request-metric memory leak. (US-R4)"""
    import docsuri_ops.adapters.local as local

    monkeypatch.setattr(local, "_MAX_SEEN", 3)
    store = InMemoryEventStore()

    def ev(eid: str) -> TelemetryEvent:
        return TelemetryEvent(event_id=eid, kind=SignalKind.METRIC, name="m", value=1.0)

    for eid in ["a", "b", "c", "d", "e"]:  # 5 unique ids > window of 3
        assert store.append(ev(eid)) is True
    assert len(store._seen) <= 3  # bounded — does NOT grow with unique events
    assert store.append(ev("e")) is False  # recent → still deduped
    assert store.append(ev("a")) is True  # oldest was evicted → re-accepted (bounded, not a leak)


class _FakeCw:
    """Records put_metric_data calls — each call's MetricData list is one batch."""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    def put_metric_data(self, *, Namespace, MetricData) -> None:  # noqa: N803 (boto3 kwarg names)
        self.calls.append(MetricData)


def test_cloudwatch_append_is_nonblocking_and_flush_ships(monkeypatch) -> None:
    """append() enqueues (no boto3 in the caller's thread) and the background worker ships on
    flush() — so the async gateway never blocks the event loop on PutMetricData. (US-R4)"""
    from docsuri_ops.adapters.cloudwatch import CloudWatchEventStore

    fake = _FakeCw()
    monkeypatch.setattr(CloudWatchEventStore, "_get_cw", lambda self: fake)
    store = CloudWatchEventStore(namespace="Test")
    try:
        assert store.append(
            TelemetryEvent(event_id="m1", kind=SignalKind.METRIC, name="x", value=1.0)
        ) is True
        store.flush()  # block until the worker drains the queue
        assert [d["MetricName"] for md in fake.calls for d in md] == ["x"]
    finally:
        store.close()


def test_cloudwatch_batches_metric_data(monkeypatch) -> None:
    """A burst of metric events ships as ONE PutMetricData call with many MetricData entries,
    not one call per metric — cuts the per-request API/cost multiplier. (US-R4)"""
    from docsuri_ops.adapters.cloudwatch import CloudWatchEventStore

    fake = _FakeCw()
    monkeypatch.setattr(CloudWatchEventStore, "_get_cw", lambda self: fake)
    store = CloudWatchEventStore(namespace="Test")
    try:
        events = [
            TelemetryEvent(event_id=f"m{i}", kind=SignalKind.METRIC, name="x", value=1.0)
            for i in range(5)
        ]
        store._ship_batch(events)  # exercise batching directly (deterministic, no queue race)
        assert len(fake.calls) == 1  # 5 metrics → ONE PutMetricData call
        assert len(fake.calls[0]) == 5  # carrying 5 MetricData entries
    finally:
        store.close()


def test_put_metrics_chunks_at_batch_size(monkeypatch) -> None:
    """More than _METRIC_BATCH metrics split into multiple PutMetricData calls (stay under the
    API's per-call ceiling) without dropping any. (US-R4)"""
    import docsuri_ops.adapters.cloudwatch as cw

    monkeypatch.setattr(cw, "_METRIC_BATCH", 2)
    fake = _FakeCw()
    monkeypatch.setattr(cw.CloudWatchEventStore, "_get_cw", lambda self: fake)
    store = cw.CloudWatchEventStore(namespace="Test")
    try:
        events = [
            TelemetryEvent(event_id=f"m{i}", kind=SignalKind.METRIC, name="x", value=1.0)
            for i in range(5)
        ]
        store._ship_batch(events)
        assert len(fake.calls) == 3  # ceil(5 / 2) chunks
        assert sum(len(md) for md in fake.calls) == 5  # nothing dropped
    finally:
        store.close()


def test_worker_survives_ship_error(monkeypatch) -> None:
    """An unexpected error in _ship_batch must NOT kill the worker — a dead daemon would lose all
    later telemetry and hang flush()/close(). The next event must still be processed. (US-R4)"""
    from docsuri_ops.adapters.cloudwatch import CloudWatchEventStore

    shipped: list[str] = []
    calls = {"n": 0}

    def flaky(self, events) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")  # unexpected worker error on the first batch
        shipped.extend(e.event_id for e in events)

    monkeypatch.setattr(CloudWatchEventStore, "_ship_batch", flaky)
    store = CloudWatchEventStore(namespace="Test")
    try:
        store.append(TelemetryEvent(event_id="a", kind=SignalKind.METRIC, name="x", value=1.0))
        store.flush()  # first batch raised — worker must survive (flush still returns)
        store.append(TelemetryEvent(event_id="b", kind=SignalKind.METRIC, name="x", value=1.0))
        store.flush()
        assert "b" in shipped  # worker processed a later event → it stayed alive
    finally:
        store.close()
