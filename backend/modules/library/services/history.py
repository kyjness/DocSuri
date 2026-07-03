"""U4 — SearchHistoryService (US-L3/FR-10).

Write is event-driven and non-blocking (NFR-P1): ``record_search`` consumes the at-least-once
``SearchExecutedEvent`` (FROZEN) idempotently by ``dedupe_key`` (BR-L7/INV-L3) and prunes to the
rolling retention cap (BR-L6). Read (list/rerun/clear) is synchronous and owner-scoped.
"""

from __future__ import annotations

from uuid import uuid4

from docsuri_shared.events import SearchExecutedEvent

from backend.modules.accounts.models import Action, Principal

from ..audit import make_event
from ..authz import authorize_owned
from ..models import HistoryEntry, NotFoundError
from ..ports import AuditSink, SearchGatewayPort, UserDataRepository
from ..schemas import HistoryPageDTO, SearchResultSetDTO
from ..validation import build_page, dedupe_key, to_history_dto

RETENTION_LIMIT = 500  # BR-L6 rolling retention per owner


class SearchHistoryService:
    def __init__(
        self, repo: UserDataRepository, gateway: SearchGatewayPort, audit: AuditSink
    ) -> None:
        self._repo = repo
        self._gateway = gateway
        self._audit = audit

    def record_search(self, event: SearchExecutedEvent) -> HistoryEntry | None:
        """Idempotently record an executed search (at-least-once → exactly-once). Returns the new
        entry, or None when the event was a duplicate re-delivery."""
        owner = event.userId
        key = dedupe_key(owner, event.requestId, event.query)
        repo = self._repo.history

        if repo.find_by_dedupe_key(owner, key) is not None:
            return None  # INV-L3: duplicate re-delivery, no-op

        entity = HistoryEntry(
            id=str(uuid4()),
            owner_id=owner,
            query=event.query,
            executed_at=event.timestamp,
            result_count=event.resultCount,
            dedupe_key=key,
        )
        repo.insert(entity)
        repo.prune_to(owner, RETENTION_LIMIT)  # BR-L6
        return entity

    def list(self, principal: Principal, params) -> HistoryPageDTO:
        return build_page(
            self._repo.history.list_page,
            principal.user_id,
            params,
            key_of=lambda h: (h.executed_at, h.id),
            to_dto=to_history_dto,
            page_ctor=HistoryPageDTO,
        )

    async def rerun(self, principal: Principal, item_id: str) -> SearchResultSetDTO:
        entity = self._repo.history.get(principal.user_id, item_id)
        if entity is None:
            raise NotFoundError("history entry not found")
        authorize_owned(principal, Action.RERUN, entity.owner_id)
        # INV-L2: re-enter the gateway-fronted search contract (never a direct U2 call).
        return await self._gateway.search(entity.query, principal)

    def clear(self, principal: Principal) -> int:
        n = self._repo.history.clear(principal.user_id)
        self._audit.record(make_event("history.clear", "history", None, principal.user_id))
        return n
