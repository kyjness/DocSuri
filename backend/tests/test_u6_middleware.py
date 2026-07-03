from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.middleware import InMemoryRateLimiter, configure_u6_middleware
from backend.middleware.gateway import _rate_limit_key


def test_u6_middleware_adds_security_headers_and_request_id() -> None:
    app = FastAPI()
    configure_u6_middleware(app, production=True)

    @app.get("/ok")
    def ok() -> dict:
        return {"ok": True}

    response = TestClient(app).get("/ok", headers={"X-Request-ID": "req-u6"})

    assert response.headers["X-Request-ID"] == "req-u6"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'self'" in response.headers["Content-Security-Policy"]


def test_u6_middleware_maps_unhandled_errors_to_generic_response() -> None:
    app = FastAPI()
    configure_u6_middleware(app, production=True)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("internal detail must not leak")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.json()["message"] == "Something went wrong. Please try again."
    assert "internal detail" not in response.text


def test_u6_middleware_rate_limit_seam_fails_closed() -> None:
    app = FastAPI()
    configure_u6_middleware(app, rate_limiter=InMemoryRateLimiter(max_requests=1), production=True)

    @app.get("/limited")
    def limited() -> dict:
        return {"ok": True}

    client = TestClient(app)

    assert client.get("/limited").status_code == 200
    assert client.get("/limited").status_code == 429


def test_u6_middleware_does_not_trust_forwarded_for_by_default() -> None:
    app = FastAPI()
    configure_u6_middleware(app, rate_limiter=InMemoryRateLimiter(max_requests=1), production=True)

    @app.get("/limited")
    def limited() -> dict:
        return {"ok": True}

    client = TestClient(app)

    assert client.get("/limited", headers={"X-Forwarded-For": "203.0.113.1"}).status_code == 200
    assert client.get("/limited", headers={"X-Forwarded-For": "203.0.113.2"}).status_code == 429


