# DO NOT EDIT. Generated from the JSON Schema SSOT in shared/ by tools/generate.py.
# Change the schema and regenerate (§5-B); never hand-edit.

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, RootModel
from typing import Any, Literal


class EvidenceScope(StrEnum):
    """
    근거 모을 논문 집합 범위(Q4=A 혼합). auto: 질의 주도 자동 검색. explicit: 사용자 명시 paper 집합만. mixed: 자동 검색 + 명시 집합 병합.
    """

    auto = 'auto'
    explicit = 'explicit'
    mixed = 'mixed'


class AnchorType(StrEnum):
    """
    anchor가 가리키는 DocModel 블록의 종류(선택, FR-47 v2). 소비자(U12·FE)가 DocModel을 다시 읽지 않고 분기하기 위한 것 — FE는 이 값으로 인용 칩 라벨(표 3·그림 2·식 4)을 고른다. anchor가 없으면(예: sourceScope=abstract) 생략한다. Trace: FR-47.
    """

    paragraph = 'paragraph'
    list = 'list'
    code = 'code'
    table = 'table'
    figure = 'figure'
    formula = 'formula'


class SourceScope(StrEnum):
    """
    근거 범위 등급(선택, FR-31/FR-47 v2). fulltext = DocModel 확보 논문의 원문 verbatim 인용(앵커 보유). abstract = 본문을 확보하지 못해 초록 범위에서 인용(앵커 없음, 코퍼스 밖 논문의 폴백). figure = 그림 해석 기반(인용문이 아니라 해석 — 주장의 수치는 논문 텍스트에 실재해야 하고, 정성 서술은 이 표시로 검증 강도 차이를 드러낸다). 범위는 결과 단위가 아니라 출처 단위다 — 한 응답에 세 종류가 섞인다. 생략 시 fulltext로 해석한다(하위호환). Trace: FR-31, FR-47, C-2.
    """

    fulltext = 'fulltext'
    abstract = 'abstract'
    figure = 'figure'


