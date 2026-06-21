"""Gateway seam — the single ``enforce`` invocation site (INV-1).

In production this logic lives in the U6 gateway post-handler that wraps the U2 handler;
here it is a framework-agnostic function the router (and tests) call. It runs the U2
orchestrator up to the grounding input, invokes the injected GroundingEnforcementHook
(U6's single authority), then asks the orchestrator to finalize. The U2 domain core
(``service.orchestrator``) never calls ``enforce`` itself.
"""

from __future__ import annotations

from docsuri_shared.dtos import SearchRequest, SearchResponse
from docsuri_shared.ports import GroundingEnforcementHook

from ..domain.models import RequestContext
from ..service.orchestrator import SearchOrchestrationService


def run_search(
    orchestrator: SearchOrchestrationService,
    grounding_hook: GroundingEnforcementHook,
    request: SearchRequest,
    ctx: RequestContext,
) -> SearchResponse:
    outcome = orchestrator.plan_and_retrieve(request, ctx)
    if outcome.response is not None:
        return outcome.response  # validation error or no-match empty page (terminal already)

    pending = outcome.pending
    assert pending is not None  # noqa: S101 — outcome is response XOR pending by construction
    gi = pending.grounding_input
    # SINGLE grounding invocation (INV-1) — performed by the gateway seam, not the domain core.
    decision = grounding_hook.enforce(gi.candidate_response, gi.retrieved_records)
    return orchestrator.finalize(pending, decision)
