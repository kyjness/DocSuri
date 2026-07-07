from __future__ import annotations

import os

from docsuri_shared.authz import Principal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from .models import (
    BehaviorEventCreate,
    MetadataValidationError,
    PersonalizationDecision,
    PersonalizationSettings,
    RecentlyViewedItem,
    RecentlyViewedList,
    SettingsUpdate,
    ValidatedBehaviorEventCreate,
)
from .repository import PersonalizationRepository
from .service import (
    BehaviorEventRecorder,
    PersonalizationReadPort,
    PersonalizationSettingsService,
)


def _feature_enabled() -> None:
    if os.getenv("PERSONALIZATION_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=404, detail="not found")


router = APIRouter(
    prefix="/api/personalization",
    tags=["Personalization"],
    dependencies=[Depends(_feature_enabled)],
)


def get_repo() -> PersonalizationRepository:
    raise RuntimeError("personalization repository is not wired")


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal


def _observability(request: Request):
    return getattr(request.app.state, "observability", None)


PRINCIPAL_DEP = Depends(get_principal)
REPO_DEP = Depends(get_repo)


@router.post("/events")
async def record_event(
    dto: BehaviorEventCreate,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: PersonalizationRepository = REPO_DEP,
):
    try:
        valid = ValidatedBehaviorEventCreate.model_validate(dto.model_dump())
    except (ValidationError, MetadataValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BehaviorEventRecorder(repo, _observability(request)).record(principal.user_id, valid)


@router.get("/decision/search", response_model=PersonalizationDecision)
async def search_decision(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: PersonalizationRepository = REPO_DEP,
) -> PersonalizationDecision:
    return PersonalizationReadPort(repo, observability=_observability(request)).search_decision(
        principal.user_id
    )


@router.get("/decision/summary-defaults", response_model=PersonalizationDecision)
async def summary_defaults(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: PersonalizationRepository = REPO_DEP,
) -> PersonalizationDecision:
    return PersonalizationReadPort(repo, observability=_observability(request)).summary_defaults(
        principal.user_id
    )


@router.get("/settings", response_model=PersonalizationSettings)
async def get_settings(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: PersonalizationRepository = REPO_DEP,
) -> PersonalizationSettings:
    return PersonalizationSettingsService(repo, _observability(request)).get(principal.user_id)


@router.patch("/settings", response_model=PersonalizationSettings)
async def update_settings(
    dto: SettingsUpdate,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: PersonalizationRepository = REPO_DEP,
) -> PersonalizationSettings:
    return PersonalizationSettingsService(repo, _observability(request)).set_enabled(
        principal.user_id, dto.enabled
    )


@router.post("/delete-events")
async def delete_events(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: PersonalizationRepository = REPO_DEP,
):
    deleted = PersonalizationSettingsService(repo, _observability(request)).delete_events(
        principal.user_id
    )
    return {"deletedEvents": deleted}


@router.post("/reset-profile")
async def reset_profile(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: PersonalizationRepository = REPO_DEP,
):
    PersonalizationSettingsService(repo, _observability(request)).reset_profile(principal.user_id)
    return {"status": "reset"}


recently_viewed_router = APIRouter(
    prefix="/mypage",
    tags=["Personalization"],
    dependencies=[Depends(_feature_enabled)],
)


@recently_viewed_router.get("/recently-viewed", response_model=RecentlyViewedList)
async def recently_viewed(
    principal: Principal = PRINCIPAL_DEP,
    repo: PersonalizationRepository = REPO_DEP,
) -> RecentlyViewedList:
    rows = repo.list_recent_papers(principal.user_id)
    items = [
        RecentlyViewedItem(arxivId=arxiv_id, title=title, viewedAt=viewed_at)
        for arxiv_id, title, viewed_at in rows
    ]
    return RecentlyViewedList(items=items)


routers = (router, recently_viewed_router)
