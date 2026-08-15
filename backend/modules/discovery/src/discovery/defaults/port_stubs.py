"""U6 port stubs (MR-3) — TEST/LOCAL ONLY. Real enforcement/cost/observability are U6's
single authority (INV-1/BR-12). These let U2 + U5 develop before U6 exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docsuri_shared.events import SearchExecutedEvent
from docsuri_shared.ports import Verdict


@dataclass(frozen=True, slots=True)
class _Decision:
    """Concrete GroundingDecision (verdict + violations)."""

    verdict: Verdict
    violations: tuple = ()


class StubGroundingHook:
    """Pass-through grounding by default; set ``verdict='abstain'`` to force the abstain path.

    Stands in for the U6 gateway's GroundingEnforcementHook — but note the orchestrator never
    calls this; the gateway seam (``discovery.api``) does (INV-1)."""

    def __init__(self, verdict: Verdict = "pass") -> None:
        self._verdict = verdict

    def enforce(self, candidate, retrieved) -> _Decision:  # noqa: ARG002
        return _Decision(verdict=self._verdict)

    def run_eval_set(self, eval_set):  # noqa: ARG002 — provisional
        raise NotImplementedError("eval set is U6/OP owned")


@dataclass(frozen=True, slots=True)
class _Budget:
    """Concrete BudgetState. ``degrade_mode`` ∈ {normal, rerank-off, lexical-only}."""

    tier: str = "normal"
    degrade_mode: str = "normal"
    circuit_state: str = "closed"


class StubCostGuard:
    """Returns a fixed advisory budget state (default NORMAL). U2 only reads it (BR-12)."""

    def __init__(self, degrade_mode: str = "normal") -> None:
        self._budget = _Budget(degrade_mode=degrade_mode)

    def get_budget_state(self) -> _Budget:
        return self._budget


class NoopObservabilityHub:
    """No-op collector (U6 implements the real one)."""

    def emit_metric(self, name, value, tags) -> None: ...  # noqa: ARG002
    def emit_log(self, entry) -> None: ...  # noqa: ARG002
    def start_span(self, name, context):  # noqa: ARG002
        return None
    def audit_append(self, event) -> None: ...  # noqa: ARG002


@dataclass
class InMemoryEventPublisher:
    """Collects SearchExecuted events (non-blocking). U4 consumes the real bus."""

    events: list[SearchExecutedEvent] = field(default_factory=list)

    def publish_search_executed(self, event: SearchExecutedEvent) -> None:
        self.events.append(event)
