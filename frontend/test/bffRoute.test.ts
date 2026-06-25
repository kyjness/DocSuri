import { describe, it, expect, beforeEach, vi } from 'vitest';

// The route imports the server-only HttpTransport; neutralize the `server-only` guard so the
// handler can be exercised under the (jsdom) test runtime.
vi.mock('server-only', () => ({}));

// Pin the BFF onto the mock transport and stub it to return 204 No Content — the exact upstream
// shape (a successful DELETE: un-bookmark / delete saved search / clear history) that used to be
// turned into a 500 by NextResponse.json() attaching a body to a 204. Locks the route-level fix.
vi.mock('@/lib/api/mockTransport', () => ({
  MockTransport: class {
    async send() {
      return { status: 204, body: null, setCookies: [] };
    }
  },
}));

import { NextRequest } from 'next/server';
import { DELETE } from '@/app/bff/[...path]/route';

describe('BFF proxy (app/bff/[...path]/route)', () => {
  beforeEach(() => {
    delete process.env.DOCSURI_GATEWAY_URL; // unset → MockTransport (the stub above)
  });

  it('relays an upstream 204 as a body-less 204 (not a 500)', async () => {
    const req = new NextRequest('http://localhost/bff/library/items/x', { method: 'DELETE' });
    const res = await DELETE(req, { params: Promise.resolve({ path: ['library', 'items', 'x'] }) });

    expect(res.status).toBe(204);
    expect(await res.text()).toBe('');
  });
});
