from __future__ import annotations

import logging
from types import SimpleNamespace

from docsuri_shared._generated.dtos.docmodel_schema import DocModel
from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceAbstainResult,
    EvidenceRequest,
    EvidenceResult,
    EvidenceScope,
)

from .assembler import EvidenceComparisonAssembler
from .extractor import EvidenceExtractor, LlmUnavailable
from .models import (
    AgentRunContext,
    TurnAbstainResult,
    TurnResult,
    TurnSuccessResult,
)
from .tools import EvidenceDocModelTool, EvidencePaperSearchTool, PaperSearchUnavailable

logger = logging.getLogger(__name__)

_ABSTAIN_NO_CORPUS = 'out_of_corpus'
_ABSTAIN_INSUFFICIENT = 'insufficient_evidence'
_ABSTAIN_LLM_FAILURE = 'llm_unavailable'
_ABSTAIN_COST_DEGRADED = 'cost_degraded'


class EvidenceAgentOrchestrator:
    """Tool 자율 오케스트레이션 — Search→DocModel→Extract→Assemble."""

    def __init__(
        self,
        *,
        search_tool: EvidencePaperSearchTool,
        doc_model_tool: EvidenceDocModelTool,
        extractor: EvidenceExtractor,
        assembler: EvidenceComparisonAssembler,
        cost_guard: object | None = None,
    ) -> None:
        self._search = search_tool
        self._doc_model = doc_model_tool
        self._extractor = extractor
        self._assembler = assembler
        # NFR-C1: U6 단일 권위(cost guard) — None이면 외부 budget_signal만으로 게이트.
        self._cost_guard = cost_guard

    def _cost_gated(self) -> bool:
        if self._cost_guard is None:
            return False
        from docsuri_ops.cost_guard import is_cost_critical

        return is_cost_critical(self._cost_guard.get_budget_state())

    def run(self, ctx: AgentRunContext, request: EvidenceRequest) -> TurnResult:
        # --- 1. 비용 게이트 확인(BR-EV-7) — 외부 신호 우선, 없으면 U6 cost guard 직접 조회.
        # error가 아닌 abstain(cost_degraded): research 경로가 '[abstain] cost_degraded'로
        # 영속해 FE 라벨('일시적으로 서비스 이용량이 제한…')에 닿는다(US-EV6).
        if ctx.budget_signal.get('state', 'ok') != 'ok' or self._cost_gated():
            return TurnAbstainResult(
                outcome=EvidenceAbstainResult(
                    state='abstain',
                    abstainReason=_ABSTAIN_COST_DEGRADED,
                )
            )

        # --- 2. 논문 검색(BR-EV-2 scope 분기) ---
        scope = EvidenceScope(request.scope) if request.scope else EvidenceScope.auto
        paper_ids: list[str] = list(request.paperIds or [])

        try:
            search_result = self._search.search(
                # 멀티턴(FR-37): 이전 사용자 질문을 검색 질의에 포함해 후속 질문이 이전 근거
                # 맥락을 잇게 한다. 추출(아래)은 현재 topic에만 근거 — 검색 corpus만 확장.
                topic=_contextualize_topic(request.topic, ctx.prior_topics),
                scope=scope,
                paper_ids=paper_ids,
            )
        except PaperSearchUnavailable:
            logger.warning('paper search unavailable — abstaining')
            return TurnAbstainResult(
                outcome=EvidenceAbstainResult(
                    state='abstain',
                    abstainReason=_ABSTAIN_NO_CORPUS,
                )
            )

        # US-EV4(#268) 2차 — 본문이 동봉된 첨부(md/txt)는 corpus가 비어도 추출 대상이 된다.
        attachment_docs = [
            doc
            for doc in ctx.attachment_docs
            if doc.doc_model is not None or (doc.text and doc.text.strip())
        ]
        if not search_result.records and not attachment_docs:
            return TurnAbstainResult(
                outcome=EvidenceAbstainResult(
                    state='abstain',
                    abstainReason=_ABSTAIN_NO_CORPUS,
                )
            )

        # --- 3. DocModel 로드 ---
        doc_models: list[tuple[str, DocModel] | tuple[str, DocModel, str]] = []
        for record in search_result.records:
            paper_id = _get_paper_id(record)
            if not paper_id:
                continue
            doc_model = self._doc_model.get_doc_model(paper_id)
            if doc_model is not None:
                doc_models.append((paper_id, doc_model))

        # --- 3b. 첨부 문서를 근거 추출 대상에 포함(US-EV4 AC1) ---
        for doc in attachment_docs:
            if doc.doc_model is not None and doc.paper_id:
                doc_models.append(
                    (
                        doc.paper_id,
                        doc.doc_model,
                        doc.record_ref or doc.paper_id,
                    )
                )
            else:
                attachment_id = f'attachment:{doc.name}'
                doc_models.append(
                    (
                        attachment_id,
                        _attachment_doc_model(doc),
                        doc.record_ref or attachment_id,
                    )
                )

        if not doc_models:
            return TurnAbstainResult(
                outcome=EvidenceAbstainResult(
                    state='abstain',
                    abstainReason=_ABSTAIN_NO_CORPUS,
                )
            )

        # --- 4. LLM 추출 (INV-EV-3 날조 금지 extractor 내부 강제) ---
        try:
            items = self._extractor.extract(topic=request.topic, doc_models=doc_models)
        except LlmUnavailable:
            logger.warning('LLM unavailable during evidence extraction — fail-closed(BR-EV-12)')
            return TurnAbstainResult(
                outcome=EvidenceAbstainResult(
                    state='abstain',
                    abstainReason=_ABSTAIN_LLM_FAILURE,
                )
            )

        # INV-EV-2 — 빈 성공 금지
        if not items:
            return TurnAbstainResult(
                outcome=EvidenceAbstainResult(
                    state='abstain',
                    abstainReason=_ABSTAIN_INSUFFICIENT,
                )
            )

        # --- 5. 비교표 조립(BR-EV-5) ---
        result: EvidenceResult = self._assembler.assemble(
            items=items,
            search_result=search_result,
            paper_count=len(doc_models),
        )
        return TurnSuccessResult(outcome=result)


