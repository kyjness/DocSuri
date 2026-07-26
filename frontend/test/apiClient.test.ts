import { describe, it, expect, vi } from 'vitest';
import { ApiClient } from '@/lib/api/apiClient';
import { UserFacingError } from '@/lib/api/errors';
import {
  isBinaryTransportBody,
  type Transport,
  type TransportRequest,
  type TransportResponse,
} from '@/lib/api/transport';
import { pageResponse } from '@/mocks/searchFixtures';

function transportOf(impl: (req: TransportRequest) => Promise<TransportResponse>): Transport & {
  calls: number;
} {
  const t = {
    calls: 0,
    async send(req: TransportRequest) {
      t.calls += 1;
      return impl(req);
    },
  };
  return t;
}

const fast = { timeoutMs: 1000, retryBackoffMs: 1 };

describe('ApiClient retry policy', () => {
  it('retries an idempotent GET once on 5xx then succeeds', async () => {
    let n = 0;
    const t = transportOf(async () =>
      ++n === 1
        ? { status: 500, body: null }
        : { status: 200, body: { userId: 'u', expiresAt: 'x' } },
    );
    const client = new ApiClient(t, fast);
    const session = await client.currentSession();
    expect(session).toEqual({ userId: 'u', expiresAt: 'x' });
    expect(t.calls).toBe(2);
  });

  it('does NOT retry a state-changing POST', async () => {
    const t = transportOf(async () => ({ status: 500, body: null }));
    const client = new ApiClient(t, fast);
    await expect(client.signup({ email: 'a@b.co', password: 'x' })).rejects.toBeInstanceOf(
      UserFacingError,
    );
    expect(t.calls).toBe(1);
  });

  it('surfaces a backend {detail} 400 reason (FastAPI envelope), not the generic fallback', async () => {
    // Module HTTPExceptions serialize as {detail}; the frontend must read it (regression guard
    // for the "signup blocked" incident where {detail} was swallowed into "문제가 발생했습니다").
    const t = transportOf(async () => ({
      status: 400,
      body: { detail: '이미 등록된 이메일 주소입니다.' },
    }));
    const client = new ApiClient(t, fast);
    await expect(client.signup({ email: 'a@b.co', password: 'Abcdef123!' })).rejects.toMatchObject({
      kind: 'unknown',
      message: '이미 등록된 이메일 주소입니다.',
    });
  });

  it('sends login reCAPTCHA token through the transport header', async () => {
    let seen: TransportRequest | undefined;
    const t = transportOf(async (req) => {
      seen = req;
      return { status: 200, body: { status: 'success' } };
    });
    await new ApiClient(t, fast).login(
      { email: 'a@b.co', password: 'Abcdef123!' },
      'captcha-token',
    );
    expect(seen?.headers).toEqual({ 'X-Recaptcha-Token': 'captcha-token' });
  });

  it('normalizes a transport throw to a network UserFacingError', async () => {
    const t = transportOf(async () => {
      throw new Error('boom');
    });
    const client = new ApiClient(t, fast);
    await expect(client.currentSession()).rejects.toMatchObject({ kind: 'network' });
    expect(t.calls).toBe(2); // idempotent → one retry
  });

  it('dedups concurrent identical idempotent requests', async () => {
    const t = transportOf(async () => {
      await new Promise((r) => setTimeout(r, 20));
      return { status: 200, body: { userId: 'u', expiresAt: 'x' } };
    });
    const client = new ApiClient(t, fast);
    const [a, b] = await Promise.all([client.currentSession(), client.currentSession()]);
    expect(a).toEqual({ userId: 'u', expiresAt: 'x' });
    expect(b).toEqual({ userId: 'u', expiresAt: 'x' });
    expect(t.calls).toBe(1);
  });
});

