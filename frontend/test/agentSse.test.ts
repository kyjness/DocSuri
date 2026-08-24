// v3 §5.3 — evidence 턴 이벤트 스트림 소비(GET 리더 + after 재접속 + 폴링 폴백).
// novelty SSE 파서 테스트(agentChatScreen.test.tsx)와 동일한 프레임 형식을 공유한다.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient } from '@/lib/api/apiClient';
import type { Transport, TransportRequest, TransportResponse } from '@/lib/api/transport';
import { parseNoveltySseEvents, readTurnEvents } from '@/lib/agentChat/sse';
import type { AgentTimelineEvent } from '@/lib/agentChat/types';

const CLAIM_STATEMENT = '벤치마크 재사용은 데이터 누수 위험을 높인다.';
const EVENTS_PATH = '/api/evidence/turns/t1/events';

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function progressFrame(id: string, stage: string, payload: Record<string, unknown> = {}): string {
  return frame('progress', {
    eventId: id,
    state: 'running',
    stage,
    message: stage,
    payload,
  });
}

function sseResponse(chunks: string[], contentType = 'text/event-stream'): Response {
  let index = 0;
  const encoder = new TextEncoder();
  return {
    ok: true,
    status: 200,
    headers: { get: (key: string) => (key === 'content-type' ? contentType : null) },
    body: {
      getReader: () => ({
        read: async () =>
          index < chunks.length
            ? { done: false, value: encoder.encode(chunks[index++]) }
            : { done: true, value: undefined },
        // 실제 리더 계약 — 구독을 버릴 때 스트림을 끊는 경로가 여기 있다.
        cancel: async () => {
          index = chunks.length;
        },
      }),
    },
  } as unknown as Response;
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status < 400,
    status,
    headers: { get: (key: string) => (key === 'content-type' ? 'application/json' : null) },
    json: async () => body,
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('readTurnEvents (v3 §5.3 turn event stream)', () => {
  it('delivers progress events progressively, terminal payload only from the result frame', async () => {
    const seen: Array<{ atEvent: string; stage: string }> = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe(`/bff${EVENTS_PATH}?after=2`);
        expect(init?.method).toBe('GET');
        return sseResponse([
          progressFrame('t1:accepted', 'accepted', { seq: 0 }),
          progressFrame('t1:3', 'tool', { tool: 'corpus_search', seq: 3 }),
          frame('result', { turnId: 't1', result: { state: 'ok', claims: [{ statement: CLAIM_STATEMENT }] } }),
        ]);
      }),
    );

    const outcome = await readTurnEvents({
      path: `${EVENTS_PATH}?after=2`,
      onEvents: (events: AgentTimelineEvent[]) =>
        events.forEach((event) => seen.push({ atEvent: event.id, stage: event.stage })),
    });

    expect(seen).toEqual([
      { atEvent: 't1:accepted', stage: 'accepted' },
      { atEvent: 't1:3', stage: 'tool' },
    ]);
    expect(outcome).toEqual({
      kind: 'terminal',
      payload: { turnId: 't1', result: { state: 'ok', claims: [{ statement: CLAIM_STATEMENT }] } },
    });
  });

  it('returns the JSON body as-is when the server answers application/json (mock path)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(200, { events: [], turn: { turnId: 't1' } })));

    const outcome = await readTurnEvents({ path: EVENTS_PATH });

    expect(outcome).toEqual({ kind: 'json', status: 200, body: { events: [], turn: { turnId: 't1' } } });
  });

  it('reports failed with the last seq when the stream breaks before the terminal', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => sseResponse([progressFrame('t1:1', 'tool', { seq: 1 }), progressFrame('t1:4', 'tool', { seq: 4 })])),
    );

    const outcome = await readTurnEvents({ path: EVENTS_PATH });

    expect(outcome).toEqual({ kind: 'failed', lastSeq: 4 });
  });

  it('maps an error frame to failed (fail-soft, no crash)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => sseResponse([progressFrame('t1:1', 'tool', { seq: 1 }), frame('error', { message: 'x' })])),
    );

    const outcome = await readTurnEvents({ path: EVENTS_PATH });

    expect(outcome).toEqual({ kind: 'failed', lastSeq: 1 });
  });

  it('passes the abort signal through and cancels the reader when the subscription is dropped', async () => {
    // 안 끊으면 서버 제너레이터가 상한(10분)까지 초당 폴링을 계속한다.
    const controller = new AbortController();
    let seenSignal: AbortSignal | undefined;
    let cancelled = false;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        seenSignal = init?.signal ?? undefined;
        const res = sseResponse([progressFrame('t1:1', 'tool', { seq: 1 })]);
        const reader = res.body!.getReader();
        const wrapped = { ...reader, cancel: async () => { cancelled = true; } };
        return { ...res, body: { getReader: () => wrapped } } as unknown as Response;
      }),
    );

    const outcome = await readTurnEvents({ path: EVENTS_PATH, signal: controller.signal });

    expect(seenSignal).toBe(controller.signal);
    expect(cancelled).toBe(true);
    expect(outcome).toEqual({ kind: 'failed', lastSeq: 1 });
  });

  it('parses split frames across chunk boundaries and carries seq into sequence', async () => {
    const events: AgentTimelineEvent[] = [];
    const whole = progressFrame('t1:7', 'tool', { tool: 'read_paper', seq: 7 }) + frame('result', { ok: true });
    const cut = Math.floor(whole.length / 2);
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([whole.slice(0, cut), whole.slice(cut)])));

    const outcome = await readTurnEvents({
      path: EVENTS_PATH,
      onEvents: (incoming: AgentTimelineEvent[]) => events.push(...incoming),
    });

    expect(events.map((event) => [event.id, event.sequence])).toEqual([['t1:7', 7]]);
    expect(outcome.kind).toBe('terminal');
  });
});

