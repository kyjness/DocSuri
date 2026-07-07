"""U4 — SavedSearchService (US-L1/FR-8): save, list, delete, rerun a user's queries."""

from __future__ import annotations

from docsuri_shared.authz import Action, Principal

from ..audit import make_event
from ..authz import authorize_owned
from ..models import NotFoundError, QuotaExceededError
from ..ports import AuditSink, SearchGatewayPort, UserDataRepository
from ..schemas import (
    SavedSearchCreateDTO,
    SavedSearchDTO,
    SavedSearchPageDTO,
    SearchResultSetDTO,
)
from ..validation import (
    UserDataDTOAndValidation,
    build_page,
    normalize_query,
    to_saved_dto,
)

MAX_SAVED_PER_OWNER = 200  # BR-L2


class SavedSearchService:
    def __init__(
        self, repo: UserDataRepository, gateway: SearchGatewayPort, audit: AuditSink
    ) -> None:
        self._repo = repo
        self._gateway = gateway
        self._audit = audit

    def save(self, principal: Principal, dto: SavedSearchCreateDTO) -> SavedSearchDTO:
        entity = UserDataDTOAndValidation.validate_and_map(dto, principal)
        owner = principal.user_id
        repo = self._repo.saved_searches

        # BR-L1: idempotent on (owner, normalized_query) — re-save returns existing, may relabel.
        existing = repo.find_by_normalized(owner, entity.normalized_query)
        if existing is not None:
            if entity.label is not None and entity.label != existing.label:
                # Use the updated row so the response reflects the new label on every adapter.
                # (SQL's find_by_normalized returns a detached copy; without this the response
                #  would echo the stale label even though the row was relabeled — BR-L1/FR-8.)
                existing = repo.update_label(owner, existing.id, entity.label) or existing
            ret_dto = to_saved_dto(existing)
            object.__setattr__(ret_dto, "was_created", False)
            return ret_dto

        # BR-L2: per-owner quota.
        if repo.count(owner) >= MAX_SAVED_PER_OWNER:
            raise QuotaExceededError(
                f"saved-search limit of {MAX_SAVED_PER_OWNER} reached"
            )

        repo.insert(entity)
        self._audit.record(make_event("saved_search.create", "saved_search", entity.id, owner))
        ret_dto = to_saved_dto(entity)
        object.__setattr__(ret_dto, "was_created", True)
        return ret_dto

    def list(self, principal: Principal, params, *, query: str | None = None) -> SavedSearchPageDTO:
        if query is not None:
            normalized = normalize_query(query)
            entity = self._repo.saved_searches.find_by_normalized(principal.user_id, normalized)
            items = [to_saved_dto(entity)] if entity is not None else []
            return SavedSearchPageDTO(items=items, nextCursor=None)
        return build_page(
            self._repo.saved_searches.list_page,
            principal.user_id,
            params,
            key_of=lambda s: (s.created_at, s.id),
            to_dto=to_saved_dto,
            page_ctor=SavedSearchPageDTO,
        )

    def delete(self, principal: Principal, item_id: str) -> None:
        entity = self._repo.saved_searches.get(principal.user_id, item_id)
        if entity is None:
            raise NotFoundError("saved search not found")  # SEC-9 generalized
        authorize_owned(principal, Action.DELETE, entity.owner_id)  # SEC-8 single authority
        self._repo.saved_searches.delete(principal.user_id, item_id)
        self._audit.record(
            make_event("saved_search.delete", "saved_search", item_id, principal.user_id)
        )

    async def rerun(self, principal: Principal, item_id: str) -> SearchResultSetDTO:
        entity = self._repo.saved_searches.get(principal.user_id, item_id)
        if entity is None:
            raise NotFoundError("saved search not found")
        authorize_owned(principal, Action.RERUN, entity.owner_id)
        # INV-L2: re-enter the gateway-fronted search contract (never a direct U2 call).
        return await self._gateway.search(entity.query, principal)