describe('ApiClient outcome mapping', () => {
  it('maps 200 page body to a page outcome', async () => {
    const t = transportOf(async () => ({ status: 200, body: pageResponse }));
    const out = await new ApiClient(t, fast).search('transformer');
    expect(out.kind).toBe('page');
  });

  it('maps 401 on search to an auth error', async () => {
    const t = transportOf(async () => ({ status: 401, body: null }));
    await expect(new ApiClient(t, fast).search('q')).rejects.toMatchObject({ kind: 'auth' });
  });

  it('sends search with the 30s cold-path timeout override (QA 2026-07-10 F1)', async () => {
    // 콜드 검색(첫 질의)은 정상 완료가 9~12초 — 기본 10초 타임아웃이 완료 직전에 끊어
    // 504로 보이던 회귀 가드. BFF의 SEARCH_GATEWAY_TIMEOUT_MS(30s)와 함께 움직인다.
    let seen: TransportRequest | undefined;
    const t = transportOf(async (req) => {
      seen = req;
      return { status: 200, body: pageResponse };
    });
    await new ApiClient(t, fast).search('transformer');
    expect(seen?.timeoutMs).toBe(30_000);
  });

  it('returns null session on 401', async () => {
    const t = transportOf(async () => ({ status: 401, body: null }));
    expect(await new ApiClient(t, fast).currentSession()).toBeNull();
  });
});

