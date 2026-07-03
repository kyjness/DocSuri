"""SEC-15 / INV-3 — build_app registers fail-closed handlers that leak no internal detail.

A specific SearchUnavailable → generic 503, and a global catch-all (any unhandled exception)
→ generic 500 with no stack/internal info. Verified by invoking the registered handlers
directly (no network / TestClient dependency). Skipped if the optional `api` extra (FastAPI)
is not installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from discovery.api.router import (  # noqa: E402 — after importorskip
    _ANONYMOUS_USER_ID,
    _resolve_user_id,
    build_app,
)
from discovery.mocks import build_mock_orchestrator  # noqa: E402
from discovery.ports.search_ports import IndexUnavailable  # noqa: E402
from discovery.service.orchestrator import SearchUnavailable  # noqa: E402


def _app():
    bundle = build_mock_orchestrator()
    return build_app(bundle.orchestrator, bundle.grounding_hook)


class _Principal:
    def __init__(self, user_id: str) -> None:
        self.user_id = user_id


def test_resolve_user_id_prefers_gateway_principal() -> None:
    # SEC-8/BR-13: a gateway-injected principal always wins, in both prod and dev — the
    # X-User-Id header is ignored when an authenticated principal is present.
    assert _resolve_user_id(_Principal("u-real"), "spoofed", allow_dev_user=False) == "u-real"
    assert _resolve_user_id(_Principal("u-real"), "spoofed", allow_dev_user=True) == "u-real"


def test_resolve_user_id_production_ignores_spoofable_header() -> None:
    # /api/search is auth-OPTIONAL: anonymous requests arrive with principal=None. Prod must
    # NOT trust the client X-User-Id header (it is U4's history owner key — spoofing it injects
    # history into another account, SEC-8) → fixed anonymous id regardless of the header.
    assert _resolve_user_id(None, "victim@example.com", allow_dev_user=False) == _ANONYMOUS_USER_ID
    assert _resolve_user_id(None, None, allow_dev_user=False) == _ANONYMOUS_USER_ID


def test_resolve_user_id_dev_app_honors_header() -> None:
    # The standalone mock-first app (build_app) opts in to the header for multi-user dev testing.
    assert _resolve_user_id(None, "dev-bob", allow_dev_user=True) == "dev-bob"
    assert _resolve_user_id(None, None, allow_dev_user=True) == "dev-user"


def test_search_unavailable_handler_is_generic_503() -> None:
    app = _app()
    handler = app.exception_handlers[SearchUnavailable]
    response = handler(None, SearchUnavailable("opensearch host db-1 connection timeout"))
    assert response.status_code == 503
    assert b"db-1" not in response.body  # no internal detail leaked (SEC-9)


def test_search_unavailable_handler_logs_request_correlated_store_cause(caplog) -> None:
    # The 503 log line must be self-contained: the request id AND the real store cause (walked from
    # the __cause__ chain: SearchUnavailable → which query failed → the OpenSearch error) so an
    # incident needs no timestamp join to a separate adapter log. Detail stays server-side (SEC-9).
    from types import SimpleNamespace

    app = _app()
    handler = app.exception_handlers[SearchUnavailable]
    root = TimeoutError("connect timed out")
    idx = IndexUnavailable("OpenSearch k-NN query failed after 3 attempt(s)")
    idx.__cause__ = root
    exc = SearchUnavailable("search index unavailable")
    exc.__cause__ = idx
    request = SimpleNamespace(state=SimpleNamespace(request_id="req-123"))

    with caplog.at_level("WARNING"):
        response = handler(request, exc)

    assert response.status_code == 503
    logged = caplog.text
    assert "req-123" in logged  # request correlation
    assert "after 3 attempt(s)" in logged  # which query + retry budget
    assert "TimeoutError" in logged and "connect timed out" in logged  # real root cause


def test_global_catch_all_handler_is_generic_500() -> None:
    app = _app()
    assert Exception in app.exception_handlers  # catch-all registered (SEC-15/INV-3)
    handler = app.exception_handlers[Exception]
    response = handler(None, RuntimeError("secret stack trace internal detail"))
    assert response.status_code == 500
    assert b"secret" not in response.body
    assert b"stack" not in response.body
