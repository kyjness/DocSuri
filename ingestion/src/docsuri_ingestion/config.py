from __future__ import annotations

from datetime import UTC, datetime

# Deployment corpus slice (2026-08-13). Narrowed from the five-category phase-1 slice
# ("cs.LG", "cs.AI", "cs.CL", "cs.CV", "stat.ML") to NLP/AI only, and the window moved from
# calendar 2025 to the months preceding the batch.
#
# WHY NARROWER. The box sets a hard ceiling of ~4,500 papers (Lightsail 4 GB → ~1.8 GB k-NN),
# of which ~1,500 are the named foundational list, leaving ~3,000 for the date window. Spread
# over five categories that is ~7 weeks — measured, the five together produce ~1,700 papers a
# month and cs.LG alone is 52% of them. Seven weeks is too thin for U12: a novelty check that
# cannot find prior art reports "novel", and it cannot tell that apart from "not indexed".
# Restricting to cs.CL + cs.AI (40% of the volume including cross-lists, ~680/month, measured
# on a 200-paper sample) buys ~4.4 months instead, so a subfield is covered deeply rather than
# every subfield thinly. Breadth lost this way is visible to the user and is disclosed by
# FR-48; density lost is not.
#
# Decision record: inception/requirements/
#   requirement-verification-questions-corpus-and-deployment.md
CORPUS_SLICE_CATEGORIES: tuple[str, ...] = ("cs.CL", "cs.AI")
# Set at batch time. ~4.4 months at the measured rate; verify the actual harvest count against
# the ~3,000 ceiling BEFORE parsing, since 2026 volume is higher than the 2025 sample it was
# estimated from and overshooting the ceiling silently breaks the memory budget.
CORPUS_START = datetime(2026, 4, 1, tzinfo=UTC)
CORPUS_END = datetime(2026, 9, 1, tzinfo=UTC)

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
