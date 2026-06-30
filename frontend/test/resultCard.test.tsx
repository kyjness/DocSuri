import type { ReactNode } from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ResultCard } from '@/components/ResultCard';
import type { ResultCardVM } from '@/types/generated';

// next/link renders an <a> in tests; pass through className/data-testid.
vi.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, ...props }: { children: ReactNode } & Record<string, unknown>) => (
    <a {...(props as Record<string, string>)}>{children}</a>
  ),
}));

const base: ResultCardVM = {
  title: 'Attention Is All You Need',
  authors: ['A. Vaswani', 'N. Shazeer'],
  year: 2017,
  arxivId: '1706.03762v5',
  abstractSnippet: 'The dominant sequence transduction models…',
  relevance: '높음',
  arxivUrl: 'https://arxiv.org/abs/1706.03762',
};

describe('ResultCard', () => {
  it('renders the exposed fields', () => {
    render(<ResultCard card={base} />);
    expect(screen.getByTestId('result-card-title')).toHaveTextContent('Attention Is All You Need');
    expect(screen.getByTestId('result-card-authors')).toHaveTextContent('A. Vaswani, N. Shazeer');
    expect(screen.getByTestId('result-card-year')).toHaveTextContent('2017');
    expect(screen.getByTestId('result-card-arxiv-id')).toHaveTextContent('1706.03762v5');
  });

  it('never renders the internal relevance score (SEC-9)', () => {
    render(<ResultCard card={base} />);
    expect(screen.queryByTestId('result-card-relevance')).toBeNull();
    expect(screen.queryByText(/관련도/)).toBeNull();
  });

  it('renders the top-right bookmark slot when provided', () => {
    render(<ResultCard card={base} bookmark={<button data-testid="bm">담기</button>} />);
    expect(screen.getByTestId('bm')).toBeInTheDocument();
  });

  it('links title and snippet to the paper detail route', () => {
    render(<ResultCard card={base} />);
    expect(screen.getByTestId('result-card-title')).toHaveAttribute('href', '/paper/1706.03762v5');
    expect(screen.getByTestId('result-card-snippet')).toHaveAttribute('href', '/paper/1706.03762v5');
  });

  it('renders external text as escaped content (no raw HTML injection)', () => {
    render(<ResultCard card={{ ...base, title: '<img src=x onerror=alert(1)>' }} />);
    const title = screen.getByTestId('result-card-title');
    expect(title).toHaveTextContent('<img src=x onerror=alert(1)>');
    expect(title.querySelector('img')).toBeNull();
  });

  it('shows the source name and an external link-out for a non-arXiv result (Q2)', () => {
    render(
      <ResultCard
        card={{
          ...base,
          sourceName: 'Semantic Scholar',
          sourceUrl: 'https://www.semanticscholar.org/paper/abc',
        }}
      />,
    );
    const source = screen.getByTestId('result-card-source');
    expect(source).toHaveTextContent('Semantic Scholar');
    expect(source).toHaveAttribute('href', 'https://www.semanticscholar.org/paper/abc');
    expect(source).toHaveAttribute('rel', 'noopener noreferrer');
    expect(source).toHaveAttribute('target', '_blank');
  });

  it('keeps the arXiv label and links out via sourceUrl when present (Q2)', () => {
    render(<ResultCard card={{ ...base, sourceName: 'arXiv', sourceUrl: base.arxivUrl }} />);
    const source = screen.getByTestId('result-card-arxiv-id');
    expect(source).toHaveTextContent('arXiv:1706.03762v5');
    expect(source).toHaveAttribute('href', base.arxivUrl);
  });

  it('does not render a hostile link scheme as an href (external-link safety)', () => {
    render(<ResultCard card={{ ...base, sourceName: 'OpenAlex', sourceUrl: 'javascript:alert(1)' }} />);
    const source = screen.getByTestId('result-card-source');
    expect(source).toHaveTextContent('OpenAlex');
    expect(source.tagName).toBe('SPAN'); // unsafe scheme dropped → plain span, not an <a>
  });
});
