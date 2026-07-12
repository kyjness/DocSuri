// Agent SSE plumbing — novelty 스냅샷 SSE(N-001 #257)와 evidence 동기 턴 스트리밍(US-EV2,
// NFR-P6)이 같은 프레이밍(`event: <name>\ndata: {...}`)과 progress wire shape
// (eventId/state/message/payload/createdAt)를 공유한다. AgentChatScreen에 있던 파서를
// 이 모듈로 옮겨 두 경로가 한 벌의 코드로 동작한다.
import type { AgentTimelineEvent, AgentTimelineState } from './types';

export interface SseBlock {
  event: string;
  data: string;
}

/** SSE 텍스트(블록 구분 \n\n) → {event, data} 목록. 불완전/빈 블록은 버린다. */
export function parseSseBlocks(text: string): SseBlock[] {
  return text
    .split(/\r?\n\r?\n/)
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
  return {
    id,
    stage: stringValue(record.stage) ?? stage,
    label: stringValue(record.message) ?? stage,
    // N-001 — REST polling과 동일한 payload→detail 매핑(#257): source/query/count/사유.
    detail: timelineDetail(payload),
    state: mapTimelineState(stage),
  };
}

function mapTimelineState(stage: string): AgentTimelineState {
  if (stage === 'failed' || stage === 'cancelled') return 'failed';
  if (stage === 'degraded') return 'degraded';
  if (stage === 'completed') return 'completed';
  return 'running';
}

/** novelty 스냅샷 SSE 텍스트 → timeline 이벤트 목록 (기존 parseNoveltySseEvents). */
export function parseNoveltySseEvents(text: string): AgentTimelineEvent[] {
  return parseSseBlocks(text)
    .filter((block) => block.event === 'progress')
    .map((block) => {
      try {
        return mapProgressEvent(JSON.parse(block.data));
      } catch {
        return null;
      }
    })
    .filter((event): event is AgentTimelineEvent => Boolean(event));
}

// N-001(#257) — SSE 경로도 REST polling과 동일 payload→detail 매핑을 쓴다.
export function timelineDetail(payload?: Record<string, unknown>): string | undefined {
  if (!payload) return undefined;
  const count = countFromPayload(payload);
  const parts = [
    labeled('소스', payload.source ?? payload.sourceType ?? payload.type),
    labeled('쿼리', payload.query),
    labeled('요약', payload.outputSummary),
    // 0건도 '발견한 출처 수'다(US-NV7 #257) — falsy 체크로 삼키지 않는다.
    count !== undefined ? `결과 ${count}건` : undefined,
    safeReason(payload),
  ];
  return parts.filter(Boolean).join(' · ') || undefined;
}

export type AgentTurnStreamOutcome =
  | { kind: 'terminal'; payload: unknown }
  | { kind: 'json'; status: number; body: unknown }
  | { kind: 'failed'; jobId?: string };

/**
 * 동기 evidence 턴 SSE 소비(US-EV2) — POST + Accept: text/event-stream.
 *
 * - progress 프레임 → onEvents(점진 렌더링). 최종 claims는 터미널 `result` 프레임에만
 *   실려 온다(C-2/INV-EV-3) — 이 함수는 터미널 payload를 그대로 반환할 뿐 중간
 *   프레임에서 결과를 조립하지 않는다.
 * - 서버가 JSON으로 응답하면(비동기 pending·mock 등) 재전송 없이 그 본문을 그대로
 *   JSON 경로 결과로 넘긴다.
 * - 스트림이 터미널 없이 끊기면 'failed' + 관측된 jobId(started 이벤트 payload) 반환 —
 *   백엔드는 턴을 끝까지 완결하므로 호출자가 스냅샷으로 복구한다(PR #338 교훈).
 */
export async function streamAgentTurn(options: {
  path: string;
  body: unknown;
  onEvents?: (events: AgentTimelineEvent[]) => void;
}): Promise<AgentTurnStreamOutcome> {
  const res = await fetch(`/bff${options.path}`, {
    method: 'POST',
    headers: { accept: 'text/event-stream', 'content-type': 'application/json' },
    credentials: 'same-origin',
    cache: 'no-store',
    body: JSON.stringify(options.body),
  });

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
  if (!res.ok || !res.body) return { kind: 'failed' };

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let jobId: string | undefined;

  const handleBlock = (block: SseBlock): AgentTurnStreamOutcome | null => {
    if (block.event === 'progress') {
      let raw: unknown;
      try {
        raw = JSON.parse(block.data);
      } catch {
        return null;
      }
      jobId = extractJobId(raw) ?? jobId;
      const event = mapProgressEvent(raw);
      if (event) options.onEvents?.([event]);
      return null;
    }
    if (block.event === 'result') {
      try {
        return { kind: 'terminal', payload: JSON.parse(block.data) };
      } catch {
        return { kind: 'failed', jobId };
      }
    }
    if (block.event === 'error') return { kind: 'failed', jobId };
    return null;
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (value) buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split(/\r?\n\r?\n/);
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
    return { kind: 'failed', jobId };
  }
  // 터미널 없이 스트림 종료 — 백엔드가 계속 완결하므로 호출자 복구에 맡긴다.
  return { kind: 'failed', jobId };
}

function extractJobId(raw: unknown): string | undefined {
  if (!raw || typeof raw !== 'object') return undefined;
  const payload = (raw as Record<string, unknown>).payload;
  if (!payload || typeof payload !== 'object') return undefined;
  return stringValue((payload as Record<string, unknown>).jobId);
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
