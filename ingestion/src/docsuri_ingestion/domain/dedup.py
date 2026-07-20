"""Per-paper dedup decision policy (P1 idempotency).

Pure and store-independent: the control-plane ports fetch the stored ``DedupState`` and hand it
here, so the local and Postgres adapters cannot drift apart on what counts as a duplicate.
"""

from __future__ import annotations

from .enums import DedupDecision, DedupStateKind
from .models import DedupResult, DedupState


def decide_dedup(state: DedupState | None, version: int, fingerprint: str) -> DedupResult:
    """Classify an incoming (version, fingerprint) against the stored state for that paper.

    Unseen paper → NEW. Older version → STALE (never overwrites a newer one). Same version with
    an unchanged fingerprint that already reached INDEXED → DUPLICATE (the redelivery
    short-circuit). Anything else is a genuine re-ingest → CHANGED.
    """
    if state is None:
        return DedupResult(DedupDecision.NEW)
    if version < state.current_version:
        return DedupResult(DedupDecision.STALE)
    if (
        version == state.current_version
        and state.fingerprint == fingerprint
        and state.state is DedupStateKind.INDEXED
    ):
        return DedupResult(DedupDecision.DUPLICATE)
    return DedupResult(DedupDecision.CHANGED)