def test_u6_middleware_trusts_proxy_stamped_hop_not_spoofable_leftmost() -> None:
    # PR #45 review fix: with trust_proxy_headers the limiter keys on the hop our proxy stamped
    # (rightmost by default), NOT the attacker-controllable leftmost. Rotating the leftmost claim
    # must NOT mint a fresh bucket (no rate-limit evasion); a different trusted hop must.
    app = FastAPI()
    configure_u6_middleware(
        app,
        rate_limiter=InMemoryRateLimiter(max_requests=1),
        production=True,
        trust_proxy_headers=True,
    )

    @app.get("/limited")
    def limited() -> dict:
        return {"ok": True}

    client = TestClient(app)

    # Trusted (rightmost) hop 203.0.113.7 fixed; attacker rotates the leftmost claim.
    first = client.get("/limited", headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.7"})
    spoofed_leftmost = client.get("/limited", headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.7"})
    different_trusted = client.get("/limited", headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.8"})

    assert first.status_code == 200
    assert spoofed_leftmost.status_code == 429  # same trusted hop → same bucket (no evasion)
    assert different_trusted.status_code == 200  # different trusted hop → different bucket


def test_rate_limit_key_supports_cloudfront_alb_chain() -> None:
    class _Client:
        host = "10.0.0.10"

    class Req:
        headers = {"X-Forwarded-For": "198.51.100.20, 203.0.113.7"}
        client = _Client()

    assert (
        _rate_limit_key(Req(), trust_proxy_headers=True, trusted_proxy_count=2)
        == "198.51.100.20"
    )


def test_rate_limit_key_handles_missing_client() -> None:
    class RequestWithoutClient:
        headers: dict[str, str] = {}
        client = None

    assert _rate_limit_key(RequestWithoutClient()) == "unknown-client"


def test_rate_limit_key_ignores_non_ip_forwarded_value() -> None:
    # A garbage/spoofed forwarded hop must not become a key (would let an attacker mint buckets);
    # fall back to the direct client instead.
    class _Client:
        host = "10.9.8.7"

    class Req:
        headers = {"X-Forwarded-For": "not-an-ip"}
        client = _Client()

    assert _rate_limit_key(Req(), trust_proxy_headers=True) == "10.9.8.7"


def test_in_memory_rate_limiter_compacts_expired_keys() -> None:
    now = 0.0

    def clock() -> float:
        return now

    # compact_every=1 forces the full sweep each call so the expiry branch is deterministic.
    limiter = InMemoryRateLimiter(
        max_requests=1, window_seconds=1.0, clock=clock, compact_every=1
    )

    assert limiter.allow("old-a")
    assert limiter.allow("old-b")
    now = 2.0
    assert limiter.allow("new")

    assert set(limiter._events) == {"new"}


def test_in_memory_rate_limiter_evicts_lru_over_max_keys() -> None:
    # max_keys is an exact bound (no off-by-one) and eviction is least-recently-used.
    limiter = InMemoryRateLimiter(
        max_requests=5, window_seconds=100.0, clock=lambda: 0.0, max_keys=2
    )

    assert limiter.allow("a")
    assert limiter.allow("b")
    assert limiter.allow("c")  # pushes past the cap → least-recently-used "a" is evicted

    assert set(limiter._events) == {"b", "c"}
    assert len(limiter._events) == 2


# ── Auth injection middleware tests ──


class _FakeSessionManager:
    """Minimal SessionManager stub for auth injection tests."""

    def __init__(self, principals: dict[str, object] | None = None, *, fail: bool = False):
        self._principals = principals or {}
        self._fail = fail

    async def verify(self, session_id: str):
        if self._fail:
            raise RuntimeError("Redis unavailable")
        principal = self._principals.get(session_id)
        if principal is None:
            from backend.modules.accounts.models import UnauthorizedException

            raise UnauthorizedException("invalid session")
        return principal


def test_auth_injection_sets_principal_on_request_state() -> None:
    from backend.modules.accounts.models import Principal, UserRole

    principal = Principal(
        user_id="00000000-0000-4000-8000-000000000042", role=UserRole.USER, mfa_verified=False
    )
    mgr = _FakeSessionManager(principals={"valid-session": principal})

    app = FastAPI()
    configure_u6_middleware(app, session_manager=mgr, production=True)

    captured = {}

    @app.get("/protected")
    def protected(request: Request) -> dict:
        captured["principal"] = request.state.principal
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/protected", cookies={"session_id": "valid-session"})

    assert response.status_code == 200
    assert captured["principal"].user_id == "00000000-0000-4000-8000-000000000042"


def test_auth_injection_rejects_unauthenticated_protected_route() -> None:
    mgr = _FakeSessionManager()

    app = FastAPI()
    configure_u6_middleware(app, session_manager=mgr, production=True)

    @app.get("/protected")
    def protected() -> dict:
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/protected")

    assert response.status_code == 401
    assert "authentication required" in response.json()["message"]


def test_auth_injection_skips_public_paths() -> None:
    mgr = _FakeSessionManager()

    app = FastAPI()
    configure_u6_middleware(app, session_manager=mgr, production=True)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200


def test_auth_injection_optional_for_search_without_cookie() -> None:
    mgr = _FakeSessionManager()

    app = FastAPI()
    configure_u6_middleware(app, session_manager=mgr, production=True)

    @app.post("/api/search")
    def search(request: Request) -> dict:
        return {"principal": getattr(request.state, "principal", None)}

    client = TestClient(app)
    response = client.post("/api/search")

    assert response.status_code == 200
    assert response.json()["principal"] is None


def test_auth_injection_fail_closed_on_session_store_failure() -> None:
    mgr = _FakeSessionManager(fail=True)

    app = FastAPI()
    configure_u6_middleware(app, session_manager=mgr, production=True)

    @app.get("/protected")
    def protected() -> dict:
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/protected", cookies={"session_id": "any-session"})

    assert response.status_code == 401
    assert "expired or invalid" in response.json()["message"]


class _RecordingHub:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, str | None]] = []
        self.logs: list[str | None] = []

    def emit_metric(self, name, value, tags) -> None:
        self.metrics.append((name, tags.get("status")))

    def emit_log(self, entry) -> None:
        self.logs.append(entry.get("level"))

    def start_span(self, name, context):
        return None

    def audit_append(self, event) -> None: ...


def test_gateway_emits_telemetry_for_production_exception() -> None:
    """Production auth path (session_manager set): an unhandled route exception must STILL emit
    the error log + latency/throughput tagged status=500. Previously this path propagated past
    the emit block and recorded nothing. (US-R4)"""
    from backend.modules.accounts.models import Principal, UserRole

    principal = Principal(
        user_id="00000000-0000-4000-8000-000000000099", role=UserRole.USER, mfa_verified=False
    )
    hub = _RecordingHub()
    app = FastAPI()
    configure_u6_middleware(
        app,
        observability=hub,
        session_manager=_FakeSessionManager(principals={"x": principal}),
        production=True,
    )

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("kaboom")

    resp = TestClient(app, raise_server_exceptions=False).get(
        "/boom", cookies={"session_id": "x"}
    )

    assert resp.status_code == 500
    assert ("gateway.request.latency", "500") in hub.metrics
    assert ("gateway.request.throughput", "500") in hub.metrics
    assert "error" in hub.logs  # _emit_error fired on the prod auth path
