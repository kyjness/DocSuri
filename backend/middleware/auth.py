"""Gateway auth injection — resolves session cookie → Principal on request.state.

Runs inside the U6 gateway after rate-limit/request-id but before any route. Paths that
don't require authentication (health, login, signup, public assets) are skipped — the
downstream handler is responsible for checking ``request.state.principal`` if it needs auth
(library/controller.py raises 401 on absence, discovery reads X-User-Id as fallback).

Fail-Closed: if the session store is unreachable, the request is rejected (401) rather
than proceeding unauthenticated — consistent with U3 BR-A3 session policy.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

log = logging.getLogger("docsuri.backend.middleware.auth")

# Paths that never require authentication (prefix match).
_PUBLIC_PREFIXES = (
    "/health",
    "/readyz",
    "/auth/signup",
    "/auth/login",
    # 가입 없이 둘러보기 — **세션이 없는 상태로 부르는 것이 목적**이다. 여기 없으면 미들웨어가
    # 401을 내서 "로그인해야 로그인할 수 있는" 상태가 된다(2026-08-25 배포본에서 걸렸다).
    # 엔드포인트 자체는 `DOCSURI_DEMO_LOGIN_ENABLED`가 꺼지면 404이므로, 공개 목록에 있다고
    # 항상 열리는 것은 아니다.
    "/auth/demo",
    "/auth/verify-email",
    # PENDING-account recovery (resend mail) — public like signup/verify
    "/auth/resend-verification",
    # FR-26 password reset (request + confirm) — public like signup
    "/auth/password-reset",
    # FR-27 Google/ORCID OIDC start + callback — full-page redirects with no session yet.
    # NOT "/auth/social/link" (that confirms a link for a logged-in user → needs a session).
    "/auth/social/google",
    "/auth/social/orcid",
    # FR-28 email-change confirm — clicked from the verification mail (no session).
    # NOT "/auth/email-change/request" which is logged-in.
    "/auth/email-change/confirm",
    "/docs",
    "/openapi.json",
)

# Paths where auth is optional (sets principal if cookie present, but doesn't block).
_AUTH_OPTIONAL_PREFIXES = (
    "/auth/session",
    "/api/search",
)


async def inject_principal(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
    *,
    session_manager,
) -> Response:
    """Middleware logic: resolve session cookie into Principal on request.state.

    Designed to be called from inside the gateway middleware (not installed separately)
    so that request_id and rate-limit have already been applied.
    """
    path = request.url.path

    if _is_public(path):
        request.state.principal = None
        return await call_next(request)

    session_id = request.cookies.get("session_id")
    optional = _is_auth_optional(path)

    if not session_id:
        if optional:
            request.state.principal = None
            return await call_next(request)
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=401, content={"message": "authentication required"})

    try:
        principal = await session_manager.verify(session_id)
    except Exception:
        if optional:
            request.state.principal = None
            return await call_next(request)
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=401, content={"message": "session expired or invalid"})

    request.state.principal = principal
    return await call_next(request)


def _is_public(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES)


def _is_auth_optional(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _AUTH_OPTIONAL_PREFIXES)
