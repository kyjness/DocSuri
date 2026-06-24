import type { ReactNode } from 'react';
import Link from 'next/link';
import styles from './ResultCard.module.css';
import type { ResultCardVM } from '@/types/generated';

// ResultCard (LC-6, FR-4/5, SEC-9) — single paper, phone-optimized.
// Renders ONLY the exposed fields (BR-U5-4). External text is escaped by React
// (BR-U5-6). The internal relevance score is never rendered (SEC-9); result ordering
// is conveyed by the list's sort control instead. Title and abstract snippet link to
// the paper detail route (/paper/[id]). `bookmark` is an optional top-right control
// (save to library); `action` is an optional footer slot, so the same card serves
// both live results and the library.

interface ResultCardProps {
  card: ResultCardVM;
  bookmark?: ReactNode;
  action?: ReactNode;
}

export function ResultCard({ card, bookmark, action }: ResultCardProps) {
  const detailHref = `/paper/${encodeURIComponent(card.arxivId)}`;

  return (
    <article className={styles.card} data-testid="result-card">
      {bookmark ? <div className={styles.bookmark}>{bookmark}</div> : null}
      <Link className={styles.titleLink} href={detailHref} data-testid="result-card-title">
        <h3 className={styles.title}>{card.title}</h3>
      </Link>
      <p className={styles.meta}>
        <span data-testid="result-card-authors">{card.authors.join(', ')}</span>
        {card.year ? (
          <>
            <span aria-hidden="true"> · </span>
            <span data-testid="result-card-year">{card.year}</span>
          </>
        ) : null}
        <span aria-hidden="true"> · </span>
        <span data-testid="result-card-arxiv-id">arXiv:{card.arxivId}</span>
      </p>
      {card.abstractSnippet ? (
        <Link className={styles.snippetLink} href={detailHref} data-testid="result-card-snippet">
          <p className={styles.snippet}>{card.abstractSnippet}</p>
        </Link>
      ) : null}
      {action ? <div className={styles.footer}>{action}</div> : null}
    </article>
  );
}
