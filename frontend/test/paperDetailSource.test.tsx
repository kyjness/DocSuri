import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { PaperMetaVM } from '@/types/paperMeta';

// Source-neutral detail header (Phase 2 Q2): the detail route agrees with the search card on a
// paper's discovery source. Isolate the header — mock usePaperMeta (force a resolved value) and
// the heavy children so only the source label/link-out is under test.
let metaValue: { status: 'done'; meta: PaperMetaVM };
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/usePaperMeta', () => ({ usePaperMeta: () => metaValue }));
vi.mock('@/lib/renderMath', () => ({ renderInlineMath: (s: string) => s }));
vi.mock('@/lib/personalization', () => ({ recordPaperOpened: vi.fn() }));
vi.mock('@/components/SaveToLibraryButton', () => ({ SaveToLibraryButton: () => null }));
vi.mock('@/components/CitationTreePanel', () => ({ CitationTreePanel: () => null }));
vi.mock('@/components/SummaryModal', () => ({ SummaryModal: () => null }));

import { PaperDetailIsland } from '@/components/PaperDetailIsland';

const base: PaperMetaVM = {
  arxivId: '2005.14165v4',
  title: 'Language Models are Few-Shot Learners',
  authors: ['Tom B. Brown'],
  year: 2020,
  abstract: 'We show that scaling up language models improves few-shot performance.',
  arxivUrl: 'https://arxiv.org/abs/2005.14165',
};

describe('PaperDetailIsland — source-neutral header (Q2)', () => {
  it('shows the source name and a source link-out for a non-arXiv paper', () => {
    metaValue = {
      status: 'done',
      meta: {
        ...base,
        sourceName: 'Semantic Scholar',
        sourceUrl: 'https://www.semanticscholar.org/paper/abc',
      },
    };
    render(<PaperDetailIsland paperId="2005.14165v4" version={1} />);
    expect(screen.getByTestId('paper-source')).toHaveTextContent('Semantic Scholar');
    const link = screen.getByTestId('paper-source-link');
    expect(link).toHaveTextContent('Semantic Scholar에서 원문 보기');
    expect(link).toHaveAttribute('href', 'https://www.semanticscholar.org/paper/abc');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('keeps the arXiv label/link for an arXiv paper (default source)', () => {
    metaValue = { status: 'done', meta: { ...base } }; // no sourceName → arXiv
    render(<PaperDetailIsland paperId="2005.14165v4" version={1} />);
    expect(screen.getByTestId('paper-source')).toHaveTextContent('arXiv:2005.14165v4');
    expect(screen.getByTestId('paper-source-link')).toHaveTextContent('arXiv에서 원문 보기');
  });

  it('drops a hostile link scheme — no href rendered (external-link safety)', () => {
    metaValue = {
      status: 'done',
      meta: { ...base, sourceName: 'OpenAlex', sourceUrl: 'javascript:alert(1)', arxivUrl: undefined },
    };
    render(<PaperDetailIsland paperId="2006.11239v2" version={1} />);
    expect(screen.queryByTestId('paper-source-link')).toBeNull();
    expect(screen.getByTestId('paper-source')).toHaveTextContent('OpenAlex');
  });
});
