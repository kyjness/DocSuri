"""The U2 ↔ U6 grounding boundary, exercised with REAL types on both sides.

``docsuri_ops.grounding.GroundingEnforcementHook.enforce`` is duck-typed: it probes the candidate
for ``cards`` / ``results`` / ``items`` / ``ranked`` / ``candidates`` and each item for ``.record``
and an id. Discovery's own suite drives it through ``StubGroundingHook`` and ops' suite feeds it
dicts, so nothing else in CI puts discovery's actual ``RankedResults`` / ``Candidate`` /
``IndexRecord`` in front of the real hook. A rename on either side would then abstain every
search — "관련 논문 없음" for all queries — with every lane green. This is the only test that
would go red.
"""

from __future__ import annotations

import pytest

pytest.importorskip("discovery")
pytest.importorskip("docsuri_ops")

from discovery.domain.grounding_adapter import GroundingAdapter  # noqa: E402
from discovery.domain.models import Candidate, RankedResults  # noqa: E402
from discovery.testing.fixtures import RECORDS  # noqa: E402
from docsuri_ops.grounding import GroundingEnforcementHook  # noqa: E402


def _ranked(n: int = 3) -> RankedResults:
    ranked = tuple(
        Candidate(record=RECORDS[i], retrieval_score=1.0 / (i + 1)) for i in range(n)
    )
    return RankedResults(ranked=ranked, ranking_mode="baseline")


def test_real_hook_passes_discoverys_real_ranked_results() -> None:
    ranked = _ranked()
    gi = GroundingAdapter().to_grounding_input(ranked, plan=None)

    decision = GroundingEnforcementHook().enforce(gi.candidate_response, gi.retrieved_records)

    assert decision.verdict == "pass", decision.violations


def test_real_hook_still_blocks_a_card_that_was_not_retrieved() -> None:
    """The pass above must not be a hook that passes everything: swap in a candidate whose
    record was NOT among the retrieved ones and the same real hook has to refuse it."""
    ranked = _ranked(2)
    stranger = RankedResults(
        ranked=(*ranked.ranked, Candidate(record=RECORDS[4], retrieval_score=0.1)),
        ranking_mode="baseline",
    )
    retrieved = tuple(c.record for c in ranked.ranked)  # RECORDS[4] deliberately absent

    decision = GroundingEnforcementHook().enforce(stranger, retrieved)

    assert decision.verdict != "pass"
