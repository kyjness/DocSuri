"""U4 — SearchHistoryService unit tests (US-L3/FR-10): idempotent consume, retention, scoping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from backend.modules.library.history_consumer import SearchHistoryEventConsumer
from backend.modules.library.models import NotFoundError
from backend.modules.library.schemas import PageParams
from backend.modules.library.services import history as hist_mod
from docsuri_shared.events import SearchExecutedEvent


def _event(
    owner_id: str,
    query: str,
    when: datetime,
    count: int = 3,
    request_id: str = "req-1",
) -> SearchExecutedEvent:
    return SearchExecutedEvent(
        userId=owner_id,
        requestId=request_id,
        query=query,
        timestamp=when,
        resultCount=count,
    )


def test_record_is_idempotent_at_least_once(make_services, make_principal):
    """BR-L7/INV-L3: re-delivery of the same event creates exactly one row."""
    _s, _l, hist, _repo, _a = make_services()
    p = make_principal()
    ev = _event(p.user_id, "q1", datetime.now(UTC))
    first = hist.record_search(ev)
    dup = hist.record_search(ev)
    assert first is not None
    assert dup is None  # duplicate suppressed
    page = hist.list(p, PageParams(limit=10))
    assert len(page.items) == 1


def test_distinct_request_ids_record_repeated_query(make_services, make_principal):
    """BR-L7: requestId distinguishes intentional repeated identical searches."""
    _s, _l, hist, _repo, _a = make_services()
    p = make_principal()
    when = datetime.now(UTC)
    first = hist.record_search(_event(p.user_id, "q1", when, request_id="req-a"))
    second = hist.record_search(_event(p.user_id, "q1", when, request_id="req-b"))
    assert first is not None
    assert second is not None
    assert len(hist.list(p, PageParams(limit=10)).items) == 2


def test_consumer_validates_and_records(make_services, make_principal):
    _s, _l, hist, _repo, _a = make_services()
    p = make_principal()
    consumer = SearchHistoryEventConsumer(hist)
    entry = consumer.consume(
        {
            "userId": p.user_id,
            "requestId": "req-dict",
            "query": "via dict",
            "timestamp": datetime.now(UTC).isoformat(),
            "resultCount": 7,
        }
    )
    assert entry is not None
    page = hist.list(p, PageParams(limit=10))
    assert page.items[0].query == "via dict"
    assert page.items[0].resultCount == 7


def test_retention_prunes_to_cap(make_services, make_principal, monkeypatch):
    """BR-L6: rolling retention keeps only the most-recent N per owner."""
    monkeypatch.setattr(hist_mod, "RETENTION_LIMIT", 3)
    _s, _l, hist, _repo, _a = make_services()
    p = make_principal()
    base = datetime.now(UTC)
    for i in range(6):
        hist.record_search(_event(p.user_id, f"q{i}", base + timedelta(seconds=i)))
    page = hist.list(p, PageParams(limit=50))
    assert len(page.items) == 3
    # most-recent-first: the survivors are q5, q4, q3
    assert [it.query for it in page.items] == ["q5", "q4", "q3"]


def test_list_owner_scoped(make_services, make_principal):
    _s, _l, hist, _repo, _a = make_services()
    a, b = make_principal(), make_principal()
    hist.record_search(_event(a.user_id, "a-query", datetime.now(UTC)))
    hist.record_search(_event(b.user_id, "b-query", datetime.now(UTC)))
    assert len(hist.list(a, PageParams(limit=10)).items) == 1


def test_clear_is_owner_scoped(make_services, make_principal):
    _s, _l, hist, _repo, _a = make_services()
    a, b = make_principal(), make_principal()
    hist.record_search(_event(a.user_id, "qa", datetime.now(UTC)))
    hist.record_search(_event(b.user_id, "qb", datetime.now(UTC)))
    n = hist.clear(a)
    assert n == 1
    assert len(hist.list(a, PageParams(limit=10)).items) == 0
    assert len(hist.list(b, PageParams(limit=10)).items) == 1  # b untouched


@pytest.mark.asyncio
async def test_rerun_cross_owner_notfound(make_services, make_principal):
    _s, _l, hist, _repo, _a = make_services()
    owner, attacker = make_principal(), make_principal()
    entry = hist.record_search(_event(owner.user_id, "x", datetime.now(UTC)))
    with pytest.raises(NotFoundError):
        await hist.rerun(attacker, entry.id)
    result = await hist.rerun(owner, entry.id)
    assert result.root.meta.resultCount == 0
