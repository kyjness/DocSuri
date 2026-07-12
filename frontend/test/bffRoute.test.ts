import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// The route imports the server-only HttpTransport; neutralize the `server-only` guard so the
// handler can be exercised under the (jsdom) test runtime.
vi.mock('server-only', () => ({}));

// Pin the BFF onto a lightweight mock transport. DELETE returns the exact upstream shape
// (successful un-bookmark/delete/clear history) that used to become a 500 when
// NextResponse.json() attached a body to 204; PATCH locks settings updates through the BFF.
vi.mock('@/lib/api/mockTransport', () => ({
  MockTransport: class {
    async send(req: { method: string; body?: unknown }) {
      if (req.method === 'PATCH') {
        return {
          status: 200,
          body: {
            userId: 'mock-user',
            enabled: Boolean((req.body as { enabled?: unknown } | undefined)?.enabled),
            rawEventsDeletedAt: null,
            profileResetAt: null,
            updatedAt: '2026-06-25T00:00:00Z',
          },
          setCookies: [],
        };
      }
      return { status: 204, body: null, setCookies: [] };
    }
  },
}));

import { NextRequest } from 'next/server';
import { DELETE, GET, PATCH } from '@/app/bff/[...path]/route';

describe('BFF proxy (app/bff/[...path]/route)', () => {
  beforeEach(() => {
    delete process.env.DOCSURI_GATEWAY_URL; // unset → MockTransport (the stub above)
    delete process.env.DOCSURI_BFF_ALLOW_MOCK;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('relays an upstream 204 as a body-less 204 (not a 500)', async () => {
    const req = new NextRequest('http://localhost/bff/library/items/x', { method: 'DELETE' });
    const res = await DELETE(req, { params: Promise.resolve({ path: ['library', 'items', 'x'] }) });

    expect(res.status).toBe(204);
    expect(await res.text()).toBe('');
  });

  it('relays PATCH bodies for personalization settings updates', async () => {
    const req = new NextRequest('http://localhost/bff/api/personalization/settings', {
      method: 'PATCH',
      body: JSON.stringify({ enabled: false }),
      headers: { 'content-type': 'application/json' },
    });
    const res = await PATCH(req, {
      params: Promise.resolve({ path: ['api', 'personalization', 'settings'] }),
    });

    expect(res.status).toBe(200);
    await expect(res.json()).resolves.toMatchObject({ enabled: false });
  });

  it('passes Novelty event streams through without JSON parsing', async () => {
    process.env.DOCSURI_GATEWAY_URL = 'https://api.example.test';
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
      return new Response('event: progress\ndata: {"eventId":"evt-1"}\n\n', {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const req = new NextRequest('http://localhost/bff/api/novelty/jobs/job-1/events?after=evt-0', {
      method: 'GET',
      headers: { cookie: 'sid=abc' },
    });
    const res = await GET(req, {
      params: Promise.resolve({ path: ['api', 'novelty', 'jobs', 'job-1', 'events'] }),
    });
    const [url, init] = fetchMock.mock.calls[0];
    const headers = init?.headers as Headers;

    expect(String(url)).toBe(
      'https://api.example.test/api/novelty/jobs/job-1/events?after=evt-0',
    );
    expect(headers.get('accept')).toBe('text/event-stream');
    expect(headers.get('cookie')).toBe('sid=abc');
    expect(res.headers.get('content-type')).toContain('text/event-stream');
    await expect(res.text()).resolves.toContain('event: progress');
  });

  it('streams a sync evidence turn POST through the SSE hop (US-EV2)', async () => {
    process.env.DOCSURI_GATEWAY_URL = 'https://api.example.test';
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
      return new Response('event: progress\ndata: {"eventId":"e1"}\n\nevent: result\ndata: {}\n\n', {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { POST } = await import('@/app/bff/[...path]/route');
    const req = new NextRequest('http://localhost/bff/api/research/jobs', {
      method: 'POST',
      body: JSON.stringify({ content: '근거 질문' }),
      headers: {
        accept: 'text/event-stream',
        'content-type': 'application/json',
        cookie: 'sid=abc',
      },
    });
    const res = await POST(req, {
      params: Promise.resolve({ path: ['api', 'research', 'jobs'] }),
    });
    const [url, init] = fetchMock.mock.calls[0];
    const headers = init?.headers as Headers;

    expect(String(url)).toBe('https://api.example.test/api/research/jobs');
    expect(init?.method).toBe('POST');
    expect(headers.get('accept')).toBe('text/event-stream');
    expect(headers.get('content-type')).toBe('application/json');
    expect(headers.get('cookie')).toBe('sid=abc');
    expect(init?.body).toBe(JSON.stringify({ content: '근거 질문' }));
    expect(res.headers.get('content-type')).toContain('text/event-stream');
    await expect(res.text()).resolves.toContain('event: result');
  });

  it('falls through to the JSON proxy for turn SSE requests when no gateway is set (mock mode)', async () => {
    const { POST } = await import('@/app/bff/[...path]/route');
    const req = new NextRequest('http://localhost/bff/api/research/jobs', {
      method: 'POST',
      body: JSON.stringify({ content: 'mock turn' }),
      headers: { accept: 'text/event-stream', 'content-type': 'application/json' },
    });
    const res = await POST(req, {
      params: Promise.resolve({ path: ['api', 'research', 'jobs'] }),
    });

    // 스텁 MockTransport는 204를 돌려준다 — 핵심은 SSE 홉이 아니라 일반 proxy로 갔다는 것.
    expect(res.status).toBe(204);
    expect(res.headers.get('content-type') ?? '').not.toContain('text/event-stream');
  });

  it('fails closed in production when the gateway URL is missing', async () => {
    const previous = process.env.NODE_ENV;
    vi.stubEnv('NODE_ENV', 'production');
    try {
      const req = new NextRequest('http://localhost/bff/library/items/x', { method: 'DELETE' });
      const res = await DELETE(req, {
        params: Promise.resolve({ path: ['library', 'items', 'x'] }),
      });

      expect(res.status).toBe(503);
      await expect(res.json()).resolves.toMatchObject({
        message: '일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.',
      });
    } finally {
      vi.stubEnv('NODE_ENV', previous);
    }
  });
});
