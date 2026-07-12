"""One-time category backfill for U9 personalization (US-P4 search boost).

Events recorded before record-time category enrichment shipped (commit 97bde2aa) were stored with
no ``subject.category``, so ProfileAggregator credits them nothing and existing users' search
boosts stay empty. This heals the stored events: for each paper-scoped event lacking a category,
resolve the paper's primary arXiv category via discovery and write it back. Profiles are NOT reset
here — the TTL-on-read refresh (``PERSONALIZATION_PROFILE_TTL_SECONDS``) rebuilds them from the
healed events within one TTL window on the user's next search.

Run in-VPC against the API image (has RDS + discovery): ``python -m
backend.modules.personalization.backfill [--dry-run]``. Idempotent and fail-open per paper.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

from backend.config import Settings
from backend.db import make_engine, make_session_factory

from .repository import PersonalizationRepository, SqlPersonalizationRepository
from .service import _CATEGORY_EVENTS, _emit_metric


@dataclass(frozen=True)
class BackfillReport:
    scanned: int
    updated: int
    unresolved: int


def backfill_categories(
    repo: PersonalizationRepository,
    resolver: Callable[[str], str | None],
    *,
    dry_run: bool = False,
    observability=None,
) -> BackfillReport:
    """Fill ``subject.category`` on paper-scoped events that lack it. Idempotent (already-
    categorized events are never scanned), fail-open per paper (an unresolvable paperId is left
    unchanged and counted as ``unresolved``). Resolves each unique paperId once. Profile-pure."""
    event_types = {event_type.value for event_type in _CATEGORY_EVENTS}
    rows = repo.list_uncategorized_paper_events(event_types)
    cache: dict[str, str | None] = {}
    updated = 0
    unresolved = 0
    for event_id, paper_id in rows:
        if paper_id not in cache:
            try:
                cache[paper_id] = resolver(paper_id)
            except Exception:  # noqa: BLE001 — enrichment is best-effort; a lookup error skips it
                cache[paper_id] = None
        category = cache[paper_id]
        if not category:
            unresolved += 1
            continue
        if not dry_run:
            repo.set_event_category(event_id, category)
        updated += 1
    _emit_metric(observability, "personalization.category_backfill", float(updated))
    return BackfillReport(scanned=len(rows), updated=updated, unresolved=unresolved)


def _resolver_from_app() -> Callable[[str], str | None]:
    # Reuse the app's own wiring so the resolver hits the same prod discovery/OpenSearch the
    # record-time enrichment uses — no reconstruction of real_wiring here.
    from backend.app import create_app

    bundle = getattr(create_app().state, "discovery_bundle", None)
    resolve = getattr(getattr(bundle, "paper_service", None), "primary_category", None)
    if not callable(resolve):
        raise RuntimeError("discovery paper_service.primary_category unavailable — cannot backfill")
    return resolve


def run(*, dry_run: bool = False) -> int:
    settings = Settings.from_env()
    resolver = _resolver_from_app()
    engine = make_engine(settings.database_url)
    session = make_session_factory(engine)()
    try:
        report = backfill_categories(
            SqlPersonalizationRepository(session), resolver, dry_run=dry_run
        )
        if not dry_run:
            session.commit()
        print(
            f"category backfill: scanned={report.scanned} updated={report.updated} "
            f"unresolved={report.unresolved} dry_run={dry_run}"
        )
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(run(dry_run="--dry-run" in sys.argv))
