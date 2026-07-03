"""U4 — keyset cursor pagination (BR-L8): completeness, order, opacity, tamper rejection."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from backend.modules.accounts.models import Principal, UserRole
from backend.modules.library.audit import InMemoryAuditSink
from backend.modules.library.gateway import StubSearchGateway
from backend.modules.library.models import SavedSearch, ValidationException
from backend.modules.library.repository.memory import InMemoryUserDataRepository
from backend.modules.library.schemas import PageParams
from backend.modules.library.services.saved_search import SavedSearchService
from backend.modules.library.validation import decode_cursor, encode_cursor
from hypothesis import given
from hypothesis import strategies as st


def _seed(repo: InMemoryUserDataRepository, owner_id: str, n: int) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(n):
        repo.saved_searches.insert(
            SavedSearch(
                id=str(uuid.uuid4()),
                owner_id=owner_id,
                query=f"q{i}",
                normalized_query=f"q{i}",
                created_at=base + timedelta(seconds=i),
            )
        )


def test_pagination_covers_all_items_once_in_order(make_principal):
    repo = InMemoryUserDataRepository()
    svc = SavedSearchService(repo, StubSearchGateway(), InMemoryAuditSink())
    p = make_principal()
    _seed(repo, p.user_id, 23)

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page = svc.list(p, PageParams(limit=5, cursor=cursor))
        seen.extend(it.query for it in page.items)
        pages += 1
        cursor = page.nextCursor
        if cursor is None:
            break
        assert pages < 100  # guard against an infinite loop

    assert len(seen) == 23
    assert len(set(seen)) == 23  # no duplicates, no gaps
    # most-recent-first: q22, q21, ... q0
    assert seen == [f"q{i}" for i in range(22, -1, -1)]


def test_last_page_has_no_next_cursor(make_principal):
    repo = InMemoryUserDataRepository()
    svc = SavedSearchService(repo, StubSearchGateway(), InMemoryAuditSink())
    p = make_principal()
    _seed(repo, p.user_id, 3)
    page = svc.list(p, PageParams(limit=10))
    assert len(page.items) == 3
    assert page.nextCursor is None


def test_limit_over_max_rejected(make_principal):
    repo = InMemoryUserDataRepository()
    svc = SavedSearchService(repo, StubSearchGateway(), InMemoryAuditSink())
    p = make_principal()
    with pytest.raises(ValidationException):
        svc.list(p, PageParams(limit=101))


def test_tampered_cursor_rejected(make_principal):
    repo = InMemoryUserDataRepository()
    svc = SavedSearchService(repo, StubSearchGateway(), InMemoryAuditSink())
    p = make_principal()
    with pytest.raises(ValidationException):
        svc.list(p, PageParams(limit=5, cursor="!!!not-base64!!!"))


def test_cursor_codec_roundtrip():
    key = (datetime(2026, 6, 17, 12, 0, tzinfo=UTC), "abc-123")
    assert decode_cursor(encode_cursor(key)) == key
    assert decode_cursor(None) is None


# ── Keyset Cursor Pagination PBT-Cursor ──


@given(
    items=st.lists(
        st.tuples(st.integers(min_value=0, max_value=100_000), st.uuids().map(str)),
        min_size=0,
        max_size=50,
        unique_by=lambda x: x[1],
    ),
    page_limit=st.integers(min_value=1, max_value=20),
)
def test_saved_searches_pagination_pbt(items, page_limit):
    repo = InMemoryUserDataRepository()
    svc = SavedSearchService(repo, StubSearchGateway(), InMemoryAuditSink())
    owner_id = "00000000-0000-0000-0000-000000000000"
    principal = Principal(user_id=owner_id, role=UserRole.USER)

    base_time = datetime(2026, 1, 1, tzinfo=UTC)

    # Insert items
    for idx, (offset, item_id) in enumerate(items):
        repo.saved_searches.insert(
            SavedSearch(
                id=item_id,
                owner_id=owner_id,
                query=f"query_{idx}",
                normalized_query=f"query_{idx}",
                created_at=base_time + timedelta(seconds=offset),
            )
        )

    seen: list[tuple[datetime, str, str]] = []
    cursor = None
    pages = 0
    while True:
        page = svc.list(principal, PageParams(limit=page_limit, cursor=cursor))
        assert len(page.items) <= page_limit

        for item in page.items:
            entity = repo.saved_searches.get(owner_id, item.id)
            assert entity is not None
            seen.append((entity.created_at, entity.id, entity.query))

        pages += 1
        cursor = page.nextCursor
        if cursor is None:
            break
        assert pages < 100

    assert len(seen) == len(items)
    seen_ids = {x[1] for x in seen}
    expected_ids = {x[1] for x in items}
    assert seen_ids == expected_ids

    def sort_key(item_tuple):
        offset, item_id = item_tuple
        return (base_time + timedelta(seconds=offset), item_id)

    expected_sorted = sorted(items, key=sort_key, reverse=True)

    for actual, expected in zip(seen, expected_sorted, strict=True):
        expected_time, expected_id = sort_key(expected)
        assert actual[0] == expected_time
        assert actual[1] == expected_id
