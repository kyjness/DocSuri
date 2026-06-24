'use client';

// GlossaryTermBadge (개인 용어집 Phase 1) — a kept-as-is term badge that, when open, shows a
// tiny inline editor to save the user's preferred Korean rendering via POST /api/glossary.
// Mock-first: getApiClient() routes to MockTransport in dev. Open state is CONTROLLED by the
// parent (TranslationView) so only one editor is open at a time and an outside click closes
// it. `term` is external data, escaped by React (XSS, BR-SF-9). Phase 1 has no auto-rerun and
// does not pre-fill an existing override (the translation response carries no saved value yet).
import { useEffect, useId, useRef, useState } from 'react';
import { getApiClient } from '@/lib/api';
import styles from './GlossaryTermBadge.module.css';

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

interface GlossaryTermBadgeProps {
  term: string;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  /** The user's previously saved rendering for this term, pre-filled on open (Phase 2a). */
  initialValue?: string;
  /** Notify the parent of a successful save so its term map stays in sync. */
  onSaved?: (termTo: string) => void;
}

export function GlossaryTermBadge({
  term,
  open,
  onOpen,
  onClose,
  initialValue = '',
  onSaved,
}: GlossaryTermBadgeProps) {
  const [value, setValue] = useState('');
  const [status, setStatus] = useState<SaveStatus>('idle');
  const inputRef = useRef<HTMLInputElement | null>(null);
  const wasOpenRef = useRef(false);
  const panelId = useId();

  // Pre-fill with the saved rendering only on the open transition, then focus. A late-arriving
  // glossary fetch can change initialValue while the editor is already open; re-running the
  // pre-fill then would clobber the user's in-progress draft, so we latch on open instead.
  // On close: reset the draft/state so a reopened badge re-reads initialValue afresh.
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setValue(initialValue);
      requestAnimationFrame(() => inputRef.current?.focus());
    } else if (!open) {
      setValue('');
      setStatus('idle');
    }
    wasOpenRef.current = open;
  }, [open, initialValue]);

  const save = async () => {
    const termTo = value.trim();
    if (!termTo || status === 'saving') return;
    setStatus('saving');
    try {
      await getApiClient().upsertGlossaryTerm({ termFrom: term, termTo });
      setStatus('saved');
      onSaved?.(termTo);
    } catch {
      setStatus('error');
    }
  };

  return (
    <span className={styles.wrap}>
      <button
        type="button"
        className={styles.term}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => (open ? onClose() : onOpen())}
        title="탭하여 내 번역어 지정"
        data-testid="glossary-badge"
      >
        {term}
      </button>

      {open ? (
        <span id={panelId} className={styles.popover} role="group" aria-label={`${term} 번역어 지정`}>
          {status === 'saved' ? (
            <span className={styles.savedNote} role="status" data-testid="glossary-saved">
              저장됨 · 다시 번역하면 반영돼요
            </span>
          ) : (
            <>
              <input
                ref={inputRef}
                className={styles.input}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void save();
                  if (e.key === 'Escape') onClose();
                }}
                placeholder={`${term} → 내 번역어`}
                aria-label={`${term}의 번역어`}
                maxLength={40}
                disabled={status === 'saving'}
                data-testid="glossary-input"
              />
              <button
                type="button"
                className={styles.save}
                onClick={() => void save()}
                disabled={!value.trim() || status === 'saving'}
                data-testid="glossary-save"
              >
                {status === 'saving' ? '저장 중…' : '저장'}
              </button>
            </>
          )}
          {status === 'error' ? (
            <span className={styles.error} role="alert">
              저장 실패 · 다시 시도해 주세요
            </span>
          ) : null}
        </span>
      ) : null}
    </span>
  );
}
