from __future__ import annotations

from dataclasses import dataclass

from docsuri_ops.domain.enums import IncidentClass
from docsuri_ops.domain.models import (
    ClassifiedIncidentRecord,
    DashboardWindow,
    OpsDashboardView,
)


@dataclass(slots=True)
class OpsDashboardService:
    incident_store: object
    cost_guard: object | None = None
    health_service: object | None = None
    event_store: object | None = None

    def get_dashboard(self, window: DashboardWindow) -> OpsDashboardView:
        incidents = self.list_incidents(window=window)
        alerts = [
            alert
            for alert in self.incident_store.list_alerts()
            if window.contains(alert.timestamp)
        ]
        cost_state = self.cost_guard.get_budget_state() if self.cost_guard else None
        # Deep (not shallow): the dashboard must reflect stale-index / dependency-down, not a
        # constant "healthy". shallow_check always returns healthy, hiding degradation — the same
        # "don't render a falsely-healthy view" principle as the metrics below. (Finding 2)
        health = self.health_service.deep_check() if self.health_service else None

        # Event-derived metrics need a store we can read back. The production
        # CloudWatchEventStore is write-only (supports_readback=False) — its metrics live in
        # CloudWatch, queried via the console/GetMetricData, not this in-process event log.
        # Report None there rather than fabricating zeros that read as "healthy/quiet". (US-R4)
        # ponytail: a GetMetricData read path is the upgrade if the in-app view must show prod perf.
        latency_p95 = error_rate = throughput = None
        grounding_health = None
        readable = self.event_store is not None and getattr(
            self.event_store, "supports_readback", True
        )
        if readable:
            events = [
                e for e in self.event_store.list_events() if window.contains(e.timestamp)
            ]
            grounding_health = {"pass": 0, "block": 0, "abstain": 0}

            latencies = [
                e.value
                for e in events
                if e.kind.value == "metric"
                and e.name == "gateway.request.latency"
                and e.value is not None
            ]
            if latencies:
                latencies.sort()
                idx = int(len(latencies) * 0.95)
                latency_p95 = round(latencies[min(idx, len(latencies) - 1)], 6)

            # Throughput = count of the explicit per-request counter ONLY. The gateway emits a
            # latency AND a throughput event per request, so also counting latency events
            # double-counted throughput (and halved error_rate). (US-R4 finding)
            throughput = float(
                sum(
                    1
                    for e in events
                    if e.kind.value == "metric" and e.name == "gateway.request.throughput"
                )
            )

            # Errors = 5xx-status latency events ONLY (one latency is emitted per request, incl.
            # exceptions). Counting the separate gateway error-log too would double-count a
            # single failure (error_rate could exceed 1.0). (US-R4)
            error_events = [
                e
                for e in events
                if e.kind.value == "metric"
                and e.name == "gateway.request.latency"
                and e.tags.get("status", "").startswith("5")
            ]
            if throughput > 0:
                error_rate = round(len(error_events) / throughput, 6)
            else:
                error_rate = 1.0 if error_events else 0.0

            for e in events:
                if e.kind.value == "metric" and e.name == "discovery.search.grounding":
                    verdict = e.tags.get("verdict", "unknown")
                    grounding_health[verdict] = grounding_health.get(verdict, 0) + 1

        return OpsDashboardView(
            window=window,
            incident_count=len(incidents),
            alert_count=len(alerts),
            cost_state=cost_state,
            health=health,
            latency_p95=latency_p95,
            error_rate=error_rate,
            throughput=throughput,
            grounding_health=grounding_health,
        )

    def list_incidents(
        self,
        *,
        window: DashboardWindow | None = None,
        incident_class: IncidentClass | None = None,
    ) -> list[ClassifiedIncidentRecord]:
        incidents = self.incident_store.list_incidents()
        if window is not None:
            incidents = [
                incident for incident in incidents if window.contains(incident.timestamp)
            ]
        if incident_class is not None:
            incidents = [
                incident
                for incident in incidents
                if incident.incident_class == incident_class
            ]
        return incidents

    def summarize_by_class(self, window: DashboardWindow) -> dict[str, int]:
        summary = {incident_class.value: 0 for incident_class in IncidentClass}
        for incident in self.list_incidents(window=window):
            summary[incident.incident_class.value] += 1
        return summary
