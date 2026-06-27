from __future__ import annotations

from docsuri_shared.vector_spec import IndexRecord
from hypothesis import given
from hypothesis import strategies as st

from docsuri_ops.detectors import HallucinationDetector
from docsuri_ops.domain.enums import IncidentClass, Severity
from docsuri_ops.grounding import GroundingEnforcementHook


def make_record(arxiv_id: str) -> IndexRecord:
    return IndexRecord(
        chunkId=f"{arxiv_id}:0",
        paperId=arxiv_id,
        version=1,
        vector=[0.0] * 1024,
        section="abstract",
        lexicalTerms="graph neural retrieval",
        blockRefs=[],
        title=f"Paper {arxiv_id}",
        authors=["Ada Researcher"],
        year=2026,
        arxivId=f"{arxiv_id}v1",
        abstract="A grounded abstract.",
        abstractSnippet="A grounded abstract.",
        arxivUrl=f"https://arxiv.org/abs/{arxiv_id}v1",
        categories=["cs.AI"],
    )


def test_grounding_passes_when_exposed_card_is_retrieved() -> None:
    hook = GroundingEnforcementHook()
    record = make_record("2401.00001")

    decision = hook.enforce(
        {"cards": [{"arxivId": "2401.00001v1", "arxivUrl": "https://arxiv.org/abs/2401.00001v1"}]},
        [record],
    )

    assert decision.verdict == "pass"
    assert decision.violations == ()


def test_grounding_normalizes_arxiv_identifier_case_and_version() -> None:
    hook = GroundingEnforcementHook()

    decision = hook.enforce(
        {"cards": [{"arxivId": "2401.00001V1"}]},
        [{"arxivId": "2401.00001v2", "paperId": "2401.00001"}],
    )

    assert decision.verdict == "pass"


def test_grounding_does_not_strip_version_suffix_from_non_arxiv_ids() -> None:
    hook = GroundingEnforcementHook()

    decision = hook.enforce(
        {"cards": [{"paperId": "internal-paper-v2"}]},
        [{"paperId": "internal-paper"}],
    )

    assert decision.verdict == "block"


def test_grounding_strips_version_for_old_style_arxiv_ids() -> None:
    # Regression (PR #45 review): old-style ids (archive/NNNNNNN) must be version-normalized too.
    # Previously the version was not stripped, so the same paper at different versions falsely
    # blocked. cs.AI/0601001v2 (candidate) must match cs.AI/0601001 (retrieved).
    hook = GroundingEnforcementHook()

    decision = hook.enforce(
        {"cards": [{"arxivId": "cs.AI/0601001v2"}]},
        [{"arxivId": "cs.AI/0601001"}],
    )

    assert decision.verdict == "pass"


def test_grounding_keeps_old_style_archive_prefix_so_cross_archive_is_blocked() -> None:
    # The archive prefix is part of the id: hep-th/0601001 != astro-ph/0601001 (no collision),
    # so a fabricated cross-archive reference is still blocked (no version-strip false negative).
    hook = GroundingEnforcementHook()

    decision = hook.enforce(
        {"cards": [{"arxivId": "hep-th/0601001"}]},
        [{"arxivId": "astro-ph/0601001"}],
    )

    assert decision.verdict == "block"


def test_grounding_blocks_fabricated_arxiv_id() -> None:
    hook = GroundingEnforcementHook()

    decision = hook.enforce(
        {"cards": [{"arxivId": "9999.99999", "arxivUrl": "https://arxiv.org/abs/9999.99999"}]},
        [make_record("2401.00001")],
    )

    assert decision.verdict == "block"
    assert decision.violations[0].code == "fabricated_reference"


def test_grounding_abstains_for_out_of_corpus_query() -> None:
    hook = GroundingEnforcementHook()

    decision = hook.enforce({"answer": "No matching corpus paper."}, [])

    assert decision.verdict == "abstain"


def test_hallucination_detector_maps_block_to_class_b_incident() -> None:
    hook = GroundingEnforcementHook()
    decision = hook.enforce({"cards": [{"arxivId": "9999.99999"}]}, [make_record("2401.00001")])
    detector = HallucinationDetector()

    candidate = detector.evaluate_grounding(
        request_id="req-grounding",
        decision=decision,
        signal_id="grounding-1",
    )

    assert candidate is not None
    assert candidate.incident_class == IncidentClass.HALLUCINATION
    assert candidate.severity == Severity.CRITICAL


@given(st.lists(st.integers(min_value=0, max_value=99999), min_size=1, max_size=6, unique=True))
def test_exposed_arxiv_ids_must_be_subset_of_retrieved_ids(ids: list[int]) -> None:
    hook = GroundingEnforcementHook()
    arxiv_ids = [f"2401.{item:05d}" for item in ids]
    records = [make_record(arxiv_id) for arxiv_id in arxiv_ids]
    candidate = {"cards": [{"arxivId": arxiv_id} for arxiv_id in arxiv_ids]}

    assert hook.enforce(candidate, records).verdict == "pass"
