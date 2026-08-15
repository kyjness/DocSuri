"""Liveness / readiness endpoints.

Deliberately dependency-free: ``/health`` and ``/healthz`` must succeed even when no
modules are mounted and no DB/Redis is configured (so a bare app-shell deploy and CI
smoke tests pass). ``/readyz`` reports which modules actually mounted — useful while the
track PRs are landing one at a time.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Request, Response

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "docsuri-backend"}


@router.get("/healthz")
def healthz() -> dict:
    """Liveness alias (k8s-style)."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(request: Request, response: Response) -> dict:
    """Readiness — reflects the modules wired into this process."""
    result = getattr(request.app.state, "mount_result", None)
    skipped = [name for name, _ in result.skipped] if result else []
    # A module nobody configured is legitimately absent; only the mount gate knows what
    # "configured" means for each one, so take its word rather than re-deriving the condition.
    unconfigured = set(result.unconfigured) if result else set()
    required = _required_modules()
    blocking = [name for name in skipped if name in required and name not in unconfigured]
    if blocking:
        response.status_code = 503
    return {
        "status": "ready" if not blocking else "not_ready",
        "mounted": list(result.mounted) if result else [],
        "skipped": skipped,
        "blocking": blocking,
    }


def _required_modules() -> set[str]:
    """Modules this deployment shape expects to be present.

    Real-first modules (discovery, summarization) belong here unconditionally: "configured ⇒
    must mount" is enforced by ``readyz`` subtracting ``MountResult.unconfigured``, not by
    re-testing their env here. ``RESEARCH_AGENT_ENABLED`` stays a condition because it is an
    ops toggle rather than something the module discovers about itself.
    """
    required = {
        "accounts",
        "discovery",
        "library",
        "mypage",
        "ops",
        "citation_graph",
        "personalization",
        "novelty",
        "summarization",
    }
    if os.getenv("RESEARCH_AGENT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        required.add("research")
    return required
