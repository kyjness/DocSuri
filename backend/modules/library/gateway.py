"""U4 Library — rerun search-gateway seam (INV-L2).

Re-running a saved search or a history entry MUST NOT call U2 directly: it re-enters the
gateway-fronted search contract (U6 ApiGatewayMiddleware → U2) so the cost guard and the
grounding-enforcement hook re-apply on every rerun (no backdoor — application-design "rerun
reconciliation"). U4 ships a deterministic ``StubSearchGateway`` placeholder; the real binding
to the U6 gateway swaps in behind the same ``SearchGatewayPort`` without touching U4 callers.
"""

from __future__ import annotations

import asyncio
import uuid
from functools import partial
from typing import TYPE_CHECKING

from docsuri_shared.authz import Principal
from docsuri_shared.dtos import (
    DegradedResultDTO,
    ResultMeta,
    SearchRequest,
    SearchResultPageDTO,
    SearchResultSetDTO,
)

from .models import GatewayUnavailableError

if TYPE_CHECKING:
    from fastapi import FastAPI


class StubSearchGateway:
    """Placeholder satisfying ``SearchGatewayPort``. Returns an empty, non-degraded result page —
    an honest stand-in until the U6 gateway is wired. Real implementations forward the query +
    principal through the gateway to U2."""

    async def search(self, query: str, principal: Principal) -> SearchResultSetDTO:
        page = SearchResultPageDTO(
            cards=[],
            meta=ResultMeta(resultCount=0, degraded=False, degradationMode=None),
        )
        return SearchResultSetDTO(page)


class DiscoverySearchGateway:
    """Real SearchGatewayPort backed by the U2 discovery orchestrator via the gateway seam.

    Reads app.state.discovery_bundle / app.state.grounding_hook at call time so mount order
    (library mounts before discovery) does not cause a circular dependency at startup.
    """

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def search(self, query: str, principal: Principal) -> SearchResultSetDTO:
        from discovery.api.gateway_seam import run_search
        from discovery.domain.models import AuthSession, RequestContext

        bundle = getattr(self._app.state, "discovery_bundle", None)
        grounding_hook = getattr(self._app.state, "grounding_hook", None)

        if bundle is None or grounding_hook is None:
            raise GatewayUnavailableError("search temporarily unavailable")

        ctx = RequestContext(
            auth_session=AuthSession(user_id=principal.user_id),
            request_id=str(uuid.uuid4()),
        )
        request = SearchRequest(query=query)

        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(
                None,
                partial(run_search, bundle.orchestrator, grounding_hook, request, ctx),
            )
        except Exception as exc:
            raise GatewayUnavailableError("search temporarily unavailable") from exc

        root = response.root

        if isinstance(root, SearchResultPageDTO):
            return SearchResultSetDTO(root)

        if isinstance(root, DegradedResultDTO):
            # Degrade gracefully: expose cards as a page (meta.degraded=true preserved)
            return SearchResultSetDTO(SearchResultPageDTO(cards=root.cards, meta=root.meta))

        # AbstainDTO or ValidationErrorDTO → empty page
        return SearchResultSetDTO(
            SearchResultPageDTO(
                cards=[],
                meta=ResultMeta(resultCount=0, degraded=False, degradationMode=None),
            )
        )
