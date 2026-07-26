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


def test_misnamed_items_key_is_a_shape_error_not_an_empty_artifact() -> None:
    """컨테이너 키를 틀리면 "비어 있다"가 아니라 "형태가 틀렸다"로 돌려줘야 한다.

    로컬 실스택에서 실제로 겪은 실패다: 모델이 similar_works에 {"works": [...]}를
    보냈고 게이트는 payload["items"]만 읽어 empty_artifact로 거부했다. 그 사유는
    데이터가 비었다고 말할 뿐 키가 틀렸다는 사실을 알려주지 않아, 모델이 같은 구조로
    19회 재시도하다 예산을 소진했다 — 필수 세트가 영영 완성되지 않았다.
    """
    payload = {
        "works": [
            {
                "artifact_type": "paper",
                "title": "CoinPress",
                "source_refs": [_ref()],
                "evidence_status": "supported",
            }
        ]
    }
    rejection = evaluate_artifact(ArtifactKind.SIMILAR_WORKS, payload, _KNOWN)
    assert rejection is not None
    assert rejection.reason is GateRejectionReason.INVALID_SHAPE
    # 사유가 무엇을 고쳐야 하는지 담아야 한다 — 그래야 다음 시도가 달라진다.
    assert "items" in rejection.detail and "works" in rejection.detail


def test_misnamed_items_reason_names_every_array_key_it_found() -> None:
    """미리 정해둔 이름 목록에 기대지 않는다 — 실제로 쓴 키를 그대로 돌려줘야
    처음 보는 오답(`papers`·`tables`…)에도 같은 수리 정보가 나간다."""
    payload = {"papers": [{"title": "A"}], "notes": ["b"]}
    rejection = evaluate_artifact(ArtifactKind.SIMILAR_WORKS, payload, _KNOWN)
    assert rejection is not None
    assert rejection.reason is GateRejectionReason.INVALID_SHAPE
    assert "papers" in rejection.detail and "notes" in rejection.detail


def test_genuinely_empty_items_still_reports_empty_artifact() -> None:
    """키가 맞고 정말로 비었으면 여전히 empty_artifact다 — 형태 오류와 구분된다."""
    rejection = evaluate_artifact(ArtifactKind.SIMILAR_WORKS, {"items": []}, _KNOWN)
    assert rejection is not None
    assert rejection.reason is GateRejectionReason.EMPTY_ARTIFACT


def test_save_artifact_spec_documents_every_supported_kind() -> None:
    """툴 스펙이 kind별 payload 형태를 알려줘야 모델이 키를 추측하지 않는다.

    스펙에 형태가 없으면 모델은 컨테이너 키를 지어내고, 게이트는 그걸 거부한다.
    새 ArtifactKind를 추가하면서 스펙을 빠뜨리면 같은 함정이 다시 생기므로,
    지원 kind 집합과 스펙 문서화 집합이 어긋나지 않게 못 박는다.
    """
    from backend.modules.novelty.domain.agent_step import (
        SAVE_ARTIFACT_PAYLOAD_SHAPES,
        SAVE_ARTIFACT_SPEC,
    )

    assert set(SAVE_ARTIFACT_PAYLOAD_SHAPES) == {kind.value for kind in ArtifactKind}
    assert SAVE_ARTIFACT_SPEC.parameters["properties"]["kind"]["enum"] == sorted(
        kind.value for kind in ArtifactKind
    )
    # 목록형 산출물은 "items"를 쓰라는 지시가 설명에 있어야 한다.
    assert '"items"' in SAVE_ARTIFACT_SPEC.description


def test_payload_shapes_name_every_required_field_of_the_model() -> None:
    """형태 설명은 게이트가 검증하는 모델에서 갈라져 나오면 안 된다.

    설명은 산문이라 모델 필드가 바뀌어도 조용히 남는다. 모델이 설명대로 보냈는데
    필수 필드가 빠져 거부되면, 사유를 읽고 고칠 방법이 없다 — 이 브랜치가 없애려던
    상태 그대로다(실제로 evidence의 abstain_reason, experiment_plan의 비어 있지 않은
    배열 조건이 빠져 있었다). 필수 필드 이름이 설명에 전부 등장하는지 못 박는다.
    """
    from backend.modules.novelty.domain import models
    from backend.modules.novelty.domain.agent_step import SAVE_ARTIFACT_PAYLOAD_SHAPES

    # kind → 게이트가 payload(또는 items 원소)를 검증할 때 쓰는 모델.
    models_by_kind = {
        ArtifactKind.EVIDENCE: models.EvidenceSnapshot,
        ArtifactKind.SIMILAR_WORKS: models.SimilarWorkItem,
        ArtifactKind.GAP_ANALYSIS: models.GapItem,
        ArtifactKind.EXTERNAL_FINDINGS: models.ExternalFinding,
        ArtifactKind.NOVELTY_CANDIDATES: models.NoveltyCandidate,
        ArtifactKind.EXPERIMENT_PLAN: models.ExperimentPlan,
    }
    assert set(models_by_kind) == set(ArtifactKind)  # kind가 늘면 여기도 늘어야 한다

    for kind, model in models_by_kind.items():
        shape = SAVE_ARTIFACT_PAYLOAD_SHAPES[kind.value]
        required = [
            name for name, field in model.model_fields.items() if field.is_required()
        ]
        missing = [name for name in required if name not in shape]
        assert not missing, f"{kind.value} 형태 설명에 필수 필드 누락: {missing}"
