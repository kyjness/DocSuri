import { describe, it, expect, beforeAll } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SummaryView } from '@/components/SummaryView';
import { preloadMathEngine } from '@/lib/renderMath';
import type { SummaryVM } from '@/types/generated';

// The summary prompt emits formulas/symbols as LaTeX ($…$ / $$…$$); SummaryView must render each
// field through MathJax so they show as typeset math, not flattened unicode / raw `$…$` source.
// Math rendering is lazy — warm the engine so each render produces its SVG (mjx-container) synchronously.
beforeAll(async () => {
  await preloadMathEngine();
});
function vm(overrides: Partial<SummaryVM> = {}): SummaryVM {
  return {
    tldr: '',
    contributions: [],
    method: '',
    results: '',
    limitations: '',
    reproducibility: { code: '', data: '' },
    anchors: [],
    ...overrides,
  } as SummaryVM;
}

describe('SummaryView math rendering', () => {
  it('renders inline `$…$` math in a field as MathJax, not raw source', () => {
    render(<SummaryView summary={vm({ method: 'loss $E_\\phi(m)$ is minimized' })} />);
    const view = screen.getByTestId('summary-view');
    expect(view.querySelector('mjx-container')).not.toBeNull();
    expect(view.textContent).not.toContain('$E_\\phi(m)$');
    expect(view.textContent).toContain('is minimized');
  });

  it('renders display `$$…$$` math in results', () => {
    render(<SummaryView summary={vm({ results: '$$\\nabla_r f = 0$$' })} />);
    const view = screen.getByTestId('summary-view');
    expect(view.querySelector('mjx-container[display="true"]')).not.toBeNull();
  });

  it('renders math inside contribution list items', () => {
    render(<SummaryView summary={vm({ contributions: ['introduces $\\lambda_E$'] })} />);
    const view = screen.getByTestId('summary-view');
    expect(view.querySelector('mjx-container')).not.toBeNull();
    expect(view.textContent).not.toContain('$\\lambda_E$');
  });

  it('leaves plain prose (no delimiters) untouched', () => {
    render(<SummaryView summary={vm({ tldr: 'a plain sentence' })} />);
    const view = screen.getByTestId('summary-view');
    expect(view.querySelector('mjx-container')).toBeNull();
    expect(view.textContent).toContain('a plain sentence');
  });
});
