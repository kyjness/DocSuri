import { isNoveltyResultPayload } from './noveltyResult';
import type { NoveltyResultPayload } from './noveltyResult';

export interface EvidenceSourceRef {
  paperId: string;
  recordRef: string;
  anchor?: string | null;
  quote?: string | null;
}

export interface EvidenceClaim {
  statement: string;
  supporting: EvidenceSourceRef[];
  conflicting: EvidenceSourceRef[];
}

export interface EvidenceCoverage {
  paperCount: number;
  queryUsed?: string | null;
}

export interface EvidenceResultPayload {
  state: 'ok';
  claims: EvidenceClaim[];
  coverage: EvidenceCoverage;
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

// research/service.py가 evidence orchestrator 결과를 assistant 메시지로 저장할 때 쓰는 세 가지
// 형태를 판별한다: JSON 문자열(EvidenceResult), "[abstain] <reason>", "[error] ...", 일반 텍스트.
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
