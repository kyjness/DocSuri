from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from .models import (
    BehaviorEvent,
    BehaviorEventCreate,
    BehaviorEventType,
    EventRecordResult,
    PersonalizationDecision,
    PersonalizationSettings,
    UserInterestProfile,
    utc_now,
)
from .repository import PersonalizationRepository


def _emit_metric(observability, name: str, value: float = 1.0, tags: dict | None = None) -> None:
    emit = getattr(observability, "emit_metric", None)
    if emit is None:
        return
    try:
        emit(name, value, tags or {})
    except Exception:
        pass


# KPI funnel counters (#346): the success-metric hierarchy — AI 호출 > 검색 > 완독 — is measured
# from these U9 events, emitted as dimensionless CloudWatch counters (namespace DocSuri/Production)
# so the ops dashboard graphs them with a plain Sum metric. The events themselves stay in Postgres.
# Only funnel-relevant types emit; the insert dedupe means a re-fired event is not double-counted.
_FUNNEL_METRIC: dict[BehaviorEventType, str] = {
    BehaviorEventType.SEARCH_EXECUTED: "personalization.funnel.search",
    BehaviorEventType.SUMMARY_TRANSLATION_REQUESTED: "personalization.funnel.ai_invocation",
    BehaviorEventType.PAPER_OPENED: "personalization.funnel.paper_opened",
    BehaviorEventType.READ_COMPLETED: "personalization.funnel.read_completed",
}


# Event types where ProfileAggregator credits a single paper's category to categoryWeights
# (the input to the US-P4 search boost). SEARCH_EXECUTED is excluded — its category signal is
# metadata.topCategories over the RESULT SET, which the /events path (a single queryHash) can't
# resolve. paper_opened/library_added/summary_translation_requested each name one paperId.
_CATEGORY_EVENTS: frozenset[BehaviorEventType] = frozenset(
    {
        BehaviorEventType.PAPER_OPENED,
        BehaviorEventType.LIBRARY_ADDED,
        BehaviorEventType.SUMMARY_TRANSLATION_REQUESTED,
    }
)


class BehaviorEventRecorder:
    def __init__(
        self,
        repo: PersonalizationRepository,
        observability=None,
        category_resolver: Callable[[str], str | None] | None = None,
    ) -> None:
        self._repo = repo
        self._observability = observability
        # paperId → primary arXiv category (U2 index lookup), injected at the controller. None
        # (standalone/tests/index down) → events store uncategorized, exactly as before. # ponytail:
        # no cache — event volume is tiny and /events is fire-and-forget; add lru_cache if it grows.
        self._category_resolver = category_resolver

    def record(self, user_id: str, dto: BehaviorEventCreate) -> EventRecordResult:
        try:
            if not self._repo.get_settings(user_id).enabled:
                return EventRecordResult(recorded=False, reason="disabled")
            dto = self._with_category(dto)
            inserted = self._repo.insert_event(
                BehaviorEvent(userId=user_id, **dto.model_dump())
            )
            if not inserted:
                return EventRecordResult(recorded=False, duplicate=True, reason="duplicate")
            funnel_metric = _FUNNEL_METRIC.get(dto.eventType)
            if funnel_metric is not None:
                _emit_metric(self._observability, funnel_metric)
            return EventRecordResult(recorded=True, reason="recorded")
        except Exception:
            _emit_metric(self._observability, "personalization.record_failure")
            return EventRecordResult(recorded=False, reason="degraded")

    def _with_category(self, dto: BehaviorEventCreate) -> BehaviorEventCreate:
        """Attach the paper's category to a paper-scoped event so ProfileAggregator can build
        categoryWeights (US-P4 search boost). Best-effort and idempotent: no resolver, a
        non-paper event, an already-categorized subject, a missing paperId, or a lookup
        miss/failure all return ``dto`` unchanged — recording never depends on enrichment
        (BR-P13)."""
        resolver = self._category_resolver
        if resolver is None or dto.eventType not in _CATEGORY_EVENTS:
            return dto
        subject = dto.subject
        if subject.category or not subject.paperId:
            return dto
        try:
            category = resolver(subject.paperId)
        except Exception:  # noqa: BLE001 — enrichment must never fail event recording
            return dto
        if not category:
            return dto
        return dto.model_copy(
            update={"subject": subject.model_copy(update={"category": category})}
        )