class SourceRef(BaseModel):
    """
    단일 출처 핸들 — 기존 계약 재사용. paperId = IndexRecord.arxivId(vector-spec §2). 사용자 업로드 문서는 paperId="userdoc:{uuid}", recordRef="upload:{ownerId}:{jobId}:{attachmentId}" — 실재 arXiv id가 없으므로 arxiv.org URL 조립 금지(무날조). recordRef = IndexRecord 식별자(실재성 검증 핸들). anchor = DocModel Section/Block id(summarization AnchorTarget 동일 방식). quote = 원문 스니펫(근거 인용, 선택). 내부 벡터/청크/점수 미노출(SEC-9). Trace: FR-5, SEC-9, vector-spec §2, summarization.schema.json AnchorTarget.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    paperId: str = Field(
        ...,
        description='출처 문서 id. arXiv: 표시용 arXiv ID(버전 포함 가능, Source: IndexRecord.arxivId). 사용자 업로드: "userdoc:{uuid}" 네임스페이스 — 실재 arXiv id 없음, arxiv.org URL 조립 금지(무날조). Trace: FR-5, vector-spec §2.',
    )
    recordRef: str = Field(
        ...,
        description='IndexRecord 식별자(실재성 검증 핸들). 사용자 업로드: "upload:{ownerId}:{jobId}:{attachmentId}". 내부 벡터·청크 정보 미포함. Trace: FR-5, vector-spec §2.',
    )
    anchor: str | None = Field(
        None,
        description='DocModel Section/Block 결정적 id(선택). 요약 AnchorTarget 계약과 동일 방식. Trace: summarization.schema.json.',
    )
    quote: str | None = Field(
        None,
        description='원문 인용 스니펫(선택, 추출 근거 표시용). 생성 산문 금지(C-2) — 논문 원문만.',
    )
    anchorType: AnchorType | None = Field(
        None,
        description='anchor가 가리키는 DocModel 블록의 종류(선택, FR-47 v2). 소비자(U12·FE)가 DocModel을 다시 읽지 않고 분기하기 위한 것 — FE는 이 값으로 인용 칩 라벨(표 3·그림 2·식 4)을 고른다. anchor가 없으면(예: sourceScope=abstract) 생략한다. Trace: FR-47.',
    )
    sourceScope: SourceScope | None = Field(
        None,
        description='근거 범위 등급(선택, FR-31/FR-47 v2). fulltext = DocModel 확보 논문의 원문 verbatim 인용(앵커 보유). abstract = 본문을 확보하지 못해 초록 범위에서 인용(앵커 없음, 코퍼스 밖 논문의 폴백). figure = 그림 해석 기반(인용문이 아니라 해석 — 주장의 수치는 논문 텍스트에 실재해야 하고, 정성 서술은 이 표시로 검증 강도 차이를 드러낸다). 범위는 결과 단위가 아니라 출처 단위다 — 한 응답에 세 종류가 섞인다. 생략 시 fulltext로 해석한다(하위호환). Trace: FR-31, FR-47, C-2.',
    )


class EvidenceItem(BaseModel):
    """
    단일 근거 명제 + 지지/상충 출처(Q3=B). statement = 논문에서 추출한 근거 명제(핵심 주장·방법·결과 수치·한계 — Q1=A). supporting = 명제를 지지하는 출처. conflicting = 명제와 상충하는 출처(페이즈 5 novelty 판단 입력). confidence 제외(FR-5 그라운딩·환각 위험 — Q3=B). 생성 산문 금지(C-2). Trace: Q1, Q3, FR-5, C-2, D5.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    statement: str = Field(
        ...,
        description='추출된 근거 명제(핵심 주장·방법·결과 수치·한계). 생성 산문 금지 — 논문 기반 추출만(C-2, FR-5).',
    )
    supporting: list[SourceRef] = Field(
        ..., description='명제를 지지하는 출처 목록. Trace: FR-5.'
    )
    conflicting: list[SourceRef] = Field(
        ...,
        description='명제와 상충하는 출처 목록(페이즈 5 novelty 판단 입력). 빈 배열 = 상충 없음. Trace: D5.',
    )


class StoppedReason(StrEnum):
    """
    탐색 종료 사유(선택, v2). 비기술 사유만 — 내부 상태·예외 상세 비노출(SEC-9). sufficient이면 화면에 확인 범위를 표시하지 않는다. cancelled = 사용자가 취소해 그 시점까지 검증된 근거로 만든 부분 답(v3 §2.8). 터미널 상태는 ok|abstain 2종을 유지하며 이 필드는 상태가 아니라 부가 정보다. Trace: FR-37 v2, SEC-9.
    """

    sufficient = 'sufficient'
    budget_exhausted = 'budget_exhausted'
    partial_failure = 'partial_failure'
    cancelled = 'cancelled'


