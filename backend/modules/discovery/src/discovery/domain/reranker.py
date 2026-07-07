"""Rerank application — the PURE half of cross-encoder reranking (FR-3 quality; BR-5).

The I/O half (calling the model) is the ``RerankAdapter`` (adapters/mocks). This module holds
only deterministic, no-I/O logic: how many candidates to rerank per scope (``rerank_width``),
what text to score (``rerank_text``), and how to fold the returned scores back onto the candidate
set (``apply_rerank``) so the ranker's single ``ranking_score`` sort key does the rest.
"""

from __future__ import annotations

from collections.abc import Sequence

from docsuri_shared.vector_spec import IndexRecord

from .models import Candidate, SearchScope

# Rerank breadth M per scope: the top-M slice of the fused pool sent to the cross-encoder. Start
# conservative — cross-encoder latency is ~linear in M and LITE is the P50<3s hot path. M is tuned
# up only once a quantitative signal exists (click logs or a labeled set); phase 7 ships these
# starting values with functional + qualitative validation only. M ≥ top-N (20) by construction so
# the reranked head fully covers the displayed page; the un-reranked tail never surfaces.
RERANK_TOP_M_LITE = 30
RERANK_TOP_M_FULL = 50


def rerank_width(scope: SearchScope) -> int:
    """Candidates to rerank for the scope (FULL has latency headroom; LITE is the hot path)."""
    return RERANK_TOP_M_FULL if scope is SearchScope.FULL else RERANK_TOP_M_LITE


def rerank_text(record: IndexRecord) -> str:
    """Paper-level text the cross-encoder scores against the query: title + abstract. Stable
    across scopes — the abstract is the paper-level signal (a body chunk would bias to length)."""
    title = (record.title or "").strip()
    abstract = (record.abstract or "").strip()
    return f"{title}\n\n{abstract}".strip()


def apply_rerank(
    candidates: Sequence[Candidate], scores: Sequence[float], width: int
) -> tuple[Candidate, ...]:
    """Rerank the top-``width`` candidates and RETURN ONLY THOSE (the un-reranked tail is dropped).

    Each returned candidate carries its rerank score as ``ranking_score`` (frozen copy); the ranker
    re-sorts by that single key. The tail is discarded deliberately: rerank scores and the tail's
    RRF fusion scores are on different scales, so keeping the tail would let a tail RRF value
    outrank a low reranked score and surface an un-reranked item. Callers guarantee ``width`` ≥ the
    displayed top-N (``rerank_width`` ≥ ``TOP_N``), so dropping the tail never shrinks the page.
    ``scores`` MUST align 1:1 with ``candidates[:width]`` (adapter's input order/count)."""
    head = tuple(candidates[:width])
    if len(scores) != len(head):
        raise ValueError(f"rerank score/candidate length mismatch: {len(scores)} != {len(head)}")
    return tuple(c.with_ranking_score(float(s)) for c, s in zip(head, scores, strict=True))
