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
  // Source-neutral label + link-out (FR-4/FR-5, Phase 2 Q2): arXiv keeps "arXiv:<id>"; a
  // non-arXiv result (Semantic Scholar / OpenAlex) shows its source name. The link-out uses
  // the source-neutral sourceUrl, guarded to http(s) so a malformed/hostile scheme can't ride
  // the href (external-link safety); rel=noopener noreferrer prevents tabnabbing/referrer leak.
  const sourceName = card.sourceName ?? 'arXiv';
  const isArxiv = sourceName.toLowerCase() === 'arxiv';
  const sourceLabel = isArxiv ? `arXiv:${card.arxivId}` : sourceName;
  const sourceTestId = isArxiv ? 'result-card-arxiv-id' : 'result-card-source';
  const sourceUrl =
    card.sourceUrl && /^https?:\/\//i.test(card.sourceUrl) ? card.sourceUrl : undefined;

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
        {sourceUrl ? (
          <a
            className={styles.sourceLink}
            href={sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            data-testid={sourceTestId}
          >
            {sourceLabel}
          </a>
        ) : (
          <span data-testid={sourceTestId}>{sourceLabel}</span>
        )}
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
