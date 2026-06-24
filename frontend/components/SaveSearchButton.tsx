'use client';

import { useState } from 'react';
import { getApiClient } from '@/lib/api';
import styles from './library/Library.module.css';

// SaveSearchButton (US-L1, FR-8) — persists the just-executed query as a saved
// search. Resets to idle when the query changes (keyed by `query` from the parent).
export function SaveSearchButton({ query }: { query: string }) {
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  const onSave = async () => {
    if (state === 'saving' || state === 'saved') return;
    setState('saving');
    try {
      await getApiClient().saveSearch({ query });
      setState('saved');
    } catch {
      setState('error');
    }
  };

  const label = state === 'saved' ? '저장됨' : state === 'error' ? '재시도' : '검색어 저장';
  return (
    <button
      type="button"
      className={styles.action}
      onClick={() => void onSave()}
      disabled={state === 'saving' || state === 'saved'}
      data-testid="save-search"
    >
      {label}
    </button>
  );
}
