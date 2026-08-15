"""Rerank application — the PURE half of cross-encoder reranking (FR-3 quality; BR-5).

The I/O half (calling the model) is the ``RerankAdapter`` (adapters/testing). This module holds
only deterministic, no-I/O logic: how many candidates to rerank per scope (``rerank_width`` — a
breadth policy only, never a pool-depth one), what text to score (``rerank_text``), and how to
fold the returned scores back onto the candidate set (``apply_rerank``) so the ranker's single
``ranking_score`` sort key does the rest.
"""

from __future__ import annotations

from collections.abc import Sequence

from docsuri_shared.vector_spec import IndexRecord

from .models import Candidate, SearchScope

# Rerank breadth M per scope: the top-M slice of the fused pool sent to the cross-encoder.
# M is ONE policy — how many candidates are worth a cross-encoder score. It is deliberately not
# also the pool depth: ``apply_rerank`` keeps the un-reranked tail (demoted), so choosing M is a
# quality/cost decision and nothing downstream shrinks because of it.
#
# The values are a floor, not an optimum. The original "tune up once a quantitative signal
# exists" gate still stands for finding the BEST M — the golden set is a 6-record synthetic
# corpus with bag-of-keywords embeddings (see eval/golden_set.py), which cannot rank a 119k-paper
# index. Real signal (2026-08-15, eval/live_cases.py over the 119k index, all 20 cases measured
# — contaminated ones retried rather than dropped): recall@10 is IDENTICAL with rerank on and off
# (0.950 both). Rank of the first relevant paper moves more often than it doesn't, and moves the
# right way ~2:1 — chain-of-thought 5→1, GPT-3 17→12, RAG 4→2, BERT 7→5, RLHF 3→2, 한국어 정렬
# 4→2, against ViT 4→5, LoRA 1→2, U-Net 2→4. So rerank earns its place on rank; this is still
# not evidence that any particular M beats another.
#
# Latency is flat in M — measured 2026-08-15 against Bedrock Cohere Rerank v3.5 (Tokyo):
# 1.1-1.9s from 30 to 150 documents (211KB payload). COST IS NOT: Bedrock bills Cohere Rerank per
# search unit = one query × up to 100 documents, and a document over ~500 tokens is split into
# chunks that each count. So M>100 is ≥2 units on every query, and M=100 tips to 2 whenever one
# title+abstract runs long. 80/100 keeps every query inside one unit with headroom on the hot
# path; raising M is a purchase, not a free widening. The other binding constraint is the
# per-account request-rate quota, which does not depend on M at all.
RERANK_TOP_M_LITE = 80
RERANK_TOP_M_FULL = 100

# Width of the score band the un-reranked tail is compressed into, immediately below the lowest
# reranked score. Small enough that the tail never collides with the reranked range; the exact
# size carries no meaning because only the ORDER is read.
_TAIL_BAND = 1e-3


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
    """Fold rerank scores onto the top-``width``, KEEPING the un-reranked tail below them.

    Each reranked candidate carries its rerank score as ``ranking_score`` (frozen copy); the ranker
    re-sorts by that single key. ``scores`` MUST align 1:1 with ``candidates[:width]`` (the
    adapter's input order/count).

    The tail cannot keep its RRF score — rerank scores and fusion scores are on different scales,
    so a tail RRF value could outrank a low reranked score and surface an un-reranked item above a
    scored one. But dropping the tail (the earlier behaviour) made M do double duty: it silently
    became the depth of the candidate pool, so turning rerank on NARROWED the result set and any
    future page-2 would have to be sized around a rerank knob. Both concerns are satisfied by
    compressing the tail into a thin band directly beneath the lowest reranked score: it keeps its
    fused order among itself, and it can never cross into the reranked range.
    """
    head = tuple(candidates[:width])
    if len(scores) != len(head):
        raise ValueError(f"rerank score/candidate length mismatch: {len(scores)} != {len(head)}")
    if not head:
        return tuple(candidates)  # nothing was scored — leave the fused order untouched
    reranked = tuple(c.with_ranking_score(float(s)) for c, s in zip(head, scores, strict=True))
    tail = tuple(candidates[width:])
    if not tail:
        return reranked
    floor = min(float(s) for s in scores)
    step = _TAIL_BAND / len(tail)
    return reranked + tuple(
        c.with_ranking_score(floor - step * (i + 1)) for i, c in enumerate(tail)
    )
