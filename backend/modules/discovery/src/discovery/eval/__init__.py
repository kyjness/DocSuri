"""U2 discovery relevance-quality evaluation harness (QT-2).

Closes the QA 2026-07-10 gap "QT-2 relevance quality harness does not exist": US-D3's
"Recall@10 ≥ 0.7" had no golden set and no recall runner (ranking was verified structurally
only). This package supplies both:

  * ``golden_set``  — a small, fixture-backed golden set (query → expected relevant paperIds)
    plus out-of-domain junk queries marked expect-abstain (US-D6 / F2).
  * ``recall``      — a pure, reusable ``recall_at_k`` + ``run_recall_eval`` runner. Today it
    runs against the deterministic mock retriever in CI; the SAME runner takes a real-adapter
    search callable for offline eval against the live corpus later (no code change).

This is the *search-domain* counterpart to U7's ``summarization.eval.grounding_eval``
(a different quality axis — recall vs. grounding fidelity — but the same "labeled cases →
deterministic runner → CI regression" shape).
"""

from .golden_set import (
    JUNK_CASES,
    RECALL_TARGET,
    RELEVANT_CASES,
    GoldenCase,
)
from .recall import (
    RecallCaseResult,
    RecallReport,
    recall_at_k,
    run_recall_eval,
)

__all__ = [
    "GoldenCase",
    "JUNK_CASES",
    "RECALL_TARGET",
    "RELEVANT_CASES",
    "RecallCaseResult",
    "RecallReport",
    "recall_at_k",
    "run_recall_eval",
]
