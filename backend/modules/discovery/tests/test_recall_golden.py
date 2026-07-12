"""QT-2 relevance quality harness — closes the QA 2026-07-10 gap that US-D3's "Recall@10 ≥ 0.7"
had no golden set and no recall runner (ranking was verified structurally only).

Three things are pinned here against the deterministic fixture-backed retriever:

  1. the pure ``recall_at_k`` math (synthetic inputs, no pipeline);
  2. Recall@10 ≥ 0.7 on the in-domain golden set, run through the real ``run_search`` seam
     (``discovery.eval.run_recall_eval`` + the mock orchestrator);
  3. the out-of-domain junk queries reach the no-match empty page — with the US-D6 relevance
     floor doing the work for near-noise neighbors (reusing the ``_search_with_floor`` technique
     from ``test_no_match_floor.py``).

The corpus/embedding are coarse stand-ins (fixtures.py), so the Recall@10 number here proves
the harness wiring; the SAME runner grades the live corpus offline when pointed at real adapters.
"""

from __future__ import annotations

import re

from docsuri_shared.dtos import SearchRequest, SearchResultPageDTO

from discovery.api import run_search
from discovery.domain.models import AuthSession, RequestContext
from discovery.eval import (
    JUNK_CASES,
    RECALL_TARGET,
    RELEVANT_CASES,
    recall_at_k,
    run_recall_eval,
)
from discovery.mocks import build_mock_orchestrator

_ARXIV_VERSION = re.compile(r"v\d+$")


def _ctx() -> RequestContext:
    return RequestContext(auth_session=AuthSession(user_id="u1"), request_id="req-1")


def _paper_id(arxiv_id: str) -> str:
    """Card display id (paperId + version, e.g. '2401.00001v1') → bare paperId."""
    return _ARXIV_VERSION.sub("", arxiv_id)


def _make_search(floor: float = 0.0):
    """A ``SearchFn`` for the runner: query → ranked paperIds through the mock ``run_search`` seam.

    A fresh bundle per query keeps events/state isolated; ``floor`` sets the US-D6 relevance
    floor (0 = off). Non-page terminals (abstain / empty) yield an empty id list.
    """

    def search(query: str) -> list[str]:
        bundle = build_mock_orchestrator()
        bundle.orchestrator._no_match_knn_floor = floor
        resp = run_search(
            bundle.orchestrator, bundle.grounding_hook, SearchRequest(query=query), _ctx()
        )
        if not isinstance(resp.root, SearchResultPageDTO):
            return []
        return [_paper_id(card.arxivId) for card in resp.root.cards]

    return search


def _run_one(query: str, floor: float):
    bundle = build_mock_orchestrator()
    bundle.orchestrator._no_match_knn_floor = floor
    resp = run_search(
        bundle.orchestrator, bundle.grounding_hook, SearchRequest(query=query), _ctx()
    )
    return resp, bundle


# --- 1. pure recall math --------------------------------------------------------------------


def test_recall_at_k_full_and_partial() -> None:
    assert recall_at_k(["a", "b", "c"], {"a", "b"}, 10) == 1.0
    # only the top-1 slice counts: one of two relevant present → 0.5
    assert recall_at_k(["a", "x", "b"], {"a", "b"}, 1) == 0.5
    assert recall_at_k(["x", "y"], {"a"}, 10) == 0.0


def test_recall_at_k_rejects_empty_relevant() -> None:
    # A junk/abstain case has no relevant set; grading it is a caller bug, not a silent 1.0.
    try:
        recall_at_k(["a"], set(), 10)
    except ValueError:
        pass
    else:  # pragma: no cover - the assertion below fails the test if no raise happened
        raise AssertionError("expected ValueError for empty relevant set")


# --- 2. Recall@10 on the in-domain golden set -----------------------------------------------


def test_recall_at_10_meets_target() -> None:
    report = run_recall_eval(_make_search(), RELEVANT_CASES, k=10)
    assert report.results, "golden set graded no cases"
    # US-D3 acceptance bar. The mock recalls every relevant paper, so this is comfortably met;
    # the assertion is the portable contract carried to the real-adapter offline run.
    assert report.mean_recall >= RECALL_TARGET
    assert report.min_recall >= RECALL_TARGET  # no single golden query falls under the bar


def test_recall_covers_cross_lingual_cases() -> None:
    # Korean queries recall the English papers only because the embedding leg (not BM25) matches.
    report = run_recall_eval(_make_search(), RELEVANT_CASES, k=10)
    korean = [r for r in report.results if any("가" <= ch <= "힣" for ch in r.query)]
    assert korean, "expected Korean cross-lingual cases in the golden set"
    assert all(r.recall == 1.0 for r in korean)


# --- 3. junk queries must abstain (US-D6 / F2) ----------------------------------------------


def test_zero_signal_junk_is_empty_even_without_floor() -> None:
    # No corpus keyword overlap → no candidates → empty page (floor OFF). paperIds = [].
    zero_signal = JUNK_CASES[0]
    resp, bundle = _run_one(zero_signal.query, floor=0.0)
    assert isinstance(resp.root, SearchResultPageDTO)
    assert resp.root.cards == []
    assert resp.root.meta.resultCount == 0
    assert bundle.event_publisher.events[0].resultCount == 0


def test_near_noise_junk_needs_the_floor_to_abstain() -> None:
    # near-noise: a single tangential keyword gives a low positive k-NN score, so WITHOUT the
    # floor k-NN falsely surfaces cards (the US-D6 problem)...
    near_noise = JUNK_CASES[1]
    resp_off, _ = _run_one(near_noise.query, floor=0.0)
    assert isinstance(resp_off.root, SearchResultPageDTO)
    assert resp_off.root.cards  # falsely non-empty when the floor is off

    # ...and WITH a floor above the near-noise score it reaches the no-match empty page (US-D6).
    resp_on, bundle = _run_one(near_noise.query, floor=1.5)
    assert isinstance(resp_on.root, SearchResultPageDTO)
    assert resp_on.root.cards == []
    assert resp_on.root.meta.resultCount == 0
    assert bundle.event_publisher.events[0].resultCount == 0


def test_floor_that_abstains_junk_keeps_the_real_query() -> None:
    # The same floor (1.5) that abstains the near-noise junk (best k-NN ≈ 1) must NOT abstain a
    # genuine in-domain query (best k-NN ≈ 3) — the floor separates real from noise.
    resp, _ = _run_one("diffusion models for protein structure prediction", floor=1.5)
    assert isinstance(resp.root, SearchResultPageDTO)
    assert resp.root.cards
