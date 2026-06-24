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
});
