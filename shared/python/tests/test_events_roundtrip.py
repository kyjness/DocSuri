"""Event models round-trip, dispatch their unions, and handle the `class` alias."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from docsuri_shared import events


def test_search_executed_event_frozen_shape_roundtrip():
    payload = {
        "userId": "u1",
        "requestId": "req-1",
        "query": "diffusion models",
        "timestamp": "2026-06-16T00:00:00Z",
        "resultCount": 5,
    }
    ev = events.SearchExecutedEvent.model_validate(payload)
    assert ev.resultCount == 5
    assert set(events.SearchExecutedEvent.model_fields) == {
        "userId",
        "requestId",
        "query",
        "timestamp",
        "resultCount",
    }


def test_paper_retracted_event_roundtrip():
    ev = events.PaperRetractedEvent.model_validate(
        {"paperId": "2401.00001v2", "timestamp": "2026-06-16T00:00:00Z"}
    )
    assert ev.paperId == "2401.00001v2"


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"eventId": "e1", "arxivRef": "2106.01234"}, "NewArxivEvent"),
        (
            {"jobId": "j1", "error": {"stage": "fetch", "error": "timeout"}},
            "IngestionFailureSignal",
        ),
    ],
)
def test_ingestion_event_union_dispatch(payload, expected):
    ev = events.IngestionEvent.model_validate(payload)
    assert type(ev.root).__name__ == expected


def test_classified_incident_class_alias_roundtrip():
    payload = {"class": "a", "severity": "critical", "requestId": "r1"}
    inc = events.ClassifiedIncident.model_validate(payload)
    assert inc.class_ == events.IncidentClass.a
    assert inc.severity == events.Severity.critical
    # The wire field name is `class`, not `class_`.
    assert inc.model_dump(by_alias=True) == {
        "class": "a",
        "severity": "critical",
        "requestId": "r1",
    }


def test_incident_class_and_severity_enums():
    assert {c.value for c in events.IncidentClass} == {"a", "b", "c"}
    assert {s.value for s in events.Severity} == {"info", "warning", "critical"}


def test_ops_alert_requestId_optional():
    alert = events.OpsAlert.model_validate({"severity": "warning"})
    assert alert.requestId is None


def test_event_rejects_extra_field():
    with pytest.raises(ValidationError):
        events.AccountCreated.model_validate(
            {"userId": "u1", "timestamp": "2026-06-16T00:00:00Z", "password": "leak"}
        )
