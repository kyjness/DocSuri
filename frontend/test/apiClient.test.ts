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
      return { status: 200, body: pageResponse };
    });
    const client = new ApiClient(t, fast);
    const [a, b] = await Promise.all([client.search('같은질의'), client.search('같은질의')]);
    expect(a.kind).toBe('page');
    expect(b.kind).toBe('page');
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
