"""U4 Library — port interfaces (typing.Protocol seams).

Ports decouple the domain services from concrete adapters so the module is mock-first: the
in-memory adapters are the default (the app-shell mounts U4 with no live infra), and the SQL /
gateway / audit adapters swap in through the same interfaces (D10). Every repository method is
**owner-scoped** — owner_id is a required argument, so an adapter structurally cannot return
another owner's row (INV-L1, the SEC-8 data-layer backstop).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from backend.modules.accounts.models import Principal

from .audit import AuditEvent
from .models import HistoryEntry, LibraryItem, SavedSearch
from .schemas import SearchResultSetDTO

# A keyset cursor key: (sort_instant, id). Pages are most-recent-first, so "after" means
# strictly older than this key in (instant desc, id desc) order.
CursorKey = tuple[datetime, str]


@runtime_checkable
class SavedSearchRepository(Protocol):
    def get(self, owner_id: str, item_id: str) -> SavedSearch | None: ...
    def find_by_normalized(self, owner_id: str, normalized_query: str) -> SavedSearch | None: ...
    def count(self, owner_id: str) -> int: ...
    def insert(self, item: SavedSearch) -> SavedSearch: ...
    def delete(self, owner_id: str, item_id: str) -> bool: ...
    def update_label(
        self, owner_id: str, item_id: str, label: str | None
    ) -> SavedSearch | None: ...
    def list_page(
        self, owner_id: str, limit: int, after: CursorKey | None
    ) -> list[SavedSearch]: ...


@runtime_checkable
class LibraryRepository(Protocol):
    def get(self, owner_id: str, item_id: str) -> LibraryItem | None: ...
    def find_by_arxiv(self, owner_id: str, arxiv_id: str) -> LibraryItem | None: ...
    def count(self, owner_id: str) -> int: ...
    def insert(self, item: LibraryItem) -> LibraryItem: ...
    def delete(self, owner_id: str, item_id: str) -> bool: ...
    def mark_retracted(self, paper_id: str) -> int: ...
    def list_page(
        self, owner_id: str, limit: int, after: CursorKey | None
    ) -> list[LibraryItem]: ...


@runtime_checkable
class SearchHistoryRepository(Protocol):
    def get(self, owner_id: str, item_id: str) -> HistoryEntry | None: ...
    def find_by_dedupe_key(self, owner_id: str, dedupe_key: str) -> HistoryEntry | None: ...
    def insert(self, item: HistoryEntry) -> HistoryEntry: ...
    def clear(self, owner_id: str) -> int: ...
    def prune_to(self, owner_id: str, max_keep: int) -> int: ...
    def list_page(
        self, owner_id: str, limit: int, after: CursorKey | None
    ) -> list[HistoryEntry]: ...


@runtime_checkable
class UserDataRepository(Protocol):
    """Aggregate of the three owner-scoped sub-repositories (application-design U4)."""

    saved_searches: SavedSearchRepository
    library: LibraryRepository
    history: SearchHistoryRepository


@runtime_checkable
class SearchGatewayPort(Protocol):
    """Re-run seam (INV-L2). Rerun re-enters the gateway-fronted search contract
    (U6 ApiGatewayMiddleware → U2) so cost + grounding hooks re-apply — NEVER a direct U2 call.
    """

    async def search(self, query: str, principal: Principal) -> SearchResultSetDTO: ...


@runtime_checkable
class AuditSink(Protocol):
    """Mutating-op audit (SEC-13). Payloads carry no sensitive/internal fields (SEC-9)."""

    def record(self, event: AuditEvent) -> None: ...