describe('ApiClient agent chat mapping', () => {
  it('keeps sessions from the healthy agent mode when the other mode fails', async () => {
    const t = transportOf(async (req) => {
      if (req.path === '/api/research/jobs?limit=20') return { status: 500, body: null };
      if (req.path === '/api/novelty/jobs?limit=20') {
        return {
          status: 200,
          body: {
            jobs: [
              {
                jobId: 'n1',
                topic: 'Novelty topic',
                state: 'completed',
                updatedAt: '2026-07-01T00:00:00Z',
              },
            ],
          },
        };
      }
      return { status: 404, body: null };
    });

    await expect(new ApiClient(t, fast).listAgentSessions()).resolves.toMatchObject([
      { id: 'novelty:n1', mode: 'novelty', state: 'completed' },
    ]);
  });

  it('fails session loading when all agent modes fail', async () => {
    const t = transportOf(async () => ({ status: 503, body: null }));

    await expect(new ApiClient(t, fast).listAgentSessions()).rejects.toMatchObject({
      kind: 'server',
    });
  });

  it('blocks real research sends until the research worker is enabled', async () => {
    const previousReal = process.env.NEXT_PUBLIC_DOCSURI_REAL_API;
    const previousResearch = process.env.NEXT_PUBLIC_DOCSURI_RESEARCH_AGENT_ENABLED;
    process.env.NEXT_PUBLIC_DOCSURI_REAL_API = '1';
    delete process.env.NEXT_PUBLIC_DOCSURI_RESEARCH_AGENT_ENABLED;
    const t = transportOf(async () => ({ status: 200, body: null }));
    try {
      await expect(
        new ApiClient(t, fast).sendAgentMessage('agent-evidence-local', {
          content: 'research check',
          mode: 'evidence',
        }),
      ).rejects.toMatchObject({
        message: 'Research는 아직 실배포에서 사용할 수 없습니다.',
      });
      expect(t.calls).toBe(0);
    } finally {
      if (previousReal === undefined) delete process.env.NEXT_PUBLIC_DOCSURI_REAL_API;
      else process.env.NEXT_PUBLIC_DOCSURI_REAL_API = previousReal;
      if (previousResearch === undefined) {
        delete process.env.NEXT_PUBLIC_DOCSURI_RESEARCH_AGENT_ENABLED;
      } else {
        process.env.NEXT_PUBLIC_DOCSURI_RESEARCH_AGENT_ENABLED = previousResearch;
      }
    }
  });

  it('loads a novelty session without a result artifact and hides internal payload strings', async () => {
    const t = transportOf(async (req) => {
      if (req.path === '/api/novelty/jobs/n1') {
        return {
          status: 200,
          body: {
            job: {
              jobId: 'n1',
              topic: 'Novelty topic',
              state: 'failed',
              updatedAt: '2026-07-01T00:00:00Z',
            },
            events: [
              {
                eventId: 'e1',
                state: 'failed',
                message: 'Novelty failed',
                progressPercent: 50,
                payload: {
                  source: 'github',
                  query: 'rag',
                  resultCount: 2,
                  error: 'Traceback: secret stack',
                  detail: 'internal detail',
                },
                createdAt: '2026-07-01T00:00:00Z',
              },
            ],
          },
        };
      }
      if (req.path === '/api/novelty/jobs/n1/messages') {
        return {
          status: 200,
          body: {
            messages: [
              {
                messageId: 'm1',
                role: 'user',
                content: 'hello',
                attachments: [{ fileName: 'draft.pdf', contentType: 'application/pdf' }],
                createdAt: '2026-07-01T00:00:00Z',
              },
            ],
          },
        };
      }
      if (req.path === '/api/novelty/jobs/n1/result') return { status: 404, body: null };
      return { status: 500, body: null };
    });

    const snapshot = await new ApiClient(t, fast).loadAgentSession('novelty:n1');

    expect(snapshot.messages[0].attachments?.[0]).toMatchObject({
      name: 'draft.pdf',
      kind: 'pdf',
    });
    expect(snapshot.events[0].detail).toContain('소스: github');
    expect(snapshot.events[0].detail).toContain('처리 중 오류가 발생했습니다.');
    expect(snapshot.events[0].detail).not.toContain('Traceback');
    expect(snapshot.events[0].detail).not.toContain('internal detail');
  });

  it('uploads research PDFs before sending attachment metadata to the job', async () => {
    const requests: TransportRequest[] = [];
    const uploadRef = {
      id: 'a1',
      name: 'scan.pdf',
      kind: 'pdf',
      sizeBytes: 8,
      status: 'ready',
      objectKey: 'evidence/u1/a1/a1/scan.pdf',
      paperId: 'userdoc:11111111-1111-4111-8111-111111111111',
      recordRef: 'upload:u1:userdoc-a1:a1',
    };
    const t = transportOf(async (req) => {
      requests.push(req);
      if (req.path.startsWith('/api/research/attachments?')) {
        expect(isBinaryTransportBody(req.body)).toBe(true);
        return { status: 200, body: uploadRef };
      }
      if (req.path === '/api/research/jobs') {
        const body = req.body as { attachments?: unknown[] };
        expect(body.attachments?.[0]).toMatchObject({
          objectKey: uploadRef.objectKey,
          paperId: uploadRef.paperId,
          recordRef: uploadRef.recordRef,
        });
        expect(body.attachments?.[0]).not.toHaveProperty('sourceFile');
        return { status: 201, body: { jobId: 'r1', state: 'active' } };
      }
      if (req.path === '/api/research/jobs/r1') {
        return {
          status: 200,
          body: {
            job: {
              jobId: 'r1',
              title: 'PDF evidence',
              state: 'completed',
              updatedAt: '2026-07-01T00:00:00Z',
            },
            messages: [],
          },
        };
      }
      return { status: 500, body: null };
    });

    await new ApiClient(t, fast).sendAgentMessage('agent-evidence-local', {
      content: 'PDF evidence',
      mode: 'evidence',
      attachments: [
        {
          id: 'a1',
          name: 'scan.pdf',
          kind: 'pdf',
          sizeBytes: 8,
          status: 'ready',
          sourceFile: new Blob(['%PDF-1.4'], { type: 'application/pdf' }),
        },
      ],
    });

    expect(requests.map((req) => req.path.split('?')[0])).toEqual([
      '/api/research/attachments',
      '/api/research/jobs',
      '/api/research/jobs/r1',
    ]);
  });

  it('uploads novelty PDF manuscripts as raw PDF after creating the manuscript job', async () => {
    const requests: TransportRequest[] = [];
    const t = transportOf(async (req) => {
      requests.push(req);
      if (req.path === '/api/novelty/jobs') {
        const body = req.body as { manuscript?: unknown };
        expect(body.manuscript).toEqual({
          fileName: 'draft.pdf',
          contentType: 'application/pdf',
          objectKey: null,
        });
        return { status: 201, body: { jobId: 'n1', state: 'queued' } };
      }
      if (req.path.startsWith('/api/novelty/jobs/n1/manuscript?')) {
        expect(isBinaryTransportBody(req.body)).toBe(true);
        expect(req.path).toContain('fileName=draft.pdf');
        return {
          status: 200,
          body: {
            job: {
              jobId: 'n1',
              topic: 'manuscript check',
              state: 'queued',
              updatedAt: '2026-07-01T00:00:00Z',
            },
            events: [],
          },
        };
      }
      if (req.path === '/api/novelty/jobs/n1') {
        return {
          status: 200,
          body: {
            job: {
              jobId: 'n1',
              topic: 'manuscript check',
              state: 'queued',
              updatedAt: '2026-07-01T00:00:00Z',
            },
            events: [],
          },
        };
      }
      if (req.path === '/api/novelty/jobs/n1/messages') {
        return { status: 200, body: { messages: [] } };
      }
      if (req.path === '/api/novelty/jobs/n1/result') return { status: 404, body: null };
      return { status: 500, body: null };
    });

    await new ApiClient(t, fast).sendAgentMessage('agent-novelty-local', {
      content: 'manuscript check',
      mode: 'novelty',
      attachments: [
        {
          id: 'a1',
          name: 'draft.pdf',
          kind: 'pdf',
          sizeBytes: 8,
          status: 'ready',
          sourceFile: new Blob(['%PDF-1.4'], { type: 'application/pdf' }),
        },
      ],
    });

    expect(requests[0].path).toBe('/api/novelty/jobs');
    expect(requests[1].path.split('?')[0]).toBe('/api/novelty/jobs/n1/manuscript');
  });

  it('sends only fields the novelty job schema accepts', async () => {
    // 서버 CreateJobRequest는 extra=forbid다 — 모르는 키가 하나라도 있으면 잡 생성이
    // 매번 422가 되고 novelty 전체가 실환경에서 시작조차 못 한다(로컬 실스택 검증에서
    // `exportToNotion`으로 실제 발생). 키 집합 자체를 못 박는다.
    let createBody: Record<string, unknown> | undefined;
    const t = transportOf(async (req) => {
      if (req.path === '/api/novelty/jobs') {
        createBody = req.body as Record<string, unknown>;
        return { status: 201, body: { jobId: 'n1', state: 'queued' } };
      }
      if (req.path === '/api/novelty/jobs/n1') {
        return {
          status: 200,
          body: {
            job: {
              jobId: 'n1',
              topic: 'rag eval',
              state: 'queued',
              updatedAt: '2026-07-01T00:00:00Z',
            },
            events: [],
          },
        };
      }
      if (req.path === '/api/novelty/jobs/n1/messages') {
        return { status: 200, body: { messages: [] } };
      }
      if (req.path === '/api/novelty/jobs/n1/result') return { status: 404, body: null };
      return { status: 500, body: null };
    });

    await new ApiClient(t, fast).sendAgentMessage('agent-novelty-local', {
      content: 'rag eval',
      mode: 'novelty',
    });

    expect(Object.keys(createBody ?? {}).sort()).toEqual([
      'constraints',
      'inputType',
      'manuscript',
      'topic',
    ]);
  });

  it('rejects an oversize PDF attachment before any upload request', async () => {
    const t = transportOf(async () => ({ status: 200, body: null }));
    const bigPdf = new Blob([new Uint8Array(10 * 1024 * 1024 + 1)], { type: 'application/pdf' });
    await expect(
      new ApiClient(t, fast).sendAgentMessage('agent-evidence-local', {
        content: 'oversize pdf',
        mode: 'evidence',
        attachments: [
          {
            id: 'a1',
            name: 'big.pdf',
            kind: 'pdf',
            sizeBytes: bigPdf.size,
            status: 'ready',
            sourceFile: bigPdf,
          },
        ],
      }),
    ).rejects.toMatchObject({ message: 'PDF 파일은 10MB 이하만 업로드할 수 있습니다.' });
    expect(t.calls).toBe(0);
  });

  it('sends novelty follow-up messages in real API mode (steering / on-demand)', async () => {
    const previous = process.env.NEXT_PUBLIC_DOCSURI_REAL_API;
    process.env.NEXT_PUBLIC_DOCSURI_REAL_API = '1';
    const requests: TransportRequest[] = [];
    const t = transportOf(async (req) => {
      requests.push(req);
      if (req.path === '/api/novelty/jobs/n1') {
        return {
          status: 200,
          body: {
            job: {
              jobId: 'n1',
              topic: 'follow up',
              state: 'completed',
              updatedAt: '2026-07-01T00:00:00Z',
            },
            events: [],
          },
        };
      }
      if (req.path === '/api/novelty/jobs/n1/messages') {
        return { status: 200, body: { messages: [] } };
      }
      if (req.path === '/api/novelty/jobs/n1/result') return { status: 404, body: null };
      return { status: 500, body: null };
    });
    try {
      await new ApiClient(t, fast).sendAgentMessage('novelty:n1', {
        content: 'follow up',
        mode: 'novelty',
      });
      // 분류(스티어링/온디맨드)는 서버가 한다 — 프론트는 같은 엔드포인트로 보낸다.
      const posted = requests.find((req) => req.method === 'POST');
      expect(posted?.path).toBe('/api/novelty/jobs/n1/messages');
      // novelty 대화 스키마는 content만 받는다(extra=forbid) — research와 달리
      // 첨부 키를 실으면 매 전송이 422가 되어 기능 전체가 죽는다. 키 존재를 못 박는다.
      expect(posted?.body).toEqual({ content: 'follow up' });
    } finally {
      if (previous === undefined) delete process.env.NEXT_PUBLIC_DOCSURI_REAL_API;
      else process.env.NEXT_PUBLIC_DOCSURI_REAL_API = previous;
    }
  });

  it('maps server-assigned message kind and artifact ref onto agent messages', async () => {
    const t = transportOf(async (req) => {
      if (req.path === '/api/novelty/jobs/n1') {
        return {
          status: 200,
          body: {
            job: {
              jobId: 'n1',
              topic: 'rag',
              state: 'completed',
              updatedAt: '2026-07-01T00:00:00Z',
            },
            events: [],
          },
        };
      }
      if (req.path === '/api/novelty/jobs/n1/messages') {
        return {
          status: 200,
          body: {
            messages: [
              {
                messageId: 'm1',
                role: 'user',
                kind: 'on_demand_request',
                content: '실험 계획 짜줘',
                createdAt: '2026-07-01T00:00:00Z',
              },
              {
                messageId: 'm2',
                role: 'agent',
                kind: 'agent_reply',
                content: '만들었어요',
                resultingArtifactRef: 'art-1',
                createdAt: '2026-07-01T00:00:01Z',
              },
              {
                messageId: 'm3',
                role: 'agent',
                kind: 'nonsense',
                content: '알 수 없는 분류',
                createdAt: '2026-07-01T00:00:02Z',
              },
            ],
          },
        };
      }
      if (req.path === '/api/novelty/jobs/n1/result') return { status: 404, body: null };
      return { status: 500, body: null };
    });

    const snapshot = await new ApiClient(t, fast).loadAgentSession('novelty:n1');

    expect(snapshot.messages[0].kind).toBe('on_demand_request');
    expect(snapshot.messages[1]).toMatchObject({
      kind: 'agent_reply',
      resultingArtifactRef: 'art-1',
    });
    // 알 수 없는 분류는 버린다 — 서버가 새 kind를 추가해도 렌더링이 깨지지 않는다.
    expect(snapshot.messages[2].kind).toBeUndefined();
  });
});
