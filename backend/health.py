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
    blocking = [name for name in skipped if name in _required_modules()]
    if blocking:
        response.status_code = 503
    return {
        "status": "ready" if not blocking else "not_ready",
        "mounted": list(result.mounted) if result else [],
        "skipped": skipped,
        "blocking": blocking,
    }


def _required_modules() -> set[str]:
    required = {
        "accounts",
        "discovery",
        "library",
        "mypage",
        "ops",
        "citation_graph",
        "personalization",
        "novelty",
    }
    if os.getenv("RESEARCH_AGENT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}:
        required.add("research")
    if os.getenv("DOCSURI_SUMMARY_BUCKET"):
        required.add("summarization")
    return required
