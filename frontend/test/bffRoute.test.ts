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

  it('streams evidence turn events (GET) through the SSE hop (v3 §5.3)', async () => {
    process.env.DOCSURI_GATEWAY_URL = 'https://api.example.test';
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
      return new Response('event: progress\ndata: {"eventId":"e1"}\n\nevent: result\ndata: {}\n\n', {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { GET } = await import('@/app/bff/[...path]/route');
    const req = new NextRequest('http://localhost/bff/api/evidence/turns/t-1/events?after=3', {
      method: 'GET',
      headers: { accept: 'text/event-stream', cookie: 'sid=abc' },
    });
    const res = await GET(req, {
      params: Promise.resolve({ path: ['api', 'evidence', 'turns', 't-1', 'events'] }),
    });
    const [url, init] = fetchMock.mock.calls[0];
    const headers = init?.headers as Headers;

    expect(String(url)).toBe('https://api.example.test/api/evidence/turns/t-1/events?after=3');
    expect(init?.method).toBe('GET');
    expect(headers.get('accept')).toBe('text/event-stream');
    expect(headers.get('cookie')).toBe('sid=abc');
    expect(res.headers.get('content-type')).toContain('text/event-stream');
    await expect(res.text()).resolves.toContain('event: result');
  });

  it('falls through to the JSON proxy for turn events when no gateway is set (mock mode)', async () => {
    const { GET } = await import('@/app/bff/[...path]/route');
    const req = new NextRequest('http://localhost/bff/api/evidence/turns/t-1/events', {
      method: 'GET',
      headers: { accept: 'text/event-stream' },
    });
    const res = await GET(req, {
      params: Promise.resolve({ path: ['api', 'evidence', 'turns', 't-1', 'events'] }),
    });

    // 핵심은 SSE 홉이 아니라 일반 proxy로 갔다는 것 — MockTransport가 JSON으로 답한다.
    expect(res.headers.get('content-type') ?? '').not.toContain('text/event-stream');
  });

  it('does not treat the turn accept POST as a stream', async () => {
    process.env.DOCSURI_GATEWAY_URL = 'https://api.example.test';
    const fetchMock = vi.fn(async () => new Response('{}', { status: 202 }));
    vi.stubGlobal('fetch', fetchMock);
    const { POST } = await import('@/app/bff/[...path]/route');
    const req = new NextRequest('http://localhost/bff/api/evidence/turns', {
      method: 'POST',
      body: JSON.stringify({ topic: '근거 질문' }),
      headers: { accept: 'text/event-stream', 'content-type': 'application/json' },
    });
    const res = await POST(req, {
      params: Promise.resolve({ path: ['api', 'evidence', 'turns'] }),
    });
    expect(res.headers.get('content-type') ?? '').not.toContain('text/event-stream');
  });

  // 이 홉을 넘으면 게이트웨이가 보는 클라이언트는 프론트 컨테이너다. XFF를 안 넘기면
  // 백엔드의 레이트 리미터가 전 방문자를 IP 하나로 묶어 사이트 전체가 한 버킷을 나눠 쓴다
  // (배포본 실측: API 271건 중 429가 43건 — 화면에는 헤더가 통째로 빠진 상세 페이지로 보였다).
  it('forwards the client address Caddy stamped (JSON proxy)', async () => {
    process.env.DOCSURI_GATEWAY_URL = 'https://api.example.test';
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) => new Response('{}', { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { GET } = await import('@/app/bff/[...path]/route');
    const req = new NextRequest('http://localhost/bff/api/papers/1706.03762v7', {
      method: 'GET',
      headers: { cookie: 'sid=abc', 'x-forwarded-for': '203.0.113.9' },
    });
    await GET(req, {
      params: Promise.resolve({ path: ['api', 'papers', '1706.03762v7'] }),
    });

    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init?.headers).get('x-forwarded-for')).toBe('203.0.113.9');
  });

  it('passes a spoofed hop through untouched so the backend can count from the right', async () => {
    // Caddy는 클라이언트가 보낸 XFF를 지우지 않고 append한다. 백엔드가 오른쪽에서 세므로
    // 위조 hop이 앞에 붙어 있어도 잡히는 것은 실제 주소다 — 여기서 hop을 더 붙이거나
    // 앞부분을 잘라내면 그 셈이 어긋난다.
    process.env.DOCSURI_GATEWAY_URL = 'https://api.example.test';
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) => new Response('{}', { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { GET } = await import('@/app/bff/[...path]/route');
    const req = new NextRequest('http://localhost/bff/api/search', {
      method: 'GET',
      headers: { 'x-forwarded-for': '10.0.0.1, 203.0.113.9' },
    });
    await GET(req, { params: Promise.resolve({ path: ['api', 'search'] }) });

    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init?.headers).get('x-forwarded-for')).toBe('10.0.0.1, 203.0.113.9');
  });

  it('forwards the client address on the SSE hop too', async () => {
    process.env.DOCSURI_GATEWAY_URL = 'https://api.example.test';
    const fetchMock = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) =>
        new Response('event: progress\ndata: {}\n\n', {
          status: 200,
          headers: { 'content-type': 'text/event-stream' },
        }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const { GET } = await import('@/app/bff/[...path]/route');
    const req = new NextRequest('http://localhost/bff/api/evidence/turns/t-1/events', {
      method: 'GET',
      headers: { cookie: 'sid=abc', 'x-forwarded-for': '203.0.113.9' },
    });
    await GET(req, {
      params: Promise.resolve({ path: ['api', 'evidence', 'turns', 't-1', 'events'] }),
    });

    const [, init] = fetchMock.mock.calls[0];
    expect((init?.headers as Headers).get('x-forwarded-for')).toBe('203.0.113.9');
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
