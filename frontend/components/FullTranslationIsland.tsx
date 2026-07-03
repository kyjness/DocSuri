'use client';

// FullTranslationIsland — the 본문 번역 surface as its OWN window (not a modal), mirroring
// the doc-model 본문 route. Runs useSummarize(task=translate, scope=full) and maps the
// outcome union to the translation view / state surfaces (BR-SF-14, no infinite loading).
// External text escaped by React (BR-SF-9). real-first: real BFF transport, mock in dev.
import { useEffect, useMemo } from 'react';
import type { AssetRef } from '@/types/generated';
import { useSummarize } from '@/lib/useSummarize';
import { useAssets } from '@/lib/useAssets';
import { TranslationView } from './TranslationView';
import { StateView } from './StateView';

export function FullTranslationIsland({ paperId, version }: { paperId: string; version: number }) {
  const { state, run } = useSummarize();
  const { state: assetState, load: loadAssets } = useAssets();

  const request = { task: 'translate', paperId, version, scope: 'full' } as const;
  useEffect(() => {
    void run(request);
    void loadAssets(paperId, version); // figures in the translated doc-model join these by assetId
    // eslint-disable-next-line react-hooks/exhaustive-deps -- request is derived from these
  }, [paperId, version, run, loadAssets]);

  // Map assetId → signed asset so the translated doc-model's figure blocks render their images.
  const assetsById = useMemo(() => {
    const map = new Map<string, AssetRef>();
    if (assetState.status === 'done' && assetState.outcome.kind === 'assets') {
      for (const a of assetState.outcome.assets) map.set(a.assetId, a);
    }
    return map;
  }, [assetState]);

  const retry = () => void run(request);

  if (state.status === 'idle' || state.status === 'loading') {
    return (
      <StateView
        kind="loading"
        title="전문 번역 중… (시간이 걸릴 수 있어요)"
        message="잠시만 기다려 주세요."
      />
    );
  }

  const { outcome } = state;
  switch (outcome.kind) {
    case 'translation':
      return (
        <TranslationView
          translation={outcome.translation}
          cached={outcome.cached}
          showGlossary
          assetsById={assetsById}
          // Re-run so a just-applied glossary group reflects: weak terms as a read-time overlay on
          // the cached base, strong terms as a fresh (cache-miss) re-translation. `run` no-ops only
          // while the same request is in-flight; here it settled, so this re-issues (or gets
          // `pending`, which the hook then polls).
          onRegenerate={retry}
        />
      );
    case 'summary':
      return <StateView kind="error" message="예상치 못한 결과예요." onRetry={retry} />;
    case 'pending':
      // Reached ONLY when the API returned `pending` — the full-text translation was dispatched to
      // a background job (multi-chunk, tens of seconds) and the hook polls until ready (the inline
      // `loading` state above covers short waits). So tell the user it's running in the background.
      return (
        <StateView
          kind="loading"
          title="번역 생성 중…"
          message="AI가 백그라운드에서 논문을 번역하고 있어요. 논문이 길면 시간이 걸릴 수 있어요. 완료되면 여기에 표시돼요."
        />
      );
    case 'abstain':
      return <StateView kind="abstain" message="근거가 부족해 번역을 보류했어요." />;
    case 'degraded':
      return <StateView kind="degraded" message={outcome.message} onRetry={retry} />;
    case 'sourceUnavailable':
      return <StateView kind="sourceUnavailable" />;
    case 'invalid':
      return <StateView kind="invalid" message={outcome.message} />;
    case 'error':
      return <StateView kind="error" message={outcome.message} onRetry={retry} />;
  }
}
