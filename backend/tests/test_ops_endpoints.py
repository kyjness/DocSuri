from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from docsuri_ops.domain.enums import IncidentClass, Severity, SignalKind
from docsuri_ops.domain.models import ClassifiedIncidentRecord, TelemetryEvent
from docsuri_shared.authz import Principal, UserRole
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings

_TEST_SETTINGS = Settings(env="test", database_url="sqlite://")


class FakeSessionManager:
    async def verify(self, session_id: str) -> Principal:
        if session_id == "admin-mfa":
            return Principal(
                user_id="00000000-0000-4000-8000-000000000001",
                role=UserRole.ADMIN,
                mfa_verified=True,
            )
        elif session_id == "admin-no-mfa":
            return Principal(
                user_id="00000000-0000-4000-8000-000000000001",
                role=UserRole.ADMIN,
                mfa_verified=False,
            )
        elif session_id == "user":
            return Principal(
                user_id="00000000-0000-4000-8000-000000000002",
                role=UserRole.USER,
                mfa_verified=True,
            )
        from backend.modules.accounts.models import UnauthorizedException
        raise UnauthorizedException("invalid session")


@pytest.fixture
def client_with_auth():
    with patch("backend.app._build_session_manager") as mock_build:
        mock_build.return_value = FakeSessionManager()
        app = create_app(_TEST_SETTINGS)
        # Ensure we have clean stores
        app.state.telemetry_store.events.clear()
        app.state.telemetry_store._seen.clear()
        app.state.incident_store.incidents.clear()
        app.state.incident_store.alerts.clear()
        app.state.incident_store._incident_seen.clear()
        app.state.incident_store._alert_seen.clear()
        yield TestClient(app)


