import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, renderHook, render } from '@testing-library/react';
import React from 'react';

// Mock the api module so we can script building → building → page (lazy build polling).
const getDocModel = vi.fn();
vi.mock('@/lib/api', () => ({
  getApiClient: () => ({ getDocModel }),
}));

import { useDocModel } from '@/lib/useDocModel';

const PAGE = {
  kind: 'page' as const,
  docModel: { meta: { paperId: 'x', version: 1 }, sections: [] },
  cached: false,
};

describe('useDocModel — lazy build polling (BR-30/D6)', () => {
  beforeEach(() => {
    getDocModel.mockReset();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('polls while building (backoff = retryAfterMs), then renders the page once built', async () => {
    getDocModel
      .mockResolvedValueOnce({ kind: 'building', retryAfterMs: 1000 })
      .mockResolvedValueOnce({ kind: 'building', retryAfterMs: 1000 })
      .mockResolvedValueOnce(PAGE);

    const { result } = renderHook(() => useDocModel());
    await act(async () => {
      await result.current.load({ paperId: 'x', version: 1 });
    });
    expect(result.current.state).toMatchObject({ status: 'done', outcome: { kind: 'building' } });
    expect(getDocModel).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000); // 2nd poll — still building
    });
    expect(getDocModel).toHaveBeenCalledTimes(2);
    expect(result.current.state).toMatchObject({ outcome: { kind: 'building' } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000); // 3rd poll — built
    });
    expect(getDocModel).toHaveBeenCalledTimes(3);
    expect(result.current.state).toMatchObject({ outcome: { kind: 'page' } });
  });

  it('gives up after the poll cap with a retryable error message', async () => {
    getDocModel.mockResolvedValue({ kind: 'building', retryAfterMs: 1000 });

    const { result } = renderHook(() => useDocModel());
    await act(async () => {
      await result.current.load({ paperId: 'x', version: 1 });
    });
    for (let i = 0; i < 6; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
    }
    expect(result.current.state).toMatchObject({ status: 'done', outcome: { kind: 'error' } });
    expect(getDocModel).toHaveBeenCalledTimes(6); // capped — does not spin forever
  });

  it('does not re-fetch in a loop when the request errors (stable load ref)', async () => {
    // A backend non-200 makes getApiClient().getDocModel throw → fetchOnce clears activeKey so a
    // manual retry can re-fetch. Regression: `load` used to change identity on every status
    // transition, and the viewer's effect lists `load` as a dependency — so a single error spun an
    // unbounded re-fetch loop (the 429 request storm). Mimic that effect here and assert it fires once.
    getDocModel.mockRejectedValue(new Error('boom')); // stands in for a 500/429

    function Harness() {
      const { state, load } = useDocModel();
      React.useEffect(() => {
        void load({ paperId: 'x', version: 1 });
      }, [load]); // same dependency shape as DocModelViewer's effect
      return React.createElement('div', null, state.status);
    }

    await act(async () => {
      render(React.createElement(Harness));
    });
    // Flush the rejected fetch + any resulting re-renders; a stable `load` must not re-trigger.
    await act(async () => {
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(getDocModel).toHaveBeenCalledTimes(1);
  });

  it('settles immediately when already built (no polling)', async () => {
    getDocModel.mockResolvedValue(PAGE);

    const { result } = renderHook(() => useDocModel());
    await act(async () => {
      await result.current.load({ paperId: 'x', version: 1 });
    });
    expect(result.current.state).toMatchObject({ outcome: { kind: 'page' } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(getDocModel).toHaveBeenCalledTimes(1); // no extra polls scheduled
  });
});
