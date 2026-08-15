"""Rerank application — the PURE half of cross-encoder reranking (FR-3 quality; BR-5).

The I/O half (calling the model) is the ``RerankAdapter`` (adapters/testing). This module holds
only deterministic, no-I/O logic: how many candidates to rerank per scope (``rerank_width``),
what text to score (``rerank_text``), and how to fold the returned scores back onto the candidate
set (``apply_rerank``) so the ranker's single ``ranking_score`` sort key does the rest.
"""

from __future__ import annotations

from collections.abc import Sequence

from docsuri_shared.vector_spec import IndexRecord

from .models import Candidate, SearchScope

# Rerank breadth M per scope: the top-M slice of the fused pool sent to the cross-encoder.
#
# M is NOT just a rerank knob — ``apply_rerank`` drops the tail, so M is also the size of the
# candidate pool the ranker ever sees. Turning rerank on therefore NARROWS the pool: fusion
# delivers ~150-300 papers (two 150-wide legs, PaperId-deduped) and the old 30/50 threw most of
# them away, capping results below the depth pagination needs. These values restore that loss.
#
# They are a floor, not an optimum. The original "tune up once a quantitative signal exists"
# gate still stands for finding the BEST M — the golden set is a 6-record synthetic corpus with
# bag-of-keywords embeddings (see eval/golden_set.py), which cannot rank a 119k-paper index.
# Measured 2026-08-15 against Bedrock Cohere Rerank v3.5 (Tokyo): latency is flat in M
# (1.1-1.9s from 30 to 150 documents, 211KB payload), so the widening is essentially free on
# the P50<3s LITE path. The binding constraint is the per-account request-rate quota, not M.
RERANK_TOP_M_LITE = 100
RERANK_TOP_M_FULL = 150


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
