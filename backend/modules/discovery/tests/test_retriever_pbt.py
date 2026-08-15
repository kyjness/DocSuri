"""PBT-07 — hybrid dedup idempotent (PaperId) + resultset preservation (BR-4)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from discovery.domain.retriever import _reciprocal_rank_fusion
from discovery.testing.fixtures import RECORDS

_record_strategy = st.lists(st.sampled_from(RECORDS), max_size=20)


@given(_record_strategy)
def test_dedup_unique_paper_ids_and_preserves_set(sample) -> None:
    list1 = [(r, 1.0) for r in sample]
    fused = _reciprocal_rank_fusion([list1])
    out_pids = [c.record.paperId for c in fused]
    # dedup: no PaperId appears twice (even though papers have multiple chunks)
    assert len(out_pids) == len(set(out_pids))
    # resultset preservation: every input PaperId is present exactly once
    assert set(out_pids) == {r.paperId for r in sample}


@given(_record_strategy, _record_strategy)
def test_two_lists_merge_preserves_union(list_a, list_b) -> None:
    fused = _reciprocal_rank_fusion([[(r, 1.0) for r in list_a], [(r, 1.0) for r in list_b]])
    out_pids = {c.record.paperId for c in fused}
    assert out_pids == {r.paperId for r in list_a} | {r.paperId for r in list_b}


@given(_record_strategy)
def test_fusion_is_deterministic(sample) -> None:
    lst = [(r, 1.0) for r in sample]
    first = [c.record.paperId for c in _reciprocal_rank_fusion([lst])]
    second = [c.record.paperId for c in _reciprocal_rank_fusion([lst])]
    assert first == second
