"""U10 My Page — Subscription HTTP controller (mock, no real PG/billing) + DI seams.

Single synchronous router. Mirrors U4 library's wiring: the controller obtains the
authenticated ``Principal`` (set on ``request.state`` by the U6 gateway middleware in the
assembled monolith) and maps to HTTP — fail-closed to 401. The DI provider defaults to the
mock-first in-memory adapter so the module mounts and serves with no live infra; the app-shell
overrides it for production (SQL).
"""

from __future__ import annotations

import os
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.modules.accounts.integrations.oidc import ORCID_BASES, fetch_orcid_public_record
from backend.modules.accounts.models import Principal

from .ports import AccountRepository, SubscriptionRepository
from .repository.memory import InMemoryAccountRepository, InMemorySubscriptionRepository
from .schemas import (
    AccountProfileDTO,
    ConsentsDTO,
    ConsentsUpdate,
    OrcidProfileDTO,
    OrcidWorkDTO,
    SubscriptionDTO,
)
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


@account_router.get("/orcid-profile", response_model=OrcidProfileDTO)
async def get_orcid_profile(
    principal: Principal = Depends(get_principal),
    svc: AccountService = Depends(get_account_service),
) -> OrcidProfileDTO:
    """ORCID 공개 프로필 (FR-27/BR-A13). 이름·소속은 로그인 시 캐시한 값, works는 ORCID Public
    API에서 라이브로 best-effort 취득(실패 시 빈 목록). ORCID로 로그인하지 않은 계정은 404."""
    identity = svc.get_orcid_identity(principal)
    if identity is None:
        raise HTTPException(status_code=404, detail="orcid profile not found")
    _, pub_base = ORCID_BASES.get(os.getenv("ORCID_OIDC_ENV", "prod"), ORCID_BASES["prod"])
    record = await fetch_orcid_public_record(identity.orcid_id, pub_base=pub_base)
    works = [OrcidWorkDTO(title=w["title"], year=w.get("year")) for w in record.get("works", [])]
    return OrcidProfileDTO(
        orcidId=identity.orcid_id,
        name=identity.name or identity.orcid_id,
        affiliation=identity.affiliation,
        works=works,
    )


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
