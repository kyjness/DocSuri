import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SummaryView } from '@/components/SummaryView';
import type { SummaryVM, AnchorVM } from '@/types/generated';

// Several claims in one field routinely cite the SAME source; the backend canonicalizes them to one
// label, so a naive 1:1 render shows identical repeated "출처: <label>" chips. SummaryView must
// collapse duplicates to one chip per (field, label). This also heals summaries cached before the
// backend de-dup shipped, whose stored anchors are immutable in S3.

function anchor(field: string, label: string, span: string): AnchorVM {
  return { field, label, span, target: 'section' };
}

function vm(anchors: AnchorVM[]): SummaryVM {
  return {
    tldr: 't',
    contributions: ['c'],
    method: 'm',
    results: 'r',
    limitations: 'l',
    reproducibility: { code: '', data: '' },
    anchors,
  } as SummaryVM;
}

describe('SummaryView anchor chips', () => {
  it('collapses duplicate same-field/same-label anchors to one chip', () => {
    render(
      <SummaryView
        summary={vm([
          anchor('method', 'Introduction', 'a'),
          anchor('method', 'Introduction', 'b'),
          anchor('method', 'Introduction', 'c'),
        ])}
        onAnchor={() => {}}
      />,
    );
    const chips = screen.getAllByTestId('summary-anchor');
    expect(chips).toHaveLength(1);
    expect(chips[0]).toHaveTextContent('출처: Introduction');
  });

  it('keeps distinct labels within a field', () => {
    render(
      <SummaryView
        summary={vm([
          anchor('results', 'Table 1', 'a'),
          anchor('results', 'Table 1', 'b'),
          anchor('results', 'Section 4', 'c'),
        ])}
        onAnchor={() => {}}
      />,
    );
    const chips = screen.getAllByTestId('summary-anchor');
    expect(chips.map((c) => c.textContent)).toEqual(['출처: Table 1', '출처: Section 4']);
  });
});
