"""Shared fixtures for U4 Library tests.

Tests run on the mock-first in-memory adapters (no live infra). ``make_app`` mounts the three
routers on a bare FastAPI app and overrides the DI seams — including ``get_principal`` (which
normally reads request.state.principal set by U6 middleware) so a test can act as any principal.
"""

from __future__ import annotations

import uuid

import pytest
from backend.modules.accounts.models import Principal, UserRole
from backend.modules.library import controller
from backend.modules.library.audit import InMemoryAuditSink
from backend.modules.library.gateway import StubSearchGateway
from backend.modules.library.repository.memory import InMemoryUserDataRepository
from backend.modules.library.services.history import SearchHistoryService
from backend.modules.library.services.library import LibraryService
from backend.modules.library.services.saved_search import SavedSearchService
from fastapi import FastAPI


def _new_principal() -> Principal:
    return Principal(user_id=str(uuid.uuid4()), role=UserRole.USER)


def _new_services(repo: InMemoryUserDataRepository | None = None):
    repo = repo or InMemoryUserDataRepository()
    gw = StubSearchGateway()
    audit = InMemoryAuditSink()
    return (
        SavedSearchService(repo, gw, audit),
        LibraryService(repo, audit),
        SearchHistoryService(repo, gw, audit),
        repo,
        audit,
    )


def _build_app(principal: Principal, repo: InMemoryUserDataRepository | None = None):
    repo = repo or InMemoryUserDataRepository()
    gw = StubSearchGateway()
    audit = InMemoryAuditSink()
    app = FastAPI()
    for router in controller.routers:
        app.include_router(router)
    app.dependency_overrides[controller.get_user_data_repo] = lambda: repo
    app.dependency_overrides[controller.get_search_gateway] = lambda: gw
    app.dependency_overrides[controller.get_audit_sink] = lambda: audit
    app.dependency_overrides[controller.get_principal] = lambda: principal
    return app, repo


@pytest.fixture
def make_principal():
    return _new_principal


@pytest.fixture
def make_services():
    return _new_services


@pytest.fixture
def make_app():
    return _build_app
