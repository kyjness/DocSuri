import { isNoveltyResultPayload } from './noveltyResult';
import type { NoveltyResultPayload } from './noveltyResult';

/** 인용한 DocModel 블록의 종류(FR-47 v2) — 칩 라벨을 고르는 근거. */
export type EvidenceAnchorType =
  | 'paragraph'
  | 'list'
  | 'code'
  | 'table'
  | 'figure'
  | 'formula';

/**
 * 근거 범위 등급. 한 응답에 세 종류가 섞이므로 출처 단위로 붙는다.
 * - fulltext: 원문 verbatim 인용(앵커 보유)
 * - abstract: 본문을 확보하지 못해 초록 범위에서 인용(앵커 없음)
 * - figure: 그림 해석 기반 — 인용문이 아니다
 */
export type EvidenceSourceScope = 'fulltext' | 'abstract' | 'figure';

export interface EvidenceSourceRef {
  paperId: string;
  recordRef: string;
  anchor?: string | null;
  quote?: string | null;
  anchorType?: EvidenceAnchorType | null;
  sourceScope?: EvidenceSourceScope | null;
}

export interface EvidenceClaim {
  statement: string;
  supporting: EvidenceSourceRef[];
  conflicting: EvidenceSourceRef[];
}

export interface EvidenceCoverage {
  paperCount: number;
  queryUsed?: string | null;
  /** 확인한 논문 수 / 발견한 후보 수 — 탐색이 어디까지 갔는지(FR-37 v2). */
  examined?: number | null;
  candidates?: number | null;
  stoppedReason?: 'sufficient' | 'budget_exhausted' | 'partial_failure' | 'cancelled' | null;
}

/**
 * 판단 산문의 문장 하나(v3 §4.2). 산문을 한 덩어리가 아니라 문장 단위로 받는 이유는
 * 화면이 두 종류를 **구분해서** 그려야 하기 때문이다 — cited는 기계가 확인한 문장,
 * synthesis는 모델이 근거들을 종합해 쓴 문장이라 원문에 그대로 있지 않다.
 * `refs`는 근거표 행 번호(1-기반)다.
 */
export interface EvidenceAnswerSegment {
  text: string;
  refs: number[];
  kind: 'cited' | 'synthesis';
}

/** §4.3 기계 검사 결과 — 표시용이 아니라 지표·디버깅용이다. */
export interface EvidenceAnswerChecks {
  demoted: number;
  regenerated: boolean;
  fallback: boolean;
}

export interface EvidenceAnswer {
  segments: EvidenceAnswerSegment[];
  checks: EvidenceAnswerChecks;
}

export interface EvidenceResultPayload {
  state: 'ok';
  claims: EvidenceClaim[];
  coverage: EvidenceCoverage;
  answer?: EvidenceAnswer | null;
}

export type ParsedAgentContent =
  | { kind: 'evidence'; result: EvidenceResultPayload }
  | { kind: 'novelty'; result: NoveltyResultPayload }
  | { kind: 'abstain'; reason: string }
  | { kind: 'error' }
  | { kind: 'text'; text: string };

/**
 * 기권 문구(v3 §2.3·§2.4·§2.9) — **대화가 끊기지 않는다.**
 *
 * 종전 4종은 "보류했습니다" "수행할 수 없습니다" 같은 시스템 통보라 다음 수를 알려주지
 * 않았다. 사유마다 사용자가 할 수 있는 일이 다르므로, 무엇을 해보라고 말하는 데까지
 * 간다 — 후보가 없으면 넓히기, 후보는 있는데 근거가 없으면 다른 표현, 취소는 이어가기.
 * "제한" "degraded" 같은 내부 용어는 쓰지 않는다(v2 Q10 승계).
 */
const ABSTAIN_REASON_LABEL: Record<string, string> = {
  out_of_corpus:
    '이 주제를 다룬 논문을 찾지 못했어요. 주제를 넓히거나 다른 용어로 물어봐 주세요.',
  insufficient_evidence:
    '이 질문에 대한 근거를 확인한 논문에서 찾지 못했어요. 질문을 다른 표현으로 바꾸거나, 범위를 넓혀 다시 물어봐 주세요.',
  cost_degraded: '오늘 이용량에 도달했어요. 내일 00:00에 다시 열려요. 이전 답변은 계속 볼 수 있어요.',
  // v3 §2.8 — 취소는 근거 부족이 아니다. 찾기 전에 멈췄다는 사실만 말한다.
  cancelled: '취소했어요. 확인한 논문에서는 아직 근거를 찾기 전이었어요.',
  // 백엔드가 사유를 **지어내는** 것을 막았지, 이 사유를 없앤 것이 아니다 —
  // `assembler`가 치명 오류에서 여전히 낸다. 항목을 지웠더니 진짜 LLM 실패가
  // 일반 폴백 문구로 떨어졌다. 사유를 지우기 전에 생산자를 세는 것이 먼저다.
  llm_unavailable: '지금은 분석을 끝내지 못했어요. 잠시 뒤 같은 질문을 다시 물어봐 주세요.',
};

