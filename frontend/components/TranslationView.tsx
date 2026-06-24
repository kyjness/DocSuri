'use client';

import { useEffect, useRef, useState } from 'react';
import type { AssetRef, TranslationVM } from '@/types/generated';
import { useGlossaryTerms } from '@/lib/useGlossaryTerms';
import { GlossaryTermBadge } from './GlossaryTermBadge';
import { DocModelBody } from './DocModelViewer';
import styles from './TranslationView.module.css';

// TranslationView (US-S2, BR-SF-9 / BR-S18) — Korean translation rendered as a "translated
// doc-model": the SAME structured rich view as the original body (sections·수식·표·그림),
// only the text is Korean. Plus kept-terms badges (untranslated terms kept as-is). External
// text is escaped by React. No anchors (translation is grounding-free). The scope label is
// not repeated here — the modal heading already names 초록/전문 번역.
// Each kept-term badge is tappable (GlossaryTermBadge) to save a personal rendering
// (개인 용어집 Phase 1). This view owns the "which badge is editing" state so only one
// editor is open at a time, and a click outside the badge row closes it.

// Stable empty map so an abstract translation (no figures) doesn't re-create one each render.
const NO_ASSETS: Map<string, AssetRef> = new Map();

interface TranslationViewProps {
  translation: TranslationVM;
  cached?: boolean;
  /** Show the personal-glossary editor (kept-term badges). Only the full-text translation
   * (본문 번역) exposes it; the abstract translation does not. */
  showGlossary?: boolean;
  /** Signed figure/table asset urls (by assetId) for figures inside the translated doc-model.
   * Omitted for abstract translation (no figures). */
  assetsById?: Map<string, AssetRef>;
}

export function TranslationView({
  translation,
  cached,
  showGlossary = false,
  assetsById,
}: TranslationViewProps) {
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const termsRef = useRef<HTMLDivElement | null>(null);
  const { terms, setTerm } = useGlossaryTerms();

  // Close the open editor on any pointer-down outside the glossary section. `pointerdown`
  // covers both mouse and touch (a plain `mousedown` may not fire on a real phone), and fires
  // before click so a tap elsewhere dismisses before it activates anything.
  useEffect(() => {
    if (openIndex === null) return;
    const onPointerDown = (e: PointerEvent) => {
      if (termsRef.current && !termsRef.current.contains(e.target as Node)) {
        setOpenIndex(null);
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [openIndex]);

  return (
    <div className={styles.root} data-testid="translation-view">
      {cached ? (
        <span className={styles.cached} data-testid="translation-cached">
          저장된 결과
        </span>
      ) : null}

      {showGlossary && translation.keptTerms.length > 0 ? (
        <section className={styles.glossary} ref={termsRef} aria-label="핵심 용어">
          <h3 className={styles.glossaryTitle}>핵심 용어</h3>
          <p className={styles.glossaryHint}>
            번역에서 원어 그대로 둔 핵심 용어예요. 탭해서 내 번역어를 지정할 수 있어요.
          </p>
          <div className={styles.terms}>
            {translation.keptTerms.map((t, i) => (
              <GlossaryTermBadge
                key={`${t}-${i}`}
                term={t}
                open={openIndex === i}
                onOpen={() => setOpenIndex(i)}
                onClose={() => setOpenIndex(null)}
                initialValue={terms[t] ?? ''}
                onSaved={(termTo) => setTerm(t, termTo)}
              />
            ))}
          </div>
        </section>
      ) : null}

      <div className={styles.text}>
        <DocModelBody docModel={translation.docModel} assetsById={assetsById ?? NO_ASSETS} />
      </div>
    </div>
  );
}
