from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field

from docsuri_shared.events import ClassifiedIncident, OpsAlert

from docsuri_ops._dedup import BoundedSeen
from docsuri_ops.domain.models import AlertRecord, ClassifiedIncidentRecord, TelemetryEvent

# Cap the in-memory event buffer so a long-running non-CloudWatch process (dev/staging) can't
# grow it without bound; the dashboard only aggregates a recent window, so dropping the oldest
# events is harmless. ponytail: bump if a wider dashboard window is ever needed. (US-R4)
_MAX_EVENTS = 50_000
# Bounded dedup window (LRU): preserves idempotency for redelivered events while capping memory
# — per-request metric emission carries random event_ids that would otherwise grow _seen forever.
_MAX_SEEN = 100_000


@dataclass(slots=True)
class InMemoryEventStore:
    events: deque[TelemetryEvent] = field(default_factory=lambda: deque(maxlen=_MAX_EVENTS))
    audit_events: list[dict] = field(default_factory=list)
    _seen: OrderedDict[str, None] = field(default_factory=OrderedDict)

    def append(self, event: TelemetryEvent) -> bool:
        if event.dedup_key in self._seen:
            return False
        self._seen[event.dedup_key] = None
        if len(self._seen) > _MAX_SEEN:
            self._seen.popitem(last=False)  # evict oldest — bound the dedup window (US-R4)
        self.events.append(event)
        return True

    def append_audit(self, event: dict) -> None:
        self.audit_events.append(dict(event))

    def list_events(self) -> list[TelemetryEvent]:
        return list(self.events)


@dataclass(slots=True)
class InMemoryIncidentStore:
    incidents: list[ClassifiedIncidentRecord] = field(default_factory=list)
    alerts: list[AlertRecord] = field(default_factory=list)
    _incident_seen: BoundedSeen = field(default_factory=BoundedSeen)  # bounded LRU dedup
    _alert_seen: BoundedSeen = field(default_factory=BoundedSeen)  # bounded LRU dedup

    def append_incident(self, incident: ClassifiedIncidentRecord) -> bool:
        key = f"{incident.incident_class.value}:{incident.request_id}:{incident.reason}"
        if key in self._incident_seen:
            return False
        self._incident_seen.add(key)
        self.incidents.append(incident)
        return True

    def append_alert(self, alert: AlertRecord) -> bool:
        if alert.dedup_key in self._alert_seen:
            return False
        self._alert_seen.add(alert.dedup_key)
        self.alerts.append(alert)
        return True

    def list_incidents(self) -> list[ClassifiedIncidentRecord]:
        return list(self.incidents)

    def list_alerts(self) -> list[AlertRecord]:
        return list(self.alerts)


@dataclass(slots=True)
class CapturingAlertPublisher:
    incidents: list[ClassifiedIncident] = field(default_factory=list)
    alerts: list[OpsAlert] = field(default_factory=list)
    fail: bool = False

    def publish_incident(self, incident: ClassifiedIncident) -> bool:
        if self.fail:
            return False
        self.incidents.append(incident)
        return True

    def publish_alert(self, alert: OpsAlert) -> bool:
        if self.fail:
            return False
        self.alerts.append(alert)
        return True


@dataclass(slots=True)
class InMemoryTelemetrySource:
    queued: deque[TelemetryEvent] = field(default_factory=deque)
    acked: list[str] = field(default_factory=list)

    def receive(self, max_messages: int = 10) -> list[TelemetryEvent]:
        messages: list[TelemetryEvent] = []
        while self.queued and len(messages) < max_messages:
            messages.append(self.queued.popleft())
        return messages

    def ack(self, event: TelemetryEvent) -> None:
        self.acked.append(event.event_id)
