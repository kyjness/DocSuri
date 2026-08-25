// Agent SSE plumbing — novelty 스냅샷 SSE(N-001 #257)와 evidence 턴 이벤트 스트림(v3 §5.3)이
// 같은 프레이밍(`event: <name>\ndata: {...}`)과 progress wire shape
// (eventId/state/message/payload/createdAt)를 공유한다. AgentChatScreen에 있던 파서를
// 이 모듈로 옮겨 두 경로가 한 벌의 코드로 동작한다.
import type { AgentTimelineEvent, AgentTimelineState } from './types';

export interface SseBlock {
  event: string;
  data: string;
}

/** SSE 블록 구분자 — 스냅샷 파서와 스트림 리더가 같은 프레이밍 규칙을 봐야 한다. */
const SSE_BLOCK_DELIM = /\r?\n\r?\n/;

/** SSE 텍스트(블록 구분 \n\n) → {event, data} 목록. 불완전/빈 블록은 버린다. */
export function parseSseBlocks(text: string): SseBlock[] {
  return text
    .split(SSE_BLOCK_DELIM)
    .map(parseSseBlock)
    .filter((block): block is SseBlock => Boolean(block));
}

function parseSseBlock(block: string): SseBlock | null {
  let eventName = 'message';
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith('event:')) eventName = line.slice('event:'.length).trim();
    if (line.startsWith('data:')) data.push(line.slice('data:'.length).trimStart());
  }
  if (data.length === 0) return null;
  return { event: eventName, data: data.join('\n') };
}

/** progress 이벤트(공유 wire shape) → timeline 이벤트. 형식이 어긋나면 null. */
export function mapProgressEvent(raw: unknown): AgentTimelineEvent | null {
  if (!raw || typeof raw !== 'object') return null;
  const record = raw as Record<string, unknown>;
  const id = stringValue(record.eventId);
  const stage = stringValue(record.state) ?? 'running';
  if (!id) return null;
  const payload =
    record.payload && typeof record.payload === 'object'
      ? (record.payload as Record<string, unknown>)
      : undefined;
  // evidence 이벤트는 트레이스 seq를 싣는다 — 재접속 병합 때 삽입순이 아니라 이 값으로 정렬한다.
  const seq = payload && typeof payload.seq === 'number' ? payload.seq : undefined;
  const timestamp = stringValue(payload?.at) ?? stringValue(record.createdAt);
  return {
    id,
    stage: stringValue(record.stage) ?? stage,
    label: stringValue(record.message) ?? stage,
    // N-001 — REST polling과 동일한 payload→detail 매핑(#257): source/query/count/사유.
    detail: timelineDetail(payload),
    state: mapTimelineState(stage),
    ...(seq !== undefined ? { sequence: seq } : {}),
    // 단계별 소요 시간의 재료. evidence는 트레이스 행의 `at`, 그 밖(accepted·novelty)은
    // 프레임의 createdAt이다 — 둘 다 없으면 화면이 시간을 안 그린다.
    ...(timestamp !== undefined ? { at: timestamp } : {}),
  };
}

function mapTimelineState(stage: string): AgentTimelineState {
  if (stage === 'failed' || stage === 'cancelled') return 'failed';
  if (stage === 'degraded') return 'degraded';
  if (stage === 'completed') return 'completed';
  return 'running';
}

/** progress wire 객체 목록 → timeline 이벤트. 형식이 어긋난 항목은 버린다. */
export function mapProgressEvents(raws: unknown[]): AgentTimelineEvent[] {
  return raws
    .map((raw) => mapProgressEvent(raw))
    .filter((event): event is AgentTimelineEvent => Boolean(event));
}

/** novelty 스냅샷 SSE 텍스트 → timeline 이벤트 목록 (기존 parseNoveltySseEvents). */
export function parseNoveltySseEvents(text: string): AgentTimelineEvent[] {
  const payloads = parseSseBlocks(text)
    .filter((block) => block.event === 'progress')
    .map((block) => {
      try {
        return JSON.parse(block.data) as unknown;
      } catch {
        return null;
      }
    })
    .filter((raw): raw is unknown => raw !== null);
  return mapProgressEvents(payloads);
}

// N-001(#257) — SSE 경로도 REST polling과 동일 payload→detail 매핑을 쓴다.
//
// evidence 트레이스 행은 novelty와 키가 다르다(argsSummary/resultSummary/outcome). 종전에는
// 여기서 novelty 키만 읽어 evidence 단계의 detail이 **항상 undefined**였고, 그래서 화면에는
// 라벨만 남아 "도구 실행"이 여덟 줄 쌓였다 — 진행 상황이 안 적힌 게 아니라 실려 오는데
// 안 읽고 있었다.
export function timelineDetail(payload?: Record<string, unknown>): string | undefined {
  if (!payload) return undefined;
  const count = countFromPayload(payload);
  const parts = [
    labeled('소스', payload.source ?? payload.sourceType ?? payload.type),
    labeled('쿼리', payload.query),
    labeled('요약', payload.outputSummary),
    // 0건도 '발견한 출처 수'다(US-NV7 #257) — falsy 체크로 삼키지 않는다.
    count !== undefined ? `결과 ${count}건` : undefined,
    // evidence — 결과 요약은 백엔드가 이미 사용자 어휘로 쓴다(`result_summary`는 화면
    // 전용이고 모델은 못 본다). 여기서 되파싱하지 않는다.
    //
    // **`argsSummary`는 싣지 않는다.** 그쪽은 `paper_ids=['arxiv:2106.09685v2', …],
    // stance=counter` 같은 모델 컨텍스트·운영 트레이스용 key=value 덤프이고, 도메인이
    // "되파싱하면 바닥 검사가 화면 문자열에 묶인다"고 규정한 값이다. 화면에 실으면 그
    // 절단 규칙(80자/300자)이 사용자 계약이 되어, 트레이스 포맷을 바꾸는 것이 UI 변경이
    // 된다. 사용자가 알아야 하는 것(무엇을 검색했나)은 검색 도구가 `resultSummary`에
    // 자기 `query`로 싣는다 — 되파싱이 아니라 생산자가 아는 값이다.
    stringValue(payload.resultSummary),
    safeReason(payload),
  ];
  return parts.filter(Boolean).join(' · ') || undefined;
}

