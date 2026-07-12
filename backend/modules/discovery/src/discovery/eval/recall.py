"""QT-2 Recall@k runner — the reusable relevance metric US-D3 ("Recall@10 ≥ 0.7") needs.

Pure and deterministic (no I/O, no LLM): it drives a ``search`` callable that returns the
ranked paperIds for a query and scores each labeled case's recall@k. The callable is the seam
— in CI it wraps the mock orchestrator (see ``tests/test_recall_golden.py``); for an offline
eval against the live corpus it wraps the real read-path adapters, unchanged. This mirrors the
summary domain's ``run_grounding_eval`` (labeled cases → deterministic runner → CI regression).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass

from .golden_set import GoldenCase

# A search callable: query text → ranked paperIds (best first). Real or mock behind the seam.
SearchFn = Callable[[str], Sequence[str]]


def recall_at_k(retrieved: Sequence[str], relevant: Collection[str], k: int) -> float:
    """Fraction of the ``relevant`` paperIds present in the top-``k`` ``retrieved`` ids.

    Recall@k = |relevant ∩ retrieved[:k]| / |relevant|. An empty ``relevant`` set has undefined
    recall — the caller (a junk/abstain case) must not grade it — so we surface that as a
    programming error rather than silently returning a misleading 1.0.
    """
    if not relevant:
        raise ValueError("recall_at_k is undefined for an empty relevant set (junk case?)")
    if k <= 0:
        return 0.0
    top_k = set(retrieved[:k])
    hits = sum(1 for pid in relevant if pid in top_k)
    return hits / len(relevant)


@dataclass(frozen=True, slots=True)
class RecallCaseResult:
    query: str
    recall: float
    retrieved: tuple[str, ...]
    relevant: frozenset[str]


@dataclass(frozen=True, slots=True)
class RecallReport:
    results: tuple[RecallCaseResult, ...]
    k: int

    @property
    def mean_recall(self) -> float:
        """Mean recall@k over the graded cases (0.0 when there are none)."""
        if not self.results:
            return 0.0
        return sum(r.recall for r in self.results) / len(self.results)

    @property
    def min_recall(self) -> float:
        """Worst single-case recall@k — the case that would sink a per-query bar."""
        if not self.results:
            return 0.0
        return min(r.recall for r in self.results)


def run_recall_eval(search: SearchFn, cases: Sequence[GoldenCase], k: int = 10) -> RecallReport:
    """Run every graded (non-abstain) case through ``search`` and score recall@k.

    Junk/abstain cases (``expect_abstain`` or empty ``relevant``) are skipped — recall is
    undefined for them; they are exercised on the abstain path, not this metric.
    """
    graded = [c for c in cases if c.relevant and not c.expect_abstain]
    results = tuple(
        RecallCaseResult(
            query=case.query,
            recall=recall_at_k(retrieved := tuple(search(case.query)), case.relevant, k),
            retrieved=retrieved,
            relevant=case.relevant,
        )
        for case in graded
    )
    return RecallReport(results=results, k=k)
