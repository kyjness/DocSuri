"""Grounding test double.

Unlike the cost/observability/event defaults in :mod:`discovery.defaults`, an always-pass
grounding hook has no legitimate serving use — it would serve ungrounded results, which INV-1
exists to prevent. The app-shell always injects the real U6 ``GroundingEnforcementHook``; this
stands in only for tests and the standalone dev router.
"""

from __future__ import annotations

from dataclasses import dataclass

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
