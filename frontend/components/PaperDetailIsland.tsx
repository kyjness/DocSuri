'use client';

// PaperDetailIsland (P3·P5) — the client island inside the SSR /paper/[id] shell.
// Owns the 요약/초록번역/각주트리 action bar and the paper metadata (title/authors/abstract).
// 본문(doc-model rich view) and 본문 번역 open as full-screen IN-APP routes (Link / router.push,
// same tab — each has its own ← back arrow), not a browser tab or inline. Choosing a summary
// source anchor navigates to the 본문 route scrolled to the matching block. real-first.
import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import type { AnchorVM } from '@/types/generated';
import { usePaperMeta } from '@/lib/usePaperMeta';
import { renderInlineMath } from '@/lib/renderMath';
import { SummaryModal, type DetailView } from './SummaryModal';
import { SaveToLibraryButton } from './SaveToLibraryButton';
import { CitationTreePanel } from './CitationTreePanel';
import { recordPaperOpened } from '@/lib/personalization';
import styles from './PaperDetailIsland.module.css';

interface PaperDetailIslandProps {
  paperId: string;
  version: number;
  arxivUrl?: string;
}

// Top action bar (modal openers). 본문 / 본문 번역 live below the metadata instead.
const ACTIONS: { view: DetailView; label: string }[] = [
  { view: 'summary', label: '요약' },
  { view: 'abstractTrans', label: '초록 번역' },
];

export function PaperDetailIsland({ paperId, version, arxivUrl }: PaperDetailIslandProps) {
  const safeArxivUrl =
    arxivUrl && (arxivUrl.startsWith('http://') || arxivUrl.startsWith('https://'))
      ? arxivUrl
      : undefined;
  const [modalView, setModalView] = useState<DetailView | null>(null);
  const [citationOpen, setCitationOpen] = useState(false);
  const meta = usePaperMeta(paperId);
  const router = useRouter();
  const openedRef = useRef<string | null>(null);

  useEffect(() => {
    if (openedRef.current === paperId) return;
    openedRef.current = paperId;
    recordPaperOpened(paperId);
  }, [paperId]);

  // 본문 / 본문 번역 are in-app routes (Link). A summary source anchor navigates to the 본문
  // route scrolled to the matching block (label carried via the query).
  const bodyHref = `/paper/${encodeURIComponent(paperId)}/doc-model?version=${version}`;
  const translateHref = `/paper/${encodeURIComponent(paperId)}/translate?version=${version}`;
  const openBody = (anchor?: AnchorVM | null) => {
    const sp = new URLSearchParams({ version: String(version) });
    if (anchor?.label) {
      sp.set('anchorLabel', anchor.label);
      if (anchor.span) sp.set('anchorSpan', anchor.span);
    }
    router.push(`/paper/${encodeURIComponent(paperId)}/doc-model?${sp.toString()}`);
  };

  return (
    <div className={styles.root}>
      {/* Sticky action bar directly under the DocSuri header — each button opens the
          summary/translation modal at its tab. */}
      <div className={styles.actionsBar} role="group" aria-label="논문 상세 액션">
        {ACTIONS.map((a) => (
          <button
            key={a.view}
            type="button"
            className={styles.action}
            onClick={() => setModalView(a.view)}
            data-testid={`open-${a.view}`}
          >
            {a.label}
          </button>
        ))}
        <button
          type="button"
          className={styles.action}
          onClick={() => setCitationOpen((v) => !v)}
          data-testid="open-citation-tree"
        >
          각주 트리
        </button>
      </div>

      {citationOpen ? (
        <CitationTreePanel paperId={paperId} onClose={() => setCitationOpen(false)} />
      ) : null}

      {meta.status === 'done' && meta.meta ? (
        <header className={styles.meta} data-testid="paper-meta">
          <div className={styles.titleRow}>
            <h1 className={styles.title} data-testid="paper-title">
              {meta.meta.title}
            </h1>
            <SaveToLibraryButton
              card={{
                arxivId: paperId,
                title: meta.meta.title,
                authors: meta.meta.authors,
                year: meta.meta.year,
                abstractSnippet: meta.meta.abstract,
                arxivUrl: meta.meta.arxivUrl ?? arxivUrl,
              }}
            />
          </div>
          <p className={styles.authors} data-testid="paper-authors">
            {meta.meta.authors.join(', ')}
            {meta.meta.year ? <span className={styles.year}> · {meta.meta.year}</span> : null}
          </p>
          <p className={styles.abstract} data-testid="paper-abstract">
            {renderInlineMath(meta.meta.abstract)}
          </p>
          <p className={styles.idline}>
            <span>arXiv:{paperId}</span>
            {safeArxivUrl ? (
              <a
                className={styles.link}
                href={safeArxivUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                arXiv에서 원문 보기
              </a>
            ) : null}
          </p>
        </header>
      ) : meta.status === 'loading' ? (
        <p className={styles.metaLoading} data-testid="paper-meta-loading">
          논문 정보를 불러오는 중…
        </p>
      ) : null}

      {/* Body access — below the metadata. Both navigate in-app to a full-screen route (each
          with its own ← back): 본문 = the doc-model rich view, 본문 번역 = the full-text translation. */}
      <div className={styles.bodyActions} role="group" aria-label="본문">
        <Link className={styles.action} href={bodyHref} data-testid="open-doc-model">
          본문
        </Link>
        <Link className={styles.action} href={translateHref} data-testid="open-full-translation">
          본문 번역
        </Link>
      </div>

      {modalView ? (
        <SummaryModal
          paperId={paperId}
          version={version}
          view={modalView}
          onClose={() => setModalView(null)}
          onAnchor={openBody}
        />
      ) : null}
    </div>
  );
}
