'use client';

import { useEffect, useState } from 'react';
import { getApiClient } from '@/lib/api';
import styles from './library/Library.module.css';

// SaveSearchButton (US-L1, FR-8) — persists the just-executed query as a saved
// search. Checks on mount whether the query is already saved (first page only).
export function SaveSearchButton({ query }: { query: string }) {
  const [state, setState] = useState<'checking' | 'idle' | 'saving' | 'saved' | 'error'>('checking');

  useEffect(() => {
    let cancelled = false;
    getApiClient()
      .listSavedSearches({ query })
      .then((page) => {
        if (cancelled) return;
        setState(page.items.length > 0 ? 'saved' : 'idle');
      })
      .catch(() => {
        if (!cancelled) setState('idle');
      });
    return () => {
      cancelled = true;
    };
  }, [query]);

  const onSave = async () => {
    if (state !== 'idle' && state !== 'error') return;
    setState('saving');
    try {
      await getApiClient().saveSearch({ query });
      setState('saved');
    } catch {
      setState('error');
    }
  };

  if (state === 'checking') return null;

  const label = state === 'saved' ? '저장됨' : state === 'saving' ? '저장 중…' : state === 'error' ? '재시도' : '검색어 저장';
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
