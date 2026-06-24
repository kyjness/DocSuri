from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.modules.accounts.models import Principal, UserRole
from backend.modules.personalization import controller
from backend.modules.personalization.models import (
    BehaviorEvent,
    BehaviorEventCreate,
    BehaviorEventType,
    BehaviorSubject,
    MetadataValidationError,
    validate_metadata,
)
from backend.modules.personalization.repository import InMemoryPersonalizationRepository
from backend.modules.personalization.service import (
    BehaviorEventRecorder,
    PersonalizationReadPort,
    ProfileAggregator,
    purge_expired_events,
)


def _principal(user_id: str | None = None) -> Principal:
    return Principal(user_id=user_id or str(uuid4()), role=UserRole.USER)


def _event(
    user_id: str,
    dedupe: str,
    category: str = "cs.AI",
    occurred_at: datetime | None = None,
) -> BehaviorEvent:
    return BehaviorEvent(
        userId=user_id,
        eventType=BehaviorEventType.LIBRARY_ADDED,
        subject=BehaviorSubject(kind="paper", paperId=f"p-{dedupe}", category=category),
        metadata={"paperCategory": category, "savedSource": "test"},
        dedupeKey=dedupe,
        occurredAt=occurred_at or datetime.now(UTC),
    )


def _client(monkeypatch, principal: Principal | None = None, repo=None) -> TestClient:
    monkeypatch.setenv("PERSONALIZATION_ENABLED", "true")
    app = create_app(Settings(env="test", database_url="sqlite://"))
    app.dependency_overrides[controller.get_principal] = lambda: principal or _principal()
    if repo is not None:
        app.dependency_overrides[controller.get_repo] = lambda: repo
    return TestClient(app)


def test_behavior_event_dto_roundtrip() -> None:
    dto = BehaviorEventCreate(
        eventType="library_added",
        subject={"kind": "paper", "paperId": "2401.1", "category": "cs.AI"},
        metadata={"paperCategory": "cs.AI", "savedSource": "library"},
        dedupeKey="d1",
    )

    again = BehaviorEventCreate.model_validate_json(dto.model_dump_json())

    assert again.eventType is BehaviorEventType.LIBRARY_ADDED
    assert again.subject.paperId == "2401.1"
    assert again.dedupeKey == "d1"


def test_metadata_allowlist_rejects_free_payload() -> None:
    try:
        validate_metadata(
            BehaviorEventType.SOURCE_ANCHOR_CLICKED,
            {"anchorId": "a1", "rawText": "quoted source text"},
        )
    except MetadataValidationError:
        pass
    else:  # pragma: no cover - failure path clarity
        raise AssertionError("raw source metadata should be rejected")


def test_record_event_dedupes_per_owner() -> None:
    repo = InMemoryPersonalizationRepository()
    recorder = BehaviorEventRecorder(repo)
    user_id = str(uuid4())
    dto = BehaviorEventCreate(
        eventType="paper_opened",
        subject={"kind": "paper", "paperId": "p1", "category": "cs.AI"},
        metadata={"entrySurface": "detail", "paperCategory": "cs.AI"},
        dedupeKey="same",
    )

    first = recorder.record(user_id, dto)
    second = recorder.record(user_id, dto)

    assert first.recorded is True
    assert second.duplicate is True
    assert len(repo.list_events(user_id)) == 1


def test_owner_isolation_and_deterministic_aggregation() -> None:
    user_a = str(uuid4())
    user_b = str(uuid4())
    events = [_event(user_a, "2", "cs.LG"), _event(user_a, "1", "cs.AI")]
    profile_a = ProfileAggregator().aggregate(user_a, list(reversed(events)))
    profile_a_again = ProfileAggregator().aggregate(user_a, events)
    profile_b = ProfileAggregator().aggregate(user_b, [_event(user_b, "1", "math.OC")])

    assert profile_a is not None
    assert profile_a_again is not None
    assert profile_a.categoryWeights == profile_a_again.categoryWeights
    assert "math.OC" not in profile_a.categoryWeights
    assert profile_b is not None
    assert "cs.AI" not in profile_b.categoryWeights