def test_ops_authentication_and_authorization_guards(client_with_auth: TestClient) -> None:
    # 1. No Session Cookie -> 401
    resp = client_with_auth.get("/ops/dashboard")
    assert resp.status_code == 401
    assert "authentication required" in resp.json()["message"]

    # 2. Invalid Session -> 401
    resp = client_with_auth.get("/ops/dashboard", cookies={"session_id": "invalid"})
    assert resp.status_code == 401
    assert "session expired or invalid" in resp.json()["message"]

    # 3. Non-Admin User -> 403
    resp = client_with_auth.get("/ops/dashboard", cookies={"session_id": "user"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "forbidden"

    # 4. Admin but No MFA -> 403
    resp = client_with_auth.get("/ops/dashboard", cookies={"session_id": "admin-no-mfa"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "forbidden"

    # 5. Admin with MFA -> 200 (happy path)
    resp = client_with_auth.get("/ops/dashboard", cookies={"session_id": "admin-mfa"})
    assert resp.status_code == 200


def test_ops_dashboard_metrics_aggregation(client_with_auth: TestClient) -> None:
    app = client_with_auth.app
    telemetry_store = app.state.telemetry_store

    now = datetime.now(UTC)

    # Populate telemetry events inside the current window
    # 20 latency metrics from 0.01s to 0.20s
    for i in range(1, 21):
        telemetry_store.append(
            TelemetryEvent(
                event_id=f"lat-{i}",
                kind=SignalKind.METRIC,
                timestamp=now - timedelta(minutes=5),
                request_id=f"req-lat-{i}",
                name="gateway.request.latency",
                value=float(i) / 100.0,
            )
        )

    # 4 throughput metrics
    for i in range(1, 5):
        telemetry_store.append(
            TelemetryEvent(
                event_id=f"thru-{i}",
                kind=SignalKind.METRIC,
                timestamp=now - timedelta(minutes=5),
                request_id=f"req-thru-{i}",
                name="gateway.request.throughput",
                value=1.0,
            )
        )

    # 2 error metrics: 1 log with level error, 1 latency with 500 status tag
    telemetry_store.append(
        TelemetryEvent(
            event_id="err-log",
            kind=SignalKind.LOG,
            timestamp=now - timedelta(minutes=5),
            request_id="req-err-1",
            payload={"level": "error", "message": "error occurred"},
        )
    )
    telemetry_store.append(
        TelemetryEvent(
            event_id="err-lat",
            kind=SignalKind.METRIC,
            timestamp=now - timedelta(minutes=5),
            request_id="req-err-2",
            name="gateway.request.latency",
            value=0.5,
            tags={"status": "500"},
        )
    )

    # 6 grounding health events: 3 pass, 2 block, 1 abstain
    for i, verdict in enumerate(["pass", "pass", "pass", "block", "block", "abstain"]):
        telemetry_store.append(
            TelemetryEvent(
                event_id=f"gnd-{i}",
                kind=SignalKind.METRIC,
                timestamp=now - timedelta(minutes=5),
                request_id=f"req-gnd-{i}",
                name="discovery.search.grounding",
                value=1.0,
                tags={"verdict": verdict},
            )
        )

    # Add 1 event outside the window (2 hours ago) which should not be aggregated
    telemetry_store.append(
        TelemetryEvent(
            event_id="lat-old",
            kind=SignalKind.METRIC,
            timestamp=now - timedelta(hours=2),
            request_id="req-lat-old",
            name="gateway.request.latency",
            value=2.0,
        )
    )

    # Fetch dashboard with default window (1 hour)
    resp = client_with_auth.get("/ops/dashboard", cookies={"session_id": "admin-mfa"})
    assert resp.status_code == 200
    data = resp.json()

    # Verify window dates
    assert data["window"]["start"] is not None
    assert data["window"]["end"] is not None

    # Latencies: 20 regular + 1 error latency = 21 latencies total inside window
    # Sorted: 0.01, 0.02, ..., 0.20, 0.50
    # p95 index = int(21 * 0.95) = 19
    # Sorted list: [0.01, ..., 0.19, 0.20, 0.50]
    # Index 19 is 0.20
    assert data["latency_p95"] == pytest.approx(0.20)

    # Throughput counts ONLY the explicit gateway.request.throughput counter (4 here), NOT
    # latency events — the gateway emits one of each per request, so counting both would
    # double-count throughput. The 21 latency events present must NOT inflate this. (US-R4)
    assert data["throughput"] == 4

    # Errors = 5xx-status latency events ONLY (1 here). The error log is NOT counted: the
    # gateway emits one latency (with status) per request incl. exceptions, so counting the
    # log too would double-count a single failure. Error rate = 1 / 4 = 0.25. (US-R4)
    assert data["error_rate"] == pytest.approx(0.25)

    # Grounding health: 3 pass, 2 block, 1 abstain
    assert data["grounding_health"] == {"pass": 3, "block": 2, "abstain": 1}


def test_ops_incidents_filtering_and_query(client_with_auth: TestClient) -> None:
    app = client_with_auth.app
    incident_store = app.state.incident_store

    now = datetime.now(UTC)

    # Add incidents
    incident_store.append_incident(
        ClassifiedIncidentRecord(
            incident_class=IncidentClass.COST_EXPLOSION,
            severity=Severity.WARNING,
            request_id="req-cost-1",
            reason="High intraday spend detected",
            timestamp=now - timedelta(minutes=10),
        )
    )
    incident_store.append_incident(
        ClassifiedIncidentRecord(
            incident_class=IncidentClass.HALLUCINATION,
            severity=Severity.CRITICAL,
            request_id="req-hall-1",
            reason="Grounding violation threshold exceeded",
            timestamp=now - timedelta(minutes=20),
        )
    )
    incident_store.append_incident(
        ClassifiedIncidentRecord(
            incident_class=IncidentClass.PARTIAL_RESULT,
            severity=Severity.INFO,
            request_id="req-part-1",
            reason="Search returned zero results gracefully",
            timestamp=now - timedelta(hours=2),  # Outside default 1hr window
        )
    )

    # Query all incidents with cookies
    resp = client_with_auth.get("/ops/incidents", cookies={"session_id": "admin-mfa"})
    assert resp.status_code == 200
    data = resp.json()
    # Should return all 3 incidents since window is optional when
    # start/end query parameters are omitted
    assert len(data) == 3

    # Query only IncidentClass.COST_EXPLOSION ("a")
    resp = client_with_auth.get(
        "/ops/incidents",
        params={"incident_class": "a"},
        cookies={"session_id": "admin-mfa"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["incident_class"] == "a"
    assert data[0]["request_id"] == "req-cost-1"

    # Query with window to exclude the old partial result incident (older than 1 hour)
    start_time = (now - timedelta(minutes=45)).isoformat()
    end_time = now.isoformat()
    resp = client_with_auth.get(
        "/ops/incidents",
        params={"start": start_time, "end": end_time},
        cookies={"session_id": "admin-mfa"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Should only return the 2 recent incidents
    assert len(data) == 2
    assert any(x["request_id"] == "req-cost-1" for x in data)
    assert any(x["request_id"] == "req-hall-1" for x in data)

    # Query with invalid incident class -> 400
    resp = client_with_auth.get(
        "/ops/incidents",
        params={"incident_class": "invalid"},
        cookies={"session_id": "admin-mfa"},
    )
    assert resp.status_code == 400
    assert "Invalid incident class" in resp.json()["detail"]
