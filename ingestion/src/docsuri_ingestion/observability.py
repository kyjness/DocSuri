from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any


class LoggingObservabilityHub:
    def __init__(self, logger_name: str = "docsuri.ingestion") -> None:
        self._logger = logging.getLogger(logger_name)

    def emit_metric(self, name: str, value: float, tags=None) -> None:
        self.emit_log(
            {
                "type": "metric",
                "name": name,
                "value": value,
                "tags": dict(tags or {}),
            }
        )

    def emit_log(self, entry) -> None:
        safe_entry = sanitize_log_entry(dict(entry))
        safe_entry.setdefault("timestamp", datetime.now(UTC).isoformat())
        self._logger.info(json.dumps(safe_entry, sort_keys=True))

    def emit_failure_signal(self, job_id: str, *, stage: str, error: str) -> None:
        self.emit_log(
            {
                "type": "ingestion_failure",
                "jobId": job_id,
                "stage": stage,
                "error": error,
            }
        )


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level, format="%(message)s")


# Credential markers for log entries. Narrower than the settings dump's list on purpose: a log
# entry's URLs, endpoints and ids are the debugging signal, so only actual secrets are removed.
# "api_key"/"apikey" rather than a bare "key" so domain fields like canonical_key stay readable.
_SECRET_LOG_MARKERS = ("secret", "password", "token", "dsn", "credential", "api_key", "apikey")


def sanitize_log_entry(entry: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in entry.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_LOG_MARKERS):
            redacted[key] = "***redacted***"
        else:
            redacted[key] = value
    return redacted