def test_delete_events_removes_future_personalization() -> None:
    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    repo.insert_event(_event(user_id, "d1"))

    assert PersonalizationReadPort(repo).search_decision(user_id).reason == "profile_available"
    deleted = repo.delete_events(user_id)

    assert deleted == 1
    assert PersonalizationReadPort(repo).search_decision(user_id).reason == "no_profile"
    assert repo.get_settings(user_id).profileResetAt is not None


def test_delete_events_ignores_backdated_events_after_delete() -> None:
    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    repo.insert_event(_event(user_id, "d1"))

    repo.delete_events(user_id)
    reset_at = repo.get_settings(user_id).profileResetAt
    assert reset_at is not None
    repo.insert_event(_event(user_id, "late-old", occurred_at=reset_at - timedelta(seconds=1)))

    assert PersonalizationReadPort(repo).search_decision(user_id).reason == "no_profile"


def test_profile_reset_ignores_old_events_until_new_signal() -> None:
    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    repo.insert_event(_event(user_id, "old", occurred_at=datetime.now(UTC) - timedelta(days=1)))

    assert PersonalizationReadPort(repo).search_decision(user_id).reason == "profile_available"
    repo.reset_profile(user_id)

    assert PersonalizationReadPort(repo).search_decision(user_id).reason == "no_profile"


def test_retention_purge_is_idempotent() -> None:
    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    cutoff = datetime.now(UTC) - timedelta(days=90)
    repo.insert_event(_event(user_id, "old", occurred_at=cutoff - timedelta(seconds=1)))
    repo.insert_event(_event(user_id, "new", occurred_at=cutoff + timedelta(seconds=1)))

    assert purge_expired_events(repo, cutoff) == 1
    assert purge_expired_events(repo, cutoff) == 0
    assert [event.dedupeKey for event in repo.list_events(user_id)] == ["new"]


def test_api_records_and_returns_decision(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryPersonalizationRepository()
    client = _client(monkeypatch, principal, repo)

    resp = client.post(
        "/api/personalization/events",
        json={
            "eventType": "library_added",
            "subject": {"kind": "paper", "paperId": "p1", "category": "cs.AI"},
            "metadata": {"paperCategory": "cs.AI", "savedSource": "library"},
            "dedupeKey": "api-1",
        },
    )
    decision = client.get("/api/personalization/decision/search").json()

    assert resp.status_code == 200
    assert resp.json()["recorded"] is True
    assert decision["reason"] == "profile_available"
    assert decision["searchBoosts"]["cs.AI"] == 1.0


def test_api_settings_disable_recording(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryPersonalizationRepository()
    client = _client(monkeypatch, principal, repo)

    assert client.patch("/api/personalization/settings", json={"enabled": False}).status_code == 200
    resp = client.post(
        "/api/personalization/events",
        json={
            "eventType": "library_added",
            "subject": {"kind": "paper", "paperId": "p1", "category": "cs.AI"},
            "metadata": {"paperCategory": "cs.AI", "savedSource": "library"},
            "dedupeKey": "api-disabled",
        },
    )

    assert resp.json()["reason"] == "disabled"
    assert repo.list_events(principal.user_id) == []


def test_api_delete_and_reset(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryPersonalizationRepository()
    repo.insert_event(_event(principal.user_id, "d1"))
    client = _client(monkeypatch, principal, repo)

    assert client.post("/api/personalization/delete-events").json() == {"deletedEvents": 1}
    assert client.post("/api/personalization/reset-profile").json() == {"status": "reset"}


def test_feature_flag_blocks_endpoint_by_default() -> None:
    client = TestClient(create_app(Settings(env="test", database_url="sqlite://")))

    assert client.get("/api/personalization/decision/search").status_code == 404


def test_personalization_repo_must_be_wired() -> None:
    try:
        controller.get_repo()
    except RuntimeError as exc:
        assert "not wired" in str(exc)
    else:  # pragma: no cover - failure path clarity
        raise AssertionError("default personalization repo should not be process-global")