# 최근 몇 개 topic만·각 얼마까지 — research content(≤12000자)를 그대로 이어붙이면 검색 질의가
# 폭주하므로 상한을 둔다. ponytail: 3개·200자 고정, 필요하면 늘린다.
_MAX_PRIOR_TOPICS = 3
_PRIOR_TOPIC_CHARS = 200


def _attachment_doc_model(doc: object) -> object:
    """첨부 본문의 최소 DocModel 스탠드인(US-EV4 #268 2차).

    생성 스키마 DocModel(extra=forbid, meta.provenance 필수)을 첨부용으로 억지로
    채우는 대신, extractor·prompt가 실제로 읽는 필드(fullText / meta.title /
    sections[].title·blocks[].text)만 가진 구조 동형 객체를 만든다. PDF는 공통
    doc-model 파이프라인 경유가 후속(Q6=A) — 그때 진짜 DocModel로 대체된다.
    """
    name = getattr(doc, 'name', '') or '첨부 문서'
    text = (getattr(doc, 'text', '') or '').strip()
    block = SimpleNamespace(id='att.p1', type='paragraph', text=text)
    section = SimpleNamespace(id='att', title=name, blocks=[block], sections=[])
    meta = SimpleNamespace(title=f'첨부 문서: {name}')
    return SimpleNamespace(meta=meta, fullText=text, sections=[section])


def _contextualize_topic(topic: str, prior_topics: tuple[str, ...]) -> str:
    """멀티턴 검색 질의 = 최근 이전 topic들 + 현재 topic (PR #338 리뷰 Blocking #2/FR-37)."""
    recent = [t.strip()[:_PRIOR_TOPIC_CHARS] for t in prior_topics if t.strip()]
    recent = recent[-_MAX_PRIOR_TOPICS:]
    if not recent:
        return topic
    return ' '.join([*recent, topic])


def _get_paper_id(record: object) -> str | None:
    """IndexRecord 또는 ScoredRecord에서 arxivId 추출 (INV-EV-5: 점수 미노출)."""
    for attr in ('arxivId', 'paper_id', 'paperId', 'id'):
        val = getattr(record, attr, None)
        if val:
            return str(val)
    return None
