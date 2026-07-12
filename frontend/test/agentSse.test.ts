// US-EV2/NFR-P6 — 동기 evidence 턴 SSE 소비(스트리밍 리더 + JSON 폴백).
// novelty SSE 파서 테스트(agentChatScreen.test.tsx)와 동일한 프레임 형식을 공유한다.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiClient } from '@/lib/api/apiClient';
import type { Transport, TransportRequest, TransportResponse } from '@/lib/api/transport';
import { parseNoveltySseEvents, streamAgentTurn } from '@/lib/agentChat/sse';
import type { AgentTimelineEvent } from '@/lib/agentChat/types';

const CLAIM_STATEMENT = '벤치마크 재사용은 데이터 누수 위험을 높인다.';

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

describe('streamAgentTurn (US-EV2 sync SSE)', () => {
  it('delivers progress events progressively, terminal payload only from the result frame', async () => {
    const seen: Array<{ atEvent: string; stage: string }> = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          progressFrame('e1', 'started', { jobId: 'job-9' }),
          progressFrame('e2', 'papers_fetched', { count: 3 }),
          // 터미널 프레임에만 검증된 claims가 실린다(C-2/INV-EV-3).
          frame('result', {
            jobId: 'job-9',
            state: 'completed',
            claims: [{ statement: CLAIM_STATEMENT }],
          }),
        ]),
      ),
    );

    const events: AgentTimelineEvent[] = [];
    const outcome = await streamAgentTurn({
      path: '/api/research/jobs',
      body: { content: 'q' },
      onEvents: (incoming) => {
        events.push(...incoming);
        seen.push({ atEvent: incoming[0].id, stage: incoming[0].stage });
      },
    });

    expect(outcome).toEqual({
      kind: 'terminal',
      payload: { jobId: 'job-9', state: 'completed', claims: [{ statement: CLAIM_STATEMENT }] },
    });
    // 진행 이벤트는 프레임마다 점진 도착했고(터미널 이전), claim 텍스트를 싣지 않는다.
    expect(seen.map((s) => s.stage)).toEqual(['started', 'papers_fetched']);
    for (const event of events) {
      expect(JSON.stringify(event)).not.toContain(CLAIM_STATEMENT);
    }
    expect(events[1].detail).toBe('결과 3건');
  });

  it('returns the JSON body as-is when the server answers application/json (no resend)', async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(200, { jobId: 'job-1', state: 'completed' }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const outcome = await streamAgentTurn({ path: '/api/research/jobs', body: {} });

    expect(outcome).toEqual({
      kind: 'json',
      status: 200,
      body: { jobId: 'job-1', state: 'completed' },
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('reports failed with the observed jobId when the stream breaks before the terminal', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => sseResponse([progressFrame('e1', 'started', { jobId: 'job-7' })])),
    );

    const outcome = await streamAgentTurn({ path: '/api/research/jobs', body: {} });

    expect(outcome).toEqual({ kind: 'failed', jobId: 'job-7' });
  });

  it('maps an error frame to failed (fail-soft, no crash)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          progressFrame('e1', 'started', { jobId: 'job-3' }),
          frame('error', { message: '일시적인 오류로 답변을 생성하지 못했습니다.' }),
        ]),
      ),
    );

    const outcome = await streamAgentTurn({ path: '/api/research/jobs', body: {} });

    expect(outcome).toEqual({ kind: 'failed', jobId: 'job-3' });
  });

  it('parses split frames across chunk boundaries', async () => {
    const whole = progressFrame('e1', 'extracting', { paperCount: 2 }) + frame('result', { ok: 1 });
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => sseResponse([whole.slice(0, 25), whole.slice(25, 60), whole.slice(60)])),
    );

    const events: AgentTimelineEvent[] = [];
    const outcome = await streamAgentTurn({
      path: '/api/evidence/turns',
      body: {},
      onEvents: (incoming) => events.push(...incoming),
    });

    expect(events.map((e) => e.stage)).toEqual(['extracting']);
    expect(outcome).toEqual({ kind: 'terminal', payload: { ok: 1 } });
  });
});

describe('ApiClient.sendAgentMessage streaming integration', () => {
  function snapshotTransport(): Transport & { calls: TransportRequest[] } {
    const t = {
      calls: [] as TransportRequest[],
      streamsAgentTurns: true,
      async send(req: TransportRequest): Promise<TransportResponse> {
        t.calls.push(req);
        if (req.method === 'GET' && req.path === '/api/research/jobs/job-9') {
          return {
            status: 200,
            body: {
              job: { jobId: 'job-9', title: 'q', state: 'completed', updatedAt: '2026-07-10' },
              messages: [
                {
                  messageId: 'm1',
                  role: 'assistant',
                  content: JSON.stringify({ state: 'ok', claims: [] }),
                  createdAt: '2026-07-10',
                },
              ],
            },
          };
        }
        return { status: 200, body: { jobId: 'job-9', state: 'completed' } };
      },
    };
    return t;
  }

  it('streams progress then resolves with the snapshot (claims only after terminal)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        sseResponse([
          progressFrame('e1', 'started', { jobId: 'job-9' }),
          progressFrame('e2', 'validating', { claimCount: 1 }),
          frame('result', { jobId: 'job-9', state: 'completed' }),
        ]),
      ),
    );
    const t = snapshotTransport();
    const client = new ApiClient(t, { timeoutMs: 1000, retryBackoffMs: 1 });

    const order: string[] = [];
    const result = await client.sendAgentMessage(
      'agent-evidence-local',
      { content: 'q', mode: 'evidence' },
      (events) => order.push(...events.map((e) => e.stage)),
    );

    // 진행 이벤트가 스냅샷(최종 결과)보다 먼저 도착했다 — 점진 렌더링 시퀀스.
    expect(order).toEqual(['started', 'validating']);
    expect(result.session.id).toBe('evidence:job-9');
    expect(result.outcome).toBe('completed');
    // 최종 본문은 터미널 이후 스냅샷에서만 온다 — POST가 transport로 중복 전송되지 않았다.
    expect(t.calls.filter((req) => req.method === 'POST')).toHaveLength(0);
  });

  it('falls back to the JSON transport path when the SSE fetch is unavailable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('network down');
      }),
    );
    const t = snapshotTransport();
    const client = new ApiClient(t, { timeoutMs: 1000, retryBackoffMs: 1 });

    const result = await client.sendAgentMessage('agent-evidence-local', {
      content: 'q',
      mode: 'evidence',
    });

    expect(result.session.id).toBe('evidence:job-9');
    expect(t.calls.some((req) => req.method === 'POST' && req.path === '/api/research/jobs')).toBe(
      true,
    );
  });

  it('recovers via snapshot (not a resend) when the stream breaks after start', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => sseResponse([progressFrame('e1', 'started', { jobId: 'job-9' })])),
    );
    const t = snapshotTransport();
    const client = new ApiClient(t, { timeoutMs: 1000, retryBackoffMs: 1 });

    const result = await client.sendAgentMessage('agent-evidence-local', {
      content: 'q',
      mode: 'evidence',
    });

    expect(result.session.id).toBe('evidence:job-9');
    // 백엔드는 턴을 계속 완결하므로 재전송하지 않는다(비용 이중 지출 금지).
    expect(t.calls.filter((req) => req.method === 'POST')).toHaveLength(0);
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
