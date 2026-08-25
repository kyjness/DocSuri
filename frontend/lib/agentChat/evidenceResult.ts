import type {
  AbstainReason,
  EvidenceAnswer as GeneratedAnswer,
  PaperIdNamespace,
} from '@/types/generated/evidence';

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
  /** 코퍼스 밖 논문의 출처 네임스페이스. **없으면 코퍼스 논문이다**(백엔드가 판정해 싣는다). */
  namespace?: PaperIdNamespace | null;
  /** 출처 논문의 제목. 없으면 화면이 paperId를 그대로 쓴다(그때만 식별자가 보인다). */
  title?: string | null;
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
  /** 실시간 조회가 온전히 돌지 못했다(v3 §7) — 소스 이름은 오지 않는다(SEC-9). */
  liveLookupDegraded?: boolean | null;
}

/**
 * 판단 계약(v3 §4)은 **스키마에서 그대로 가져온다**. 손으로 다시 적으면 스키마가 움직여도
 * 여기가 안 움직이고, CI는 그것을 못 본다 — `AnswerSegment`가 두 벌 있으면 화면이 낡은
 * 쪽을 믿는다. 세 타입 다 필수 필드뿐이라 그대로 쓸 수 있다.
 *
 * 아래 `EvidenceSourceRef`·`EvidenceCoverage`는 아직 손으로 적혀 있다. 생성분은
 * `anchor?: string`인데 서버는 `null`을 실어 보내고(pydantic 기본 직렬화), 그 차이를
 * 지금 지우면 null 검사가 타입에서 사라진다. 스키마가 nullable을 인정하기 전까지는
 * 여기가 더 정확하다 — 옮기려면 스키마부터 고친다.
 */
export type {
  AnswerChecks as EvidenceAnswerChecks,
  AnswerSegment as EvidenceAnswerSegment,
  EvidenceAnswer,
} from '@/types/generated/evidence';