class ProfileAggregator:
    def aggregate(self, user_id: str, events: list[BehaviorEvent]) -> UserInterestProfile | None:
        if not events:
            return None
        category_weights: defaultdict[str, float] = defaultdict(float)
        keyword_weights: defaultdict[str, float] = defaultdict(float)
        paper_signals: defaultdict[str, float] = defaultdict(float)
        summary_defaults: dict[str, str] = {}
        translation_defaults: dict[str, str] = {}
        glossary_version: str | None = None

        for event in sorted(events, key=lambda e: (e.occurredAt, e.eventId)):
            category = event.subject.category or event.metadata.get("paperCategory")
            if event.eventType is BehaviorEventType.SEARCH_EXECUTED:
                for cat in event.metadata.get("topCategories") or []:
                    category_weights[str(cat)] += 0.5
                for keyword in event.metadata.get("keywords") or []:
                    keyword_weights[str(keyword)] += 0.25
            elif event.eventType is BehaviorEventType.PAPER_OPENED:
                if category:
                    category_weights[str(category)] += 1.0
                if event.subject.paperId:
                    paper_signals[event.subject.paperId] += 1.0
            elif event.eventType is BehaviorEventType.LIBRARY_ADDED:
                if category:
                    category_weights[str(category)] += 3.0
                if event.subject.paperId:
                    paper_signals[event.subject.paperId] += 3.0
            elif event.eventType is BehaviorEventType.LIBRARY_REMOVED:
                if event.subject.paperId:
                    paper_signals.pop(event.subject.paperId, None)
            elif event.eventType is BehaviorEventType.SUMMARY_TRANSLATION_REQUESTED:
                if category:
                    category_weights[str(category)] += 2.0
                if persona := event.metadata.get("selectedPersona"):
                    summary_defaults["persona"] = str(persona)
                if scope := event.metadata.get("translationScope"):
                    translation_defaults["scope"] = str(scope)
            elif event.eventType is BehaviorEventType.GLOSSARY_UPDATED:
                if version := event.metadata.get("glossaryVersion"):
                    glossary_version = str(version)

        return UserInterestProfile(
            userId=user_id,
            categoryWeights=_bounded(category_weights),
            keywordWeights=_bounded(keyword_weights),
            paperSignals=_bounded(paper_signals),
            summaryDefaults=summary_defaults,
            translationDefaults=translation_defaults,
            glossaryVersion=glossary_version,
            updatedAt=utc_now(),
        )


def _bounded(values: dict[str, float]) -> dict[str, float]:
    if not values:
        return {}
    max_value = max(values.values()) or 1.0
    return {
        key: round(min(1.0, max(0.0, value / max_value)), 4)
        for key, value in sorted(values.items())
        if value > 0
    }


# BR-P8 search-boost contract: each category boost ∈ [-0.1, +0.1], Σ|boost| ≤ 0.2. Enforced
# HERE (at the read port) so every consumer gets contract-compliant values — the ranker never
# has to re-clamp. Category weights are stored in [0,1]; the decision maps them to boosts.
_BOOST_CEILING = 0.1
_BOOST_TOTAL = 0.2


def _to_search_boosts(weights: dict[str, float]) -> dict[str, float]:
    boosts = {
        key: max(-_BOOST_CEILING, min(_BOOST_CEILING, value * _BOOST_CEILING))
        for key, value in weights.items()
        if value
    }
    total = sum(abs(b) for b in boosts.values())
    if total > _BOOST_TOTAL:
        scale = _BOOST_TOTAL / total
        boosts = {key: b * scale for key, b in boosts.items()}
    return boosts


