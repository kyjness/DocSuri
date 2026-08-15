"""U6 port defaults (MR-3) — the cost/observability/event path taken when the app-shell does
not inject a hook. Real cost and observability are U6's single authority (BR-12); these keep a
search serving when that authority is absent, so they run on the serving path.

The grounding gate is deliberately NOT here. It has no safe default — an always-pass hook would
serve ungrounded results — so it is required, and its test double lives in
:mod:`discovery.testing`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docsuri_shared.events import SearchExecutedEvent


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
