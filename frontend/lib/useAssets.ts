'use client';

// useAssets (FR-17) — fetches the figure/table manifest for a paper (signed URLs only).
// real-first BFF transport, mock in dev. Load-on-demand with per-(paper,version) dedup
// so the detail island can trigger it once.
import { useCallback, useRef, useState } from 'react';
import { getApiClient, type AssetsOutcome } from '@/lib/api';

export type AssetsState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'done'; outcome: AssetsOutcome };

export function useAssets() {
  const [state, setState] = useState<AssetsState>({ status: 'idle' });
  const activeKey = useRef<string | null>(null);

  const load = useCallback(
    async (paperId: string, version: number) => {
      const key = `${paperId}@${version}`;
      if (activeKey.current === key) return; // dedup: already loading / loaded for this paper
      activeKey.current = key;
      setState({ status: 'loading' });
      try {
        const outcome = await getApiClient().getAssets(paperId, version);
        if (activeKey.current !== key) return;
        setState({ status: 'done', outcome });
      } catch {
        if (activeKey.current !== key) return;
        // Clear the dedup key so retry (onRetry → load(same paper,version)) can re-fetch;
        // the key only guards in-flight / successfully-loaded requests, not failed ones.
        activeKey.current = null;
        setState({
          status: 'done',
          outcome: { kind: 'error', message: '그림·도표를 불러올 수 없어요.' },
        });
      }
    },
    [],
  );

  return { state, load };
}
