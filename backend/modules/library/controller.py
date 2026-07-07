"""U4 Library — HTTP controllers (3 routers) + DI seams.

Three synchronous-CRUD routers (saved searches / library / history). Ownership is delegated to
U3's AuthorizationGuard inside the services; the controller only obtains the authenticated
``Principal`` (set on ``request.state`` by the U6 gateway middleware in the assembled monolith)
and maps domain exceptions to HTTP — generalizing cross-owner/absent to 404 (SEC-9) and failing
closed to 401/404/500. The DI providers default to the mock-first in-memory adapters so the
module mounts and serves with no live infra; the app-shell overrides them for production.
"""

from __future__ import annotations

from functools import lru_cache

from docsuri_shared.authz import Principal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .audit import InMemoryAuditSink
from .gateway import StubSearchGateway
from .models import (
    DomainException,
    GatewayUnavailableError,
    NotFoundError,
    QuotaExceededError,
    ValidationException,
)
from .ports import AuditSink, SearchGatewayPort, UserDataRepository
from .repository.memory import InMemoryUserDataRepository
from .schemas import (
    HistoryPageDTO,
    LibraryItemCreateDTO,
    LibraryItemDTO,
    LibraryPageDTO,
    PageParams,
    SavedSearchCreateDTO,
    SavedSearchDTO,
    SavedSearchPageDTO,
    SearchResultSetDTO,
)
from .services.history import SearchHistoryService
from .services.library import LibraryService
from .services.saved_search import SavedSearchService
from .validation import validate_limit


# ── DI seams (overridable by the app-shell; default = mock-first singletons) ──
@lru_cache(maxsize=1)
def get_user_data_repo() -> UserDataRepository:
    return InMemoryUserDataRepository()


@lru_cache(maxsize=1)
def get_search_gateway() -> SearchGatewayPort:
    return StubSearchGateway()


@lru_cache(maxsize=1)
def get_audit_sink() -> AuditSink:
    return InMemoryAuditSink()


