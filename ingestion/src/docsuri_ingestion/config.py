from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
# The window is a LENGTH ending at the batch date, not two pinned dates.
#
# 135 days is what ~3,000 papers costs at the measured ~680/month for these two categories, and
# 3,000 is what the box leaves once the ~1,500 named foundational papers are in (4 GB Lightsail
# → ~1.8 GB k-NN → ~4,500 total). Expressing it as a duration says the actual decision — "the
# most recent ~4.4 months" — instead of encoding it in two magic dates that rot the moment the
# batch slips a week.
#
# It also removes a whole failure mode: a pinned end date one day past today made arXiv OAI
# answer `badArgument: until date too late` with HTTP 200 and no records, which the harvest read
# as an empty window and reported as success. Deriving the end from the clock cannot be too late.
#
# VERIFY THE ACTUAL HARVEST COUNT AGAINST THE ~3,000 CEILING BEFORE PARSING: the rate was
# estimated from a 2025 sample and 2026 volume is higher, and overshooting does not fail loudly —
# it silently exceeds the box's k-NN budget and only surfaces as a dead search after deploy.
# Pin both bounds explicitly with DOCSURI_BACKFILL_START / _END to reproduce a past run.
CORPUS_WINDOW_DAYS = 135


def _corpus_window() -> tuple[datetime, datetime]:
    """(start, end) for the deployment slice, ending at today 00:00 UTC.

    Read once at import, which is what a snapshot-freeze corpus wants (Q7=B): the batch resolves
    the window when it starts and every stage of that run shares it.
    """
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=CORPUS_WINDOW_DAYS), end


CORPUS_START, CORPUS_END = _corpus_window()

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
