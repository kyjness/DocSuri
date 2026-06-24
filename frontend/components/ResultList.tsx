import type { ReactNode } from 'react';
import styles from './ResultList.module.css';
import { ResultCard } from './ResultCard';
import type { ResultCardVM } from '@/types/generated';

// ResultList (LC-1/6, FR-3) — top-N list. When degraded, a non-technical banner
// sits on top; the degradationMode is never shown verbatim (BR-U5-8/12). The list
// renders cards in the order it receives them (PBT-03); any re-ordering (e.g. the
// search sort control) happens upstream. `renderBookmark` adds a top-right save
// control; `renderAction` adds a footer control.

interface ResultListProps {
  cards: ResultCardVM[];
  degraded?: boolean;
  renderBookmark?: (card: ResultCardVM, index: number) => ReactNode;
  renderAction?: (card: ResultCardVM, index: number) => ReactNode;
}

export function ResultList({ cards, degraded = false, renderBookmark, renderAction }: ResultListProps) {
  return (
    <section className={styles.list} aria-label="검색 결과" data-testid="result-list">
      {degraded ? (
        <p className={styles.banner} role="status" data-testid="degraded-banner">
          일부 결과만 표시됩니다.
        </p>
      ) : null}
      {cards.map((card, i) => (
        <ResultCard
          key={`${card.arxivId}-${i}`}
          card={card}
          bookmark={renderBookmark?.(card, i)}
          action={renderAction?.(card, i)}
        />
      ))}
    </section>
  );
}
