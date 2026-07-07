'use client';

// GlossaryTermEditor — the tiny "내 번역어 지정" editor for the open glossary chip. The parent renders
// ONE of these per group and floats it as an absolute overlay directly below the tapped chip: it is
// out of flow (chips never move) and lives OUTSIDE the collapsed chip row's clip (so it shows even
// when the row is collapsed — no need to expand the whole list). Nothing is sent to the server here:
// 저장 stages the rendering into the parent draft; it only persists + reflects on the group's "반영"
// button. The confirmation auto-dismisses after a moment. `term` is external data, escaped by React.
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import styles from './GlossaryTermBadge.module.css';

// How long the "지정됨" confirmation lingers before the editor auto-closes.
const CONFIRM_DISMISS_MS = 2500;
// Gap between the chip's bottom and the editor overlay.
const ANCHOR_GAP_PX = 6;

interface GlossaryTermEditorProps {
  /** Panel id (matches the open chip's aria-controls). */
  id: string;
  term: string;
  /** Standard rendering to pre-fill for a mapping term (e.g. attention → 어텐션) when unset. */
  defaultValue?: string;
  /** The user's current rendering — pre-fills the input over ``defaultValue``. */
  saved?: string;
  /** True when this term has a PENDING draft edit — the editor then offers 지우기 to un-stage it. */
  pending?: boolean;
  /** The chip button this editor floats below. */
  anchor: HTMLButtonElement | null;
  /** The positioned group container the overlay is measured against. */
  container: HTMLElement | null;
  /** Stage the entered rendering into the parent draft (no network here). */
  onSave: (termTo: string) => void;
  /** Discard this term's pending draft edit (un-stage). */
  onClear: () => void;
  onClose: () => void;
}

export function GlossaryTermEditor({
  id,
  term,
  defaultValue = '',
  saved,
  pending = false,
  anchor,
  container,
  onSave,
  onClear,
  onClose,
}: GlossaryTermEditorProps) {
  // Latched on mount (= open): a late-arriving glossary fetch can change `saved` while typing, and
  // re-seeding then would clobber the in-progress draft. Mount == open, so the initializer is enough.
  const [value, setValue] = useState(() => saved ?? defaultValue);
  const [staged, setStaged] = useState(false);
  const [top, setTop] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Position the overlay right below the tapped chip. Re-measure on reflow (chips rewrap on resize,
  // moving the anchor) via a ResizeObserver on the group + window resize.
  useLayoutEffect(() => {
    if (!anchor || !container) return;
    const place = () => {
      const a = anchor.getBoundingClientRect();
      const c = container.getBoundingClientRect();
      setTop(a.bottom - c.top + ANCHOR_GAP_PX);
    };
    place();
    const ro = new ResizeObserver(place);
    ro.observe(container);
    window.addEventListener('resize', place);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', place);
    };
  }, [anchor, container]);

  // Focus the input once it's open (after paint so the overlay is positioned first).
  useEffect(() => {
    const raf = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(raf);
  }, []);

  // Auto-dismiss the confirmation: the group's "반영" button (not this note) is the durable cue.
  useEffect(() => {
    if (!staged) return;
    const t = setTimeout(onClose, CONFIRM_DISMISS_MS);
    return () => clearTimeout(t);
  }, [staged, onClose]);

  const save = () => {
    const termTo = value.trim();
    if (!termTo) return;
    onSave(termTo);
    setStaged(true);
  };

  return (
    <span
      id={id}
      className={styles.popover}
      style={{ top }}
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
              onClick={onClear}
              data-testid="glossary-clear"
            >
              지우기
            </button>
          ) : null}
        </>
      )}
    </span>
  );
}