def get_principal(request: Request) -> Principal:
    """Authenticated principal, injected by the U6 gateway middleware (request.state.principal).
    Absent → 401 (fail-closed, INV-L4). Test/standalone callers override this dependency."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal


def get_saved_search_service(
    repo: UserDataRepository = Depends(get_user_data_repo),
    gateway: SearchGatewayPort = Depends(get_search_gateway),
    audit: AuditSink = Depends(get_audit_sink),
) -> SavedSearchService:
    return SavedSearchService(repo, gateway, audit)


def get_library_service(
    repo: UserDataRepository = Depends(get_user_data_repo),
    audit: AuditSink = Depends(get_audit_sink),
) -> LibraryService:
    return LibraryService(repo, audit)


def get_history_service(
    repo: UserDataRepository = Depends(get_user_data_repo),
    gateway: SearchGatewayPort = Depends(get_search_gateway),
    audit: AuditSink = Depends(get_audit_sink),
) -> SearchHistoryService:
    return SearchHistoryService(repo, gateway, audit)


def _to_http(exc: DomainException) -> HTTPException:
    if isinstance(exc, ValidationException):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, QuotaExceededError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, GatewayUnavailableError):
        return HTTPException(status_code=503, detail="search temporarily unavailable")
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail="not found")
    # AuthorizationError + any other domain error → generalized 404 (SEC-9, fail-closed)
    return HTTPException(status_code=404, detail="not found")


# ── Saved searches (US-L1/FR-8) ──────────────────────────────────────────────
saved_router = APIRouter(prefix="/library/saved-searches", tags=["Library/SavedSearches"])


@saved_router.post("", response_model=SavedSearchDTO, status_code=201)
async def create_saved_search(
    dto: SavedSearchCreateDTO,
    response: Response,
    principal: Principal = Depends(get_principal),
    svc: SavedSearchService = Depends(get_saved_search_service),
) -> SavedSearchDTO:
    try:
        dto_out = svc.save(principal, dto)
        if not getattr(dto_out, "was_created", True):
            response.status_code = 200
        return dto_out
    except DomainException as exc:
        raise _to_http(exc) from exc


@saved_router.get("", response_model=SavedSearchPageDTO)
async def list_saved_searches(
    limit: int = Query(default=20),
    cursor: str | None = Query(default=None),
    query: str | None = Query(default=None),
    principal: Principal = Depends(get_principal),
    svc: SavedSearchService = Depends(get_saved_search_service),
) -> SavedSearchPageDTO:
    try:
        validate_limit(limit)
        return svc.list(principal, PageParams(limit=limit, cursor=cursor), query=query)
    except DomainException as exc:
        raise _to_http(exc) from exc


@saved_router.delete("/{item_id}", status_code=204)
async def delete_saved_search(
    item_id: str,
    principal: Principal = Depends(get_principal),
    svc: SavedSearchService = Depends(get_saved_search_service),
) -> Response:
    try:
        svc.delete(principal, item_id)
    except DomainException as exc:
        raise _to_http(exc) from exc
    return Response(status_code=204)


@saved_router.post("/{item_id}/rerun", response_model=SearchResultSetDTO)
async def rerun_saved_search(
    item_id: str,
    principal: Principal = Depends(get_principal),
    svc: SavedSearchService = Depends(get_saved_search_service),
) -> SearchResultSetDTO:
    try:
        return await svc.rerun(principal, item_id)
    except DomainException as exc:
        raise _to_http(exc) from exc


# ── Library (US-L2/FR-9) ─────────────────────────────────────────────────────
library_router = APIRouter(prefix="/library/items", tags=["Library/Items"])


@library_router.post("", response_model=LibraryItemDTO, status_code=201)
async def add_library_item(
    dto: LibraryItemCreateDTO,
    response: Response,
    principal: Principal = Depends(get_principal),
    svc: LibraryService = Depends(get_library_service),
) -> LibraryItemDTO:
    try:
        dto_out = svc.add(principal, dto)
        if not getattr(dto_out, "was_created", True):
            response.status_code = 200
        return dto_out
    except DomainException as exc:
        raise _to_http(exc) from exc


@library_router.get("", response_model=LibraryPageDTO)
async def list_library(
    limit: int = Query(default=20),
    cursor: str | None = Query(default=None),
    principal: Principal = Depends(get_principal),
    svc: LibraryService = Depends(get_library_service),
) -> LibraryPageDTO:
    try:
        validate_limit(limit)
        return svc.list(principal, PageParams(limit=limit, cursor=cursor))
    except DomainException as exc:
        raise _to_http(exc) from exc


@library_router.delete("/{item_id}", status_code=204)
async def remove_library_item(
    item_id: str,
    principal: Principal = Depends(get_principal),
    svc: LibraryService = Depends(get_library_service),
) -> Response:
    try:
        svc.remove(principal, item_id)
    except DomainException as exc:
        raise _to_http(exc) from exc
    return Response(status_code=204)


# ── Search history (US-L3/FR-10) ─────────────────────────────────────────────
history_router = APIRouter(prefix="/library/history", tags=["Library/History"])


@history_router.get("", response_model=HistoryPageDTO)
async def list_history(
    limit: int = Query(default=20),
    cursor: str | None = Query(default=None),
    principal: Principal = Depends(get_principal),
    svc: SearchHistoryService = Depends(get_history_service),
) -> HistoryPageDTO:
    try:
        validate_limit(limit)
        return svc.list(principal, PageParams(limit=limit, cursor=cursor))
    except DomainException as exc:
        raise _to_http(exc) from exc


@history_router.post("/{item_id}/rerun", response_model=SearchResultSetDTO)
async def rerun_history_entry(
    item_id: str,
    principal: Principal = Depends(get_principal),
    svc: SearchHistoryService = Depends(get_history_service),
) -> SearchResultSetDTO:
    try:
        return await svc.rerun(principal, item_id)
    except DomainException as exc:
        raise _to_http(exc) from exc


@history_router.delete("", status_code=204)
async def clear_history(
    principal: Principal = Depends(get_principal),
    svc: SearchHistoryService = Depends(get_history_service),
) -> Response:
    try:
        svc.clear(principal)
    except DomainException as exc:
        raise _to_http(exc) from exc
    return Response(status_code=204)


# Routers the app-shell mounts (brief §8).
routers = (saved_router, library_router, history_router)
