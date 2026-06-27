"""Gateway seam — the U7 entry the U6 gateway (or the thin router) calls.

Authn/authz/rate-limit (SEC-8/11) are the U6 gateway's job; the principal arrives in the
request context and U7 trusts it. Unlike U2 (where grounding is the seam), U7 owns its
deterministic grounding gate, so the seam is a thin, framework-agnostic entry that runs the
orchestrator and returns the terminal response (fail-closed on any unexpected error).
"""

from __future__ import annotations

import logging

from ..domain.models import AbstainDTO, RequestContext, SummaryRequest, SummaryResponse
from ..service.orchestrator import SummarizationOrchestrationService

logger = logging.getLogger(__name__)


def run_summarization(
    orchestrator: SummarizationOrchestrationService,
    request: SummaryRequest,
    ctx: RequestContext,
) -> SummaryResponse:
    try:
        return orchestrator.run(request, ctx)
    except Exception:  # noqa: BLE001 — fail-closed: never surface internals (INV-4/SEC-15)
        # Response stays generic (no internals leak), but the cause is logged for operability —
        # silently swallowing it makes a real fault (store/glossary/cost) indistinguishable from
        # a legitimate abstain. (task=%s scope=%s so the failing path is identifiable.)
        logger.exception(
            "summarization run failed → fail-closed abstain (task=%s scope=%s)",
            getattr(request, "task", "?"),
            getattr(request, "scope", "?"),
        )
        return AbstainDTO(reason="unavailable")
