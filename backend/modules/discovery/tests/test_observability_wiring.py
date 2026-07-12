"""US-R4: discovery app metrics must reach the injected ObservabilityHub (not the void).

These pin the wiring seam fixed for US-R4 — the factory ``observability`` arg flows into the
orchestrator's ``emit_metric`` calls. ``RecordingHub`` duck-types ``docsuri_shared.ports``.
"""

from __future__ import annotations

from docsuri_shared.dtos import SearchRequest

from discovery.api import run_search
from discovery.domain.models import AuthSession, RequestContext
from discovery.mocks import build_mock_orchestrator


class RecordingHub:
    """Minimal ObservabilityHub that records emitted metrics (verifies the wiring seam)."""

    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict]] = []

    def emit_metric(self, name, value, tags) -> None:
        self.metrics.append((name, value, dict(tags)))

    def emit_log(self, entry) -> None: ...
    def start_span(self, name, context):
        return None

    def audit_append(self, event) -> None: ...


def _ctx() -> RequestContext:
    return RequestContext(auth_session=AuthSession(user_id="u1"), request_id="req-1")


def _run(hub: RecordingHub) -> None:
    bundle = build_mock_orchestrator(observability=hub)
    run_search(
        bundle.orchestrator,
        bundle.grounding_hook,
        SearchRequest(query="diffusion protein structure"),
        _ctx(),
    )


def test_injected_hub_receives_search_candidates_metric() -> None:
    """Wiring seam: the factory's observability arg reaches the orchestrator's emit."""
    hub = RecordingHub()
    _run(hub)
    assert "discovery.search.candidates" in [m[0] for m in hub.metrics]


def test_rerank_shadow_metrics_include_movement_size() -> None:
    hub = RecordingHub()
    bundle = build_mock_orchestrator(observability=hub)
    bundle.orchestrator._search_boosts = lambda _user_id: {"cs.AI": 0.1}
    run_search(
        bundle.orchestrator,
        bundle.grounding_hook,
        SearchRequest(query="diffusion protein structure"),
        _ctx(),
    )

    names = {name for name, _value, _tags in hub.metrics}
    assert "personalization.rerank_shadow" in names
    assert "personalization.rerank_shadow.max_shift" in names
    assert "personalization.rerank_shadow.boosted_count" in names


def _ranked_two_flippable():
    # A .30 (cs.LG) / B .29 (cs.AI): a cs.AI boost lifts B*1.1=.319 above A. Stub records —
    # _apply_search_boosts only reads categories / paperId / ranking_score (cf. test_ranker_pbt).
    from types import SimpleNamespace

    from discovery.domain.models import Candidate, RankedResults

    def _c(pid: str, score: float, cats: list[str]) -> Candidate:
        return Candidate(
            record=SimpleNamespace(paperId=pid, categories=list(cats)), retrieval_score=score
        )

    return RankedResults(ranked=(_c("A", 0.30, ["cs.LG"]), _c("B", 0.29, ["cs.AI"])))


def test_rerank_live_flag_gates_applied_order() -> None:
    # #345 go-live gate: SHADOW (default) emits metrics but returns the BASELINE order; LIVE
    # returns the reordered order. The metric emits in BOTH modes (real shadow data pre-flip).
    hub = RecordingHub()
    bundle = build_mock_orchestrator(observability=hub)
    bundle.orchestrator._search_boosts = lambda _uid: {"cs.AI": 0.1}
    ranked = _ranked_two_flippable()

    shadow_out = bundle.orchestrator._apply_search_boosts("u1", ranked)
    assert [c.record.paperId for c in shadow_out.ranked] == ["A", "B"]  # order unchanged
    assert "personalization.rerank_shadow" in {m[0] for m in hub.metrics}  # but measured

    bundle.orchestrator._rerank_live = True
    live_out = bundle.orchestrator._apply_search_boosts("u1", ranked)
    assert [c.record.paperId for c in live_out.ranked] == ["B", "A"]  # boosted → reordered


def test_apply_boosts_failure_emits_signal_and_keeps_baseline(monkeypatch) -> None:
    # apply_boosts is pure compute — a raise there is a code bug, not "no boosts". It must degrade
    # to the baseline order AND leave a distinct metric, else the feature silently dies into quiet
    # movement metrics (the exact no-op class #345 fixed). Guarded: the metric never sinks search.
    from discovery.service import orchestrator as orch

    hub = RecordingHub()
    bundle = build_mock_orchestrator(observability=hub)
    bundle.orchestrator._search_boosts = lambda _uid: {"cs.AI": 0.1}
    monkeypatch.setattr(orch, "apply_boosts", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError))
    ranked = _ranked_two_flippable()

    out = bundle.orchestrator._apply_search_boosts("u1", ranked)

    assert [c.record.paperId for c in out.ranked] == ["A", "B"]  # baseline, search never blocked
    assert "personalization.rerank_shadow.apply_failed" in {m[0] for m in hub.metrics}


def test_injected_hub_receives_grounding_health_metric() -> None:
    """US-R4 grounding-health signal (hallucination incident class), emitted on finalize.

    RED until SearchOrchestrationService._emit_grounding_health is implemented. The verdict
    ("pass" here) must be recoverable from the metric name OR a tag value so a CloudWatch
    alarm can route the block/abstain rate to the IR process.
    """
    hub = RecordingHub()
    _run(hub)
    grounding = [m for m in hub.metrics if "grounding" in m[0]]
    assert grounding, "finalize must emit a grounding-health metric carrying the verdict"
    name, _value, tags = grounding[0]
    assert "pass" in name or "pass" in tags.values()


def test_no_match_does_not_emit_grounding_health() -> None:
    """A no-match is an empty page, NOT a grounding abstain (BR-9 / U5 B3-a), so it must NOT
    emit a grounding-health metric — that signal tracks real enforce verdicts only, and a
    zero-result query must not inflate the hallucination/abstain rate. Zero-result visibility
    comes from the SearchExecuted event (resultCount=0) instead. (US-R4)"""
    hub = RecordingHub()
    bundle = build_mock_orchestrator(observability=hub)
    run_search(
        bundle.orchestrator,
        bundle.grounding_hook,
        SearchRequest(query="zzz nonsense token"),
        _ctx(),
    )
    grounding = [m for m in hub.metrics if "grounding" in m[0]]
    assert grounding == [], "no-match must not emit a grounding-health metric"
