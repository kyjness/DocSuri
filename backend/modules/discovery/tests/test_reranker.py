"""Rerank domain (pure) — width per scope, text projection, score-fold onto ranking_score.

Covers ``domain/reranker.py`` (no I/O) and the ``Candidate.ranking_score`` supply/sort split.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from discovery.domain.models import Candidate, SearchScope
from discovery.domain.ranker import TOP_N
from discovery.domain.reranker import (
    RERANK_TOP_M_FULL,
    RERANK_TOP_M_LITE,
    apply_rerank,
    rerank_text,
    rerank_width,
)
from discovery.mocks.fixtures import RECORDS


def _cand(i: int, score: float) -> Candidate:
    return Candidate(record=RECORDS[i % len(RECORDS)], retrieval_score=score)


def test_ranking_score_seeded_from_retrieval_score() -> None:
    # Supply/sort split: a plain Candidate is baseline-ordered (ranking_score == retrieval_score).
    c = _cand(0, 0.42)
    assert c.ranking_score == 0.42
    # A supply stage overwrites the sort key without touching provenance.
    c2 = c.with_ranking_score(0.99)
    assert c2.ranking_score == 0.99
    assert c2.retrieval_score == 0.42  # provenance preserved
    assert c.ranking_score == 0.42  # frozen: original unchanged


def test_rerank_width_per_scope() -> None:
    assert rerank_width(SearchScope.LITE) == RERANK_TOP_M_LITE
    assert rerank_width(SearchScope.FULL) == RERANK_TOP_M_FULL
    # Width must cover the displayed page so the reranked head never leaves a tail item on screen.
    assert RERANK_TOP_M_LITE >= TOP_N
    assert RERANK_TOP_M_FULL >= TOP_N


def test_rerank_text_is_title_and_abstract() -> None:
    record = RECORDS[0]
    txt = rerank_text(record)
    assert record.title in txt
    assert record.abstract in txt


def test_apply_rerank_returns_reranked_head_drops_tail() -> None:
    cands = tuple(_cand(i, 1.0 / (i + 1)) for i in range(5))
    out = apply_rerank(cands, [0.2, 0.9], width=2)
    # Only the reranked head is returned — the un-reranked tail (different score scale) is dropped.
    assert len(out) == 2
    assert out[0].ranking_score == 0.2
    assert out[1].ranking_score == 0.9
    # retrieval_score provenance is preserved on the head.
    assert out[0].retrieval_score == cands[0].retrieval_score
    # The dropped tail must not leak through.
    assert {c.record.chunkId for c in out} == {c.record.chunkId for c in cands[:2]}


def test_apply_rerank_length_mismatch_raises() -> None:
    cands = tuple(_cand(i, 1.0) for i in range(3))
    with pytest.raises(ValueError, match="length mismatch"):
        apply_rerank(cands, [0.5], width=2)


@given(st.lists(st.floats(min_value=0, max_value=1, allow_nan=False), min_size=1, max_size=12))
def test_apply_rerank_preserves_candidate_set(scores: list[float]) -> None:
    cands = tuple(_cand(i, 1.0 / (i + 1)) for i in range(len(scores)))
    out = apply_rerank(cands, scores, width=len(scores))
    # No candidate lost or duplicated — rerank reorders keys, never the membership.
    assert len(out) == len(cands)
    assert {c.record.chunkId for c in out} == {c.record.chunkId for c in cands}
