"""App-shell smoke + contract tests.

The shell must boot, serve health, generate OpenAPI, and never let one module sink the rest.
With the ``docsuri-discovery`` path source now declared (backend/pyproject.toml), accounts +
discovery actually MOUNT here; the graceful-skip path is still exercised via an injected
absent module (``test_absent_module_skips_gracefully``).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.wiring import MountResult, mount_modules

# In-memory SQLite so the accounts seam (if ever present) needs no DB file on disk.
_TEST_SETTINGS = Settings(env="test", database_url="sqlite://")


def _client() -> TestClient:
    return TestClient(create_app(_TEST_SETTINGS))


def test_app_boots_and_is_fastapi() -> None:
    app = create_app(_TEST_SETTINGS)
    assert isinstance(app, FastAPI)


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
        "research",
        "novelty",
    }


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


def test_discovery_search_endpoint_is_live() -> None:
    # The mounted discovery router serves /api/search end-to-end through the mock pipeline,
    # now gated by the REAL U6 GroundingEnforcementHook (INV-1). The mock derives retrieved
    # records from the ranked candidates, so enforce() passes and cards are returned — this
    # asserts the route is LIVE and grounding does not spuriously block the happy path.
    resp = _client().post("/api/search", json={"query": "transformer attention"})
    assert resp.status_code == 200
    assert "cards" in resp.json()


def test_paper_metadata_endpoint_is_live() -> None:
    # The mounted discovery router serves GET /api/papers/{id} (paper-detail header metadata,
    # U2-owned corpus data) end-to-end through the mock pipeline. A known fixture id returns the
    # projected metadata (full abstract); an unknown id degrades to 404 (detail page falls back
    # to the arXiv link-out). Distinct from /api/papers/{id}/full-text (summarization/U7).
    client = _client()
    ok = client.get("/api/papers/2401.00001")
    assert ok.status_code == 200
    body = ok.json()
    assert body["title"] == "Diffusion Models for Protein Structure Prediction"
    assert body["arxivId"] == "2401.00001v1"
    assert body["abstract"]  # full abstract present
    assert client.get("/api/papers/9999.99999").status_code == 404


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
        "research",
        "novelty",
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
