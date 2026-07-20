"""Secret-logging checks required by the unit's build-and-test instructions.

``aidlc-docs/construction/build-and-test/security-test-instructions.md`` names both redaction
helpers as controls to verify. Neither had a test, and ``safe_log_dict`` was in fact leaking the
Semantic Scholar API key and the OpenAlex contact address in cleartext.
"""

from __future__ import annotations

from docsuri_ingestion.observability import LoggingObservabilityHub, sanitize_log_entry
from docsuri_ingestion.settings import IngestionSettings

_DSN = "postgresql://docsuri:hunter2@db.internal:5432/docsuri"
_ENDPOINT = "https://vpc-docsuri-abc123.ap-northeast-2.es.amazonaws.com"
_QUEUE_URL = "https://sqs.ap-northeast-2.amazonaws.com/123456789012/docsuri-ingest"
_API_KEY = "ss-live-0123456789abcdef"
_MAILTO = "operator@example.com"
_KMS_KEY = "arn:aws:kms:ap-northeast-2:123456789012:key/abcd-ef01"


def _configured_settings() -> IngestionSettings:
    return IngestionSettings.model_validate(
        {
            "DOCSURI_CONTROL_PLANE_DSN": _DSN,
            "DOCSURI_OPENSEARCH_ENDPOINT": _ENDPOINT,
            "DOCSURI_SQS_QUEUE_URL": _QUEUE_URL,
            "DOCSURI_SQS_DLQ_URL": _QUEUE_URL,
            "DOCSURI_GROBID_URL": "http://grobid.internal:8070",
            "DOCSURI_SEMANTIC_SCHOLAR_API_KEY": _API_KEY,
            "DOCSURI_OPENALEX_MAILTO": _MAILTO,
            "DOCSURI_ASSET_KMS_KEY_ID": _KMS_KEY,
        }
    )


def test_safe_log_dict_discloses_no_configured_value() -> None:
    dumped = repr(_configured_settings().safe_log_dict())
    for secret in (_DSN, _ENDPOINT, _QUEUE_URL, _API_KEY, _MAILTO, _KMS_KEY):
        assert secret not in dumped, f"safe_log_dict leaked {secret!r}"
    # Even a fragment must not survive — a password or host alone is a disclosure.
    for fragment in ("hunter2", "db.internal", "vpc-docsuri-abc123", "operator@example.com"):
        assert fragment not in dumped, f"safe_log_dict leaked {fragment!r}"


def test_safe_log_dict_still_reports_whether_a_value_is_set() -> None:
    # Redaction must not destroy the reason to log the dump: configured vs not stays visible.
    configured = _configured_settings().safe_log_dict()
    assert configured["control_plane_dsn"] == "***configured***"
    assert configured["semantic_scholar_api_key"] == "***configured***"

    empty = IngestionSettings.model_validate({}).safe_log_dict()
    assert not empty["control_plane_dsn"]
    assert not empty["semantic_scholar_api_key"]

    # Non-sensitive settings stay readable, otherwise the dump is useless for diagnosis.
    assert configured["env"] == "local"
    assert configured["max_chunk_chars"] == 2400


def test_sanitize_log_entry_redacts_credentials_and_keeps_debugging_fields() -> None:
    entry = sanitize_log_entry(
        {
            "type": "ingestion_failure",
            "paperId": "2401.00001",
            "canonicalKey": "arxiv:2401.00001",
            "sourceUrl": "https://arxiv.org/pdf/2401.00001",
            "controlPlaneDsn": _DSN,
            "apiKey": _API_KEY,
            "sessionToken": "tok-abc",
            "clientSecret": "shh",
            "dbPassword": "hunter2",
        }
    )
    for field in ("controlPlaneDsn", "apiKey", "sessionToken", "clientSecret", "dbPassword"):
        assert entry[field] == "***redacted***", f"sanitize_log_entry leaked {field}"
    # A log entry's ids and public URLs are the debugging signal — they must survive.
    assert entry["paperId"] == "2401.00001"
    assert entry["canonicalKey"] == "arxiv:2401.00001"
    assert entry["sourceUrl"] == "https://arxiv.org/pdf/2401.00001"


def test_emitted_logs_go_through_sanitization(caplog) -> None:
    # The hub is the only logging path in the unit, so the guard must be applied there, not left
    # to each caller to remember.
    with caplog.at_level("INFO", logger="docsuri.ingestion"):
        LoggingObservabilityHub().emit_log({"type": "probe", "apiKey": _API_KEY})
    assert _API_KEY not in caplog.text
    assert "***redacted***" in caplog.text
