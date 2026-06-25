'use client';

// useDocModel (D4, BR-SF-11) — fetches the structured doc-model for the rich view.
// real-first transport, in-flight dedup, OA-license-gated (same shape as useAssets).
//
// Lazy build (BR-30/D6): a cache miss returns `building` while U1 produces the doc-model
// asynchronously. The hook then POLLS — re-requesting with the server's `retryAfterMs`
// backoff — up to a bounded number of times, then gives up with a retryable message. The cap
// keeps a paper with no rich source (the ~10% non-HTML case, which never finishes building)
// from spinning forever, and keeps mobile from polling indefinitely.
import { useCallback, useEffect, useRef, useState } from 'react';
import { getApiClient, type DocModelOutcome } from '@/lib/api';
import type { DocModelRequest } from '@/types/generated';

const MAX_BUILD_POLLS = 6;
const DEFAULT_POLL_BACKOFF_MS = 2000;

export type DocModelState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'done'; outcome: DocModelOutcome };

export function useDocModel() {
  const [state, setState] = useState<DocModelState>({ status: 'idle' });
  const activeKey = useRef<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollCount = useRef(0);

  const clearTimer = () => {
    if (pollTimer.current !== null) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  };

  // One request cycle; on `building` it schedules the next poll (bounded) instead of settling.
  const fetchOnce = useCallback(async (req: DocModelRequest, key: string) => {
    try {
      const outcome = await getApiClient().getDocModel(req);
      if (activeKey.current !== key) return; // superseded by a newer load()
      if (outcome.kind === 'building') {
        pollCount.current += 1;
        if (pollCount.current >= MAX_BUILD_POLLS) {
          // Gave up waiting for the lazy build — terminal but retryable (onRetry → load()).
          activeKey.current = null;
          setState({
            status: 'done',
            outcome: { kind: 'error', message: '본문을 준비 중이에요. 잠시 후 다시 시도해 주세요.' },
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
      // Clear the dedup key so a retry (StateView onRetry → load(same req)) can re-fetch.
      activeKey.current = null;
      setState({ status: 'done', outcome: { kind: 'error', message: '본문을 불러올 수 없어요.' } });
    }
  }, []);

  const load = useCallback(
    // Stable identity (deps = [fetchOnce], itself []-stable): the viewer effect lists `load` as a
    // dependency, so a `load` that changed on every status transition re-fired the effect — and on
    // a terminal error the catch below clears `activeKey`, dropping the dedup guard — which together
    // spun an unbounded re-fetch loop (a single backend non-200 became a request storm → 429s).
    async (req: DocModelRequest) => {
      const key = JSON.stringify(req);
      // Dedup: a matching key means this req is already in-flight or settled. The error/give-up
      // paths clear `activeKey` (→ null) so a manual onRetry re-fetches; an idle hook has a null
      // key too, so the old `&& state.status !== 'idle'` clause was redundant (its only purpose was
      // to keep `state.status` referenced, which is exactly what made `load` unstable).
      if (activeKey.current === key) return;
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
    clearTimer();
    pollCount.current = 0;
    setState({ status: 'idle' });
  }, []);

  // Cancel any pending poll on unmount.
  useEffect(() => () => clearTimer(), []);

  return { state, load, reset };
}
