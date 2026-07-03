"""U4 Library — in-memory repository adapters (the mock-first default, D10).

These are the default adapters: the app-shell mounts U4 with them so the module serves with NO
live database, and the test suite runs green without infra (mirrors discovery's mock-first
stance). The production ``SqlUserDataRepository`` (``sql.py``) swaps in behind the same ports.

Every method is owner-scoped (INV-L1): the owner_id argument is part of every lookup, so a query
structurally cannot cross owners — the data-layer backstop under U3's AuthorizationGuard (SEC-8).
"""

from __future__ import annotations

import re
from datetime import datetime

from ..models import HistoryEntry, LibraryItem, SavedSearch

CursorKey = tuple[datetime, str]
_VERSION_SUFFIX = re.compile(r"v\d+$")


def _strip_version(paper_id: str) -> str:
    return _VERSION_SUFFIX.sub("", paper_id)


def _paper_ids_match(stored: str, event_paper_id: str) -> bool:
    return stored == event_paper_id or _strip_version(stored) == _strip_version(event_paper_id)


def _page(rows: list, key, limit: int, after: CursorKey | None) -> list:
    """Most-recent-first keyset slice: items strictly older than ``after``, newest first."""
    ordered = sorted(rows, key=key, reverse=True)
    if after is not None:
        ordered = [r for r in ordered if key(r) < after]
    return ordered[:limit]


class InMemorySavedSearchRepository:
    def __init__(self) -> None:
        # owner_id -> {id -> SavedSearch}
        self._by_owner: dict[str, dict[str, SavedSearch]] = {}

    def _owner(self, owner_id: str) -> dict[str, SavedSearch]:
        return self._by_owner.setdefault(owner_id, {})

    def get(self, owner_id: str, item_id: str) -> SavedSearch | None:
        return self._owner(owner_id).get(item_id)

    def find_by_normalized(self, owner_id: str, normalized_query: str) -> SavedSearch | None:
        for s in self._owner(owner_id).values():
            if s.normalized_query == normalized_query:
                return s
        return None

    def count(self, owner_id: str) -> int:
        return len(self._owner(owner_id))

    def insert(self, item: SavedSearch) -> SavedSearch:
        self._owner(item.owner_id)[item.id] = item
        return item

    def update_label(self, owner_id: str, item_id: str, label: str | None) -> SavedSearch | None:
        s = self._owner(owner_id).get(item_id)
        if s is None:
            return None
        s.label = label
        return s

    def delete(self, owner_id: str, item_id: str) -> bool:
        return self._owner(owner_id).pop(item_id, None) is not None

    def list_page(self, owner_id: str, limit: int, after: CursorKey | None) -> list[SavedSearch]:
        return _page(
            list(self._owner(owner_id).values()), lambda s: (s.created_at, s.id), limit, after
        )


class InMemoryLibraryRepository:
    def __init__(self) -> None:
        self._by_owner: dict[str, dict[str, LibraryItem]] = {}

    def _owner(self, owner_id: str) -> dict[str, LibraryItem]:
        return self._by_owner.setdefault(owner_id, {})

    def get(self, owner_id: str, item_id: str) -> LibraryItem | None:
        return self._owner(owner_id).get(item_id)

    def find_by_arxiv(self, owner_id: str, arxiv_id: str) -> LibraryItem | None:
        for li in self._owner(owner_id).values():
            if li.arxiv_id == arxiv_id:
                return li
        return None

    def count(self, owner_id: str) -> int:
        return len(self._owner(owner_id))

    def insert(self, item: LibraryItem) -> LibraryItem:
        self._owner(item.owner_id)[item.id] = item
        return item

    def delete(self, owner_id: str, item_id: str) -> bool:
        return self._owner(owner_id).pop(item_id, None) is not None

    def mark_retracted(self, paper_id: str) -> int:
        changed = 0
        for bucket in self._by_owner.values():
            for item_id, item in list(bucket.items()):
                if not _paper_ids_match(item.arxiv_id, paper_id) or item.meta.retracted:
                    continue
                bucket[item_id] = LibraryItem(
                    id=item.id,
                    owner_id=item.owner_id,
                    arxiv_id=item.arxiv_id,
                    meta=item.meta.model_copy(update={"retracted": True}),
                    added_at=item.added_at,
                )
                changed += 1
        return changed

    def list_page(self, owner_id: str, limit: int, after: CursorKey | None) -> list[LibraryItem]:
        return _page(
            list(self._owner(owner_id).values()), lambda li: (li.added_at, li.id), limit, after
        )


class InMemorySearchHistoryRepository:
    def __init__(self) -> None:
        self._by_owner: dict[str, dict[str, HistoryEntry]] = {}

    def _owner(self, owner_id: str) -> dict[str, HistoryEntry]:
        return self._by_owner.setdefault(owner_id, {})

    def get(self, owner_id: str, item_id: str) -> HistoryEntry | None:
        return self._owner(owner_id).get(item_id)

    def find_by_dedupe_key(self, owner_id: str, dedupe_key: str) -> HistoryEntry | None:
        for h in self._owner(owner_id).values():
            if h.dedupe_key == dedupe_key:
                return h
        return None

    def insert(self, item: HistoryEntry) -> HistoryEntry:
        self._owner(item.owner_id)[item.id] = item
        return item

    def clear(self, owner_id: str) -> int:
        bucket = self._owner(owner_id)
        n = len(bucket)
        bucket.clear()
        return n

    def prune_to(self, owner_id: str, max_keep: int) -> int:
        """Keep the most-recent ``max_keep`` entries; drop the rest (BR-L6 rolling retention)."""
        bucket = self._owner(owner_id)
        if len(bucket) <= max_keep:
            return 0
        ordered = sorted(bucket.values(), key=lambda h: (h.executed_at, h.id), reverse=True)
        dropped = [h.id for h in ordered[max_keep:]]
        for hid in dropped:
            bucket.pop(hid, None)
        return len(dropped)

    def list_page(self, owner_id: str, limit: int, after: CursorKey | None) -> list[HistoryEntry]:
        return _page(
            list(self._owner(owner_id).values()), lambda h: (h.executed_at, h.id), limit, after
        )


class InMemoryUserDataRepository:
    """Aggregate satisfying the ``UserDataRepository`` port (3 owner-scoped sub-repos)."""

    def __init__(self) -> None:
        self.saved_searches = InMemorySavedSearchRepository()
        self.library = InMemoryLibraryRepository()
        self.history = InMemorySearchHistoryRepository()
