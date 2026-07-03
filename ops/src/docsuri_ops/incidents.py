from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
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
                    amount_usd=(
                        float(event.value)
                        if event.value is not None
                        else float(event.payload.get("amountUsd", 0.0))
                    ),
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


class PublishOutcome(Enum):
    """Result of publishing an incident — lets the worker decide whether to ack. (Finding 1)

    A duplicate is an idempotent success (ack it), NOT a failure. Conflating the two made a
    redelivered duplicate un-ackable → infinite redelivery (poison message) on a real source.
    """

    PUBLISHED = "published"  # newly stored + emitted → ack
    DUPLICATE = "duplicate"  # already recorded (idempotent) → ack
    FAILED = "failed"  # transient emit failure, nothing committed → do NOT ack, redeliver


@dataclass(slots=True)
class IncidentEventPublisher:
    incident_store: Any
    alert_publisher: Any
    event_store: Any | None = None
    _published_alerts: BoundedSeen = field(default_factory=BoundedSeen)  # bounded LRU dedup

    def publish_candidate(self, candidate: IncidentCandidate) -> PublishOutcome:
        record = ClassifiedIncidentRecord(
            incident_class=candidate.incident_class,
            severity=candidate.severity,
            request_id=candidate.request_id,
            reason=candidate.reason,
            timestamp=candidate.timestamp,
        )
        outcome = self.publish_incident(record)
        self.publish_alert(
            AlertRecord(
                severity=candidate.severity,
                request_id=candidate.request_id,
                reason=candidate.reason,
                timestamp=candidate.timestamp,
            )
        )
        return outcome

    def publish_incident(self, record: ClassifiedIncidentRecord) -> PublishOutcome:
        # Publish-before-commit for at-least-once safety: mark the incident as recorded (which
        # suppresses future redeliveries) ONLY after the external emit succeeds. So a duplicate is
        # ack-able, and a transient emit failure leaves nothing committed → redelivery re-attempts
        # cleanly instead of looping forever or dropping the incident. (Finding 1)
        if self.incident_store.has_incident(record):
            return PublishOutcome.DUPLICATE
        event = ClassifiedIncident(
            **{
                "class": SharedIncidentClass(record.incident_class.value),
                "severity": SharedSeverity(record.severity.value),
                "requestId": record.request_id,
            }
        )
        if not self.alert_publisher.publish_incident(event):
            return PublishOutcome.FAILED
        self.incident_store.append_incident(record)
        self._audit(
            {
                "eventId": f"incident:{record.incident_class.value}:{record.request_id}",
                "requestId": record.request_id,
                "class": record.incident_class.value,
                "severity": record.severity.value,
            }
        )
        return PublishOutcome.PUBLISHED

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
    # Fail closed (INV-7): a GROUNDING telemetry event with a missing/empty verdict is malformed
    # — default it to "abstain" (a non-pass that raises a WARNING incident) instead of silently
    # treating it as "pass" and dropping a possible hallucination signal. (Finding 3)
    verdict = str(payload.get("verdict") or "abstain")
    violations = tuple(payload.get("violations", ()))
    return GroundingDecision(verdict=verdict, violations=violations)
