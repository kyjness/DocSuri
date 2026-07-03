'use client';

// GlossaryTermBadge (개인 용어집) — a kept-term chip that opens a tiny inline editor to STAGE the
// user's preferred Korean rendering. Nothing is sent to the server here: the save button records the
// term into the parent's pending draft, and it only reaches the server (POST /api/glossary) + the
// translation when the user presses that group's "반영" button. So the confirmation just says it's
// staged, then auto-dismisses after a moment. The chip shows only the term; a chip with a pending or
// applied rendering is tinted (색: 미지정=파랑 / 내가 지정=주황) and that rendering pre-fills the
// editor on open. Open state is CONTROLLED by the parent so only one editor is open at a time. `term`
// is external data, escaped by React.
import { useEffect, useId, useRef, useState } from 'react';
import styles from './GlossaryTermBadge.module.css';

// How long the "지정됨" confirmation lingers before the editor auto-closes.
const CONFIRM_DISMISS_MS = 2500;

interface GlossaryTermBadgeProps {
  term: string;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  /** True for a 표준 용어 (seed keep-as-is or mapping): staged as a strong, prompt-enforced override
   * (reflected by re-generating the translation). False → weak read-time substitution. Only affects
   * how the parent stages/applies it; the editor itself is identical. */
  strong?: boolean;
  /** Standard rendering to pre-fill the editor when the user has no chosen rendering yet — used for
   * mapping terms (e.g. attention → 어텐션) so the editor starts from the standard value. */
  defaultValue?: string;
  /** The user's current rendering — a pending draft edit or a previously applied one (undefined =
   * none). Pre-fills the editor (over ``defaultValue``) and marks the chip as personalized. */
  saved?: string;
  /** True when this term has a PENDING (not-yet-applied) draft edit — the editor then offers 지우기
   * to un-stage it (an applied term is only cleared server-side, out of scope here). */
  pending?: boolean;
  /** Stage the entered rendering into the parent's pending draft (no network here). */
  onSave?: (termTo: string) => void;
  /** Discard this term's pending draft edit (un-stage). */
  onClear?: () => void;
}

export function GlossaryTermBadge({
  term,
  open,
  onOpen,
  onClose,
  strong = false,
  defaultValue = '',
  saved,
  pending = false,
  onSave,
  onClear,
}: GlossaryTermBadgeProps) {
  const [value, setValue] = useState('');
  const [staged, setStaged] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const wasOpenRef = useRef(false);
  const panelId = useId();

  // Pre-fill with the current rendering only on the open transition, then focus. A late-arriving
  // glossary fetch can change props while the editor is already open; re-running the pre-fill then
  // would clobber the user's in-progress draft, so we latch on open instead. On close: reset.
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setValue(saved ?? defaultValue);
      setStaged(false);
      requestAnimationFrame(() => inputRef.current?.focus());
    } else if (!open) {
      setValue('');
      setStaged(false);
    }
    wasOpenRef.current = open;
  }, [open, saved, defaultValue]);

  // Auto-dismiss the confirmation: the "반영" button (not this note) is the durable cue, so the
  // editor closes itself a moment after staging rather than lingering open.
  useEffect(() => {
    if (!staged) return;
    const t = setTimeout(onClose, CONFIRM_DISMISS_MS);
    return () => clearTimeout(t);
  }, [staged, onClose]);

  const save = () => {
    const termTo = value.trim();
    if (!termTo) return;
    onSave?.(termTo); // stage into the parent draft — persisted + reflected on "반영"
    setStaged(true);
  };

  return (
    <span className={styles.wrap}>
      <button
        type="button"
        className={styles.term}
        data-saved={saved ? 'true' : undefined}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => (open ? onClose() : onOpen())}
        title="탭하여 내 번역어 지정"
        data-testid="glossary-badge"
      >
        {term}
      </button>

      {open ? (
        <span
          id={panelId}
          className={styles.popover}
          role="group"
          aria-label={`${term} 번역어 지정`}
        >
          {staged ? (
            <span className={styles.savedNote} role="status" data-testid="glossary-saved">
              지정됨 · 아래 ‘반영’ 버튼을 누르면 번역에 반영돼요
            </span>
          ) : (
            <>
              <input
                ref={inputRef}
                className={styles.input}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') save();
                  if (e.key === 'Escape') onClose();
                }}
                placeholder={`${term} → 내 번역어`}
                aria-label={`${term}의 번역어`}
                maxLength={40}
                data-testid="glossary-input"
              />
              <button
                type="button"
                className={styles.save}
                onClick={save}
                disabled={!value.trim()}
                data-testid="glossary-save"
              >
                저장
              </button>
              {pending ? (
                <button
                  type="button"
                  className={styles.clear}
                  onClick={() => onClear?.()}
                  data-testid="glossary-clear"
                >
                  지우기
                </button>
              ) : null}
            </>
          )}
        </span>
      ) : null}
    </span>
  );
}
