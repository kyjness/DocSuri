'use client';

// CollapsibleTerms — clamps a 개인 용어집 chip row to ~2 lines with a 더 보기 / 접기 toggle, so a
// paper with many kept terms doesn't push the translated text far down the page. The toggle appears
// only when the chips actually overflow the collapsed height. The chip editor is floated OUTSIDE
// this clip (by the parent), so opening a chip never needs to expand the whole row.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import styles from './CollapsibleTerms.module.css';

// ~2 rows of chips. Kept in sync with `.collapsed` max-height in the stylesheet.
const COLLAPSED_MAX_PX = 60;

export function CollapsibleTerms({ label, children }: { label: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [overflowing, setOverflowing] = useState(false);
  const [expanded, setExpanded] = useState(false);

  // Show the toggle only when the chips actually exceed ~2 rows. `scrollHeight` is the full content
  // height even while `.collapsed` clips it, so this holds in both states and re-measures on reflow.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setOverflowing(el.scrollHeight > COLLAPSED_MAX_PX + 1);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [children]);

  return (
    <div>
      <div ref={ref} className={`${styles.terms}${expanded ? '' : ` ${styles.collapsed}`}`}>
        {children}
      </div>
      {overflowing ? (
        <button
          type="button"
          className={styles.toggle}
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-label={expanded ? `${label} 접기` : `${label} 더 보기`}
          data-testid="glossary-collapse-toggle"
        >
          {expanded ? '접기' : '더 보기'}
        </button>
      ) : null}
    </div>
  );
}
