from __future__ import annotations

from collections import defaultdict
from datetime import datetime

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


class BehaviorEventRecorder:
    def __init__(self, repo: PersonalizationRepository, observability=None) -> None:
        self._repo = repo
        self._observability = observability

    def record(self, user_id: str, dto: BehaviorEventCreate) -> EventRecordResult:
        try:
            if not self._repo.get_settings(user_id).enabled:
                return EventRecordResult(recorded=False, reason="disabled")
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


class PersonalizationReadPort:
    def __init__(
        self,
        repo: PersonalizationRepository,
        aggregator: ProfileAggregator | None = None,
        observability=None,
    ) -> None:
        self._repo = repo
        self._aggregator = aggregator or ProfileAggregator()
        self._observability = observability

    def search_decision(self, user_id: str) -> PersonalizationDecision:
        return self._decision(user_id, include_search=True)

    def cached_search_boosts(self, user_id: str) -> dict[str, float]:
        """Search hot path: read an existing profile only; never aggregate raw events inline."""
        try:
            settings = self._repo.get_settings_if_exists(user_id)
            if settings is not None and not settings.enabled:
                return {}
            profile = self._repo.get_profile(user_id)
            return _to_search_boosts(profile.categoryWeights) if profile else {}
        except Exception:
            _emit_metric(self._observability, "personalization.degraded_decision")
            return {}

    def summary_defaults(self, user_id: str) -> PersonalizationDecision:
        return self._decision(user_id, include_search=False)

    def _decision(self, user_id: str, *, include_search: bool) -> PersonalizationDecision:
        try:
            settings = self._repo.get_settings(user_id)
            if not settings.enabled:
                return PersonalizationDecision(enabled=False, reason="disabled")
            profile = self._repo.get_profile(user_id)
            if profile is None:
                events = self._repo.list_events(user_id)
                if settings.profileResetAt is not None:
                    events = [
                        event for event in events if event.occurredAt > settings.profileResetAt
                    ]
                profile = self._aggregator.aggregate(user_id, events)
                if profile is None:
                    return PersonalizationDecision(enabled=False, reason="no_profile")
                self._repo.save_profile(profile)
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
