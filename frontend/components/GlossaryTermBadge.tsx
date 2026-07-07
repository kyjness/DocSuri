'use client';

// GlossaryTermBadge (개인 용어집) — a kept-term chip. Tapping it opens the shared inline editor
// (`GlossaryTermEditor`) that the parent floats directly below this chip, so the chips themselves
// never reflow. The chip only reports open/close and its own DOM node (the anchor the editor
// positions against); all staging/persisting lives in the parent. A chip with a pending or applied
// rendering is tinted (파랑=미지정 / 주황=내가 지정). `term` is external data, escaped by React.
import styles from './GlossaryTermBadge.module.css';

interface GlossaryTermBadgeProps {
  term: string;
  open: boolean;
  /** The user's current rendering (pending draft or applied); when set, the chip is tinted amber. */
  saved?: string;
  /** id of the editor panel this chip controls while open (a11y: aria-controls). */
  controlsId?: string;
  /** Open the editor for this term; receives the chip element so the parent can anchor the editor. */
  onOpen: (anchor: HTMLButtonElement) => void;
  onClose: () => void;
}

export function GlossaryTermBadge({
  term,
  open,
  saved,
  controlsId,
  onOpen,
  onClose,
}: GlossaryTermBadgeProps) {
  return (
    <button
      type="button"
      className={styles.term}
      data-saved={saved ? 'true' : undefined}
      aria-expanded={open}
      aria-controls={open ? controlsId : undefined}
      onClick={(e) => (open ? onClose() : onOpen(e.currentTarget))}
      title="탭하여 내 번역어 지정"
      data-testid="glossary-badge"
    >
      {term}
    </button>
  );
}