class EvidenceCoverage(BaseModel):
    """
    근거형성에 사용된 논문·쿼리 요약 메타(투명성). 내부 점수·타이밍 미노출(SEC-9).
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    paperCount: int = Field(..., description='근거 추출에 사용된 논문 수.')
    queryUsed: str | None = Field(
        None,
        description='자동 검색 시 사용된 쿼리(auto·mixed scope). explicit scope이면 생략. v2 자율 루프는 질의를 여러 번 설계하므로 대표 질의(또는 요약)를 싣는다.',
    )
    examined: int | None = Field(
        None,
        description="실제로 확인(본문·초록 열람)한 논문 수(선택, v2). candidates와 함께 '탐색이 어디까지 갔는지'를 사용자에게 알린다. Trace: FR-37 v2.",
    )
    candidates: int | None = Field(
        None,
        description='탐색 중 발견한 후보 논문 수(선택, v2). examined < candidates이면 탐색이 완결되지 않은 것이다. Trace: FR-37 v2.',
    )
    stoppedReason: StoppedReason | None = Field(
        None,
        description='탐색 종료 사유(선택, v2). 비기술 사유만 — 내부 상태·예외 상세 비노출(SEC-9). sufficient이면 화면에 확인 범위를 표시하지 않는다. cancelled = 사용자가 취소해 그 시점까지 검증된 근거로 만든 부분 답(v3 §2.8). 터미널 상태는 ok|abstain 2종을 유지하며 이 필드는 상태가 아니라 부가 정보다. Trace: FR-37 v2, SEC-9.',
    )


class AnswerSegmentKind(StrEnum):
    """
    cited = refs의 근거로 기계가 확인한 문장 · synthesis = 모델이 근거들을 종합해 쓴 문장(기계가 확인할 수 없다). Trace: v3 §2.1, §4.3.
    """

    cited = 'cited'
    synthesis = 'synthesis'


class AnswerSegment(BaseModel):
    """
    판단 산문의 문장 하나(v3 §4.2). 산문을 한 덩어리가 아니라 문장 단위로 내보내는 이유는 §4.3 기계 검사와 §8 렌더가 같은 단위를 봐야 하기 때문이다. kind=cited는 refs의 근거로 기계가 확인한 문장이고, kind=synthesis는 모델이 근거들을 종합해 쓴 문장이라 기계가 확인할 수 없다 — 화면에서 구분한다(숨기지도, 같은 급으로 보이게 하지도 않는다). Trace: v3 §2.1, §4.2, §4.3, §8.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    text: str = Field(
        ...,
        description='문장 본문. 인용 번호는 refs가 권위이므로 text에 중복해 넣지 않는다.',
    )
    refs: list[int] = Field(
        ...,
        description='이 문장이 근거로 삼은 claims의 1-기반 번호. kind=synthesis면 반드시 빈 배열이다(§4.3 A1·A2 강등이 refs를 비우고 kind를 synthesis로 바꾼다). 번호가 실재하는지는 §4.3 A1이 판정한다 — 스키마는 범위를 이중으로 강제하지 않는다(판정 지점이 둘이 되면 어긋난다).',
    )
    kind: AnswerSegmentKind


class AnswerChecks(BaseModel):
    """
    §4.3 기계 검사의 결과 요약 — 화면 표시가 아니라 지표·디버깅용이다. Trace: v3 §4.3, §6.3.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    demoted: int = Field(
        ...,
        description="A1·A2로 종합 강등된 문장 수. 강등은 거부가 아니다 — 문장은 남되 '기계가 확인함' 표시를 잃는다.",
        ge=0,
    )
    regenerated: bool = Field(
        ..., description='거부되어 재생성을 거쳤는가(시작값 1회).'
    )
    fallback: bool = Field(
        ...,
        description='재생성도 거부되어 결정론 이어붙이기로 떨어졌는가. true면 판단 없이 근거만 있는 답이다 — 검사를 못 통과한 판단은 화면에 가지 않는다(C-2 fail-closed).',
    )


class EvidenceAnswer(BaseModel):
    """
    판단 층의 산출(v3 §4.4). 종전에는 claims를 결정론으로 이어붙인 문자열이라 조건이 갈리는 질문에 '어느 쪽인지'를 말하지 못했다. Trace: v3 §4.2, §4.4.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    segments: list[AnswerSegment] = Field(
        ..., description='문장 단위 산문. 표시 순서가 곧 배열 순서다.'
    )
    checks: AnswerChecks


