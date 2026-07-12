from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from docsuri_shared.authz import Principal, UserRole
from fastapi.testclient import TestClient
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import ValidationError

from backend.app import create_app
from backend.config import Settings
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


class _CapturingObs:
    def __init__(self) -> None:
        self.metrics: list[str] = []
        self.tagged: list[tuple[str, dict]] = []

    def emit_metric(self, name: str, value: float = 1.0, tags: dict | None = None) -> None:
        self.metrics.append(name)
        self.tagged.append((name, tags or {}))


def test_funnel_metric_emitted_once_and_only_for_funnel_events() -> None:
    # #346 KPI funnel: read_completed emits its dimensionless counter exactly once (the emit sits
    # AFTER the dedupe guard, so a re-fired event does not double-count), a non-funnel event emits
    # nothing, and the metric name matches what the dashboard graphs.
    repo = InMemoryPersonalizationRepository()
    obs = _CapturingObs()
    recorder = BehaviorEventRecorder(repo, obs)
    user_id = str(uuid4())
    read = BehaviorEventCreate(
        eventType="read_completed",
        subject={"kind": "paper", "paperId": "p1"},
        metadata={"entrySurface": "detail"},
        dedupeKey="read:p1:1",
    )
    lib = BehaviorEventCreate(
        eventType="library_added",
        subject={"kind": "paper", "paperId": "p2", "category": "cs.AI"},
        metadata={"paperCategory": "cs.AI", "savedSource": "library"},
        dedupeKey="lib:p2:1",
    )

    recorder.record(user_id, read)
    recorder.record(user_id, read)  # dedupe → must NOT re-emit
    recorder.record(user_id, lib)  # not a funnel event → no funnel metric

    assert obs.metrics == ["personalization.funnel.read_completed"]


def test_record_event_enriches_missing_category_from_resolver() -> None:
    # US-P4: a paper-scoped event arriving WITHOUT a category is enriched via the injected
    # paperId→category resolver, so ProfileAggregator can build categoryWeights (→ search boost).
    repo = InMemoryPersonalizationRepository()
    recorder = BehaviorEventRecorder(
        repo, category_resolver=lambda pid: "cs.LG" if pid == "p1" else None
    )
    user_id = str(uuid4())
    dto = BehaviorEventCreate(
        eventType="paper_opened",
        subject={"kind": "paper", "paperId": "p1"},  # no category from the client
        metadata={"entrySurface": "detail"},
        dedupeKey="paper:p1:1",
    )

    recorder.record(user_id, dto)

    stored = repo.list_events(user_id)
    assert len(stored) == 1
    assert stored[0].subject.category == "cs.LG"


def test_category_enrichment_is_fail_open_and_scoped() -> None:
    # Best-effort (BR-P13): a resolver that raises, a resolver miss, and a non-paper event
    # (search_executed) all leave subject.category untouched — recording never depends on it.
    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())

    def _boom(_pid: str) -> str | None:
        raise RuntimeError("index down")

    BehaviorEventRecorder(repo, category_resolver=_boom).record(
        user_id,
        BehaviorEventCreate(
            eventType="paper_opened",
            subject={"kind": "paper", "paperId": "p1"},
            metadata={"entrySurface": "detail"},
            dedupeKey="paper:p1:1",
        ),
    )
    BehaviorEventRecorder(repo, category_resolver=lambda _pid: None).record(
        user_id,
        BehaviorEventCreate(
            eventType="library_added",
            subject={"kind": "paper", "paperId": "p2"},
            metadata={"savedSource": "library"},
            dedupeKey="lib:p2:1",
        ),
    )
    # search_executed is out of scope: its category signal is topCategories over the result set,
    # which the single-queryHash /events path cannot resolve.
    BehaviorEventRecorder(repo, category_resolver=lambda _pid: "cs.LG").record(
        user_id,
        BehaviorEventCreate(
            eventType="search_executed",
            subject={"kind": "search", "queryHash": "abc"},
            metadata={"resultCount": 3},
            dedupeKey="search:abc:1",
        ),
    )

    stored = {e.dedupeKey: e for e in repo.list_events(user_id)}
    assert stored["paper:p1:1"].subject.category is None  # resolver raised → unchanged
    assert stored["lib:p2:1"].subject.category is None  # resolver returned None → unchanged
    assert stored["search:abc:1"].subject.category is None  # not a paper-scoped event


