'use client';

// SummaryModal — the summary/translation surface as a modal overlay opened from the
// body-first detail page. The detail-page action bar already picked the mode, so the
// modal renders ONLY that mode's content (no tab bar): 요약 shows the 전문가용/입문자용
// persona toggle + structured summary; 초록/전문 번역 show the translation. Runs
// useSummarize and maps the outcome union to the surface (BR-SF-14, no infinite
// loading). Anchor click closes the modal and asks the parent to highlight the span
// in the on-page full-text body (Q5=C).
//
// Accessibility: role="dialog" aria-modal, Escape + backdrop close, initial focus,
// and body-scroll lock while open. External text escaped by React (BR-SF-9).
import { useEffect, useRef, useState } from 'react';
import type { AnchorVM, Persona, SummarizeRequest, SummarizeScope } from '@/types/generated';
import { useSummarize } from '@/lib/useSummarize';
import { PersonaToggle } from './PersonaToggle';
import { SummaryView } from './SummaryView';
import { TranslationView } from './TranslationView';
import { StateView } from './StateView';
import { recordSourceAnchorClicked, recordSummaryRequest } from '@/lib/personalization';
import styles from './SummaryModal.module.css';

/** The three detail-page actions (요약/초록 번역/전문 번역). Each opens this modal. */
export type DetailView = 'summary' | 'abstractTrans' | 'fullTrans';

interface SummaryModalProps {
  paperId: string;
  version: number;
  /** Which mode this modal renders (chosen by the action bar / card). Fixed. */
  view: DetailView;
  onClose: () => void;
  /** Anchor chosen inside a summary — parent highlights it in the on-page body.
   * Omitted from the search/library card (no full-text body to highlight): the
   * summary's 출처 chips are then disabled. */
  onAnchor?: (anchor: AnchorVM) => void;
}

function buildRequest(
  view: DetailView,
  persona: Persona,
  paperId: string,
  version: number,
): SummarizeRequest {
  if (view === 'summary') return { task: 'summary', paperId, version, persona };
  const scope: SummarizeScope = view === 'fullTrans' ? 'full' : 'abstract';
  return { task: 'translate', paperId, version, scope };
}

const LOADING_TITLE: Record<DetailView, string> = {
  summary: '요약 생성 중…',
  abstractTrans: '초록 번역 중…',
  fullTrans: '전문 번역 중… (시간이 걸릴 수 있어요)',
};

const MODAL_TITLE: Record<DetailView, string> = {
  summary: '요약',
  abstractTrans: '초록 번역',
  fullTrans: '전문 번역',
};

export function SummaryModal({ paperId, version, view, onClose, onAnchor }: SummaryModalProps) {
  const [persona, setPersona] = useState<Persona>('expert');
  const { state, run } = useSummarize();
  const panelRef = useRef<HTMLDivElement | null>(null);

  // Re-request on view/persona change; the backend cache returns cached results
  // instantly (BR-SF-5/6), so switching tabs/levels is cheap.
  useEffect(() => {
    recordSummaryRequest(
      paperId,
      view === 'summary' ? 'summary' : 'translation',
      view === 'summary' ? { persona } : { scope: view === 'fullTrans' ? 'full' : 'abstract' },
    );
    void run(buildRequest(view, persona, paperId, version));
  }, [view, persona, paperId, version, run]);

  // Escape to close + body-scroll lock while open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    panelRef.current?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  const retry = () => void run(buildRequest(view, persona, paperId, version));

  const handleAnchor = (anchor: AnchorVM) => {
    recordSourceAnchorClicked(paperId, anchor);
    onAnchor?.(anchor);
    onClose();
  };

  function renderResult() {
    if (state.status === 'idle' || state.status === 'loading') {
      return (
        <StateView kind="loading" title={LOADING_TITLE[view]} message="잠시만 기다려 주세요." />
      );
    }
    const { outcome } = state;
    switch (outcome.kind) {
      case 'summary':
        return (
          <SummaryView
            summary={outcome.summary}
            cached={outcome.cached}
            onAnchor={onAnchor ? handleAnchor : undefined}
          />
        );
      case 'translation':
        return <TranslationView translation={outcome.translation} cached={outcome.cached} />;
      case 'pending': {
        // This state renders ONLY when the API returned `pending` — i.e. the work was dispatched
        // to a background job (BR-S6/BR-S8) and the hook keeps polling (short inline waits never
        // reach here). So it's accurate to tell the user it's running in the background, and to set
        // the "it's running, may take a while" expectation up front so the wait doesn't read as a
        // failure — without promising a specific duration we can't reliably predict.
        const noun = view === 'summary' ? '요약' : '번역';
        return (
          <StateView
            kind="loading"
            title={`${noun} 생성 중…`}
            message={`AI가 백그라운드에서 ${noun}을 만들고 있어요. 논문이 길면 시간이 걸릴 수 있어요. 완료되면 여기에 표시돼요.`}
          />
        );
      }
      case 'abstain':
        return <StateView kind="abstain" message="근거가 부족해 요약/번역을 보류했어요." />;
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

  return (
    <div className={styles.backdrop} onClick={onClose} data-testid="summary-modal-backdrop">
      <div
        ref={panelRef}
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-label="요약 및 번역"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        data-testid="summary-modal"
      >
        <div className={styles.head}>
          <h2 className={styles.heading}>{MODAL_TITLE[view]}</h2>
          {view === 'summary' ? (
            <section className={styles.personaSection} aria-label="요약 수준">
              <PersonaToggle value={persona} onChange={setPersona} />
            </section>
          ) : null}
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label="닫기"
            data-testid="summary-modal-close"
          >
            ✕
          </button>
        </div>

        <div className={styles.body} data-testid="summary-modal-result">
          {renderResult()}
        </div>
      </div>
    </div>
  );
}
