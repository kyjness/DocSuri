"""산출물 저장 게이트(BR-RA2) — save_artifact의 유일 관문, 결정론 검증(LLM-judge 금지).

검사 항목(BLM §4): SourceRef 실재성(BR-NV19 — recordRef를 공유 계약의 실재성 핸들로
사용), 산출물 종류별 필수 필드, bounded 규칙(BR-NV10/11), open_gap 탐색 범위 표기
(BR-RA10). 위반 시 기계 판독 사유를 반환하고 에이전트는 예산 내 재시도할 수 있다.
온디맨드 산출물도 같은 게이트를 통과한다(BR-RA6). 게이트를 우회하는 저장 경로를
만들지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from .models import (
    ArtifactKind,
    EvidenceSnapshot,
    ExperimentPlan,
    ExternalFinding,
    GapAnalysis,
    GapStatus,
    NoveltyCandidate,
    SimilarWorkItem,
    SourceRef,
)

__all__ = [
    "FORBIDDEN_CLAIM_KEYS",
    "GateRejection",
    "GateRejectionReason",
    "evaluate_artifact",
]


class GateRejectionReason(StrEnum):
    INVALID_SHAPE = "invalid_shape"
    EMPTY_ARTIFACT = "empty_artifact"
    MISSING_SOURCE_REFS = "missing_source_refs"
    UNKNOWN_SOURCE_REF = "unknown_source_ref"
    MISSING_SCOPE_NOTE = "missing_scope_note"
    FORBIDDEN_CLAIM = "forbidden_claim"
    UNSUPPORTED_KIND = "unsupported_kind"


@dataclass(frozen=True, slots=True)
class GateRejection:
    """저장 거부 — ToolCallRecord.outcome=rejected_by_gate로 기록되는 기계 판독 사유."""

    reason: GateRejectionReason
    detail: str


# BR-NV10 — "새로움 확정"·score·논문화 판정 금지. 구조 키 수준의 결정론 차단.
FORBIDDEN_CLAIM_KEYS = frozenset(
    {
        "novelty_score",
        "noveltyScore",
        "novelty_certainty",
        "noveltyCertainty",
        "publishability",
        "publishability_verdict",
    }
)


def evaluate_artifact(
    kind: ArtifactKind,
    payload: dict[str, Any],
    known_record_refs: frozenset[str],
) -> GateRejection | None:
    """통과 시 None, 위반 시 GateRejection. known_record_refs는 잡이 확보한
    실재 출처 핸들(recordRef) 집합 — 근거·검색 결과에서 루프가 수집한다."""
    forbidden = _find_forbidden_key(payload)
    if forbidden is not None:
        return GateRejection(
            GateRejectionReason.FORBIDDEN_CLAIM, f"forbidden claim key: {forbidden}"
        )
    try:
        if kind is ArtifactKind.EVIDENCE:
            return _check_evidence(EvidenceSnapshot.model_validate(payload))
        if kind is ArtifactKind.SIMILAR_WORKS:
            items = [SimilarWorkItem.model_validate(item) for item in _items_of(payload)]
            return _check_similar_works(items, known_record_refs)
        if kind is ArtifactKind.GAP_ANALYSIS:
            return _check_gap_analysis(GapAnalysis.model_validate(payload), known_record_refs)
        if kind is ArtifactKind.EXTERNAL_FINDINGS:
            findings = [ExternalFinding.model_validate(item) for item in _items_of(payload)]
            return _check_external_findings(findings)
        if kind is ArtifactKind.NOVELTY_CANDIDATES:
            candidates = [NoveltyCandidate.model_validate(item) for item in _items_of(payload)]
            return _check_candidates(candidates, known_record_refs)
        if kind is ArtifactKind.EXPERIMENT_PLAN:
            plan = ExperimentPlan.model_validate(payload)
            return _check_refs_known(plan.source_refs, known_record_refs)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ()))
        return GateRejection(
            GateRejectionReason.INVALID_SHAPE, f"{location}: {first.get('msg', 'invalid')}"
        )
    return GateRejection(GateRejectionReason.UNSUPPORTED_KIND, f"unsupported kind: {kind}")


def _items_of(payload: dict[str, Any]) -> list[Any]:
    items = payload.get("items")
    return items if isinstance(items, list) else []


def _find_forbidden_key(node: Any) -> str | None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in FORBIDDEN_CLAIM_KEYS:
                return key
            nested = _find_forbidden_key(value)
            if nested is not None:
                return nested
    elif isinstance(node, list):
        for item in node:
            nested = _find_forbidden_key(item)
            if nested is not None:
                return nested
    return None


def _check_refs_known(
    refs: Iterable[SourceRef], known_record_refs: frozenset[str]
) -> GateRejection | None:
    for ref in refs:
        if ref.recordRef not in known_record_refs:
            return GateRejection(
                GateRejectionReason.UNKNOWN_SOURCE_REF,
                f"recordRef not in job evidence set: {ref.recordRef[:120]}",
            )
    return None


def _check_evidence(snapshot: EvidenceSnapshot) -> GateRejection | None:
    if snapshot.state == "ok" and not snapshot.claims:
        return GateRejection(GateRejectionReason.EMPTY_ARTIFACT, "ok evidence without claims")
    if snapshot.state == "abstain" and not snapshot.abstain_reason:
        return GateRejection(
            GateRejectionReason.INVALID_SHAPE, "abstain evidence without abstain_reason"
        )
    return None


def _check_similar_works(
    items: list[SimilarWorkItem], known_record_refs: frozenset[str]
) -> GateRejection | None:
    if not items:
        return GateRejection(GateRejectionReason.EMPTY_ARTIFACT, "similar works table is empty")
    for item in items:
        # BR-NV9 — supported 행은 근거 없이 저장 불가.
        if item.evidence_status.value == "supported" and not item.source_refs:
            return GateRejection(
                GateRejectionReason.MISSING_SOURCE_REFS,
                f"supported row without source_refs: {item.title[:80]}",
            )
        rejection = _check_refs_known(item.source_refs, known_record_refs)
        if rejection is not None:
            return rejection
    return None


def _check_gap_analysis(
    analysis: GapAnalysis, known_record_refs: frozenset[str]
) -> GateRejection | None:
    if not analysis.items:
        return GateRejection(GateRejectionReason.EMPTY_ARTIFACT, "gap analysis is empty")
    for item in analysis.items:
        # BR-RA10 — 모든 판정 항목에 source_refs 필수.
        if not item.source_refs:
            return GateRejection(
                GateRejectionReason.MISSING_SOURCE_REFS,
                f"gap item without source_refs: {item.area[:80]}",
            )
        rejection = _check_refs_known(item.source_refs, known_record_refs)
        if rejection is not None:
            return rejection
        if item.status is GapStatus.OPEN_GAP and not (item.searched_scope_note or "").strip():
            return GateRejection(
                GateRejectionReason.MISSING_SCOPE_NOTE,
                f"open_gap without searched_scope_note: {item.area[:80]}",
            )
    return None


def _check_external_findings(findings: list[ExternalFinding]) -> GateRejection | None:
    if not findings:
        return GateRejection(GateRejectionReason.EMPTY_ARTIFACT, "external findings empty")
    return None


def _check_candidates(
    candidates: list[NoveltyCandidate], known_record_refs: frozenset[str]
) -> GateRejection | None:
    if not candidates:
        return GateRejection(GateRejectionReason.EMPTY_ARTIFACT, "candidates empty")
    for candidate in candidates:
        # BR-NV11 — supporting_refs 필수(근거 없는 방향 제안 금지).
        if not candidate.supporting_refs:
            return GateRejection(
                GateRejectionReason.MISSING_SOURCE_REFS,
                f"candidate without supporting_refs: {candidate.angle[:80]}",
            )
        rejection = _check_refs_known(candidate.supporting_refs, known_record_refs)
        if rejection is not None:
            return rejection
    return None