export interface EvidenceResultPayload {
  state: 'ok';
  claims: EvidenceClaim[];
  coverage: EvidenceCoverage;
  answer?: GeneratedAnswer | null;
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
const ABSTAIN_REASON_LABEL: Record<AbstainReason, string> = {
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
  // 아래 넷은 근거형성이 낸 기권이 아니라 턴 실패가 fail-closed로 수렴한 것이다
  // (BR-EV-12). 원인은 서버 로그에 있고 사용자에게는 지어내지 않는다.
  internal_error: '답변을 만들지 못했어요. 잠시 뒤 다시 물어봐 주세요.',
  dispatch_failed: '답변을 만들지 못했어요. 잠시 뒤 다시 물어봐 주세요.',
  session_unavailable: '이 대화를 불러오지 못했어요. 새로고침한 뒤 다시 물어봐 주세요.',
  unknown: '답변을 만들지 못했어요. 잠시 뒤 다시 물어봐 주세요.',
};

export function abstainReasonLabel(reason: string): string {
  // 맵의 키가 `AbstainReason`이라 사유가 늘면 **여기가 컴파일 에러로 막힌다.** 종전에는
  // 그냥 string이라, 백엔드가 내는 사유를 화면에서 지워도 아무 데서도 안 걸리고 일반
  // 문구로 조용히 떨어졌다(llm_unavailable이 실제로 그랬다).
  //
  // 런타임 폴백은 남긴다 — 저장된 옛 턴이 어휘 밖 코드를 들고 있을 수 있다.
  return (
    ABSTAIN_REASON_LABEL[reason as AbstainReason] ??
    '답변을 만들지 못했어요. 잠시 뒤 다시 물어봐 주세요.'
  );
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
  const { examined, candidates, stoppedReason, liveLookupDegraded } = coverage;

  // 실시간 조회가 죽은 것은 **탐색이 잘렸는지와 무관하게** 밝혀야 한다(v3 §7). 후보를
  // 전부 확인하고 끝난 턴도 코퍼스 밖을 못 본 것이고, 그것을 안 밝히면 "그런 논문이
  // 세상에 없다"로 읽힌다 — 사용자가 할 일이 정반대다(다시 물어보기 vs 주제 넓히기).
  const live = liveLookupDegraded
    ? '코퍼스 밖 실시간 조회가 일시적으로 되지 않아 코퍼스 안에서만 찾았습니다.'
    : null;

  const truncated =
    stoppedReason &&
    stoppedReason !== 'sufficient' &&
    typeof examined === 'number' &&
    typeof candidates === 'number' &&
    candidates > examined
      ? truncationSentence(stoppedReason, examined, candidates)
      : null;

  // 두 사실이 독립이라 각각 있을 수도, 함께 있을 수도, 둘 다 없을 수도 있다.
  const parts = [truncated, live].filter(Boolean);
  return parts.length ? parts.join(' ') : null;
}

function truncationSentence(
  stoppedReason: NonNullable<EvidenceCoverage['stoppedReason']>,
  examined: number,
  candidates: number,
): string {
  if (stoppedReason === 'budget_exhausted') {
    return `관련 논문 ${candidates}편 중 ${examined}편까지 확인했습니다. 이어서 확인할까요?`;
  }
  if (stoppedReason === 'cancelled') {
    return `취소됨 · 후보 ${candidates}편 중 ${examined}편 확인`;
  }
  return `관련 논문 ${candidates}편 중 ${examined}편을 확인했습니다. 일부 논문은 본문을 가져오지 못했습니다.`;
}


/**
 * 출처 논문으로 가는 링크. **없으면 null이고, 그때는 링크를 그리지 않는다** — 깨진 링크는
 * 링크가 없는 것보다 나쁘다.
 *
 * 목적지는 백엔드가 실어 보낸 `namespace`가 정한다(계약은 evidence.schema.json). 종전에는
 * 여기서 `paperId`의 접두어를 직접 잘랐는데, 그러면 어휘가 두 벌이 되어 접두어가 하나 늘 때
 * 이쪽만 안 고쳐지고 화면이 조용히 링크를 잃는다. 이제 어휘가 늘면 아래 switch가 컴파일에서
 * 막힌다 — 지금은 화면 정책이 어휘를 **읽기만** 한다.
 *
 * - 없음 = 코퍼스 논문 → 우리 논문 상세. 본문·요약·번역이 거기 있으므로 arxiv.org로
 *   내보내는 것보다 사용자가 할 수 있는 일이 많다(그래서 이 판단은 프론트에 남는다).
 * - `arxiv` = 실시간 조회로 찾은 논문 → arxiv.org. 우리 상세 페이지가 없다.
 * - `doi` = arXiv에 없어 DOI로 실려온 논문 → doi.org.
 * - `userdoc` = 사용자가 올린 문서 → **링크 없음.** 실재 arXiv id가 없으므로 URL을 조립하면
 *   그것이 날조다(스키마가 "arxiv.org URL 조립 금지"라고 못 박는다).
 */
export function sourceHref(ref: EvidenceSourceRef): string | null {
  const id = ref.paperId?.trim();
  if (!id) return null;
  switch (ref.namespace ?? null) {
    case 'arxiv':
      return `https://arxiv.org/abs/${encodeURIComponent(stripNamespace(id))}`;
    case 'doi':
      return `https://doi.org/${stripNamespace(id)}`;
    case 'userdoc':
      return null;
    case null:
      // **저장된 옛 턴에는 `namespace`가 없다**(이 필드 이전에 만들어진 행). 그때 접두어가
      // 붙은 id를 코퍼스로 읽으면 `/paper/arxiv%3A…`로 보내 반드시 404다 — 없는 값을
      // "코퍼스"로 단정하지 않고, 접두어가 보이면 링크를 만들지 않는다.
      return id.includes(':') ? null : `/paper/${encodeURIComponent(id)}`;
    default:
      // 어휘가 늘었는데 목적지를 안 정한 경우 — 컴파일에서 막히지만, 저장된 옛 턴이 어휘 밖
      // 값을 들고 있을 수 있으므로 런타임은 링크 없음으로 떨어진다(404로 보내지 않는다).
      return null;
  }
}

/** `{namespace}:{id}` → `{id}`. 네임스페이스는 이미 별도 필드로 왔다. */
function stripNamespace(paperId: string): string {
  const colon = paperId.indexOf(':');
  return colon < 0 ? paperId : paperId.slice(colon + 1);
}

/** 출처의 표시 이름 — 제목이 있으면 제목, 없으면 식별자. */
export function sourceLabel(ref: EvidenceSourceRef): string {
  return ref.title?.trim() || ref.paperId;
}
