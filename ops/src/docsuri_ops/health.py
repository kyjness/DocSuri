from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from docsuri_ops.domain.models import HealthStatus


@dataclass(slots=True)
class HealthCheckService:
    dependencies: dict[str, Any] = field(default_factory=dict)
    index_stats_provider: Any | None = None
    max_last_write_age: timedelta = timedelta(hours=24)

    def shallow_check(self) -> HealthStatus:
        return HealthStatus(status="healthy", dependencies={})

    def deep_check(self) -> HealthStatus:
        dependencies: dict[str, str] = {}
        details: dict[str, Any] = {}
        stale = False
        unhealthy = False

        for name, probe in self.dependencies.items():
            try:
                ok = bool(probe())
            except Exception:
                ok = False
            dependencies[name] = "healthy" if ok else "unhealthy"
            unhealthy = unhealthy or not ok

        if self.index_stats_provider is not None:
            index_health = self._check_index_stats()
            dependencies["indexStats"] = index_health["status"]
            details["indexStats"] = index_health["details"]
            stale = bool(index_health["stale"])
            unhealthy = unhealthy or index_health["status"] == "unhealthy"

        status = "unhealthy" if unhealthy else "degraded" if stale else "healthy"
        return HealthStatus(status=status, dependencies=dependencies, stale=stale, details=details)

    def _check_index_stats(self) -> dict[str, Any]:
        try:
            stats = _read_index_stats(self.index_stats_provider)
        except Exception:
            return {"status": "unhealthy", "stale": True, "details": {"reason": "provider_error"}}

        last_write = _parse_datetime(_get(stats, "last_write_timestamp"))
        index_count = _get(stats, "index_count")
        expected_count = _get(stats, "expected_index_count")
        details = {
            "lastWriteTimestamp": last_write.isoformat() if last_write else None,
            "indexCount": index_count,
            "expectedIndexCount": expected_count,
        }

        if last_write is None:
            return {"status": "unhealthy", "stale": True, "details": details}

        stale = datetime.now(UTC) - last_write > self.max_last_write_age
        mismatch = (
            index_count is not None
            and expected_count is not None
            and int(index_count) != int(expected_count)
        )
        if mismatch:
            details["countMismatch"] = True
        status = "degraded" if stale or mismatch else "healthy"
        return {"status": status, "stale": stale, "details": details}


def _read_index_stats(provider: Any) -> Any:
    for name in ("get_index_stats", "index_stats", "stats"):
        reader = getattr(provider, name, None)
        if reader is not None:
            return reader()
    return provider


def _get(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    # Optional U1 contract: an IndexStats object MAY expose to_public_internal_dict() (its public
    # projection). Probed by name — if U1 renames it, the getattr below falls back to attribute
    # access, and a field that still can't be read surfaces as last_write=None, so deep_check
    # reports unhealthy (fail-closed) rather than a silent "healthy". (US-R4 review)
    public = getattr(value, "to_public_internal_dict", None)
    if public is not None:
        return public().get(field)
    return getattr(value, field, None)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    return None
