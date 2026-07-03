from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .enums import CircuitState, DegradeMode, IncidentClass, Severity, SignalKind


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    event_id: str
    kind: SignalKind
    timestamp: datetime = field(default_factory=utc_now)
    request_id: str | None = None
    name: str | None = None
    value: float | None = None
    tags: dict[str, str] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        return self.event_id or self.request_id or f"{self.kind}:{self.timestamp.isoformat()}"


@dataclass(frozen=True, slots=True)
class UsageEvent:
    event_id: str
    amount_usd: float
    source: str
    timestamp: datetime = field(default_factory=utc_now)
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class BudgetState:
    tier: str
    degrade_mode: DegradeMode
    circuit_state: CircuitState
    spend_usd: float
    cap_usd: float
    threshold_ratio: float


@dataclass(frozen=True, slots=True)
class GroundingViolation:
    code: str
    message: str
    arxiv_id: str | None = None


@dataclass(frozen=True, slots=True)
class GroundingDecision:
    verdict: str
    violations: tuple[GroundingViolation, ...] = ()


@dataclass(frozen=True, slots=True)
class IncidentCandidate:
    incident_class: IncidentClass
    severity: Severity
    request_id: str
    reason: str
    signal_id: str
    timestamp: datetime = field(default_factory=utc_now)

    @property
    def dedup_key(self) -> str:
        return f"{self.incident_class.value}:{self.request_id}:{self.reason}"


@dataclass(frozen=True, slots=True)
class ClassifiedIncidentRecord:
    incident_class: IncidentClass
    severity: Severity
    request_id: str
    reason: str
    timestamp: datetime = field(default_factory=utc_now)

    @property
    def dedup_key(self) -> str:
        return f"{self.incident_class.value}:{self.request_id}:{self.reason}"


@dataclass(frozen=True, slots=True)
class AlertRecord:
    severity: Severity
    request_id: str | None
    reason: str
    timestamp: datetime = field(default_factory=utc_now)

    @property
    def dedup_key(self) -> str:
        return f"{self.severity.value}:{self.request_id or 'global'}:{self.reason}"


@dataclass(frozen=True, slots=True)
class DashboardWindow:
    start: datetime
    end: datetime

    def contains(self, timestamp: datetime) -> bool:
        return self.start <= timestamp <= self.end


@dataclass(frozen=True, slots=True)
class HealthStatus:
    status: str
    dependencies: dict[str, str] = field(default_factory=dict)
    stale: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReliabilityEvalCase:
    name: str
    expected_status: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReliabilityEvalReport:
    cases: tuple[dict[str, Any], ...]
    degraded_behavior_ok: bool


@dataclass(frozen=True, slots=True)
class OpsDashboardView:
    window: DashboardWindow
    incident_count: int
    alert_count: int
    cost_state: BudgetState | None
    health: HealthStatus | None
    latency_p95: float | None = None
    error_rate: float | None = None
    throughput: float | None = None
    grounding_health: dict[str, int] | None = None
