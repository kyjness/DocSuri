from __future__ import annotations

from datetime import UTC, datetime, timedelta

# Deployment corpus slice. Narrowed twice from the five-category phase-1 slice
# ("cs.LG", "cs.AI", "cs.CL", "cs.CV", "stat.ML"): first to cs.CL + cs.AI, then to cs.CL alone.
#
# WHY SO NARROW — and why the first estimate was wrong by 13x. The box sets a hard ceiling
# (Lightsail 8 GB → ~4.5 GB k-NN → ~11,000 papers), of which ~1,500 are the named foundational
# list. The first narrowing was sized from the LOCAL development corpus's composition, which
# turned out not to be a complete harvest of its own window: it implied ~680 papers/month for
# cs.CL + cs.AI, and a live OAI harvest measured ~9,000 — 36 days returned 13,602 unique papers.
# At that rate the entire recent-paper budget is EIGHT DAYS, which is worthless to U12: inside
# eight days a novelty check finds neither prior art nor the citation chain leading to it, and
# it cannot tell "not found" from "not indexed".
#
# So the trade is breadth for depth, deliberately: one subfield covered deeply beats every
# subfield covered for a week. Breadth lost this way is visible to the user as an empty result
# and is disclosed by FR-48; density lost is not visible at all.
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
