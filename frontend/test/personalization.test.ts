import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiClient } from '@/lib/api/apiClient';
import type { Transport, TransportRequest, TransportResponse } from '@/lib/api/transport';

const recordBehaviorEvent = vi.hoisted(() => vi.fn());

vi.mock('@/lib/api', () => ({
  getApiClient: () => ({ recordBehaviorEvent }),
}));

import {
  recordGlossaryUpdated,
  recordPaperOpened,
  recordReadCompleted,
  recordSearchExecuted,
} from '@/lib/personalization';

const fast = { timeoutMs: 1000, retryBackoffMs: 1 };

function recorder(impl: (req: TransportRequest) => TransportResponse): {
  transport: Transport;
  calls: TransportRequest[];
} {
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

describe('ApiClient personalization methods', () => {
  beforeEach(() => {
    recordBehaviorEvent.mockReset();
    recordBehaviorEvent.mockResolvedValue({ recorded: true, duplicate: false, reason: 'recorded' });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('records behavior events through the U9 endpoint', async () => {
    const r = recorder(() => ({
      status: 200,
      body: { recorded: true, duplicate: false, reason: 'recorded' },
    }));
    const out = await new ApiClient(r.transport, fast).recordBehaviorEvent({
      eventType: 'paper_opened',
      subject: { kind: 'paper', paperId: '2401.1' },
      source: 'frontend_anchor',
      metadata: { entrySurface: 'detail' },
      dedupeKey: 'd1',
    });

    expect(out.recorded).toBe(true);
    expect(r.calls[0]).toMatchObject({
      method: 'POST',
      path: '/api/personalization/events',
      idempotent: false,
    });
  });

  it('uses stable dedupe keys inside a short duplicate window', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-25T00:00:15Z'));

    recordSearchExecuted(' Attention ', 2);
    recordSearchExecuted('attention', 2);

    expect(recordBehaviorEvent).toHaveBeenCalledTimes(2);
    expect(recordBehaviorEvent.mock.calls[0][0].dedupeKey).toBe(
      recordBehaviorEvent.mock.calls[1][0].dedupeKey,
    );

    vi.setSystemTime(new Date('2026-06-25T00:00:31Z'));
    recordSearchExecuted('attention', 2);

    expect(recordBehaviorEvent.mock.calls[2][0].dedupeKey).not.toBe(
      recordBehaviorEvent.mock.calls[0][0].dedupeKey,
    );
  });

  it('records glossary update events without raw term text', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-25T00:00:00Z'));

    recordGlossaryUpdated(7);

    expect(recordBehaviorEvent).toHaveBeenCalledWith({
      eventType: 'glossary_updated',
      subject: { kind: 'glossary' },
      source: 'frontend_anchor',
      metadata: { glossaryVersion: 7 },
      dedupeKey: 'glossary:7:59411520',
    });
  });

  it('records version-scoped KPI funnel events', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-25T00:00:00Z'));

    recordPaperOpened('2401.1', 2);
    recordReadCompleted('2401.1', 2);

    expect(recordBehaviorEvent).toHaveBeenNthCalledWith(1, {
      eventType: 'paper_opened',
      subject: { kind: 'paper', paperId: '2401.1' },
      source: 'frontend_anchor',
      metadata: { entrySurface: 'detail' },
      dedupeKey: 'paper:2401.1:v2:59411520',
    });
    expect(recordBehaviorEvent).toHaveBeenNthCalledWith(2, {
      eventType: 'read_completed',
      subject: { kind: 'paper', paperId: '2401.1' },
      source: 'frontend_anchor',
      metadata: { entrySurface: 'detail' },
      dedupeKey: 'read:2401.1:v2:59411520',
    });
  });
});
