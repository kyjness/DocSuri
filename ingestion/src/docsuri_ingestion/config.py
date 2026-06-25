from __future__ import annotations

from datetime import UTC, datetime

CORPUS_SLICE_CATEGORIES: tuple[str, ...] = ("cs.LG", "cs.AI", "cs.CL", "cs.CV", "stat.ML")
CORPUS_START = datetime(2021, 1, 1, tzinfo=UTC)
CORPUS_END = datetime(2026, 1, 1, tzinfo=UTC)

OPEN_ACCESS_LICENSE_ALLOWLIST: tuple[str, ...] = (
    "creativecommons.org/licenses/by/",
    "creativecommons.org/licenses/by-sa/",
    "creativecommons.org/publicdomain/zero/",
    # Relaxed beyond CC-only: arXiv's default non-exclusive distribution license. Papers are
    # publicly readable on arXiv and the app links back + shows snippets (discovery, not bulk
    # redistribution) — broadens the indexable corpus from CC-only to ~all arXiv papers.
    "arxiv.org/licenses/nonexclusive-distrib",
)

WITHDRAWAL_MARKERS: tuple[str, ...] = (
    "this paper has been withdrawn",
    "this article has been withdrawn",
    "withdrawn by the author",
    "withdrawn by authors",
    "paper withdrawn",
)
