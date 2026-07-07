"""QT-8(#273 US-EV9) — 근거형성 품질 게이트 평가셋.

- 날조 근거 명제 0건: INV-EV-3 게이트(`_filter_hallucinated`)에 평가셋을 통째로 돌려
  생존 항목의 모든 quote가 논문 원문 verbatim임을 검증한다.
- EvidenceItem DTO 라운드트립: shared D5 계약의 직렬화 정합.

상시 커버 인용(중복 작성 대신 기존 게이트를 가리킨다):
- abstain 경로: test_evidence.py — orchestrator가 claims=[]·out_of_corpus를 abstain으로
  강제(INV-EV-2).
- NFR-P6 비동기 잡 오프로드: test_evidence_worker.py — pending 1회 처리·중복 전달 스킵·stale 거부.
- D5 소비측(U12가 abstain을 날조 없이 소비): test_novelty.py
  test_worker_treats_evidence_abstain_as_degradation_without_fabrication.
"""

from __future__ import annotations

from backend.modules.evidence.extractor import _filter_hallucinated

_PAPERS = {
    "p1": (
        "We propose OPAC, a pessimistic actor-critic algorithm that learns a latent "
        "reward model. OPAC achieves a 12.5% improvement over the baseline."
    ),
    "p2": (
        "Benchmark reuse inflates scores through test-set leakage; we quantify the "
        "effect across three retrieval-augmented generation benchmarks."
    ),
}

# (statement, supporting refs, 기대 생존 여부)
# 날조 quote·비인용 명제·trivially short quote는 전부 탈락해야 한다(QT-8 AC1).
_EVAL_SET = [
    (
        "OPAC learns a latent reward model.",
        [
            {
                "paperId": "p1",
                "recordRef": "p1#abs",
                "quote": (
                    "OPAC, a pessimistic actor-critic algorithm that learns a latent "
                    "reward model"
                ),
            }
        ],
        True,
    ),
    (
        "Benchmark reuse inflates scores.",
        [
            {
                "paperId": "p2",
                "recordRef": "p2#abs",
                "quote": "Benchmark reuse inflates scores through test-set leakage",
            }
        ],
        True,
    ),
    (
        "OPAC achieves a 47% improvement.",  # 수치 날조 — 원문은 12.5%
        [
            {
                "paperId": "p1",
                "recordRef": "p1#abs",
                "quote": "a 47% improvement over the baseline",
            }
        ],
        False,
    ),
    (
        "The method uses quantum annealing.",  # quote 없는 ref — verbatim 검증 우회 금지
        [{"paperId": "p2", "recordRef": "p2#abs"}],
        False,
    ),
    (
        "Scores.",  # 1토큰 quote — trivially 통과 금지
        [{"paperId": "p2", "recordRef": "p2#abs", "quote": "scores"}],
        False,
    ),
]


def _raw_item(statement: str, supporting: list[dict]) -> dict:
    return {"statement": statement, "supporting": supporting, "conflicting": []}


def test_qt8_grounding_eval_set_has_zero_surviving_fabrications() -> None:
    raw = [_raw_item(statement, refs) for statement, refs, _ in _EVAL_SET]

    survivors = _filter_hallucinated(raw, _PAPERS)

    expected = [statement for statement, _, keep in _EVAL_SET if keep]
    assert [item.statement for item in survivors] == expected
    # 생존 항목의 모든 quote는 해당 논문 원문에 verbatim으로 존재한다 — 날조 0건
    for item in survivors:
        for ref in item.supporting:
            assert ref.quote and ref.quote in _PAPERS[ref.paperId]


def test_qt8_evidence_result_dto_roundtrip() -> None:
    from docsuri_shared._generated.dtos.evidence_schema import (
        EvidenceAbstainResult,
        EvidenceCoverage,
        EvidenceItem,
        EvidenceResult,
        EvidenceResultModel,
        SourceRef,
    )

    ok = EvidenceResult(
        state="ok",
        claims=[
            EvidenceItem(
                statement="Benchmark reuse inflates scores.",
                supporting=[
                    SourceRef(
                        paperId="2401.01234",
                        recordRef="rec-1",
                        quote="benchmark reuse inflates scores",
                    )
                ],
                conflicting=[],
            )
        ],
        coverage=EvidenceCoverage(paperCount=1, queryUsed="rag eval"),
    )
    assert EvidenceResultModel.model_validate_json(ok.model_dump_json()).root == ok

    abstain = EvidenceAbstainResult(state="abstain", abstainReason="out_of_corpus")
    assert EvidenceResultModel.model_validate_json(abstain.model_dump_json()).root == abstain
