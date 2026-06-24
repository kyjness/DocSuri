'use client';

// useSummarize (P1·P5, BR-SF-4/14) — drives one summarize/translate request to a
// terminal classified outcome. real-first: calls ApiClient -> real BFF transport
// (no production mock). In-flight dedup + stale-response guard; errors normalize
// to an `error` outcome so the surface never hangs (NFR-FR1, no infinite loading).
//
// Long summary (BR-S6/BR-S8): a MAP_REDUCE-band paper runs as a background job and the
// request returns `pending`. The hook then POLLS (server's retryAfterMs backoff) up to a
// bounded number of times, then gives up with a retryable message — so the surface never
// spins forever on a job that stalls.
import { useCallback, useEffect, useRef, useState } from 'react';
import { getApiClient, type SummarizeOutcome } from '@/lib/api';
import type { SummarizeRequest } from '@/types/generated';

// Long summaries (3-5 LLM calls) take longer than a doc-model build, so the cap is generous.
const MAX_SUMMARY_POLLS = 20;
const DEFAULT_POLL_BACKOFF_MS = 3000;

export type SummarizeState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'done'; outcome: SummarizeOutcome };

export function useSummarize() {
  const [state, setState] = useState<SummarizeState>({ status: 'idle' });
  // Identifies the latest request; completions for any other key are stale (P5).
  const activeKey = useRef<string | null>(null);
  // Key of the in-flight request, for dedup. Refs (not state) keep `run` stable so
  // effects that depend on it don't re-fire on every status change (no request loop).
  const inFlightKey = useRef<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollCount = useRef(0);

  const clearTimer = () => {
    if (pollTimer.current !== null) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  };

  // One request cycle; on `pending` it schedules the next poll (bounded) instead of settling.
  const fetchOnce = useCallback(async (req: SummarizeRequest, key: string) => {
    inFlightKey.current = key;
    try {
      const outcome = await getApiClient().summarize(req);
      if (activeKey.current !== key) return; // a newer request superseded this one
      if (outcome.kind === 'pending') {
        pollCount.current += 1;
        if (pollCount.current >= MAX_SUMMARY_POLLS) {
          setState({
            status: 'done',
            outcome: { kind: 'error', message: '요약을 준비 중이에요. 잠시 후 다시 시도해 주세요.' },
          });
          return;
        }
        setState({ status: 'done', outcome });
        const delay = outcome.retryAfterMs ?? DEFAULT_POLL_BACKOFF_MS;
        pollTimer.current = setTimeout(() => void fetchOnce(req, key), delay);
        return;
      }
      setState({ status: 'done', outcome });
    } catch {
      if (activeKey.current !== key) return;
      setState({ status: 'done', outcome: { kind: 'error', message: '문제가 발생했어요.' } });
    } finally {
      if (inFlightKey.current === key) inFlightKey.current = null;
    }
  }, []);

  const run = useCallback(
    async (req: SummarizeRequest) => {
      const key = JSON.stringify(req);
      if (inFlightKey.current === key) return; // dedup the same in-flight request (BR-SF-4)
      activeKey.current = key;
      clearTimer();
      pollCount.current = 0;
      setState({ status: 'loading' });
      await fetchOnce(req, key);
    },
    [fetchOnce],
  );

  const reset = useCallback(() => {
    activeKey.current = null;
    inFlightKey.current = null;
    clearTimer();
    pollCount.current = 0;
    setState({ status: 'idle' });
  }, []);

  // Cancel any pending poll on unmount.
  useEffect(() => () => clearTimer(), []);

  return { state, run, reset };
}