class EvidenceResult(BaseModel):
    """
    근거형성 성공 산출(state=ok). claims = 추출된 근거 명제 목록(Q2=A 논문 비교형 + 쟁점 오버레이의 데이터 기반). coverage = 사용 논문·쿼리 요약. answer = 게이트를 통과한 근거만 보고 쓴 판단 산문 + 기계 검사 결과(v3 §4) — 근거에 없는 논문·수치는 검사가 막는다(C-2 동일 적용). Trace: Q2, FR-5, D5, v3 §4.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    state: Literal['ok'] = Field(..., description='ok 고정(성공). Trace: FR-5.')
    claims: list[EvidenceItem] = Field(
        ...,
        description='추출된 근거 명제 목록. 각 항목은 EvidenceItem{ statement, supporting[], conflicting[] }. Trace: Q1, Q3.',
    )
    coverage: EvidenceCoverage = Field(
        ..., description='사용 논문 수·쿼리 요약. Trace: SEC-9.'
    )
    answer: EvidenceAnswer | None = Field(
        None,
        description='판단 산문(문장 단위) + 기계 검사 결과. 근거 번호는 claims의 1-기반 순서를 가리키며 근거표 행 번호와 같은 출처다. 근거가 0건이면 null. 하위호환을 위해 선택 필드.',
    )


class EvidenceAbstainResult(BaseModel):
    """
    근거 부족·범위 밖 기권(state=abstain). 날조 대신 기권(FR-5). abstainReason = 비기술 사유만(내부 위반 상세 비노출 — SEC-9). Trace: FR-5, SEC-9, C-2.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    state: Literal['abstain'] = Field(..., description='abstain 고정. Trace: FR-5.')
    abstainReason: str = Field(
        ...,
        description='비기술 기권 사유(내부 위반 상세·점수 비노출 — SEC-9). 예: out_of_corpus, insufficient_evidence, cancelled(근거를 찾기 전에 사용자가 취소).',
    )


class EvidenceRequest(BaseModel):
    """
    근거형성 입력. topic = 연구 주제·질문. scope = 논문 집합 범위(Q4=A 혼합). paperIds = explicit·mixed scope 시 사용자 명시 paper 집합. attachments = 사용자 첨부(Q6=A, doc-model 파이프라인 재사용). constraints = 기간·분야·논문 수 제한(상세는 FD 이월). Trace: Q4, Q6.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    topic: str = Field(
        ...,
        description='연구 주제 또는 근거형성 질문. Trace: FR-1, SEC-5.',
        max_length=2000,
        min_length=1,
    )
    scope: EvidenceScope | None = Field(
        None, description='논문 집합 범위(Q4=A). 생략 시 auto.'
    )
    paperIds: list[str] | None = Field(
        None,
        description='explicit·mixed scope 시 사용자 명시 arXiv ID 목록. auto scope이면 무시.',
    )
    attachments: list[str] | None = Field(
        None,
        description='사용자 첨부 문서 핸들 목록(Q6=A, doc-model 파이프라인 재사용). 형식·크기 한도는 FD 이월.',
    )
    constraints: dict[str, Any] | None = Field(
        None,
        description='PROVISIONAL — 기간·분야·최대 논문수 제한. 상세 형태는 FD 이월.',
    )


class EvidenceResultModel(RootModel[EvidenceResult | EvidenceAbstainResult]):
    root: EvidenceResult | EvidenceAbstainResult = Field(
        ...,
        description='U4 문헌탐색·근거형성 Agent 출력 DTO 계약. ROOT = EvidenceResult (터미널 상태 유니온). 페이즈 5(연구아이디어 Agent)가 EvidenceFormationPort.form_evidence() 반환값으로 소비한다 (D5 공유 계약). 근거 출력 깊이(Q3=B): EvidenceItem{ statement, supporting[], conflicting[] } — confidence 제외(FR-5 그라운딩 원칙·환각 위험). 검색 scope(Q4=A): auto|explicit|mixed. 첨부(Q6=A): attachments? 지원. 기권(FR-5/SEC-9): state=abstain + 비기술 abstainReason, 내부 위반 상세 비노출. 생성 산문 금지(C-2): statement 필드는 논문에서 추출한 근거 명제만, 새로운 산문 생성 금지. Producer: U4; Consumer: U12. Trace: Q1, Q2, Q3, Q4, Q6, FR-5, SEC-9, C-2, D5.',
        title='EvidenceResult',
    )