export function abstainReasonLabel(reason: string): string {
  // 알려지지 않은 사유(internal_error·dispatch_failed 등)는 원인을 지어내지 않고
  // 다시 해보라고만 말한다 — 백엔드가 실제 코드를 보존하도록 고친 것과 짝이다.
  return ABSTAIN_REASON_LABEL[reason] ?? '답변을 만들지 못했어요. 잠시 뒤 다시 물어봐 주세요.';
}

function isEvidenceResultPayload(value: unknown): value is EvidenceResultPayload {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return candidate.state === 'ok' && Array.isArray(candidate.claims);
}

// apiClient의 contentFromTurnResult가 턴 결과를 메시지 본문으로 만들 때 쓰는 프로토콜을
// 판별한다: JSON 문자열(EvidenceResult), "[abstain] <reason>", "[error] ...", 일반 텍스트.
// 생산자와 파서가 한 계약이다 — 형태를 바꾸면 양쪽을 함께 바꾼다.
export function parseAgentContent(content: string): ParsedAgentContent {
  const trimmed = content.trim();

  if (trimmed.startsWith('[abstain]')) {
    return { kind: 'abstain', reason: trimmed.slice('[abstain]'.length).trim() };
  }
  if (trimmed.startsWith('[error]')) {
    return { kind: 'error' };
  }

  if (trimmed.startsWith('{')) {
    try {
      const parsed: unknown = JSON.parse(trimmed);
      if (isEvidenceResultPayload(parsed)) {
        return { kind: 'evidence', result: parsed };
      }
      if (isNoveltyResultPayload(parsed)) {
        return { kind: 'novelty', result: parsed };
      }
    } catch {
      // JSON이 아니면 일반 텍스트로 취급
    }
  }

  return { kind: 'text', text: content };
}


/** 인용 칩 라벨 — 앵커 종류를 사용자 어휘로. 종류가 없으면 라벨도 없다. */
export function anchorTypeLabel(ref: EvidenceSourceRef): string | null {
  switch (ref.anchorType) {
    case 'table':
      return '표';
    case 'figure':
      return '그림';
    case 'formula':
      return '식';
    case 'code':
      return '알고리즘';
    default:
      return null;
  }
}

/**
 * 근거 범위 배지. `fulltext`는 배지를 붙이지 않는다 — 대다수가 그것이라
 * 전부 달면 신호가 소음이 된다.
 */
export function sourceScopeBadge(
  ref: EvidenceSourceRef,
): { label: string; hint: string } | null {
  if (ref.sourceScope === 'abstract') {
    return { label: '초록', hint: '본문을 가져오지 못해 초록에서 인용했습니다' };
  }
  if (ref.sourceScope === 'figure') {
    return { label: '그림 해석', hint: '인용문이 아니라 그림을 읽어 얻은 서술입니다' };
  }
  return null;
}

/** 앵커가 없는 출처는 이동 링크를 렌더하지 않는다 — 깨진 링크를 만들지 않는다. */
export function canJumpToSource(ref: EvidenceSourceRef): boolean {
  return Boolean(ref.anchor);
}

/**
 * 확인 범위 문장(FR-37 v2). 내부 용어를 쓰지 않고 수치로 말한다.
 * 탐색이 완결됐으면(sufficient) 아무것도 표시하지 않는다.
 */
export function examinedRangeMessage(coverage: EvidenceCoverage): string | null {
  const { examined, candidates, stoppedReason } = coverage;
  if (!stoppedReason || stoppedReason === 'sufficient') return null;
  if (typeof examined !== 'number' || typeof candidates !== 'number') return null;
  if (candidates <= examined) return null;

  if (stoppedReason === 'budget_exhausted') {
    return `관련 논문 ${candidates}편 중 ${examined}편까지 확인했습니다. 이어서 확인할까요?`;
  }
  if (stoppedReason === 'cancelled') {
    return `취소됨 · 후보 ${candidates}편 중 ${examined}편 확인`;
  }
  return `관련 논문 ${candidates}편 중 ${examined}편을 확인했습니다. 일부 논문은 본문을 가져오지 못했습니다.`;
}
