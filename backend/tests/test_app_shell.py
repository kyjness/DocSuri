"""App-shell smoke + contract tests.

The shell must boot, serve health, generate OpenAPI, and never let one module sink the rest.
With the ``docsuri-discovery`` path source now declared (backend/pyproject.toml), accounts +
discovery actually MOUNT here; the graceful-skip path is still exercised via an injected
absent module (``test_absent_module_skips_gracefully``).

discovery is real-first (no mock fallback), so it mounts only when the read path is configured.
The ``_search_configured`` autouse fixture points it at an unreachable endpoint: wiring-time
construction does not touch the network (``space_guard`` treats an unreadable mapping as
"unverified" and proceeds), so the mount is exercised for real while every request fails closed.
That is what keeps ``test_discovery_and_accounts_actually_mount`` — the guard against discovery
silently skipping — meaningful without a live cluster. ``test_discovery_skips_when_unconfigured``
covers the other side of the contract.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.wiring import MountResult, mount_modules

# In-memory SQLite so the accounts seam (if ever present) needs no DB file on disk.
_TEST_SETTINGS = Settings(env="test", database_url="sqlite://")

# Reserved-but-unroutable (RFC 5735 "this host"), port 1: connect fails immediately rather
# than hanging on a timeout, keeping the suite fast.
_DEAD_OPENSEARCH = "http://127.0.0.1:1"


@pytest.fixture(autouse=True)
def _search_configured(monkeypatch) -> None:
    """Configure discovery's real read path so it mounts. Undone per-test by monkeypatch."""
    monkeypatch.setenv("DOCSURI_OPENSEARCH_ENDPOINT", _DEAD_OPENSEARCH)
    monkeypatch.setenv("DOCSURI_EMBEDDING_PROVIDER", "openai")


def _client() -> TestClient:
    return TestClient(create_app(_TEST_SETTINGS))


def test_app_boots_and_is_fastapi() -> None:
    app = create_app(_TEST_SETTINGS)
    assert isinstance(app, FastAPI)


def test_settings_from_env_configures_gateway_rate_limit(monkeypatch) -> None:
    monkeypatch.setenv("DOCSURI_GATEWAY_RATE_LIMIT_MAX_REQUESTS", "123")
    monkeypatch.setenv("DOCSURI_GATEWAY_RATE_LIMIT_WINDOW_SECONDS", "7.5")

    settings = Settings.from_env()

    assert settings.gateway_rate_limit_max_requests == 123
    assert settings.gateway_rate_limit_window_seconds == 7.5


def test_health_and_liveness() -> None:
    client = _client()
    assert client.get("/health").json() == {"status": "ok", "service": "docsuri-backend"}
    assert client.get("/healthz").json() == {"status": "ok"}


