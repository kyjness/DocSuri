import { describe, it, expect, beforeEach, vi } from 'vitest';

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
import { DELETE, PATCH } from '@/app/bff/[...path]/route';

describe('BFF proxy (app/bff/[...path]/route)', () => {
  beforeEach(() => {
    delete process.env.DOCSURI_GATEWAY_URL; // unset → MockTransport (the stub above)
    delete process.env.DOCSURI_BFF_ALLOW_MOCK;
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
