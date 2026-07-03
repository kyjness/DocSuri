"""U4 Library — SQLAlchemy repository scaffold (production adapter, D10).

Swaps in behind the same ports as the in-memory default (the tests/app-shell run on in-memory;
production injects this against the U3-inherited RDS PostgreSQL). Every query is owner-scoped
(INV-L1) and pagination is keyset on ``(sort_col, id) < (cursor)`` to match the in-memory order.
Tables map 1:1 to ``migrations/001_create_library_tables.sql``.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, or_, tuple_
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from ..models import HistoryEntry, LibraryItem, SavedSearch
from ..schemas import LibraryItemMeta

CursorKey = tuple[datetime, str]
_VERSION_SUFFIX = re.compile(r"v\d+$")


def _strip_version(paper_id: str) -> str:
    return _VERSION_SUFFIX.sub("", paper_id)


class Base(DeclarativeBase):
    pass


class SavedSearchTable(Base):
    __tablename__ = "saved_searches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_query: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LibraryItemTable(Base):
    __tablename__ = "library_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    arxiv_id: Mapped[str] = mapped_column(String(64), nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SearchHistoryTable(Base):
    __tablename__ = "search_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


def _saved_to_domain(row: SavedSearchTable) -> SavedSearch:
    return SavedSearch(
        id=row.id,
        owner_id=row.owner_id,
        query=row.query,
        normalized_query=row.normalized_query,
        created_at=row.created_at,
        label=row.label,
    )


def _library_to_domain(row: LibraryItemTable) -> LibraryItem:
    return LibraryItem(
        id=row.id,
        owner_id=row.owner_id,
        arxiv_id=row.arxiv_id,
        meta=LibraryItemMeta.model_validate(row.meta),
        added_at=row.added_at,
    )


def _history_to_domain(row: SearchHistoryTable) -> HistoryEntry:
    return HistoryEntry(
        id=row.id,
        owner_id=row.owner_id,
        query=row.query,
        executed_at=row.executed_at,
        result_count=row.result_count,
        dedupe_key=row.dedupe_key,
    )


class SqlSavedSearchRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, owner_id: str, item_id: str) -> SavedSearch | None:
        row = (
            self._s.query(SavedSearchTable)
            .filter(SavedSearchTable.owner_id == owner_id, SavedSearchTable.id == item_id)
            .first()
        )
        return _saved_to_domain(row) if row else None

    def find_by_normalized(self, owner_id: str, normalized_query: str) -> SavedSearch | None:
        row = (
            self._s.query(SavedSearchTable)
            .filter(
                SavedSearchTable.owner_id == owner_id,
                SavedSearchTable.normalized_query == normalized_query,
            )
            .first()
        )
        return _saved_to_domain(row) if row else None

    def count(self, owner_id: str) -> int:
        return self._s.query(SavedSearchTable).filter(SavedSearchTable.owner_id == owner_id).count()

    def insert(self, item: SavedSearch) -> SavedSearch:
        self._s.add(
            SavedSearchTable(
                id=item.id,
                owner_id=item.owner_id,
                query=item.query,
                normalized_query=item.normalized_query,
                label=item.label,
                created_at=item.created_at,
            )
        )
        self._s.flush()
        return item

    def update_label(self, owner_id: str, item_id: str, label: str | None) -> SavedSearch | None:
        row = (
            self._s.query(SavedSearchTable)
            .filter(SavedSearchTable.owner_id == owner_id, SavedSearchTable.id == item_id)
            .first()
        )
        if row is None:
            return None
        row.label = label
        self._s.flush()
        return _saved_to_domain(row)

    def delete(self, owner_id: str, item_id: str) -> bool:
        n = (
            self._s.query(SavedSearchTable)
            .filter(SavedSearchTable.owner_id == owner_id, SavedSearchTable.id == item_id)
            .delete()
        )
        return n > 0

    def list_page(self, owner_id: str, limit: int, after: CursorKey | None) -> list[SavedSearch]:
        q = self._s.query(SavedSearchTable).filter(SavedSearchTable.owner_id == owner_id)
        if after is not None:
            q = q.filter(tuple_(SavedSearchTable.created_at, SavedSearchTable.id) < after)
        rows = q.order_by(SavedSearchTable.created_at.desc(), SavedSearchTable.id.desc()).limit(
            limit
        )
        return [_saved_to_domain(r) for r in rows]


class SqlLibraryRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, owner_id: str, item_id: str) -> LibraryItem | None:
        row = (
            self._s.query(LibraryItemTable)
            .filter(LibraryItemTable.owner_id == owner_id, LibraryItemTable.id == item_id)
            .first()
        )
        return _library_to_domain(row) if row else None

    def find_by_arxiv(self, owner_id: str, arxiv_id: str) -> LibraryItem | None:
        row = (
            self._s.query(LibraryItemTable)
            .filter(LibraryItemTable.owner_id == owner_id, LibraryItemTable.arxiv_id == arxiv_id)
            .first()
        )
        return _library_to_domain(row) if row else None

    def count(self, owner_id: str) -> int:
        return self._s.query(LibraryItemTable).filter(LibraryItemTable.owner_id == owner_id).count()

    def insert(self, item: LibraryItem) -> LibraryItem:
        self._s.add(
            LibraryItemTable(
                id=item.id,
                owner_id=item.owner_id,
                arxiv_id=item.arxiv_id,
                meta=item.meta.model_dump(exclude_none=True),
                added_at=item.added_at,
            )
        )
        self._s.flush()
        return item

    def delete(self, owner_id: str, item_id: str) -> bool:
        n = (
            self._s.query(LibraryItemTable)
            .filter(LibraryItemTable.owner_id == owner_id, LibraryItemTable.id == item_id)
            .delete()
        )
        return n > 0

    def mark_retracted(self, paper_id: str) -> int:
        base = _strip_version(paper_id)
        rows = (
            self._s.query(LibraryItemTable)
            .filter(
                or_(
                    LibraryItemTable.arxiv_id == paper_id,
                    LibraryItemTable.arxiv_id == base,
                    LibraryItemTable.arxiv_id.like(f"{base}v%"),
                )
            )
            .all()
        )
        changed = 0
        for row in rows:
            if row.meta.get("retracted") is True:
                continue
            row.meta = {**row.meta, "retracted": True}
            changed += 1
        if changed:
            self._s.flush()
        return changed

    def list_page(self, owner_id: str, limit: int, after: CursorKey | None) -> list[LibraryItem]:
        q = self._s.query(LibraryItemTable).filter(LibraryItemTable.owner_id == owner_id)
        if after is not None:
            q = q.filter(tuple_(LibraryItemTable.added_at, LibraryItemTable.id) < after)
        rows = q.order_by(LibraryItemTable.added_at.desc(), LibraryItemTable.id.desc()).limit(limit)
        return [_library_to_domain(r) for r in rows]


class SqlSearchHistoryRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, owner_id: str, item_id: str) -> HistoryEntry | None:
        row = (
            self._s.query(SearchHistoryTable)
            .filter(SearchHistoryTable.owner_id == owner_id, SearchHistoryTable.id == item_id)
            .first()
        )
        return _history_to_domain(row) if row else None

    def find_by_dedupe_key(self, owner_id: str, dedupe_key: str) -> HistoryEntry | None:
        row = (
            self._s.query(SearchHistoryTable)
            .filter(
                SearchHistoryTable.owner_id == owner_id,
                SearchHistoryTable.dedupe_key == dedupe_key,
            )
            .first()
        )
        return _history_to_domain(row) if row else None

    def insert(self, item: HistoryEntry) -> HistoryEntry:
        self._s.add(
            SearchHistoryTable(
                id=item.id,
                owner_id=item.owner_id,
                query=item.query,
                executed_at=item.executed_at,
                result_count=item.result_count,
                dedupe_key=item.dedupe_key,
            )
        )
        self._s.flush()
        return item

    def clear(self, owner_id: str) -> int:
        return (
            self._s.query(SearchHistoryTable)
            .filter(SearchHistoryTable.owner_id == owner_id)
            .delete()
        )

    def prune_to(self, owner_id: str, max_keep: int) -> int:
        rows = (
            self._s.query(SearchHistoryTable.id)
            .filter(SearchHistoryTable.owner_id == owner_id)
            .order_by(SearchHistoryTable.executed_at.desc(), SearchHistoryTable.id.desc())
            .offset(max_keep)
            .all()
        )
        drop_ids = [r[0] for r in rows]
        if not drop_ids:
            return 0
        return (
            self._s.query(SearchHistoryTable)
            .filter(SearchHistoryTable.id.in_(drop_ids))
            .delete(synchronize_session=False)
        )

    def list_page(self, owner_id: str, limit: int, after: CursorKey | None) -> list[HistoryEntry]:
        q = self._s.query(SearchHistoryTable).filter(SearchHistoryTable.owner_id == owner_id)
        if after is not None:
            q = q.filter(tuple_(SearchHistoryTable.executed_at, SearchHistoryTable.id) < after)
        rows = q.order_by(
            SearchHistoryTable.executed_at.desc(), SearchHistoryTable.id.desc()
        ).limit(limit)
        return [_history_to_domain(r) for r in rows]


class SqlUserDataRepository:
    """Aggregate satisfying ``UserDataRepository`` against a SQLAlchemy ``Session``."""

    def __init__(self, session: Session) -> None:
        self.saved_searches = SqlSavedSearchRepository(session)
        self.library = SqlLibraryRepository(session)
        self.history = SqlSearchHistoryRepository(session)
