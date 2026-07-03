from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Protocol

from .domain.models import (
    AlertRecord,
    ClassifiedIncidentRecord,
    HealthStatus,
    TelemetryEvent,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class EventStore(Protocol):
    def append(self, event: TelemetryEvent) -> bool: ...
    def list_events(self) -> list[TelemetryEvent]: ...


class IncidentStore(Protocol):
    def has_incident(self, incident: ClassifiedIncidentRecord) -> bool: ...
    def append_incident(self, incident: ClassifiedIncidentRecord) -> bool: ...
    def append_alert(self, alert: AlertRecord) -> bool: ...
    def list_incidents(self) -> list[ClassifiedIncidentRecord]: ...
    def list_alerts(self) -> list[AlertRecord]: ...


class AlertPublisher(Protocol):
    def publish_incident(self, incident: Any) -> bool: ...
    def publish_alert(self, alert: Any) -> bool: ...


class IndexStatsProvider(Protocol):
    def index_stats(self) -> Any: ...


class TelemetrySource(Protocol):
    def receive(self, max_messages: int = 10) -> Iterable[TelemetryEvent]: ...
    def ack(self, event: TelemetryEvent) -> None: ...


class HealthProbe(Protocol):
    def check(self) -> HealthStatus: ...
