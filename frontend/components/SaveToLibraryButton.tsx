'use client';

import { useState } from 'react';
import { getApiClient } from '@/lib/api';
import styles from './SaveToLibraryButton.module.css';

// SaveToLibraryButton (US-L2, FR-9) — toggles the paper in the user's library with a
// preserved meta snapshot (BR-L5; no internal score, SEC-9). Add is idempotent
// server-side and returns the library item id, which we keep to allow un-saving with a
// second press (remove). Rendered as a bookmark icon (a result card's top-right corner,
// or the paper detail header); aria-pressed conveys the saved state and the icon fills
// once saved. Only an in-flight request disables the button — a saved paper stays
// pressable so it can be un-saved.

// Minimal save target — satisfied by ResultCardVM and by the detail page's PaperMeta.
export interface SaveTarget {
  arxivId: string;
  title: string;
  authors: string[];
  year?: number | null;
  abstractSnippet?: string;
  arxivUrl?: string;
}

type SaveState = 'idle' | 'saving' | 'saved' | 'removing' | 'error';

export function SaveToLibraryButton({ card }: { card: SaveTarget }) {
  const [state, setState] = useState<SaveState>('idle');
  // Library item id captured from the (idempotent) add response — needed to un-save.
  const [itemId, setItemId] = useState<string | null>(null);

  const onToggle = async () => {
    if (state === 'saving' || state === 'removing') return; // ignore while a request is in flight

    // Un-save: a second press removes the saved item.
    if (state === 'saved') {
      if (!itemId) return;
      setState('removing');
      try {
        await getApiClient().removeFromLibrary(itemId);
        setItemId(null);
        setState('idle');
      } catch {
        setState('saved'); // removal failed → still in the library
      }
      return;
    }

    // Save (from idle/error). Idempotent server-side; returns the item with its id.
    setState('saving');
    try {
      const item = await getApiClient().addToLibrary({
        arXivId: card.arxivId,
        meta: {
          title: card.title,
          authors: card.authors,
          year: card.year ?? null,
          arxivId: card.arxivId,
          abstractSnippet: card.abstractSnippet ?? '',
          arxivUrl: card.arxivUrl ?? '',
        },
      });
      setItemId(item.id != null ? String(item.id) : null);
      setState('saved');
    } catch {
      setState('error');
    }
  };

  const saved = state === 'saved';
  const busy = state === 'saving' || state === 'removing';
  const label = saved
    ? '라이브러리에서 빼기'
    : state === 'removing'
      ? '빼는 중'
      : state === 'error'
        ? '담기 실패 — 다시 시도'
        : state === 'saving'
          ? '담는 중'
          : '라이브러리에 담기';

  return (
    <button
      type="button"
      className={styles.bookmark}
      data-state={state}
      onClick={() => void onToggle()}
      disabled={busy}
      aria-pressed={saved}
      aria-label={label}
      title={label}
      data-testid="save-to-library"
    >
      <svg
        className={styles.icon}
        width="20"
        height="20"
        viewBox="0 0 24 24"
        aria-hidden="true"
        fill={saved ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4-7 4V4a1 1 0 0 1 1-1z" />
      </svg>
    </button>
  );
}
