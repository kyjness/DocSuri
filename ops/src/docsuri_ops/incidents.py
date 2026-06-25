from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from docsuri_shared.events import (
    ClassifiedIncident,
    OpsAlert,
)
from docsuri_shared.events import (
    IncidentClass as SharedIncidentClass,
)
from docsuri_shared.events import (
    Severity as SharedSeverity,
)

from docsuri_ops._dedup import BoundedSeen
from docsuri_ops.detectors import (
    CostExplosionDetector,
    HallucinationDetector,
    PartialResultDetector,
)
from docsuri_ops.domain.enums import SignalKind
from docsuri_ops.domain.models import (
    AlertRecord,
    BudgetState,
    ClassifiedIncidentRecord,
    GroundingDecision,
    IncidentCandidate,
    TelemetryEvent,
    UsageEvent,
)


@dataclass(slots=True)
class AiIncidentDetectorSuite:
    cost_detector: CostExplosionDetector = field(default_factory=CostExplosionDetector)
    hallucination_detector: HallucinationDetector = field(default_factory=HallucinationDetector)
    partial_result_detector: PartialResultDetector = field(default_factory=PartialResultDetector)

    def evaluate(
        self, event: TelemetryEvent, budget_state: BudgetState | None = None
    ) -> IncidentCandidate | None:
        if event.kind == SignalKind.USAGE:
            return self.cost_detector.evaluate_usage(
                UsageEvent(
                    event_id=event.event_id,
                    amount_usd=float(event.value or event.payload.get("amountUsd", 0.0)),
                    source=str(event.payload.get("source", "unknown")),
                    timestamp=event.timestamp,
                    request_id=event.request_id,
                ),
                budget_state,
            )
        if event.kind == SignalKind.GROUNDING:
            decision = _grounding_decision_from_payload(event.payload)
            return self.hallucination_detector.evaluate_grounding(
                request_id=event.request_id or event.event_id,
                decision=decision,
                signal_id=event.event_id,
            )
        if event.kind == SignalKind.PARTIAL_RESULT:
            return self.partial_result_detector.evaluate_telemetry(event)
        return None

    def classify(self, candidate: IncidentCandidate) -> ClassifiedIncidentRecord:
        return ClassifiedIncidentRecord(
            incident_class=candidate.incident_class,
            severity=candidate.severity,
            request_id=candidate.request_id,
            reason=candidate.reason,
            timestamp=candidate.timestamp,
        )


@dataclass(slots=True)
class IncidentEventPublisher:
    incident_store: Any
    alert_publisher: Any
    event_store: Any | None = None
    _published_alerts: BoundedSeen = field(default_factory=BoundedSeen)  # bounded LRU dedup

    def publish_candidate(self, candidate: IncidentCandidate) -> bool:
        record = ClassifiedIncidentRecord(
            incident_class=candidate.incident_class,
            severity=candidate.severity,
            request_id=candidate.request_id,
            reason=candidate.reason,
            timestamp=candidate.timestamp,
        )
        published = self.publish_incident(record)
        self.publish_alert(
            AlertRecord(
                severity=candidate.severity,
                request_id=candidate.request_id,
                reason=candidate.reason,
                timestamp=candidate.timestamp,
            )
        )
        return published

    def publish_incident(self, record: ClassifiedIncidentRecord) -> bool:
        added = self.incident_store.append_incident(record)
        if not added:
            return False
        event = ClassifiedIncident(
            **{
                "class": SharedIncidentClass(record.incident_class.value),
                "severity": SharedSeverity(record.severity.value),
                "requestId": record.request_id,
            }
        )
        published = self.alert_publisher.publish_incident(event)
        self._audit(
            {
                "eventId": f"incident:{record.incident_class.value}:{record.request_id}",
                "requestId": record.request_id,
                "class": record.incident_class.value,
                "severity": record.severity.value,
            }
        )
        return published

    def publish_alert(self, alert: AlertRecord) -> bool:
        if alert.dedup_key in self._published_alerts:
            return False
        added = self.incident_store.append_alert(alert)
        if not added:
            return False
        self._published_alerts.add(alert.dedup_key)
        event = OpsAlert(
            severity=SharedSeverity(alert.severity.value),
            requestId=alert.request_id,
        )
        published = self.alert_publisher.publish_alert(event)
        self._audit(
            {
                "eventId": f"alert:{alert.severity.value}:{alert.request_id or 'global'}",
                "requestId": alert.request_id,
                "severity": alert.severity.value,
            }
        )
        return published

    def _audit(self, event: dict[str, Any]) -> None:
        if self.event_store is None:
            return
        append_audit = getattr(self.event_store, "append_audit", None)
        if append_audit is not None:
            append_audit(event)


def _grounding_decision_from_payload(payload: dict) -> GroundingDecision:
    verdict = str(payload.get("verdict", "pass"))
    violations = tuple(payload.get("violations", ()))
    return GroundingDecision(verdict=verdict, violations=violations)
