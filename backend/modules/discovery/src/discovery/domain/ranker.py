"""RelevanceRanker — FR-3 / Q3=A, Q10=A (BR-5; PBT-03).

Single-responsibility sort stage: order by ``ranking_score`` descending, truncate to top-N=20.
The ranker reads ONLY ``ranking_score`` — it does not know or care which stage supplied it
(retrieval seeds ``ranking_score = retrieval_score``; a cross-encoder reranker overwrites it
upstream in the orchestrator). With no reranker (or the cost-degrade RERANK_OFF tier, surfaced
as a banner in the assembler), ``ranking_score`` still equals the RRF score → identical baseline
order. Deterministic stable order with a PaperId tie-break (PBT-03). If fewer than N candidates,
return all (no padding, US-D3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import CandidateSet, QueryPlan, RankedResults

TOP_N = 20  # FR-3 (Q10=A)

# BR-P8: personalization may only nudge the top slice, never reshuffle the tail.
_BR_P8_BOOST_CEILING = 0.1
_BOOST_TOP_FRACTION = 0.30


@dataclass(frozen=True, slots=True)
class ShadowDiff:
    """How much a bounded personalization re-rank moves the top band vs the baseline order.

    Named for its US-P4 shadow origin; now (US-P4 go-live) it measures REAL movement that was
    applied, not hypothetical. Same fields, so existing CloudWatch dashboards are unaffected.
    """

    positions_changed: int
    max_shift: int
    boosted_count: int


def _record_boost(record, boosts: dict[str, float]) -> float:
    for cat in getattr(record, "categories", None) or []:
        key = str(getattr(cat, "root", cat))  # ArxivCategory is RootModel[str]
        if key in boosts:
            return max(-_BR_P8_BOOST_CEILING, min(_BR_P8_BOOST_CEILING, boosts[key]))
    return 0.0


def apply_boosts(
    ranked: RankedResults,
    boosts: dict[str, float],
    top_fraction: float = _BOOST_TOP_FRACTION,
) -> tuple[RankedResults, ShadowDiff]:
    """Bounded category re-rank over the top ``top_fraction`` of results (BR-P8): multiplicative
    and relative to each candidate's own ``ranking_score``, so a boost NUDGES rank within the top
    band without flipping the overall order or touching the tail. Returns the reordered results
    plus a diff against the baseline order. Pure: no I/O, no mutation of the input.
    """
    items = list(ranked.ranked)
    n = len(items)
    if n < 2 or not boosts:
        return ranked, ShadowDiff(0, 0, 0)
    band = min(n, max(2, math.ceil(n * top_fraction)))
    head = items[:band]  # already (-ranking_score, paperId) order from the ranker
    boosted_count = sum(1 for c in head if _record_boost(c.record, boosts) != 0.0)
    if boosted_count == 0:
        return ranked, ShadowDiff(0, 0, 0)
    # Nudge the CURRENT sort key (ranking_score) — post-rerank this is the rerank score, so
    # personalization correctly nudges the reranked order, not the raw retrieval order.
    reordered = sorted(
        head,
        key=lambda c: (
            -(c.ranking_score * (1.0 + _record_boost(c.record, boosts))),
            c.record.paperId,
        ),
    )
    baseline_ids = [c.record.paperId for c in head]
    new_pos = {c.record.paperId: i for i, c in enumerate(reordered)}
    positions_changed = sum(1 for i, pid in enumerate(baseline_ids) if new_pos[pid] != i)
    max_shift = max((abs(new_pos[pid] - i) for i, pid in enumerate(baseline_ids)), default=0)
    boosted = RankedResults(
        ranked=tuple(reordered) + tuple(items[band:]),  # only the top band moves (BR-P8)
        ranking_mode=ranked.ranking_mode,
    )
    return boosted, ShadowDiff(positions_changed, max_shift, boosted_count)


def shadow_rerank_diff(
    ranked: RankedResults,
    boosts: dict[str, float],
    top_fraction: float = _BOOST_TOP_FRACTION,
) -> ShadowDiff:
    """Diff-only view of :func:`apply_boosts` — measures the movement WITHOUT applying it. Kept
    for the shadow PBT and any measure-only caller."""
    return apply_boosts(ranked, boosts, top_fraction)[1]


class RelevanceRanker:
    def rank(
        self,
        candidate_set: CandidateSet,
        plan: QueryPlan,  # noqa: ARG002 — reserved (filter hints); baseline ignores
        degradation,  # noqa: ARG002 — RERANK_OFF is a no-op for the baseline ranker
        top_n: int = TOP_N,
    ) -> RankedResults:
        ranked = sorted(
            candidate_set.candidates,
            key=lambda c: (-c.ranking_score, c.record.paperId),
        )[:top_n]
        return RankedResults(ranked=tuple(ranked), ranking_mode="baseline")