describe('ApiClient evidence turn lifecycle (accept → follow → snapshot)', () => {
  const TURN_OK = {
    sessionId: 'job-9',
    turnId: 't1',
    topic: 'q',
    result: { state: 'ok', claims: [], coverage: { paperCount: 0 } },
    createdAt: '2026-07-10',
  };

  function transportOf(
    answer: (req: TransportRequest) => TransportResponse,
    streams = true,
  ): Transport & { calls: TransportRequest[] } {
    const t = {
      calls: [] as TransportRequest[],
      streamsAgentTurns: streams,
      async send(req: TransportRequest): Promise<TransportResponse> {
        t.calls.push(req);
        return answer(req);
      },
    };
    return t;
  }

  function snapshotAnswer(req: TransportRequest): TransportResponse {
    if (req.method === 'POST' && req.path === '/api/evidence/turns') {
      return { status: 202, body: { ...TURN_OK, result: { state: 'pending' } } };
    }
    if (req.method === 'GET' && req.path === '/api/evidence/sessions/job-9') {
      return {
        status: 200,
        body: { id: 'job-9', title: 'q', createdAt: '2026-07-10', updatedAt: '2026-07-10', turns: [TURN_OK] },
      };
    }
    if (req.method === 'GET' && req.path === '/api/evidence/turns/t1') {
      return { status: 200, body: TURN_OK };
    }
    return { status: 500, body: null };
  }

  it('accepts with 202, then streams progress and resolves from the terminal frame', async () => {
    const t = transportOf(snapshotAnswer);
    const streamed: string[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        streamed.push(String(input));
        return sseResponse([
          progressFrame('t1:accepted', 'accepted', { sessionId: 'job-9', turnId: 't1', seq: 0 }),
          progressFrame('t1:1', 'tool', { tool: 'corpus_search', seq: 1 }),
          frame('result', TURN_OK),
        ]);
      }),
    );
    const timeline: AgentTimelineEvent[] = [];
    const client = new ApiClient(t, { timeoutMs: 1000, retryBackoffMs: 1 });

    const accepted = await client.acceptEvidenceTurn('agent-evidence-local', {
      content: 'q',
      mode: 'evidence',
    });
    const finished = await client.followEvidenceTurn(accepted.turnId, (incoming) =>
      timeline.push(...incoming),
    );

    // 수락은 한 번의 POST뿐 — 답변은 터미널 프레임에서 나오므로 세션 스냅샷을 다시 읽지 않는다.
    expect(t.calls.map((c) => `${c.method} ${c.path}`)).toEqual(['POST /api/evidence/turns']);
    expect(streamed).toEqual(['/bff/api/evidence/turns/t1/events']);
    expect(timeline.map((event) => event.stage)).toEqual(['accepted', 'tool']);
    expect(accepted.session.id).toBe('evidence:job-9');
    expect(finished.message.id).toBe('t1-agent');
  });

  it('reconnects with after=<seq> after a short backoff when the stream breaks, then resolves', async () => {
    const t = transportOf(snapshotAnswer);
    const urls: string[] = [];
    const at: number[] = [];
    let attempt = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        urls.push(String(input));
        at.push(Date.now());
        attempt += 1;
        if (attempt === 1) return sseResponse([progressFrame('t1:2', 'tool', { seq: 2 })]); // 끊김
        return sseResponse([progressFrame('t1:3', 'tool', { seq: 3 }), frame('result', TURN_OK)]);
      }),
    );

    const finished = await new ApiClient(t, { timeoutMs: 1000, retryBackoffMs: 1 }).followEvidenceTurn('t1');

    expect(urls).toEqual(['/bff/api/evidence/turns/t1/events', '/bff/api/evidence/turns/t1/events?after=2']);
    // 즉시 재접속하지 않는다 — 끊긴 원인이 그대로면 3회를 한꺼번에 태운다.
    expect(at[1] - at[0]).toBeGreaterThanOrEqual(400);
    expect(finished.turnId).toBe('t1');
    expect(finished.outcome).toBe('completed');
    expect(finished.cancelled).toBe(false);
  });

  it('falls back to polling GET /turns/{id} when the stream keeps failing (no resend)', async () => {
    const t = transportOf(snapshotAnswer);
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([])));

    const finished = await new ApiClient(t, { timeoutMs: 1000, retryBackoffMs: 1 }).followEvidenceTurn('t1');

    expect(t.calls.map((c) => `${c.method} ${c.path}`)).toEqual(['GET /api/evidence/turns/t1']);
    expect(finished.message.id).toBe('t1-agent');
  });

  it('uses the JSON events snapshot on a non-streaming transport (mock mode)', async () => {
    const t = transportOf((req) => {
      if (req.method === 'GET' && req.path === '/api/evidence/turns/t1/events') {
        return {
          status: 200,
          body: {
            events: [
              { eventId: 't1:1', state: 'completed', stage: 'tool', message: '도구 실행', payload: { seq: 1 } },
            ],
            turn: TURN_OK,
          },
        };
      }
      return snapshotAnswer(req);
    }, false);
    const timeline: AgentTimelineEvent[] = [];

    const finished = await new ApiClient(t, { timeoutMs: 1000, retryBackoffMs: 1 }).followEvidenceTurn(
      't1',
      (incoming: AgentTimelineEvent[]) => timeline.push(...incoming),
    );

    expect(timeline.map((event) => event.id)).toEqual(['t1:1']);
    expect(finished.outcome).toBe('completed');
  });

  it('marks a cancelled turn so the screen can close the timeline', async () => {
    const cancelledTurn = {
      ...TURN_OK,
      result: { state: 'ok', claims: [], coverage: { paperCount: 1, stoppedReason: 'cancelled' } },
    };
    const t = transportOf(
      (req) =>
        req.path === '/api/evidence/turns/t1/events'
          ? { status: 200, body: { events: [], turn: cancelledTurn } }
          : snapshotAnswer(req),
      false,
    );

    const finished = await new ApiClient(t, { timeoutMs: 1000, retryBackoffMs: 1 }).followEvidenceTurn('t1');

    expect(finished.cancelled).toBe(true);
  });

  it('surfaces 409 from accept when the session already has a running turn', async () => {
    const t = transportOf((req) =>
      req.path === '/api/evidence/turns'
        ? { status: 409, body: { detail: '이 대화에서 아직 진행 중인 질문이 있습니다.' } }
        : snapshotAnswer(req),
    );

    await expect(
      new ApiClient(t, { timeoutMs: 1000, retryBackoffMs: 1 }).acceptEvidenceTurn('evidence:job-9', {
        content: 'q2',
        mode: 'evidence',
      }),
    ).rejects.toThrow();
  });
});

describe('shared SSE parser (novelty snapshot compatibility)', () => {
  it('keeps the novelty progress mapping intact after the lib move', () => {
    const events = parseNoveltySseEvents(
      [
        'event: progress',
        'data: {"eventId":"evt-1","state":"retrieving_external","message":"외부 검색","payload":{"source":"github","count":2}}',
        '',
      ].join('\n'),
    );

    expect(events).toEqual([
      {
        id: 'evt-1',
        stage: 'retrieving_external',
        label: '외부 검색',
        detail: '소스: github · 결과 2건',
        state: 'running',
      },
    ]);
  });
});
