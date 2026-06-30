"""FastAPI router for U2 search (QueryIntakeController). THIN HTTP binding only.

⏳ FastAPI is a backend-shared (app-shell) decision pending @ELSAPHABA sign-off (CG-1/DS-3);
import this module only with the ``api`` extra. In production, authn/authz/rate-limit and the
grounding post-handler are the U6 gateway's job. ``/api/search`` is auth-OPTIONAL at the gateway
(anonymous search is a product feature), so an unauthenticated request arrives with
``principal=None``; the production mount never trusts the client ``X-User-Id`` header for
identity (spoofable, and ``userId`` is U4's history owner key — SEC-8) and treats anonymous as a
fixed id. The standalone dev app opts into the header for multi-user testing. The app-shell
mounts the returned router and owns real gateway wiring (CG-5).
"""

from __future__ import annotations

import uuid

from docsuri_shared.dtos import SearchRequest, ValidationErrorDTO
from docsuri_shared.ports import GroundingEnforcementHook
from fastapi import APIRouter, FastAPI, Header, Request
from fastapi.responses import JSONResponse

from ..domain.models import AuthSession, RequestContext
from ..service.orchestrator import SearchOrchestrationService, SearchUnavailable
from ..service.paper_metadata import PaperMetadataService
from .gateway_seam import run_search

# Generic fail-closed messages (SEC-9/SEC-15 — no internal detail / stack / framework info).
_UNAVAILABLE_MESSAGE = "Search is temporarily unavailable. Please try again shortly."
_GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again."

# Server-controlled identity for an unauthenticated (auth-optional) search. /api/search is
# listed in the gateway's _AUTH_OPTIONAL_PREFIXES (backend/middleware/auth.py): anonymous
# search is a product feature, so an unauthenticated request arrives with principal=None.
_ANONYMOUS_USER_ID = "anonymous"


def _resolve_user_id(principal, x_user_id: str | None, *, allow_dev_user: bool) -> str:
    """Resolve the request's user id (the SearchExecuted owner key, FR-10).

    A gateway-injected ``principal`` (SEC-8/BR-13) always wins. Otherwise PRODUCTION
    (``allow_dev_user=False``) NEVER trusts the client-supplied ``X-User-Id`` header — it is
    spoofable and ``userId`` is U4's history owner key, so honoring it would let an anonymous
    client inject search history into any account (SEC-8). Anonymous resolves to a fixed
    server-controlled id. Only the mock-first standalone app honors the header (dev multi-user
    testing)."""
    if principal is not None:
        return principal.user_id
    if allow_dev_user:
        return x_user_id or "dev-user"
    return _ANONYMOUS_USER_ID


def build_router(
    orchestrator: SearchOrchestrationService,
    grounding_hook: GroundingEnforcementHook,
    paper_service: PaperMetadataService | None = None,
    *,
    allow_dev_user: bool = False,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/search")
    def search(
        http_request: Request,
        request: SearchRequest,
        x_user_id: str | None = Header(default=None),
    ) -> JSONResponse:
        # Gateway-injected principal (SEC-8) wins; prod never trusts the X-User-Id header.
        principal = getattr(http_request.state, "principal", None)
        user_id = _resolve_user_id(principal, x_user_id, allow_dev_user=allow_dev_user)
        request_id = getattr(http_request.state, "request_id", None) or uuid.uuid4().hex
        ctx = RequestContext(
            auth_session=AuthSession(user_id=user_id), request_id=request_id
        )
        response = run_search(orchestrator, grounding_hook, request, ctx)
        status = 400 if isinstance(response.root, ValidationErrorDTO) else 200
        return JSONResponse(status_code=status, content=response.model_dump(mode="json"))

    if paper_service is not None:

        @router.get("/api/papers/{paper_id}")
        def paper_meta(paper_id: str) -> JSONResponse:
            """Paper-detail header metadata (title/authors/abstract). 404 when not indexed so
            the detail page degrades to the arXiv id + link-out. SearchUnavailable (store
            outage) is mapped to the generic 503 by the app-shell / build_app handler."""
            meta = paper_service.get_paper_meta(paper_id)
            if meta is None:
                return JSONResponse(status_code=404, content={"message": "Paper not found."})
            return JSONResponse(status_code=200, content=meta.model_dump(mode="json"))

    return router


def build_app(
    orchestrator: SearchOrchestrationService,
    grounding_hook: GroundingEnforcementHook,
    paper_service: PaperMetadataService | None = None,
) -> FastAPI:
    """Standalone dev app (mock-first). The real backend app is the app-shell's (CG-5).

    ``allow_dev_user=True``: this dev app honors the ``X-User-Id`` header for multi-user
    testing. The production app-shell mount uses the secure default (header ignored)."""
    app = FastAPI(title="DocSuri Discovery (U2) — mock-first")
    app.include_router(
        build_router(orchestrator, grounding_hook, paper_service, allow_dev_user=True)
    )

    @app.exception_handler(SearchUnavailable)
    def _on_unavailable(_request, _exc):  # fail-closed: generic 503 (INV-3/SEC-15)
        return JSONResponse(status_code=503, content={"message": _UNAVAILABLE_MESSAGE})

    @app.exception_handler(Exception)
    def _on_unexpected(_request, _exc):  # global catch-all: generic 500, no leak (INV-3/SEC-15)
        return JSONResponse(status_code=500, content={"message": _GENERIC_ERROR_MESSAGE})

    return app