def test_cached_search_boosts_builds_and_persists_profile_on_miss() -> None:
    # Gap B: with no persisted profile, the search hot path aggregates the user's category-enriched
    # events once, persists, and returns bounded boosts — so #345's live re-rank actually fires.
    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    BehaviorEventRecorder(repo, category_resolver=lambda _pid: "cs.AI").record(
        user_id,
        BehaviorEventCreate(
            eventType="library_added",
            subject={"kind": "paper", "paperId": "p1"},
            metadata={"savedSource": "library"},
            dedupeKey="lib:p1:1",
        ),
    )
    assert repo.get_profile(user_id) is None  # nothing persisted yet

    boosts = PersonalizationReadPort(repo).cached_search_boosts(user_id)

    assert boosts.get("cs.AI", 0.0) > 0.0  # boost now fires
    assert repo.get_profile(user_id) is not None  # persisted → later searches take the fast path


def test_cached_search_boosts_empty_without_events() -> None:
    # No events → aggregate returns None → no boosts (fail-open, no profile persisted).
    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    assert PersonalizationReadPort(repo).cached_search_boosts(user_id) == {}


def _record_library_add(repo, user_id: str, paper_id: str, category: str, dedupe: str) -> None:
    BehaviorEventRecorder(repo, category_resolver=lambda _pid: category).record(
        user_id,
        BehaviorEventCreate(
            eventType="library_added",
            subject={"kind": "paper", "paperId": paper_id},
            metadata={"savedSource": "library"},
            dedupeKey=dedupe,
        ),
    )


def test_profile_refreshes_when_stale() -> None:
    # US-P3 refresh: a stale profile is rebuilt on read, so a NEW categorized event's category
    # flows into the boost instead of staying frozen. ttl=0 forces "always stale".
    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    _record_library_add(repo, user_id, "p1", "cs.AI", "a:1")
    port = PersonalizationReadPort(repo, profile_ttl=timedelta(0))
    assert port.cached_search_boosts(user_id).get("cs.AI", 0.0) > 0.0  # first build

    _record_library_add(repo, user_id, "p2", "cs.LG", "b:1")  # new interest after the build
    assert port.cached_search_boosts(user_id).get("cs.LG", 0.0) > 0.0  # rebuild picked it up


def test_profile_frozen_within_ttl() -> None:
    # Within the TTL the persisted profile is reused — no rebuild, so a new event does NOT yet
    # change the boost (the fast path the TTL protects).
    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    _record_library_add(repo, user_id, "p1", "cs.AI", "a:1")
    port = PersonalizationReadPort(repo, profile_ttl=timedelta(hours=24))
    assert "cs.AI" in port.cached_search_boosts(user_id)

    _record_library_add(repo, user_id, "p2", "cs.LG", "b:1")
    assert "cs.LG" not in port.cached_search_boosts(user_id)  # cached, not rebuilt


def _record_uncategorized(repo, user_id: str, paper_id: str, dedupe: str) -> None:
    # No resolver → the event is stored WITHOUT a category (the pre-enrichment historical state).
    BehaviorEventRecorder(repo).record(
        user_id,
        BehaviorEventCreate(
            eventType="library_added",
            subject={"kind": "paper", "paperId": paper_id},
            metadata={"savedSource": "library"},
            dedupeKey=dedupe,
        ),
    )


def test_backfill_heals_categories_and_is_idempotent() -> None:
    from backend.modules.personalization.backfill import backfill_categories

    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    _record_uncategorized(repo, user_id, "2401.1", "l:1")
    # historical event carries no category → boost is empty even with rebuild forced
    empty = PersonalizationReadPort(repo, profile_ttl=timedelta(0)).cached_search_boosts(user_id)
    assert empty == {}

    report = backfill_categories(repo, resolver=lambda _pid: "cs.AI")
    assert (report.scanned, report.updated, report.unresolved) == (1, 1, 0)
    # healed event now credits categoryWeights (ttl=0 forces a rebuild off the healed event)
    boosts = PersonalizationReadPort(repo, profile_ttl=timedelta(0)).cached_search_boosts(user_id)
    assert boosts.get("cs.AI", 0.0) > 0.0
    # idempotent: the categorized event is no longer scanned
    assert backfill_categories(repo, resolver=lambda _pid: "cs.AI").scanned == 0


