from __future__ import annotations

from dataclasses import dataclass, field

from docsuri_ops._dedup import BoundedSeen
from docsuri_ops.domain.enums import CircuitState, IncidentClass, Severity
from docsuri_ops.domain.models import (
    BudgetState,
    GroundingDecision,
    IncidentCandidate,
    TelemetryEvent,
    UsageEvent,
)


@dataclass(slots=True)
class CostExplosionDetector:
    budget_cap_usd: float = 1600.0
    single_event_spike_usd: float = 50.0
    rate_limit_spike_count: int = 100
    _seen: BoundedSeen = field(default_factory=BoundedSeen)  # bounded LRU — caps dedup memory

    def evaluate_usage(
        self,
        event: UsageEvent,
        budget_state: BudgetState | None = None,
        *,
        window_id: str = "current",
        usage_count: int = 1,
    ) -> IncidentCandidate | None:
        key = f"cost:{window_id}:{event.event_id}"
        if key in self._seen:
            return None

        severity = self._severity(event, budget_state, usage_count)
        if severity is None:
            return None

        self._seen.add(key)
        return IncidentCandidate(
            incident_class=IncidentClass.COST_EXPLOSION,
            severity=severity,
            request_id=event.request_id or event.event_id,
            reason=self._reason(severity, event, budget_state, usage_count),
            signal_id=event.event_id,
            timestamp=event.timestamp,
        )

    def evaluate_rate_limit_spike(
        self, *, request_id: str, signal_id: str, count: int
    ) -> IncidentCandidate | None:
        key = f"rate:{signal_id}:{count}"
        if key in self._seen or count < self.rate_limit_spike_count:
            return None
        self._seen.add(key)
        return IncidentCandidate(
            incident_class=IncidentClass.COST_EXPLOSION,
            severity=Severity.WARNING,
            request_id=request_id,
            reason="rate-limit spike can amplify spend",
            signal_id=signal_id,
        )

    def _severity(
        self,
        event: UsageEvent,
        budget_state: BudgetState | None,
        usage_count: int,
    ) -> Severity | None:
        ratio = (
            budget_state.threshold_ratio
            if budget_state
            else event.amount_usd / self.budget_cap_usd
        )
        if (
            budget_state is not None
            and budget_state.circuit_state == CircuitState.OPEN
            or ratio >= 1.0
            or event.amount_usd >= self.budget_cap_usd * 0.20
        ):
            return Severity.CRITICAL
        if ratio >= 0.80 or event.amount_usd >= self.single_event_spike_usd:
            return Severity.WARNING
        if usage_count >= self.rate_limit_spike_count:
            return Severity.WARNING
        return None

    def _reason(
        self,
        severity: Severity,
        event: UsageEvent,
        budget_state: BudgetState | None,
        usage_count: int,
    ) -> str:
        if severity == Severity.CRITICAL:
            return "cost hard-cap exceeded or anomalous spend velocity"
        if budget_state is not None and budget_state.threshold_ratio >= 0.80:
            return "monthly cost threshold exceeded"
        if usage_count >= self.rate_limit_spike_count:
            return "rate-limit spike can amplify spend"
        return "single request spend spike"


@dataclass(slots=True)
class HallucinationDetector:
    _seen: BoundedSeen = field(default_factory=BoundedSeen)  # bounded LRU — caps dedup memory

    def evaluate_grounding(
        self,
        *,
        request_id: str,
        decision: GroundingDecision,
        signal_id: str,
    ) -> IncidentCandidate | None:
        if decision.verdict == "pass":
            return None
        key = f"hallucination:{signal_id}:{decision.verdict}"
        if key in self._seen:
            return None
        self._seen.add(key)
        severity = Severity.CRITICAL if decision.verdict == "block" else Severity.WARNING
        return IncidentCandidate(
            incident_class=IncidentClass.HALLUCINATION,
            severity=severity,
            request_id=request_id,
            reason=self._reason(decision),
            signal_id=signal_id,
        )

    def evaluate_eval_failure(
        self, *, request_id: str, signal_id: str, fabricated_reference_count: int
    ) -> IncidentCandidate | None:
        if fabricated_reference_count <= 0:
            return None
        key = f"eval:{signal_id}:{fabricated_reference_count}"
        if key in self._seen:
            return None
        self._seen.add(key)
        return IncidentCandidate(
            incident_class=IncidentClass.HALLUCINATION,
            severity=Severity.CRITICAL,
            request_id=request_id,
            reason="grounding eval detected fabricated references",
            signal_id=signal_id,
        )

    def _reason(self, decision: GroundingDecision) -> str:
        if decision.verdict == "block":
            return "grounding violation blocked fabricated reference"
        return "grounding gate abstained due to missing provenance"


@dataclass(slots=True)
class PartialResultDetector:
    _seen: BoundedSeen = field(default_factory=BoundedSeen)  # bounded LRU — caps dedup memory

    def evaluate_response(
        self, *, request_id: str, payload: dict, signal_id: str
    ) -> IncidentCandidate | None:
        reason = self._reason(payload)
        if reason is None:
            return None
        key = f"partial:{signal_id}:{reason}"
        if key in self._seen:
            return None
        self._seen.add(key)
        severity = Severity.CRITICAL if "failure" in reason else Severity.WARNING
        return IncidentCandidate(
            incident_class=IncidentClass.PARTIAL_RESULT,
            severity=severity,
            request_id=request_id,
            reason=reason,
            signal_id=signal_id,
        )

    def evaluate_telemetry(self, event: TelemetryEvent) -> IncidentCandidate | None:
        request_id = event.request_id or event.event_id
        return self.evaluate_response(
            request_id=request_id,
            payload=event.payload,
            signal_id=event.event_id,
        )

    def _reason(self, payload: dict) -> str | None:
        status = str(payload.get("status", "success"))
        if status in {"abstain", "fail_closed", "failed", "error"}:
            return None
        if status == "degraded" and payload.get("degraded") is True:
            return None

        if status == "success" and (
            payload.get("retrievalFailure") or payload.get("dependencyFailure")
        ):
            return "retrieval failure was reported as success"

        result_count = payload.get("resultCount")
        items = _items(payload)
        if status == "success" and result_count == 0:
            return "empty result was reported as success"
        if result_count is not None and len(items) != int(result_count):
            return "result count does not match returned cards"

        degraded_mode = payload.get("degradeMode") or payload.get("fallbackMode")
        if status == "success" and degraded_mode and payload.get("degraded") is not True:
            return "degraded execution was reported as success"
        return None


def _items(payload: dict) -> tuple:
    for key in ("cards", "results", "items"):
        value = payload.get(key)
        if value is not None:
            return tuple(value)
    return ()
