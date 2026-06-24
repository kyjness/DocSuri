import { describe, it, expect } from 'vitest';
import { ApiClient } from '@/lib/api/apiClient';
import type { Transport, TransportRequest, TransportResponse } from '@/lib/api/transport';
import type { SummarizeRequest } from '@/types/generated';

// Test-only stub Transport (real-first: production has no mock transport).
function transportOf(impl: (req: TransportRequest) => Promise<TransportResponse>): Transport & {
  last?: TransportRequest;
} {
  const t: Transport & { last?: TransportRequest } = {
    async send(req: TransportRequest) {
      t.last = req;
      return impl(req);
    },
  };
  return t;
}

const fast = { timeoutMs: 1000, retryBackoffMs: 1 };

const summaryOk = {
  status: 'ok',
  task: 'summary',
  meta: {},
  cached: false,
  summary: {
    tldr: 't',
    contributions: [],
    method: 'm',
    results: 'r',
    limitations: 'l',
    reproducibility: { code: 'c', data: 'd' },
    anchors: [],
  },
};

describe('ApiClient.summarize (real-first transport seam)', () => {
  it('POSTs /api/summarize and returns a classified outcome', async () => {
    const t = transportOf(async () => ({ status: 200, body: summaryOk }));
    const client = new ApiClient(t, fast);
    const req: SummarizeRequest = { task: 'summary', paperId: '2401.00001', version: 1, persona: 'expert' };
    const out = await client.summarize(req);
    expect(out.kind).toBe('summary');
    expect(t.last?.method).toBe('POST');
    expect(t.last?.path).toBe('/api/summarize');
  });

  it('maps a 400 body to invalid (fail-closed)', async () => {
    const t = transportOf(async () => ({ status: 400, body: { message: '입력 오류' } }));
    const client = new ApiClient(t, fast);
    const out = await client.summarize({ task: 'summary', paperId: 'x', version: 1 });
    expect(out.kind).toBe('invalid');
  });
});