# US-P3 profile refresh (US-P4 boost freshness): a persisted profile is otherwise frozen — new
# category-enriched events never change it, so search boosts go stale and the #345 cold-start locks
# in the empty profile built on a user's first post-go-live search. Refresh LAZILY on read: rebuild
# from current events once the profile is older than this TTL, on the next search that user makes.
# No scheduler/worker — active searchers (the only ones whose boost is consumed) self-heal on their
# own cadence; a user who never searches keeps a stale profile, which is harmless. Tune via env
# PERSONALIZATION_PROFILE_TTL_SECONDS (0 = rebuild every read).
# ponytail: TTL-on-read, not a batch job. Add a job only if profiles must refresh WITHOUT a search
# — they don't (no search → no boost read). Bump to a job if a non-search consumer ever appears.
_DEFAULT_PROFILE_TTL = timedelta(hours=24)


def _profile_ttl_from_env() -> timedelta:
    raw = os.getenv("PERSONALIZATION_PROFILE_TTL_SECONDS")
    if raw is None:
        return _DEFAULT_PROFILE_TTL
    try:
        seconds = int(raw)
    except ValueError:
        return _DEFAULT_PROFILE_TTL
    return timedelta(seconds=max(0, seconds))


class PersonalizationReadPort:
    def __init__(
        self,
        repo: PersonalizationRepository,
        aggregator: ProfileAggregator | None = None,
        observability=None,
        profile_ttl: timedelta | None = None,
    ) -> None:
        self._repo = repo
        self._aggregator = aggregator or ProfileAggregator()
        self._observability = observability
        self._profile_ttl = profile_ttl if profile_ttl is not None else _profile_ttl_from_env()

    def search_decision(self, user_id: str) -> PersonalizationDecision:
        return self._decision(user_id, include_search=True)

    def cached_search_boosts(self, user_id: str) -> dict[str, float]:
        """Search hot path: the user's bounded category boosts, or {} when personalization is off
        or there is nothing to learn from. Builds-and-persists the profile on a miss, so the FIRST
        search per user aggregates raw events once and every later search takes the fast
        get_profile path. Fail-open (BR-P13): any store/aggregation failure degrades to {}.

        QT-7 observability: every call emits exactly one applied/fallback counter —
        ``personalization.applied`` when non-empty boosts are served to the search path, else
        ``personalization.fallback`` with a ``reason`` dimension (disabled/no_profile/degraded)
        — so ops can watch the personalized-vs-baseline split without a log dive.
        # ponytail: the built profile is frozen (same as the decision path) — a scheduled refresh
        # job is the upgrade path if boosts must track evolving interest without a profile reset.
        """
        try:
            settings = self._repo.get_settings_if_exists(user_id)
            if settings is not None and not settings.enabled:
                _emit_metric(
                    self._observability, "personalization.fallback", tags={"reason": "disabled"}
                )
                return {}
            reset_at = settings.profileResetAt if settings is not None else None
            profile = self._load_or_build_profile(user_id, reset_at)
            boosts = _to_search_boosts(profile.categoryWeights) if profile else {}
            if boosts:
                _emit_metric(self._observability, "personalization.applied")
            else:
                _emit_metric(
                    self._observability, "personalization.fallback", tags={"reason": "no_profile"}
                )
            return boosts
        except Exception:
            _emit_metric(self._observability, "personalization.degraded_decision")
            _emit_metric(
                self._observability, "personalization.fallback", tags={"reason": "degraded"}
            )
            return {}

    def summary_defaults(self, user_id: str) -> PersonalizationDecision:
        return self._decision(user_id, include_search=False)

    def _decision(self, user_id: str, *, include_search: bool) -> PersonalizationDecision:
        try:
            settings = self._repo.get_settings(user_id)
            if not settings.enabled:
                return PersonalizationDecision(enabled=False, reason="disabled")
            profile = self._load_or_build_profile(user_id, settings.profileResetAt)
            if profile is None:
                return PersonalizationDecision(enabled=False, reason="no_profile")
            return PersonalizationDecision(
                enabled=True,
                searchBoosts=_to_search_boosts(profile.categoryWeights) if include_search else {},
                summaryDefaults=profile.summaryDefaults,
                translationDefaults=profile.translationDefaults,
                reason="profile_available",
            )
        except Exception:
            _emit_metric(self._observability, "personalization.degraded_decision")
            return PersonalizationDecision(enabled=False, reason="degraded")

    def _load_or_build_profile(
        self, user_id: str, profile_reset_at: datetime | None
    ) -> UserInterestProfile | None:
        """Return the persisted profile, or aggregate raw events into one and persist it. Rebuilds
        when the persisted profile is missing OR older than the refresh TTL (``_is_stale``), so
        newly category-enriched events flow into the search boost instead of a frozen snapshot
        (US-P3). Events at/before ``profile_reset_at`` are excluded (BR-P11 reset). Returns None
        when there is nothing to aggregate. Shared by the search hot path and the decision
        endpoints so both build the profile identically (BR-P7 deterministic aggregation)."""
        profile = self._repo.get_profile(user_id)
        if profile is not None and not self._is_stale(profile):
            return profile
        events = self._repo.list_events(user_id)
        if profile_reset_at is not None:
            events = [event for event in events if event.occurredAt > profile_reset_at]
        try:
            rebuilt = self._aggregator.aggregate(user_id, events)
            if rebuilt is not None:
                # aggregate() bumps updatedAt → resets the TTL clock
                self._repo.save_profile(rebuilt)
                return rebuilt
        except Exception:
            # QT-7 observability: count aggregation-pipeline failures distinctly from store
            # failures, then re-raise into the callers' fail-open catch (degraded decision /
            # empty boosts) — behavior unchanged, just no longer invisible.
            _emit_metric(self._observability, "personalization.profile_aggregation_failure")
            raise
        return profile  # nothing to aggregate → keep the existing profile (may be None)

    def _is_stale(self, profile: UserInterestProfile) -> bool:
        # ponytail: concurrent stale searches may both rebuild+save — harmless, save_profile
        # upserts and same events → same result.
        if self._profile_ttl <= timedelta(0):
            return True  # TTL 0 → always rebuild
        updated = profile.updatedAt
        if updated.tzinfo is None:  # robust to a naive round-trip; treat as UTC
            updated = updated.replace(tzinfo=UTC)
        return utc_now() - updated >= self._profile_ttl


class PersonalizationSettingsService:
    def __init__(self, repo: PersonalizationRepository, observability=None) -> None:
        self._repo = repo
        self._observability = observability

    def get(self, user_id: str) -> PersonalizationSettings:
        return self._repo.get_settings(user_id)

    def set_enabled(self, user_id: str, enabled: bool) -> PersonalizationSettings:
        _emit_metric(self._observability, "personalization.settings_updated")
        return self._repo.set_enabled(user_id, enabled)

    def delete_events(self, user_id: str) -> int:
        deleted = self._repo.delete_events(user_id)
        _emit_metric(self._observability, "personalization.raw_events_deleted", deleted)
        return deleted

    def reset_profile(self, user_id: str) -> None:
        self._repo.reset_profile(user_id)
        _emit_metric(self._observability, "personalization.profile_reset")


def purge_expired_events(
    repo: PersonalizationRepository,
    cutoff: datetime,
    observability=None,
) -> int:
    try:
        deleted = repo.purge_events_before(cutoff)
        _emit_metric(observability, "personalization.retention_purge_success", deleted)
        return deleted
    except Exception:
        _emit_metric(observability, "personalization.retention_purge_failure")
        raise
