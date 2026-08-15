"""PBT-03 — RelevanceRanker order stability + top-N truncation (BR-5)."""

from __future__ import annotations

from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from discovery.domain.models import (
    Candidate,
    CandidateSet,
    DegradationSignal,
    QueryPlan,
    RankedResults,
    RetrievalMode,
)
from discovery.domain.ranker import (
    _BR_P8_BOOST_CEILING,
    TOP_N,
    RelevanceRanker,
    ShadowDiff,
    apply_boosts,
    shadow_rerank_diff,
)
from discovery.testing.fixtures import RECORDS

_ranker = RelevanceRanker()
_plan = QueryPlan(lexical_terms=(), mode=RetrievalMode.HYBRID)
_degradation = DegradationSignal(llm_enabled=True, rerank_enabled=True)
_score_lists = st.lists(
    st.floats(min_value=0, max_value=1, allow_nan=False, allow_infinity=False), max_size=40
)


def _candidates(scores: list[float]) -> CandidateSet:
    cands = tuple(
        Candidate(record=RECORDS[i % len(RECORDS)], retrieval_score=s)
        for i, s in enumerate(scores)
    )
    return CandidateSet(candidates=cands, retrieval_mode=RetrievalMode.HYBRID)


@given(_score_lists)
def test_truncates_to_top_n_and_sorted_descending(scores: list[float]) -> None:
    ranked = _ranker.rank(_candidates(scores), _plan, _degradation, TOP_N)
    assert len(ranked.ranked) <= TOP_N
    out_scores = [c.retrieval_score for c in ranked.ranked]
    assert out_scores == sorted(out_scores, reverse=True)


@given(_score_lists)
def test_order_is_stable_deterministic(scores: list[float]) -> None:
    cset = _candidates(scores)
    first = _ranker.rank(cset, _plan, _degradation, TOP_N).ranked
    second = _ranker.rank(cset, _plan, _degradation, TOP_N).ranked
    assert [c.record.chunkId for c in first] == [c.record.chunkId for c in second]


def test_fewer_than_n_returns_all() -> None:
    ranked = _ranker.rank(_candidates([0.1, 0.2]), _plan, _degradation, TOP_N)
    assert len(ranked.ranked) == 2


def _shadow_c(paper_id: str, score: float, categories: list[str]) -> Candidate:
    # shadow_rerank_diff only reads record.categories / record.paperId — stub avoids the 1024-dim
    # vector an IndexRecord requires.
    return Candidate(
        record=SimpleNamespace(paperId=paper_id, categories=list(categories)),
        retrieval_score=score,
    )


def test_shadow_rerank_diff_boosts_within_band() -> None:
    # Baseline (score desc): A .30 / B .29 / C .10 / D .05. Boost cs.AI → B*1.1=.319 > A.
    ranked = RankedResults(
        ranked=(
            _shadow_c("A", 0.30, ["cs.LG"]),
            _shadow_c("B", 0.29, ["cs.AI"]),
            _shadow_c("C", 0.10, ["cs.AI"]),
            _shadow_c("D", 0.05, ["cs.LG"]),
        )
    )
    diff = shadow_rerank_diff(ranked, {"cs.AI": 0.1}, top_fraction=1.0)
    assert diff.boosted_count == 2
    assert diff.positions_changed >= 2  # A and B swap
    assert diff.max_shift >= 1


def test_shadow_rerank_diff_is_noop_without_matching_category() -> None:
    ranked = RankedResults(
        ranked=(_shadow_c("A", 0.30, ["cs.LG"]), _shadow_c("B", 0.20, ["cs.LG"]))
    )
    assert shadow_rerank_diff(ranked, {"cs.AI": 0.1}) == ShadowDiff(0, 0, 0)


def test_apply_boosts_reorders_head_and_matches_diff() -> None:
    # US-P4 go-live: the boost is now APPLIED. Baseline A .30 / B .29 / C .10 / D .05;
    # cs.AI boost lifts B*1.1=.319 above A → live order leads with B, and the returned diff
    # agrees with the diff-only wrapper (same computation, applied vs measured).
    ranked = RankedResults(
        ranked=(
            _shadow_c("A", 0.30, ["cs.LG"]),
            _shadow_c("B", 0.29, ["cs.AI"]),
            _shadow_c("C", 0.10, ["cs.AI"]),
            _shadow_c("D", 0.05, ["cs.LG"]),
        )
    )
    boosted, diff = apply_boosts(ranked, {"cs.AI": 0.1}, top_fraction=1.0)
    assert [c.record.paperId for c in boosted.ranked] == ["B", "A", "C", "D"]
    assert diff == shadow_rerank_diff(ranked, {"cs.AI": 0.1}, top_fraction=1.0)
    assert ranked.ranked[0].record.paperId == "A"  # input is not mutated


def test_apply_boosts_lifts_a_preferred_paper_even_at_a_negative_score() -> None:
    """A boost must mean UP regardless of the score's sign.

    ``score * (1 + b)`` reads as "nudge up" only while the score is positive; on a negative one
    it pushes the preferred paper DOWN. Negative scores are reachable — ``apply_rerank`` parks
    the un-reranked tail just below the lowest rerank score, and that band crosses zero when the
    cross-encoder floors at 0.0. Baseline is A > B (−0.0010 > −0.0011) and the boost is capped at
    10% of the score's magnitude, so B gains 0.00011 — just enough to pass A. Under the old
    ``score * (1 + b)`` B would land at −0.00121, i.e. FURTHER from A: boosted and demoted.
    """
    ranked = RankedResults(
        ranked=(_shadow_c("A", -0.0010, ["cs.LG"]), _shadow_c("B", -0.0011, ["cs.AI"])),
    )

    boosted, diff = apply_boosts(ranked, {"cs.AI": _BR_P8_BOOST_CEILING}, top_fraction=1.0)

    assert [c.record.paperId for c in boosted.ranked] == ["B", "A"]
    assert diff == shadow_rerank_diff(
        ranked, {"cs.AI": _BR_P8_BOOST_CEILING}, top_fraction=1.0
    )


def test_apply_boosts_noop_returns_input_order() -> None:
    # No matching category → identity: same order, zero diff (the fail-open baseline path).
    ranked = RankedResults(
        ranked=(_shadow_c("A", 0.30, ["cs.LG"]), _shadow_c("B", 0.20, ["cs.LG"]))
    )
    boosted, diff = apply_boosts(ranked, {"cs.AI": 0.1})
    assert [c.record.paperId for c in boosted.ranked] == ["A", "B"]
    assert diff == ShadowDiff(0, 0, 0)
