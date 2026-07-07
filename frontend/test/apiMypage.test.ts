import { describe, it, expect } from 'vitest';
import { ApiClient } from '@/lib/api/apiClient';
import type { Transport, TransportRequest, TransportResponse } from '@/lib/api/transport';

// ApiClient U10 (mypage) methods — exercised against an injected transport so paths,
// methods, DTO passthrough and error normalization are asserted deterministically (no
// MockTransport). getSubscription/subscribe/cancelSubscription are REAL (backend/modules/
// mypage); the rest are MOCK-ONLY placeholders pending U3's real OAuth/profile/consent
// contract — same request() path, so the assertions hold either way.

const fast = { timeoutMs: 1000, retryBackoffMs: 1 };

function recorder(
  impl: (req: TransportRequest) => TransportResponse,
): { transport: Transport; calls: TransportRequest[] } {
  const calls: TransportRequest[] = [];
  return {
    calls,
    transport: {
      async send(req) {
        calls.push(req);
        return impl(req);
      },
    },
  };
}

describe('ApiClient mypage (U10) methods', () => {
  it('gets the current subscription (GET /mypage/subscription)', async () => {
    const r = recorder(() => ({ status: 200, body: { plan: 'FREE', status: 'NONE' } }));
    const sub = await new ApiClient(r.transport, fast).getSubscription();
    expect(sub).toEqual({ plan: 'FREE', status: 'NONE' });
    expect(r.calls[0]).toMatchObject({
      method: 'GET',
      path: '/mypage/subscription',
      idempotent: true,
    });
  });

  it('subscribes (POST /mypage/subscription, 201)', async () => {
    const body = { plan: 'PREMIUM', status: 'ACTIVE', startedAt: 'x', currentPeriodEnd: 'y' };
    const r = recorder(() => ({ status: 201, body }));
    const out = await new ApiClient(r.transport, fast).subscribe();
    expect(out).toEqual(body);
    expect(r.calls[0]).toMatchObject({
      method: 'POST',
      path: '/mypage/subscription',
      idempotent: false,
    });
  });

  it('cancels the subscription, retaining the period end (POST /mypage/subscription/cancel)', async () => {
    const body = { plan: 'PREMIUM', status: 'CANCELED', currentPeriodEnd: 'y', canceledAt: 'z' };
    const r = recorder(() => ({ status: 200, body }));
    const out = await new ApiClient(r.transport, fast).cancelSubscription();
    expect(out).toEqual(body);
    expect(r.calls[0]).toMatchObject({ method: 'POST', path: '/mypage/subscription/cancel' });
  });

  it('gets the account profile (GET /mypage/account-profile)', async () => {
    const body = { loginProvider: 'ORCID', createdAt: 'x' };
    const r = recorder(() => ({ status: 200, body }));
    const out = await new ApiClient(r.transport, fast).getAccountProfile();
    expect(out).toEqual(body);
  });

  it('returns null for the ORCID profile on 404 (not connected via ORCID)', async () => {
    const r = recorder(() => ({ status: 404, body: null }));
    const out = await new ApiClient(r.transport, fast).getOrcidProfile();
    expect(out).toBeNull();
  });

  it('lists recently-viewed papers (GET /mypage/recently-viewed)', async () => {
    const r = recorder(() => ({
      status: 200,
      body: { items: [{ arxivId: 'a', title: 't', viewedAt: 'x' }] },
    }));
    const out = await new ApiClient(r.transport, fast).getRecentlyViewed();
    expect(out).toHaveLength(1);
  });

  it('returns [] for recently-viewed on 404 (path not yet served — graceful)', async () => {
    const r = recorder(() => ({ status: 404, body: null }));
    const out = await new ApiClient(r.transport, fast).getRecentlyViewed();
    expect(out).toEqual([]);
  });

  it('updates the nightly-push consent (POST /mypage/consents)', async () => {
    const body = { privacyPolicyAgreed: true, termsOfServiceAgreed: true, nightlyPushAgreed: true };
    const r = recorder(() => ({ status: 200, body }));
    const out = await new ApiClient(r.transport, fast).updateNightlyPushConsent(true);
    expect(out).toEqual(body);
    expect(r.calls[0]).toMatchObject({
      method: 'POST',
      path: '/mypage/consents',
      body: { nightlyPushAgreed: true },
    });
  });

  it('gets and updates personalization settings through the U9 endpoint', async () => {
    const r = recorder((req) => ({
      status: 200,
      body: {
        userId: 'u1',
        enabled: req.method === 'PATCH' ? false : true,
        rawEventsDeletedAt: null,
        profileResetAt: null,
        updatedAt: '2026-06-25T00:00:00Z',
      },
    }));
    const client = new ApiClient(r.transport, fast);

    await expect(client.getPersonalizationSettings()).resolves.toMatchObject({ enabled: true });
    await expect(client.updatePersonalizationEnabled(false)).resolves.toMatchObject({
      enabled: false,
    });
    expect(r.calls[0]).toMatchObject({
      method: 'GET',
      path: '/api/personalization/settings',
      idempotent: true,
    });
    expect(r.calls[1]).toMatchObject({
      method: 'PATCH',
      path: '/api/personalization/settings',
      body: { enabled: false },
      idempotent: false,
    });
  });

  it('deletes personalization events through the U9 endpoint', async () => {
    const r = recorder(() => ({ status: 200, body: { deletedEvents: 3 } }));
    const out = await new ApiClient(r.transport, fast).deletePersonalizationEvents();
    expect(out).toEqual({ deletedEvents: 3 });
    expect(r.calls[0]).toMatchObject({
      method: 'POST',
      path: '/api/personalization/delete-events',
      idempotent: false,
    });
  });

  it('resets the personalization profile through the U9 endpoint', async () => {
    const r = recorder(() => ({ status: 200, body: { status: 'reset' } }));
    const out = await new ApiClient(r.transport, fast).resetPersonalizationProfile();
    expect(out).toEqual({ status: 'reset' });
    expect(r.calls[0]).toMatchObject({
      method: 'POST',
      path: '/api/personalization/reset-profile',
      idempotent: false,
    });
  });

  it('deletes the owner-scoped Notion connection', async () => {
    const r = recorder(() => ({ status: 204, body: null }));
    await expect(new ApiClient(r.transport, fast).deleteNotionConnection()).resolves.toBeUndefined();
    expect(r.calls[0]).toMatchObject({
      method: 'DELETE',
      path: '/api/novelty/notion/connection',
      idempotent: false,
    });
  });

  it('withdraws the account via the REAL U3 soft-delete (POST /auth/account/delete, 204)', async () => {
    const r = recorder(() => ({ status: 204, body: null }));
    await expect(new ApiClient(r.transport, fast).withdrawAccount()).resolves.toBeUndefined();
    expect(r.calls[0]).toMatchObject({ method: 'POST', path: '/auth/account/delete' });
  });

  it('normalizes a 401 to a user-facing auth error (fail-closed)', async () => {
    const r = recorder(() => ({ status: 401, body: null }));
    await expect(new ApiClient(r.transport, fast).getSubscription()).rejects.toMatchObject({
      kind: 'auth',
    });
  });
});
