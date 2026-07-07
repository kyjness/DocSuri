from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from docsuri_shared.authz import AuthorizationGuard, Decision, Principal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

log = logging.getLogger("docsuri.ops.controller")
router = APIRouter(prefix="/ops", tags=["Operations/Dashboard"])


class WindowDTO(BaseModel):
    start: datetime
    end: datetime


class BudgetStateDTO(BaseModel):
    tier: str
    degrade_mode: str
    circuit_state: str
    spend_usd: float
    cap_usd: float
    threshold_ratio: float


class HealthStatusDTO(BaseModel):
    status: str
    dependencies: dict[str, str]
    stale: bool
    details: dict[str, Any]


class DashboardViewDTO(BaseModel):
    window: WindowDTO
    incident_count: int
    alert_count: int
    cost_state: BudgetStateDTO | None = None
    health: HealthStatusDTO | None = None
    latency_p95: float | None = None
    error_rate: float | None = None
    throughput: float | None = None
    grounding_health: dict[str, int] | None = None


class IncidentRecordDTO(BaseModel):
    incident_class: str
    severity: str
    request_id: str
    reason: str
    timestamp: datetime


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal


def enforce_admin_mfa(principal: Principal = Depends(get_principal)) -> None:
    decision = AuthorizationGuard.authorize_admin(principal, mfa_verified=principal.mfa_verified)
    if decision != Decision.ALLOW:
        raise HTTPException(status_code=403, detail="forbidden")


def get_dashboard_service(request: Request) -> Any:
    # None means the app-shell couldn't build the U6 dashboard (docsuri-ops absent). Surface
    # that as 503 rather than fabricating an empty store — an all-zero dashboard reads as
    # "healthy/quiet" and hides the misconfiguration. (US-R4 finding)
    service = getattr(request.app.state, "dashboard_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="observability not available")
    return service


@router.get("/dashboard", response_model=DashboardViewDTO)
async def get_dashboard(
    request: Request,
    _auth: None = Depends(enforce_admin_mfa),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    service: Any = Depends(get_dashboard_service),
) -> Any:
    from docsuri_ops.domain.models import DashboardWindow

    now = datetime.now(UTC)
    window_end = end or now
    window_start = start or (window_end - timedelta(hours=1))

    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=UTC)
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=UTC)

    window = DashboardWindow(start=window_start, end=window_end)
    try:
        view = service.get_dashboard(window)
    except Exception:
        # Generic message + log the detail — never leak internals to the client (SEC-9/SEC-15).
        log.exception("ops: failed to load dashboard")
        raise HTTPException(status_code=500, detail="Failed to load dashboard") from None

    cost_state = None
    if view.cost_state:
        cost_state = BudgetStateDTO(
            tier=view.cost_state.tier,
            degrade_mode=view.cost_state.degrade_mode.value,
            circuit_state=view.cost_state.circuit_state.value,
            spend_usd=view.cost_state.spend_usd,
            cap_usd=view.cost_state.cap_usd,
            threshold_ratio=view.cost_state.threshold_ratio,
        )

    health = None
    if view.health:
        health = HealthStatusDTO(
            status=view.health.status,
            dependencies=view.health.dependencies,
            stale=view.health.stale,
            details=view.health.details,
        )

    return DashboardViewDTO(
        window=WindowDTO(start=view.window.start, end=view.window.end),
        incident_count=view.incident_count,
        alert_count=view.alert_count,
        cost_state=cost_state,
        health=health,
        latency_p95=view.latency_p95,
        error_rate=view.error_rate,
        throughput=view.throughput,
        grounding_health=view.grounding_health,
    )


@router.get("/incidents", response_model=list[IncidentRecordDTO])
async def list_incidents(
    _auth: None = Depends(enforce_admin_mfa),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    incident_class: str | None = Query(default=None),
    service: Any = Depends(get_dashboard_service),
) -> Any:
    from docsuri_ops.domain.enums import IncidentClass
    from docsuri_ops.domain.models import DashboardWindow

    window = None
    if start or end:
        now = datetime.now(UTC)
        window_end = end or now
        window_start = start or (window_end - timedelta(hours=1))

        if window_start.tzinfo is None:
            window_start = window_start.replace(tzinfo=UTC)
        if window_end.tzinfo is None:
            window_end = window_end.replace(tzinfo=UTC)

        window = DashboardWindow(start=window_start, end=window_end)

    inc_class = None
    if incident_class:
        try:
            inc_class = IncidentClass(incident_class)
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid incident class: {incident_class}"
            ) from None

    try:
        records = service.list_incidents(window=window, incident_class=inc_class)
    except Exception:
        # Generic message + log the detail — never leak internals to the client (SEC-9/SEC-15).
        log.exception("ops: failed to list incidents")
        raise HTTPException(status_code=500, detail="Failed to list incidents") from None

    return [
        IncidentRecordDTO(
            incident_class=record.incident_class.value,
            severity=record.severity.value,
            request_id=record.request_id,
            reason=record.reason,
            timestamp=record.timestamp,
        )
        for record in records
    ]
