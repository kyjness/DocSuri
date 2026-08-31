import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { PaperMetaVM } from '@/types/paperMeta';

// Source-neutral detail header (Phase 2 Q2): the detail route agrees with the search card on a
// paper's discovery source. Isolate the header — mock usePaperMeta (force a resolved value) and
// the heavy children so only the source label/link-out is under test.
let metaValue:
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'done'; meta: PaperMetaVM | null };
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

// 메타 조회는 실패할 수 있다 — 404(색인 밖), 429(레이트 리밋), 게이트웨이 오류. usePaperMeta는
// 셋을 모두 `meta: null`로 정규화하고, 화면은 지금까지 그 경우 헤더 블록을 통째로 렌더하지
// 않았다. 사용자에게는 "이 논문은 초록도 없다"로 보이고 로그에는 아무것도 안 남는다
// (2026-08-31 배포본: 429 43건 중 5건이 한 논문의 상세 헤더였다).
describe('PaperDetailIsland — 메타를 못 받았을 때', () => {
  it('제목·초록 대신 arXiv id와 link-out까지는 언제나 내놓는다', () => {
    metaValue = { status: 'done', meta: null };
    render(
      <PaperDetailIsland
        paperId="2202.08455v1"
        version={1}
        arxivUrl="https://arxiv.org/abs/2202.08455v1"
      />,
    );

    expect(screen.getByTestId('paper-meta-fallback')).toBeInTheDocument();
    expect(screen.queryByTestId('paper-meta')).toBeNull();
    expect(screen.getByTestId('paper-source')).toHaveTextContent('arXiv:2202.08455v1');
    expect(screen.getByTestId('paper-source-link')).toHaveAttribute(
      'href',
      'https://arxiv.org/abs/2202.08455v1',
    );
  });

  it('첫 렌더(idle)를 실패로 읽지 않는다 — 조회 전에 실패 문구가 깜빡이면 안 된다', () => {
    metaValue = { status: 'idle' };
    render(<PaperDetailIsland paperId="2202.08455v1" version={1} />);

    expect(screen.getByTestId('paper-meta-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('paper-meta-fallback')).toBeNull();
  });

  it('로딩 중에도 실패 문구를 내지 않는다', () => {
    metaValue = { status: 'loading' };
    render(<PaperDetailIsland paperId="2202.08455v1" version={1} />);

    expect(screen.getByTestId('paper-meta-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('paper-meta-fallback')).toBeNull();
  });
});