export type TurnEventStreamOutcome =
  | { kind: 'terminal'; payload: unknown }
  | { kind: 'json'; status: number; body: unknown }
  | { kind: 'failed'; lastSeq: number };

/**
 * evidence 턴 이벤트 스트림 소비(v3 §5.3) — GET /turns/{id}/events?after=<seq>.
 *
 * - progress 프레임 → onEvents(점진 렌더링). 최종 claims는 터미널 `result` 프레임에만
 *   실려 온다(C-2/INV-EV-3) — 중간 프레임에서 결과를 조립하지 않는다.
 * - 서버가 JSON으로 응답하면(mock 경로) 재요청 없이 그 본문을 그대로 넘긴다.
 * - 스트림이 터미널 없이 끊기면 'failed' + 마지막으로 받은 seq — 호출자가 `after=`로
 *   다시 붙는다. 백엔드는 턴을 계속 돌리므로 재전송은 없다.
 */
export async function readTurnEvents(options: {
  path: string;
  onEvents?: (events: AgentTimelineEvent[]) => void;
  /** 구독을 버릴 때 끊는다 — 안 끊으면 서버 제너레이터가 상한(10분)까지 초당 폴링을 계속한다. */
  signal?: AbortSignal;
}): Promise<TurnEventStreamOutcome> {
  let lastSeq = 0;
  let res: Response;
  try {
    res = await fetch(`/bff${options.path}`, {
      method: 'GET',
      headers: { accept: 'text/event-stream' },
      credentials: 'same-origin',
      cache: 'no-store',
      signal: options.signal,
    });
  } catch {
    return { kind: 'failed', lastSeq };
  }

  const contentType = res.headers.get('content-type') ?? '';
  if (!contentType.includes('text/event-stream')) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // 본문 없는 에러 응답 — status만 전달한다.
    }
    return { kind: 'json', status: res.status, body };
  }
  if (!res.ok || !res.body) return { kind: 'failed', lastSeq };

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const handleBlock = (block: SseBlock): TurnEventStreamOutcome | null => {
    if (block.event === 'progress') {
      let raw: unknown;
      try {
        raw = JSON.parse(block.data);
      } catch {
        return null;
      }
      const event = mapProgressEvent(raw);
      if (event) {
        if (event.sequence !== undefined) lastSeq = Math.max(lastSeq, event.sequence);
        options.onEvents?.([event]);
      }
      return null;
    }
    if (block.event === 'result') {
      try {
        return { kind: 'terminal', payload: JSON.parse(block.data) };
      } catch {
        return { kind: 'failed', lastSeq };
      }
    }
    if (block.event === 'error') return { kind: 'failed', lastSeq };
    return null;
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (value) buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split(SSE_BLOCK_DELIM);
      buffer = done ? '' : (blocks.pop() ?? '');
      for (const text of blocks) {
        const block = parseSseBlock(text);
        if (!block) continue;
        const outcome = handleBlock(block);
        if (outcome) return outcome;
      }
      if (done) break;
    }
  } catch {
    return { kind: 'failed', lastSeq };
  } finally {
    await reader.cancel().catch(() => undefined);
  }
  // 터미널 없이 스트림 종료(서버 상한 10분 등) — 호출자가 after=lastSeq로 다시 붙는다.
  return { kind: 'failed', lastSeq };
}

function labeled(label: string, value: unknown): string | undefined {
  const text = stringValue(value);
  return text ? `${label}: ${text}` : undefined;
}

function safeReason(payload: Record<string, unknown>): string | undefined {
  if (hasValue(payload.error)) return '사유: 처리 중 오류가 발생했습니다.';
  if (hasValue(payload.degradedReasons) || hasValue(payload.reason)) {
    return '사유: 일부 연동이 저하되어 가능한 결과만 표시합니다.';
  }
  return undefined;
}

function countFromPayload(payload: Record<string, unknown>): number | undefined {
  const explicit = payload.count ?? payload.foundCount ?? payload.resultCount;
  if (typeof explicit === 'number') return explicit;
  return Array.isArray(payload.items) ? payload.items.length : undefined;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function hasValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'string') return value.trim().length > 0;
  return value !== null && value !== undefined;
}