def test_openapi_generates() -> None:
    schema = _client().get("/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "DocSuri Backend (modular monolith)"


def test_module_registry_complete_and_disjoint() -> None:
    # Env-independent: which modules are installed in this checkout varies, but every
    # registered module must land in exactly one bucket (never dropped, never both).
    readyz = _client().get("/readyz").json()
    assert readyz["status"] == "ready"
    mounted, skipped = set(readyz["mounted"]), set(readyz["skipped"])
    assert mounted.isdisjoint(skipped)
    assert mounted | skipped == {
        "accounts",
        "discovery",
        "library",
        "mypage",
        "summarization",
        "ops",
        "citation_graph",
        "personalization",
        "novelty",
        "evidence",
    }
    assert readyz["blocking"] == []


def test_readyz_fails_when_required_module_is_skipped() -> None:
    app = create_app(_TEST_SETTINGS)
    app.state.mount_result = MountResult(skipped=[("novelty", "mount error")])

    resp = TestClient(app).get("/readyz")

    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"
    assert resp.json()["blocking"] == ["novelty"]


def test_discovery_and_accounts_actually_mount() -> None:
    # Regression guard: discovery silently graceful-skipped on develop until it became a
    # declared dependency (pyproject path source). test_module_registry_complete_and_disjoint
    # only checks the registry *set* — which stayed green even while discovery was skipped.
    # Subset (not ==) so a newly-added module (e.g. library/U4) doesn't break this guard;
    # `skipped == []` still proves every registered module actually mounts.
    result = create_app(_TEST_SETTINGS).state.mount_result
    assert {"accounts", "discovery"} <= set(result.mounted), result.skipped
    # summarization (U7) is real-first with NO mock wiring, so it legitimately skips when the
    # real read path (S3 bucket + Bedrock) is unconfigured — as in tests. Every OTHER registered
    # module must still mount; nothing else may skip.
    assert all(name == "summarization" for name, _ in result.skipped), result.skipped


def test_discovery_search_route_is_registered() -> None:
    # The route must EXIST once discovery is configured. With the store unreachable the request
    # fails closed (503, INV-3) rather than fabricating results — the distinction that matters
    # is 503-not-404: 404 would mean the router never mounted. End-to-end happy-path search is
    # covered in discovery's own suite against build_mock_orchestrator; here the app-shell
    # contract is only "configured ⇒ route present, and an outage is retryable, not missing".
    resp = TestClient(create_app(_TEST_SETTINGS), raise_server_exceptions=False).post(
        "/api/search", json={"query": "transformer attention"}
    )
    assert resp.status_code == 503, resp.text


def test_search_store_outage_maps_to_fail_closed_503() -> None:
    # A store outage inside discovery raises SearchUnavailable. Mounted via build_router (not the
    # standalone build_app), the app-shell must map it to a fail-closed, no-leak 503 — otherwise
    # it falls through to the generic Exception→500 handler and a transient outage looks like a
    # bug instead of a retryable 503 (INV-3/SEC-15).
    from discovery.service.orchestrator import SearchUnavailable

    app = create_app(_TEST_SETTINGS)

    def _raise(*_a, **_k):
        raise SearchUnavailable("opensearch host db-1 connection timeout")

    app.state.discovery_bundle.orchestrator.plan_and_retrieve = _raise  # type: ignore[method-assign]
    resp = TestClient(app, raise_server_exceptions=False).post("/api/search", json={"query": "x"})
    assert resp.status_code == 503
    assert "temporarily unavailable" in resp.json()["message"].lower()
    assert "db-1" not in resp.text and "opensearch" not in resp.text.lower()  # no leak (SEC-9)
    assert resp.json()["requestId"]  # echoes a correlation id, like the 500 handler (errors.py)


def test_paper_metadata_route_is_registered() -> None:
    # GET /api/papers/{id} (paper-detail header metadata, U2-owned corpus data) rides the same
    # discovery router. Same contract as search: present when configured, and a store outage is
    # a fail-closed 503 — NOT the 404 the detail page uses to fall back to the arXiv link-out.
    # Conflating the two would make an outage look like "this paper does not exist".
    # Distinct from /api/papers/{id}/full-text (summarization/U7).
    resp = TestClient(create_app(_TEST_SETTINGS), raise_server_exceptions=False).get(
        "/api/papers/2401.00001"
    )
    assert resp.status_code == 503, resp.text


def test_discovery_skips_when_unconfigured(monkeypatch) -> None:
    # The other side of the real-first contract: no read path configured ⇒ discovery does not
    # mount at all, and /api/search 404s instead of answering 200 with fabricated cards. The
    # mock fallback this replaces was indistinguishable from a real answer at the HTTP layer.
    monkeypatch.delenv("DOCSURI_OPENSEARCH_ENDPOINT", raising=False)
    monkeypatch.delenv("DOCSURI_BEDROCK_MODEL_ID", raising=False)
    monkeypatch.setenv("DOCSURI_EMBEDDING_PROVIDER", "bedrock")

    app = create_app(_TEST_SETTINGS)
    skipped = dict(app.state.mount_result.skipped)

    assert "discovery" not in app.state.mount_result.mounted
    assert "not configured" in skipped["discovery"]
    assert TestClient(app).post("/api/search", json={"query": "x"}).status_code == 404
    # ...and readiness stays green: an unconfigured module is legitimately absent, so /readyz
    # must not pin the whole process at 503 (health._required_modules gates on the same env).
    readyz = TestClient(app).get("/readyz")
    assert readyz.status_code == 200
    assert readyz.json()["blocking"] == []


def test_absent_module_skips_gracefully_not_fatal() -> None:
    # Inject a guaranteed-absent integration so the skip path is tested regardless of what
    # is installed (the old version assumed the real modules were absent — broke on merge).
    def _mount_ghost(app: FastAPI, settings: Settings, result) -> None:
        raise ModuleNotFoundError("No module named 'ghost'", name="ghost")

    app = create_app(_TEST_SETTINGS)
    result = mount_modules(app, _TEST_SETTINGS, integrations=[_mount_ghost])
    assert result.mounted == []
    assert [name for name, _ in result.skipped] == ["ghost"]


def test_mount_modules_never_raises_and_records_reasons() -> None:
    app = create_app(_TEST_SETTINGS)
    result: MountResult = mount_modules(app, _TEST_SETTINGS)
    assert isinstance(result, MountResult)
    # Every attempted module is accounted for as either mounted or skipped (no silent drop).
    assert {name for name, _ in result.skipped} | set(result.mounted) == {
        "accounts",
        "discovery",
        "library",
        "mypage",
        "summarization",
        "ops",
        "citation_graph",
        "personalization",
        "novelty",
        "evidence",
    }


def test_request_id_is_echoed() -> None:
    resp = _client().get("/health", headers={"X-Request-ID": "req-abc-123"})
    assert resp.headers["X-Request-ID"] == "req-abc-123"


def test_unhandled_error_is_generic_and_leak_free() -> None:
    app = create_app(_TEST_SETTINGS)

    @app.get("/_boom")
    def _boom() -> None:
        raise RuntimeError("INTERNAL stack detail that must never reach the client")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/_boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["message"] == "Something went wrong. Please try again."
    assert "requestId" in body
    assert "INTERNAL" not in resp.text  # no internal/stack leak (SEC-15)


# ── U6 integration (critical path ④): gateway installed + real grounding hook injected ──


def test_u6_gateway_security_headers_and_request_id_live() -> None:
    # create_app installs the U6 gateway (not just the old request-id shim): every response
    # carries the security headers and a request id, applied by backend/middleware/gateway.
    resp = _client().get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"


def test_u6_real_grounding_hook_is_wired_not_stub() -> None:
    # _mount_discovery injects the real docsuri-ops GroundingEnforcementHook (INV-1 single
    # authority), replacing the always-pass StubGroundingHook.
    from docsuri_ops.grounding import GroundingEnforcementHook

    hook = create_app(_TEST_SETTINGS).state.grounding_hook
    assert isinstance(hook, GroundingEnforcementHook)
    assert type(hook).__module__.startswith("docsuri_ops")


def test_u6_observability_captures_gateway_error() -> None:
    # The gateway emits an error log to the wired ObservabilityHub before re-raising/mapping,
    # so an unhandled failure is observable server-side (keyed by request id, no client leak).
    app = create_app(_TEST_SETTINGS)

    @app.get("/_boom")
    def _boom() -> None:
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/_boom").status_code == 500
    events = app.state.telemetry_store.list_events()
    assert any(e.payload.get("level") == "error" for e in events)