def test_backfill_dry_run_and_unresolved_are_safe() -> None:
    from backend.modules.personalization.backfill import backfill_categories

    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    _record_uncategorized(repo, user_id, "2401.2", "l:1")

    assert backfill_categories(repo, resolver=lambda _pid: "cs.LG", dry_run=True).updated == 1
    # dry run wrote nothing → still uncategorized, still scannable
    unresolved = backfill_categories(repo, resolver=lambda _pid: None)
    assert (unresolved.scanned, unresolved.updated, unresolved.unresolved) == (1, 0, 1)


def test_recent_papers_falls_back_to_paper_id_without_title() -> None:
    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    repo.insert_event(
        BehaviorEvent(
            userId=user_id,
            eventType=BehaviorEventType.PAPER_OPENED,
            subject=BehaviorSubject(kind="paper", paperId="2401.00001"),
            metadata={"entrySurface": "detail"},
            dedupeKey="view-1",
        )
    )

    viewed = repo.list_recent_papers(user_id)

    assert viewed[0][0] == "2401.00001"
    assert viewed[0][1] == "2401.00001"


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
    # BR-P8: raw weight 1.0 maps to the +0.1 boost ceiling, not 1.0.
    assert decision["searchBoosts"]["cs.AI"] == 0.1


def test_search_boosts_respect_brp8_bounds() -> None:
    from backend.modules.personalization.service import _to_search_boosts

    boosts = _to_search_boosts({f"cat.{i}": 1.0 for i in range(10)})
    assert boosts
    assert all(abs(b) <= 0.1 + 1e-9 for b in boosts.values())
    assert sum(abs(b) for b in boosts.values()) <= 0.2 + 1e-9


@given(
    st.dictionaries(
        st.from_regex(r"cat\.[A-Za-z0-9]{1,8}", fullmatch=True),
        st.floats(min_value=-10, max_value=10, allow_nan=False, allow_infinity=False),
        max_size=20,
    )
)
@example({"cat.a": 1.0, "cat.b": 1.0, "cat.c": 1.0})
def test_search_boosts_always_respect_brp8_bounds(weights: dict[str, float]) -> None:
    from backend.modules.personalization.service import _to_search_boosts

    boosts = _to_search_boosts(weights)
    assert all(abs(b) <= 0.1 + 1e-9 for b in boosts.values())
    assert sum(abs(b) for b in boosts.values()) <= 0.2 + 1e-9


def test_cached_search_boosts_and_decision_build_the_same_profile() -> None:
    # Gap B (US-P4): the search hot path now builds-and-persists the profile itself on a miss
    # (was: returned {} until a prior /decision call aggregated one). It shares the same lazy
    # aggregation as search_decision, so the two agree — and the FIRST search already boosts.
    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    repo.insert_event(_event(user_id, "d1"))

    boosts = PersonalizationReadPort(repo).cached_search_boosts(user_id)
    assert boosts["cs.AI"] == 0.1
    assert repo.get_profile(user_id) is not None  # built + persisted on the hot path

    decision = PersonalizationReadPort(repo).search_decision(user_id)
    assert decision.reason == "profile_available"
    assert decision.searchBoosts == boosts


