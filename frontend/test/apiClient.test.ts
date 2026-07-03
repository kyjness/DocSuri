import { describe, it, expect, vi } from 'vitest';
import { ApiClient } from '@/lib/api/apiClient';
import { UserFacingError } from '@/lib/api/errors';
import type { Transport, TransportRequest, TransportResponse } from '@/lib/api/transport';
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
    const t = transportOf(async () => (++n === 1 ? { status: 500, body: null } : { status: 200, body: { userId: 'u', expiresAt: 'x' } }));
    const client = new ApiClient(t, fast);
    const session = await client.currentSession();
    expect(session).toEqual({ userId: 'u', expiresAt: 'x' });
    expect(t.calls).toBe(2);
  });

  it('does NOT retry a state-changing POST', async () => {
    const t = transportOf(async () => ({ status: 500, body: null }));
    const client = new ApiClient(t, fast);
    await expect(client.signup({ email: 'a@b.co', password: 'x' })).rejects.toBeInstanceOf(UserFacingError);
    expect(t.calls).toBe(1);
  });

  it('surfaces a backend {detail} 400 reason (FastAPI envelope), not the generic fallback', async () => {
    // Module HTTPExceptions serialize as {detail}; the frontend must read it (regression guard
    // for the "signup blocked" incident where {detail} was swallowed into "문제가 발생했습니다").
    const t = transportOf(async () => ({ status: 400, body: { detail: '이미 등록된 이메일 주소입니다.' } }));
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
    await new ApiClient(t, fast).login({ email: 'a@b.co', password: 'Abcdef123!' }, 'captcha-token');
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

  it('blocks real novelty manuscript sends until an upload handle exists', async () => {
    const previous = process.env.NEXT_PUBLIC_DOCSURI_REAL_API;
    process.env.NEXT_PUBLIC_DOCSURI_REAL_API = '1';
    const t = transportOf(async () => ({ status: 200, body: null }));
    try {
      await expect(
        new ApiClient(t, fast).sendAgentMessage('agent-novelty-local', {
          content: 'manuscript check',
          mode: 'novelty',
          attachments: [
            {
              id: 'a1',
              name: 'draft.pdf',
              kind: 'pdf',
              sizeBytes: 100,
              status: 'ready',
            },
          ],
        }),
      ).rejects.toMatchObject({
        message: '파일 업로드 연동 전에는 Novelty 첨부 분석을 사용할 수 없습니다.',
      });
      expect(t.calls).toBe(0);
    } finally {
      if (previous === undefined) delete process.env.NEXT_PUBLIC_DOCSURI_REAL_API;
      else process.env.NEXT_PUBLIC_DOCSURI_REAL_API = previous;
    }
  });

  it('blocks real novelty follow-up sends until the backend can re-dispatch jobs', async () => {
    const previous = process.env.NEXT_PUBLIC_DOCSURI_REAL_API;
    process.env.NEXT_PUBLIC_DOCSURI_REAL_API = '1';
    const t = transportOf(async () => ({ status: 200, body: null }));
    try {
      await expect(
        new ApiClient(t, fast).sendAgentMessage('novelty:n1', {
          content: 'follow up',
          mode: 'novelty',
        }),
      ).rejects.toMatchObject({
        message: 'Novelty 후속 대화는 아직 실배포에서 사용할 수 없습니다.',
      });
      expect(t.calls).toBe(0);
    } finally {
      if (previous === undefined) delete process.env.NEXT_PUBLIC_DOCSURI_REAL_API;
      else process.env.NEXT_PUBLIC_DOCSURI_REAL_API = previous;
    }
  });
});
