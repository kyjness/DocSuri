"""U4 — PBT-09 DTO round-trip + SEC-9 non-disclosure properties (Hypothesis).

Property: mapping any valid domain entity to its wire DTO (1) never raises, (2) preserves the
public fields, and (3) NEVER leaks an internal field (owner_id / normalized_query / dedupe_key).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from backend.modules.accounts.models import Principal, UserRole
from backend.modules.library.models import HistoryEntry, LibraryItem, SavedSearch
from backend.modules.library.schemas import (
    LibraryItemCreateDTO,
    LibraryItemMeta,
    SavedSearchCreateDTO,
)
from backend.modules.library.validation import (
    UserDataDTOAndValidation,
    to_history_dto,
    to_library_dto,
    to_saved_dto,
)
from hypothesis import given
from hypothesis import strategies as st

# internal fields that MUST NEVER appear on the wire (SEC-9)
FORBIDDEN = {"owner_id", "normalized_query", "dedupe_key", "ownerId"}

_aware = st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1)).map(
    lambda d: d.replace(tzinfo=UTC)
)
_text = st.text(min_size=1, max_size=200)
_uuid = st.builds(lambda: str(uuid.uuid4()))


@given(query=_text, label=st.none() | _text, created=_aware, owner=_uuid)
def test_saved_search_dto_roundtrip(query, label, created, owner):
    entity = SavedSearch(
        id=str(uuid.uuid4()),
        owner_id=owner,
        query=query,
        normalized_query=query.casefold(),
        created_at=created,
        label=label,
    )
    dto = to_saved_dto(entity)
    assert dto.query == entity.query
    assert dto.label == entity.label
    assert dto.createdAt == entity.created_at
    dumped = dto.model_dump()
    assert FORBIDDEN.isdisjoint(dumped.keys())
    # serialize → re-validate is stable
    assert type(dto).model_validate(dumped).id == dto.id


@given(
    title=st.text(min_size=1, max_size=200),
    authors=st.lists(st.text(min_size=1, max_size=50), max_size=5),
    year=st.none() | st.integers(min_value=1900, max_value=2100),
    added=_aware,
    owner=_uuid,
)
def test_library_item_dto_roundtrip(title, authors, year, added, owner):
    meta = LibraryItemMeta(title=title, authors=authors, year=year, arxivId="2401.00001")
    entity = LibraryItem(
        id=str(uuid.uuid4()), owner_id=owner, arxiv_id="2401.00001", meta=meta, added_at=added
    )
    dto = to_library_dto(entity)
    assert dto.arXivId == "2401.00001"
    assert dto.meta["title"] == title
    dumped = dto.model_dump()
    assert FORBIDDEN.isdisjoint(dumped.keys())


@given(query=_text, count=st.integers(min_value=0, max_value=10_000), executed=_aware, owner=_uuid)
def test_history_entry_dto_roundtrip(query, count, executed, owner):
    entity = HistoryEntry(
        id=str(uuid.uuid4()),
        owner_id=owner,
        query=query,
        executed_at=executed,
        result_count=count,
        dedupe_key="deadbeef",
    )
    dto = to_history_dto(entity)
    assert dto.query == entity.query
    assert dto.resultCount == count
    dumped = dto.model_dump()
    assert FORBIDDEN.isdisjoint(dumped.keys())


# ── PBT-09 Property 2: Create DTO → validate_and_map → to_dto roundtrip ──

valid_queries = (
    st.text(min_size=1, max_size=499).map(lambda s: s.strip()).filter(lambda s: len(s) > 0)
)
valid_labels = st.none() | (
    st.text(min_size=1, max_size=199).map(lambda s: s.strip()).filter(lambda s: len(s) > 0)
)
valid_arxiv_ids = st.from_regex(r"^\d{4}\.\d{4,5}$")

valid_metas = st.builds(
    LibraryItemMeta,
    title=st.text(min_size=1, max_size=200),
    authors=st.lists(st.text(min_size=1, max_size=50), max_size=5),
    year=st.none() | st.integers(min_value=1900, max_value=2100),
    arxivId=valid_arxiv_ids,
)


@given(
    query=valid_queries,
    label=valid_labels,
    owner_id=_uuid,
)
def test_saved_search_create_dto_roundtrip(query, label, owner_id):
    principal = Principal(user_id=owner_id, role=UserRole.USER)
    create_dto = SavedSearchCreateDTO(query=query, label=label)

    # 1. validate_and_map
    entity = UserDataDTOAndValidation.validate_and_map(create_dto, principal)

    # Assert public fields match
    assert entity.owner_id == owner_id
    assert entity.query == query.strip()
    assert entity.label == (label.strip() if label else None)

    # 2. to_dto
    dto = to_saved_dto(entity)
    assert dto.query == create_dto.query.strip()
    assert dto.label == (create_dto.label.strip() if create_dto.label else None)
    dumped = dto.model_dump()
    assert FORBIDDEN.isdisjoint(dumped.keys())


@given(
    arxiv_id=valid_arxiv_ids,
    meta=valid_metas,
    owner_id=_uuid,
)
def test_library_item_create_dto_roundtrip(arxiv_id, meta, owner_id):
    principal = Principal(user_id=owner_id, role=UserRole.USER)
    meta.arxivId = arxiv_id
    create_dto = LibraryItemCreateDTO(arXivId=arxiv_id, meta=meta)

    # 1. validate_and_map
    entity = UserDataDTOAndValidation.validate_and_map(create_dto, principal)

    # Assert public fields match
    assert entity.owner_id == owner_id
    assert entity.arxiv_id == arxiv_id.strip()
    assert entity.meta.title == meta.title

    # 2. to_dto
    dto = to_library_dto(entity)
    assert dto.arXivId == arxiv_id.strip()
    assert dto.meta["title"] == meta.title
    dumped = dto.model_dump()
    assert FORBIDDEN.isdisjoint(dumped.keys())