def test_api_settings_disable_recording(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryPersonalizationRepository()
    client = _client(monkeypatch, principal, repo)

    assert client.get("/api/personalization/settings").json()["enabled"] is True
    assert client.patch("/api/personalization/settings", json={"enabled": False}).status_code == 200
    assert client.get("/api/personalization/settings").json()["enabled"] is False
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


# ---------------------------------------------------------------------------
# US-P1 AC3 (QA 2026-07-10 gap): behavior-event store failure must NOT fail the
# caller — the event is dropped with a degrade signal (fail-open, FR-39/BR-P13).
# ---------------------------------------------------------------------------


class _FailingStoreRepo(InMemoryPersonalizationRepository):
    """Fault injection: the user_behavior_events store raises on write."""

    def insert_event(self, event: BehaviorEvent) -> bool:
        raise RuntimeError("behavior-event store down")


class _FailingSettingsRepo(InMemoryPersonalizationRepository):
    """Fault injection: even the pre-write settings read raises."""

    def get_settings(self, user_id: str):
        raise RuntimeError("settings store down")


def _valid_event_payload(dedupe: str) -> dict:
    return {
        "eventType": "library_added",
        "subject": {"kind": "paper", "paperId": "p1", "category": "cs.AI"},
        "metadata": {"paperCategory": "cs.AI", "savedSource": "library"},
        "dedupeKey": dedupe,
    }


def test_store_failure_fails_open_with_degrade_signal() -> None:
    # AC3: insert_event raising is swallowed — record() returns a degraded result instead of
    # raising into the caller, and the degrade counter fires so the drop is not silent.
    for repo in (_FailingStoreRepo(), _FailingSettingsRepo()):
        obs = _CapturingObs()
        recorder = BehaviorEventRecorder(repo, obs)

        result = recorder.record(
            str(uuid4()), BehaviorEventCreate(**_valid_event_payload("boom-1"))
        )

        assert result.recorded is False
        assert result.reason == "degraded"
        assert "personalization.record_failure" in obs.metrics


def test_api_request_survives_event_store_failure(monkeypatch) -> None:
    # AC3 end-to-end: the /events request itself still succeeds (HTTP 200) when the store is
    # down — the event is dropped with reason=degraded, never a 5xx back to the client.
    client = _client(monkeypatch, _principal(), _FailingStoreRepo())

    resp = client.post("/api/personalization/events", json=_valid_event_payload("boom-api"))

    assert resp.status_code == 200
    body = resp.json()
    assert body["recorded"] is False
    assert body["reason"] == "degraded"


# ---------------------------------------------------------------------------
# US-P1 AC2 (QA 2026-07-10 gap): only the meaningful event taxonomy is
# recordable — passive telemetry (hover/scroll/dwell) has no event type.
# ---------------------------------------------------------------------------

_PASSIVE_EVENT_TYPES = ("hover", "scroll", "dwell", "mouse_move", "scroll_depth", "dwell_time")


def test_event_taxonomy_is_closed_to_meaningful_events() -> None:
    # AC2: the recordable taxonomy is exactly the meaningful set — search, paper view, library
    # save/unsave, summary/translation request, source-anchor click, glossary edit (+
    # read_completed, the #346 KPI-funnel addition). Adding a passive type must fail this test
    # and force a story-level review.
    assert {t.value for t in BehaviorEventType} == {
        "search_executed",
        "paper_opened",
        "library_added",
        "library_removed",
        "summary_translation_requested",
        "source_anchor_clicked",
        "glossary_updated",
        "read_completed",
    }
    for passive in _PASSIVE_EVENT_TYPES:
        assert passive not in {t.value for t in BehaviorEventType}
        try:
            BehaviorEventCreate(
                eventType=passive,
                subject={"kind": "paper", "paperId": "p1"},
                metadata={},
                dedupeKey="passive-1",
            )
        except ValidationError:
            continue
        raise AssertionError(f"passive event type {passive!r} must not be recordable")


def test_api_rejects_passive_event_types(monkeypatch) -> None:
    client = _client(monkeypatch, _principal(), InMemoryPersonalizationRepository())
    for passive in _PASSIVE_EVENT_TYPES:
        resp = client.post(
            "/api/personalization/events",
            json={
                "eventType": passive,
                "subject": {"kind": "paper", "paperId": "p1"},
                "metadata": {},
                "dedupeKey": f"passive:{passive}",
            },
        )
        assert resp.status_code == 422, passive


# ---------------------------------------------------------------------------
# US-P7 / QT-7 property tests (QA 2026-07-10 gap).
# ---------------------------------------------------------------------------

_SUBJECT_KINDS = ["paper", "search", "summary", "translation", "source_anchor", "glossary"]

_JSON_SCALARS = st.one_of(
    st.text(max_size=40),
    st.integers(min_value=-(10**9), max_value=10**9),
    st.booleans(),
)

_SUBJECTS = st.builds(
    BehaviorSubject,
    kind=st.sampled_from(_SUBJECT_KINDS),
    paperId=st.none() | st.text(min_size=1, max_size=64),
    queryHash=st.none() | st.text(min_size=1, max_size=64),
    category=st.none() | st.text(min_size=1, max_size=32),
    anchorId=st.none() | st.text(min_size=1, max_size=64),
)

_EVENTS = st.builds(
    BehaviorEvent,
    userId=st.uuids().map(str),
    eventType=st.sampled_from(list(BehaviorEventType)),
    subject=_SUBJECTS,
    occurredAt=st.datetimes(
        min_value=datetime(1970, 1, 1),
        max_value=datetime(2100, 1, 1),
        timezones=st.just(UTC),
    ),
    source=st.sampled_from(["backend", "frontend_anchor"]),
    metadata=st.dictionaries(st.text(min_size=1, max_size=24), _JSON_SCALARS, max_size=5),
    dedupeKey=st.text(min_size=1, max_size=80),
)


@given(event=_EVENTS)
def test_qt7_event_dto_roundtrip_identity(event: BehaviorEvent) -> None:
    # QT-7: serialize→deserialize is the identity for any structurally valid event — the wire
    # format never drops or mutates a field.
    assert BehaviorEvent.model_validate_json(event.model_dump_json()) == event


def _library_add(user_id: str, paper_id: str, category: str, dedupe: str) -> BehaviorEventCreate:
    return BehaviorEventCreate(
        eventType="library_added",
        subject={"kind": "paper", "paperId": paper_id, "category": category},
        metadata={"paperCategory": category, "savedSource": "library"},
        dedupeKey=dedupe,
    )


@given(
    cats_a=st.lists(st.from_regex(r"a\.[A-Z]{2}", fullmatch=True), min_size=1, max_size=5),
    cats_b=st.lists(st.from_regex(r"b\.[A-Z]{2}", fullmatch=True), min_size=1, max_size=5),
)
def test_qt7_per_user_isolation(cats_a: list[str], cats_b: list[str]) -> None:
    # QT-7: user A's events never leak into user B's profile aggregation — through the real
    # recording path and the shared repo, not pre-partitioned event lists. Disjoint category
    # namespaces (a.* / b.*) make any cross-user leak observable.
    repo = InMemoryPersonalizationRepository()
    recorder = BehaviorEventRecorder(repo)
    user_a, user_b = str(uuid4()), str(uuid4())
    for i, cat in enumerate(cats_a):
        recorder.record(user_a, _library_add(user_a, f"pa-{i}", cat, f"a:{i}"))
    for i, cat in enumerate(cats_b):
        recorder.record(user_b, _library_add(user_b, f"pb-{i}", cat, f"b:{i}"))

    port = PersonalizationReadPort(repo, profile_ttl=timedelta(0))
    assert set(port.cached_search_boosts(user_a)) <= set(cats_a)
    assert set(port.cached_search_boosts(user_b)) <= set(cats_b)
    profile_a, profile_b = repo.get_profile(user_a), repo.get_profile(user_b)
    assert profile_a is not None and profile_b is not None
    assert not set(profile_a.categoryWeights) & set(cats_b)
    assert not set(profile_b.categoryWeights) & set(cats_a)
    assert all(not paper.startswith("pb-") for paper in profile_a.paperSignals)
    assert all(not paper.startswith("pa-") for paper in profile_b.paperSignals)


_CAT = st.from_regex(r"cs\.[A-Z]{2}", fullmatch=True)
_KEYWORD = st.from_regex(r"kw[a-z]{1,6}", fullmatch=True)
_ACTIONS = st.lists(
    st.one_of(
        st.tuples(st.just(BehaviorEventType.PAPER_OPENED), _CAT),
        st.tuples(st.just(BehaviorEventType.LIBRARY_ADDED), _CAT),
        st.tuples(st.just(BehaviorEventType.SUMMARY_TRANSLATION_REQUESTED), _CAT),
        st.tuples(
            st.just(BehaviorEventType.SEARCH_EXECUTED),
            st.lists(_CAT, max_size=3),
            st.lists(_KEYWORD, max_size=3),
        ),
        st.tuples(st.just(BehaviorEventType.LIBRARY_REMOVED)),
    ),
    min_size=1,
    max_size=20,
)


def _events_from_actions(user_id: str, actions: list[tuple]) -> list[BehaviorEvent]:
    base = datetime.now(UTC)
    events: list[BehaviorEvent] = []
    for i, action in enumerate(actions):
        event_type = action[0]
        occurred = base + timedelta(seconds=i)
        if event_type is BehaviorEventType.SEARCH_EXECUTED:
            subject = BehaviorSubject(kind="search", queryHash=f"q{i}")
            metadata = {"topCategories": list(action[1]), "keywords": list(action[2])}
        elif event_type is BehaviorEventType.LIBRARY_REMOVED:
            subject = BehaviorSubject(kind="paper", paperId=f"p{i}")
            metadata = {}
        else:
            subject = BehaviorSubject(kind="paper", paperId=f"p{i}", category=action[1])
            metadata = {}
        events.append(
            BehaviorEvent(
                userId=user_id,
                eventType=event_type,
                subject=subject,
                metadata=metadata,
                dedupeKey=f"e{i}",
                occurredAt=occurred,
            )
        )
    return events


@given(actions=_ACTIONS)
def test_qt7_profile_weight_invariants(actions: list[tuple]) -> None:
    # QT-7: whatever mix of meaningful events a user produces, the aggregated profile obeys
    # _bounded()'s guarantees — every weight ∈ (0, 1], each non-empty weight map is normalized
    # so its max is exactly 1.0, and aggregation is order-independent (BR-P7 determinism:
    # events are re-sorted by (occurredAt, eventId) internally).
    user_id = str(uuid4())
    events = _events_from_actions(user_id, actions)

    profile = ProfileAggregator().aggregate(user_id, events)

    assert profile is not None
    for weights in (profile.categoryWeights, profile.keywordWeights, profile.paperSignals):
        assert all(0.0 < weight <= 1.0 for weight in weights.values())
        if weights:
            assert max(weights.values()) == 1.0
    again = ProfileAggregator().aggregate(user_id, list(reversed(events)))
    assert again is not None
    assert again.categoryWeights == profile.categoryWeights
    assert again.keywordWeights == profile.keywordWeights
    assert again.paperSignals == profile.paperSignals


@given(cats=st.lists(_CAT, min_size=1, max_size=8))
def test_qt7_duplicate_event_stability(cats: list[str]) -> None:
    # QT-7: re-recording the same event (same dedupeKey) is a no-op — the store keeps one row
    # per (owner, dedupeKey), so the profile equals the record-once profile. A duplicate with a
    # NEW dedupeKey counting again is by design (each real occurrence is a real signal).
    once, twice = InMemoryPersonalizationRepository(), InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    for i, cat in enumerate(cats):
        dto = _library_add(user_id, f"p{i}", cat, f"d{i}")
        assert BehaviorEventRecorder(once).record(user_id, dto).recorded is True
        assert BehaviorEventRecorder(twice).record(user_id, dto).recorded is True
        replay = BehaviorEventRecorder(twice).record(user_id, dto)
        assert replay.duplicate is True and replay.recorded is False

    assert len(twice.list_events(user_id)) == len(cats)  # the real dedupe guarantee
    p_once = ProfileAggregator().aggregate(user_id, once.list_events(user_id))
    p_twice = ProfileAggregator().aggregate(user_id, twice.list_events(user_id))
    assert p_once is not None and p_twice is not None
    assert p_twice.categoryWeights == p_once.categoryWeights
    assert p_twice.paperSignals == p_once.paperSignals


# ---------------------------------------------------------------------------
# US-P7 observability (QA 2026-07-10 gap): fail-soft counters on the read port.
# ---------------------------------------------------------------------------


def test_aggregation_failure_emits_metric_and_fails_open() -> None:
    class _BoomAggregator:
        def aggregate(self, user_id: str, events: list) -> None:
            raise RuntimeError("aggregation bug")

    repo = InMemoryPersonalizationRepository()
    user_id = str(uuid4())
    repo.insert_event(_event(user_id, "d1"))
    obs = _CapturingObs()
    port = PersonalizationReadPort(repo, aggregator=_BoomAggregator(), observability=obs)

    assert port.cached_search_boosts(user_id) == {}  # fail-open: search proceeds unboosted
    assert "personalization.profile_aggregation_failure" in obs.metrics
    assert "personalization.degraded_decision" in obs.metrics
    assert ("personalization.fallback", {"reason": "degraded"}) in obs.tagged
    assert port.search_decision(user_id).reason == "degraded"  # decision path degrades too


def test_applied_and_fallback_counters_on_search_hot_path() -> None:
    repo = InMemoryPersonalizationRepository()
    obs = _CapturingObs()
    port = PersonalizationReadPort(repo, observability=obs)

    with_profile = str(uuid4())
    repo.insert_event(_event(with_profile, "d1"))
    assert port.cached_search_boosts(with_profile)
    assert "personalization.applied" in obs.metrics

    no_signal = str(uuid4())
    assert port.cached_search_boosts(no_signal) == {}
    assert ("personalization.fallback", {"reason": "no_profile"}) in obs.tagged

    disabled = str(uuid4())
    repo.set_enabled(disabled, False)
    assert port.cached_search_boosts(disabled) == {}
    assert ("personalization.fallback", {"reason": "disabled"}) in obs.tagged
    # exactly one applied/fallback signal per call
    applied_or_fallback = [
        name
        for name in obs.metrics
        if name in {"personalization.applied", "personalization.fallback"}
    ]
    assert len(applied_or_fallback) == 3
