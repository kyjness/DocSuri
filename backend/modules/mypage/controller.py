"""U10 My Page — Subscription HTTP controller (mock, no real PG/billing) + DI seams.

Single synchronous router. Mirrors U4 library's wiring: the controller obtains the
authenticated ``Principal`` (set on ``request.state`` by the U6 gateway middleware in the
assembled monolith) and maps to HTTP — fail-closed to 401. The DI provider defaults to the
mock-first in-memory adapter so the module mounts and serves with no live infra; the app-shell
overrides it for production (SQL).
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.modules.accounts.models import Principal

from .ports import AccountRepository, SubscriptionRepository
from .repository.memory import InMemoryAccountRepository, InMemorySubscriptionRepository
from .schemas import AccountProfileDTO, ConsentsDTO, ConsentsUpdate, SubscriptionDTO
from .services.account import AccountService
from .services.subscription import SubscriptionService


# ── DI seams (overridable by the app-shell; default = mock-first singleton) ──
@lru_cache(maxsize=1)
def get_subscription_repo() -> SubscriptionRepository:
    return InMemorySubscriptionRepository()


@lru_cache(maxsize=1)
def get_account_repo() -> AccountRepository:
    return InMemoryAccountRepository()


def get_principal(request: Request) -> Principal:
    """Authenticated principal, injected by the U6 gateway middleware (request.state.principal).
    Absent -> 401 (fail-closed). Test/standalone callers override this dependency."""
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal


def get_subscription_service(
    repo: SubscriptionRepository = Depends(get_subscription_repo),
) -> SubscriptionService:
    return SubscriptionService(repo)


def get_account_service(
    repo: AccountRepository = Depends(get_account_repo),
) -> AccountService:
    return AccountService(repo)


router = APIRouter(prefix="/mypage/subscription", tags=["MyPage/Subscription"])


@router.get("", response_model=SubscriptionDTO)
async def get_subscription(
    principal: Principal = Depends(get_principal),
    svc: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionDTO:
    return svc.get(principal)


@router.post("", response_model=SubscriptionDTO, status_code=201)
async def subscribe(
    principal: Principal = Depends(get_principal),
    svc: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionDTO:
    return svc.subscribe(principal)


@router.post("/cancel", response_model=SubscriptionDTO)
async def cancel_subscription(
    principal: Principal = Depends(get_principal),
    svc: SubscriptionService = Depends(get_subscription_service),
) -> SubscriptionDTO:
    return svc.cancel(principal)


# Account-backed profile + consents (REAL U3 accounts data via the AccountRepository port).
account_router = APIRouter(prefix="/mypage", tags=["MyPage/Account"])


@account_router.get("/account-profile", response_model=AccountProfileDTO)
async def get_account_profile(
    principal: Principal = Depends(get_principal),
    svc: AccountService = Depends(get_account_service),
) -> AccountProfileDTO:
    profile = svc.get_profile(principal)
    if profile is None:
        raise HTTPException(status_code=404, detail="account not found")
    return profile


@account_router.get("/consents", response_model=ConsentsDTO)
async def get_consents(
    principal: Principal = Depends(get_principal),
    svc: AccountService = Depends(get_account_service),
) -> ConsentsDTO:
    consents = svc.get_consents(principal)
    if consents is None:
        raise HTTPException(status_code=404, detail="account not found")
    return consents


@account_router.post("/consents", response_model=ConsentsDTO)
async def update_consents(
    body: ConsentsUpdate,
    principal: Principal = Depends(get_principal),
    svc: AccountService = Depends(get_account_service),
) -> ConsentsDTO:
    consents = svc.set_nightly_push(principal, body.nightlyPushAgreed)
    if consents is None:
        raise HTTPException(status_code=404, detail="account not found")
    return consents


# Routers the app-shell mounts (mirrors library's `routers` tuple).
routers = (router, account_router)
