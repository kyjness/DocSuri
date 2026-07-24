import { describe, it, expect, vi } from 'vitest';
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

  it('survives a generation slower than the client default deadline', async () => {
    // A cold summary is 1-2 LLM calls and routinely outran the 10s default, which aborted a
    // request the backend went on to finish and cache — the user saw a failure, then an instant
    // success on retry. Every other test here injects `fast`, so the production deadline was
    // never exercised and the gap stayed invisible; this one uses the real client config.
    const DEFAULT_DEADLINE_MS = 10_000;
    vi.useFakeTimers();
    try {
      const t = transportOf(
        () =>
          new Promise<TransportResponse>((resolve) =>
            setTimeout(() => resolve({ status: 200, body: summaryOk }), DEFAULT_DEADLINE_MS + 5_000),
          ),
      );
      const client = new ApiClient(t); // no timeout override — production configuration
      const pending = client.summarize({ task: 'summary', paperId: 'x', version: 1 });
      await vi.advanceTimersByTimeAsync(DEFAULT_DEADLINE_MS + 5_000);
      await expect(pending).resolves.toMatchObject({ kind: 'summary' });
    } finally {
      vi.useRealTimers();
    }
  });
});
