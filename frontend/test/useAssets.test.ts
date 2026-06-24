import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';

// Mock the api module so we can fail the first getAssets call and succeed the retry.
const getAssets = vi.fn();
vi.mock('@/lib/api', () => ({
  getApiClient: () => ({ getAssets }),
}));

import { useAssets } from '@/lib/useAssets';

describe('useAssets', () => {
  beforeEach(() => {
    getAssets.mockReset();
  });

  it('re-fetches on retry after a failure for the same paper/version', async () => {
    // First call rejects → error outcome; retry (same key) must hit the network again.
    getAssets
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({ kind: 'ok', assets: [] });

    const { result } = renderHook(() => useAssets());

    await act(async () => {
      await result.current.load('2401.00001', 1);
    });
    await waitFor(() => expect(result.current.state.status).toBe('done'));
    expect(result.current.state).toMatchObject({ outcome: { kind: 'error' } });
    expect(getAssets).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.load('2401.00001', 1); // onRetry path: same key
    });
    await waitFor(() =>
      expect(result.current.state).toMatchObject({ outcome: { kind: 'ok' } }),
    );
    expect(getAssets).toHaveBeenCalledTimes(2); // retry actually re-fetched
  });

  it('dedupes a successful load for the same paper/version', async () => {
    getAssets.mockResolvedValue({ kind: 'ok', assets: [] });
    const { result } = renderHook(() => useAssets());

    await act(async () => {
      await result.current.load('2401.00001', 1);
    });
    await act(async () => {
      await result.current.load('2401.00001', 1); // already loaded → no second fetch
    });
    expect(getAssets).toHaveBeenCalledTimes(1);
  });
});
