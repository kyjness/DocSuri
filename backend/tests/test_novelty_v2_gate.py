"""PBT-RA1 — 저장 게이트 차단성: 무근거·필드 누락·미실재 앵커 산출물은 저장 불가.

설계 근거: business-logic-model.md §4, business-rules.md BR-RA2/RA6/RA10, BR-NV9/10/11.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from backend.modules.novelty.domain.gate import (
    GateRejectionReason,
    evaluate_artifact,
)
from backend.modules.novelty.domain.models import ArtifactKind

_KNOWN = frozenset({"rec:paper-1", "rec:paper-2", "upload:o1:j1:a1"})


def _ref(record_ref: str = "rec:paper-1") -> dict:
    return {"paperId": "2401.00001", "recordRef": record_ref}


def _gap_item(**overrides) -> dict:
    item = {
        "area": "sparse retrieval + privacy",
        "status": "partially_covered",
        "rationale": "관련 연구 2건 존재하나 결합 평가 부재",
        "source_refs": [_ref()],
    }
    item.update(overrides)
    return item


def _experiment_plan(**overrides) -> dict:
    plan = {
        "hypothesis": "속성 삭제가 검색 품질을 유지한다",
        "novelty_angle": "privacy-first sparse retrieval",
        "baselines": ["BM25"],
        "datasets": ["BEIR"],
        "metrics": ["nDCG@10"],
        "procedure": ["전처리", "학습", "평가"],
        "risks": ["데이터셋 라이선스"],
        "resources": ["A100 1대"],
        "source_refs": [_ref()],
    }
    plan.update(overrides)
    return plan


# ── PBT-RA1: 필수 필드가 하나라도 비면 게이트는 항상 거부한다 ──

_REQUIRED_PLAN_FIELDS = (
    "hypothesis",
    "novelty_angle",
    "baselines",
    "datasets",
    "metrics",
    "procedure",
    "risks",
    "resources",
    "source_refs",
)


@given(missing=st.sampled_from(_REQUIRED_PLAN_FIELDS))
def test_pbt_ra1_experiment_plan_missing_any_required_field_rejected(missing: str) -> None:
    plan = _experiment_plan()
    del plan[missing]
    rejection = evaluate_artifact(ArtifactKind.EXPERIMENT_PLAN, plan, _KNOWN)
    assert rejection is not None
    assert rejection.reason is GateRejectionReason.INVALID_SHAPE

    plan_empty = _experiment_plan(**{missing: [] if missing != "hypothesis" else ""})
    if missing != "novelty_angle":
        assert evaluate_artifact(ArtifactKind.EXPERIMENT_PLAN, plan_empty, _KNOWN) is not None


@given(record_ref=st.text(min_size=1, max_size=60).filter(lambda ref: ref not in _KNOWN))
def test_pbt_ra1_unknown_anchor_always_rejected(record_ref: str) -> None:
    payload = {"items": [_gap_item(source_refs=[_ref(record_ref)])]}
    rejection = evaluate_artifact(ArtifactKind.GAP_ANALYSIS, payload, _KNOWN)
    assert rejection is not None
    assert rejection.reason is GateRejectionReason.UNKNOWN_SOURCE_REF


def test_pbt_ra1_gap_item_without_refs_rejected() -> None:
    payload = {"items": [_gap_item(source_refs=[])]}
    rejection = evaluate_artifact(ArtifactKind.GAP_ANALYSIS, payload, _KNOWN)
    assert rejection is not None
    assert rejection.reason is GateRejectionReason.MISSING_SOURCE_REFS


def test_open_gap_requires_searched_scope_note() -> None:
    payload = {"items": [_gap_item(status="open_gap")]}
    rejection = evaluate_artifact(ArtifactKind.GAP_ANALYSIS, payload, _KNOWN)
    assert rejection is not None
    assert rejection.reason is GateRejectionReason.MISSING_SCOPE_NOTE

    ok = {
        "items": [
            _gap_item(status="open_gap", searched_scope_note="corpus_search 3회 범위 내 미발견")
        ]
    }
    assert evaluate_artifact(ArtifactKind.GAP_ANALYSIS, ok, _KNOWN) is None


def test_well_formed_artifacts_pass() -> None:
    assert evaluate_artifact(ArtifactKind.GAP_ANALYSIS, {"items": [_gap_item()]}, _KNOWN) is None
    assert evaluate_artifact(ArtifactKind.EXPERIMENT_PLAN, _experiment_plan(), _KNOWN) is None
    evidence = {"state": "ok", "claims": [{"statement": "s", "supporting": [], "conflicting": []}]}
    assert evaluate_artifact(ArtifactKind.EVIDENCE, evidence, _KNOWN) is None
    similar = {
        "items": [
            {
                "artifact_type": "paper",
                "title": "Sparse retrieval under DP",
                "evidence_status": "supported",
                "source_refs": [_ref()],
            }
        ]
    }
    assert evaluate_artifact(ArtifactKind.SIMILAR_WORKS, similar, _KNOWN) is None


def test_supported_similar_work_row_without_refs_rejected() -> None:
    similar = {
        "items": [
            {
                "artifact_type": "paper",
                "title": "row without refs",
                "evidence_status": "supported",
                "source_refs": [],
            }
        ]
    }
    rejection = evaluate_artifact(ArtifactKind.SIMILAR_WORKS, similar, _KNOWN)
    assert rejection is not None
    assert rejection.reason is GateRejectionReason.MISSING_SOURCE_REFS


def test_forbidden_claim_keys_rejected_anywhere_in_payload() -> None:
    # BR-NV10 — "새로움 확정"·score 류 주장 구조 차단(중첩 포함).
    payload = {"items": [_gap_item(related_similar_work_ids=[])], "meta": {"novelty_score": 0.9}}
    rejection = evaluate_artifact(ArtifactKind.GAP_ANALYSIS, payload, _KNOWN)
    assert rejection is not None
    assert rejection.reason is GateRejectionReason.FORBIDDEN_CLAIM


def test_empty_artifacts_rejected() -> None:
    for kind, payload in (
        (ArtifactKind.GAP_ANALYSIS, {"items": []}),
        (ArtifactKind.SIMILAR_WORKS, {"items": []}),
        (ArtifactKind.NOVELTY_CANDIDATES, {"items": []}),
        (ArtifactKind.EXTERNAL_FINDINGS, {"items": []}),
    ):
        rejection = evaluate_artifact(kind, payload, _KNOWN)
        assert rejection is not None, kind
        assert rejection.reason is GateRejectionReason.EMPTY_ARTIFACT


def test_candidate_without_supporting_refs_rejected() -> None:
    payload = {
        "items": [
            {
                "angle": "privacy-first retrieval",
                "rationale": "기존 한계 보완",
                "supporting_refs": [],
                "excluded_claims": "새로움 확정·score·논문화 판정 불포함",
            }
        ]
    }
    rejection = evaluate_artifact(ArtifactKind.NOVELTY_CANDIDATES, payload, _KNOWN)
    assert rejection is not None
    assert rejection.reason is GateRejectionReason.MISSING_SOURCE_REFS
