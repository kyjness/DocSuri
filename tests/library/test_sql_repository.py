"""U4 — SqlSavedSearchRepository relabel regression (BR-L1/FR-8).

The in-memory adapter returns a *live* object reference from ``find_by_normalized``, so a
re-save with a new label mutates the very object the response DTO is built from. That masked a
real bug: the SQL adapter returns a *detached copy*, so the re-save response echoed the STALE
label even though the row was correctly relabeled. This pins the fix against the real SQL
adapter (on an in-memory SQLite session) so the adapter divergence can't regress unseen.
"""

from __future__ import annotations

import uuid
from datetime import UTC

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend.modules.accounts.models import Principal, UserRole
from backend.modules.library.audit import InMemoryAuditSink
from backend.modules.library.gateway import StubSearchGateway
from backend.modules.library.repository.sql import Base, SavedSearchTable, SqlUserDataRepository
from backend.modules.library.schemas import SavedSearchCreateDTO
from backend.modules.library.services.saved_search import SavedSearchService


def _restore_utc(target, _ctx):
    """SQLite has no TIMESTAMPTZ, so it loads ``created_at`` naive; production Postgres returns
    it tz-aware. Re-attach UTC on load so the test substrate matches production semantics."""
    if target.created_at is not None and target.created_at.tzinfo is None:
        target.created_at = target.created_at.replace(tzinfo=UTC)


@pytest.fixture
def sql_saved_service():
    """A SavedSearchService backed by the production SQL adapter on in-memory SQLite."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    event.listen(SavedSearchTable, "load", _restore_utc)
    svc = SavedSearchService(
        SqlUserDataRepository(session), StubSearchGateway(), InMemoryAuditSink()
    )
    try:
        yield svc
    finally:
        event.remove(SavedSearchTable, "load", _restore_utc)
        session.close()
        engine.dispose()


def test_sql_resave_with_new_label_returns_fresh_label(sql_saved_service):
    """BR-L1/FR-8: re-saving an existing query with a new label echoes the NEW label on the SQL
    adapter — not the stale pre-update copy ``find_by_normalized`` hands back."""
    p = Principal(user_id=str(uuid.uuid4()), role=UserRole.USER)

    first = sql_saved_service.save(p, SavedSearchCreateDTO(query="Transformer  Attention"))
    relabeled = sql_saved_service.save(
        p, SavedSearchCreateDTO(query="  transformer attention ", label="relabel")
    )

    assert relabeled.id == first.id  # deduped on normalized_query (BR-L1)
    assert relabeled.label == "relabel"  # fresh label, not the stale None
    assert getattr(relabeled, "was_created", True) is False  # idempotent re-save → HTTP 200
