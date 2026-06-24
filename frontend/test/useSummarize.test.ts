import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, renderHook } from '@testing-library/react';

// Mock the api module so we can script pending → pending → summary (long-summary polling).
const summarize = vi.fn();
vi.mock('@/lib/api', () => ({
  getApiClient: () => ({ summarize }),
}));

import { useSummarize } from '@/lib/useSummarize';

const SUMMARY = {
  kind: 'summary' as const,
  summary: { tldr: 't' },
  meta: { source: 'full_text' },
  cached: false,
};
const REQ = { paperId: 'x', version: 1, task: 'summary' } as never;

describe('useSummarize — long-summary polling (BR-S6/BR-S8)', () => {
  beforeEach(() => {
    summarize.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('polls while pending, then settles on the summary once the job finishes', async () => {
    summarize
      .mockResolvedValueOnce({ kind: 'pending', retryAfterMs: 1000 })
      .mockResolvedValueOnce({ kind: 'pending', retryAfterMs: 1000 })
      .mockResolvedValueOnce(SUMMARY);

    const { result } = renderHook(() => useSummarize());
    await act(async () => {
      await result.current.run(REQ);
    });
    expect(result.current.state).toMatchObject({ status: 'done', outcome: { kind: 'pending' } });
    expect(summarize).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(summarize).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(summarize).toHaveBeenCalledTimes(3);
    expect(result.current.state).toMatchObject({ outcome: { kind: 'summary' } });
  });

  it('settles immediately for a short summary (no polling)', async () => {
    summarize.mockResolvedValue(SUMMARY);
    const { result } = renderHook(() => useSummarize());
    await act(async () => {
      await result.current.run(REQ);
    });
    expect(result.current.state).toMatchObject({ outcome: { kind: 'summary' } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(summarize).toHaveBeenCalledTimes(1); // no extra polls
  });
});
