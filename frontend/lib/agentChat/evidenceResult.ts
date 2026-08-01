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
  stoppedReason?: 'sufficient' | 'budget_exhausted' | 'partial_failure' | null;
}

export interface EvidenceResultPayload {
  state: 'ok';
  claims: EvidenceClaim[];
  coverage: EvidenceCoverage;
  answer?: string | null;
}

export type ParsedAgentContent =
  | { kind: 'evidence'; result: EvidenceResultPayload }
  | { kind: 'novelty'; result: NoveltyResultPayload }
  | { kind: 'abstain'; reason: string }
  | { kind: 'error' }
  | { kind: 'text'; text: string };

const ABSTAIN_REASON_LABEL: Record<string, string> = {
  out_of_corpus: '관련 논문을 찾지 못했습니다.',
  insufficient_evidence: '근거가 충분하지 않아 답변을 보류했습니다.',
  llm_unavailable: '일시적으로 분석을 수행할 수 없습니다.',
  cost_degraded: '일시적으로 서비스 이용량이 제한되어 있습니다.',
};

export function abstainReasonLabel(reason: string): string {
  return ABSTAIN_REASON_LABEL[reason] ?? '답변을 생성하지 못했습니다.';
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
  return `관련 논문 ${candidates}편 중 ${examined}편을 확인했습니다. 일부 논문은 본문을 가져오지 못했습니다.`;
}
