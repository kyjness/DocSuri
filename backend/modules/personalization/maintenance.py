from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from backend.config import Settings
from backend.db import make_engine, make_session_factory

from .repository import SqlPersonalizationRepository
from .service import purge_expired_events


def _retention_days() -> int:
    return int(os.getenv("PERSONALIZATION_RAW_EVENT_RETENTION_DAYS") or "90")


def _build_observability():
    try:
        from docsuri_ops.observability import ObservabilityHub
    except ModuleNotFoundError:
        return None, None
    namespace = os.getenv("CLOUDWATCH_NAMESPACE")
    if namespace:
        from docsuri_ops.adapters.cloudwatch import CloudWatchEventStore

        store = CloudWatchEventStore(
            namespace=namespace,
            log_group=os.getenv("CLOUDWATCH_LOG_GROUP", "/docsuri/ops"),
            region_name=os.getenv("AWS_REGION", "ap-northeast-2"),
        )
    else:
        from docsuri_ops.adapters.local import InMemoryEventStore

        store = InMemoryEventStore()
    return ObservabilityHub(store), store


def run() -> int:
    settings = Settings.from_env()
    observability, store = _build_observability()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    session = session_factory()
    try:
        cutoff = datetime.now(UTC) - timedelta(days=_retention_days())
        deleted = purge_expired_events(
            SqlPersonalizationRepository(session), cutoff, observability
        )
        session.commit()
        print(f"personalization retention purge deleted {deleted} row(s)")
        return 0
    except Exception:
        emit = getattr(observability, "emit_metric", None)
        if emit is not None:
            try:
                emit("personalization.retention_purge_failure", 1.0, {})
            except Exception:
                pass
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()
        close = getattr(store, "close", None)
        if close is not None:
            close()


if __name__ == "__main__":
    raise SystemExit(run())
