import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { renderInlineMath } from '@/lib/renderMath';

// renderInlineMath turns TeX delimiters in plain text into KaTeX markup. The arXiv abstract
// convention is `$…$` (inline) / `$$…$$` (display); the doc-model also uses `\(…\)`.
function html(node: React.ReactNode): HTMLElement {
  const { container } = render(<>{node}</>);
  return container;
}

describe('renderInlineMath', () => {
  it('renders arXiv `$…$` inline math as KaTeX, not raw source', () => {
    const c = html(renderInlineMath('a convex combination of $K$ base measures'));
    expect(c.querySelector('.katex')).not.toBeNull();
    expect(c.textContent).not.toContain('$K$');
    expect(c.textContent).toContain('base measures');
  });

  it('handles `$β\\leq 1$` (symbols + commands)', () => {
    const c = html(renderInlineMath('matches when $β\\leq 1$.'));
    expect(c.querySelector('.katex')).not.toBeNull();
    expect(c.textContent).not.toContain('\\leq');
  });

  it('still renders the doc-model `\\(…\\)` form', () => {
    const c = html(renderInlineMath('inline \\(x^2\\) here'));
    expect(c.querySelector('.katex')).not.toBeNull();
  });

  it('renders `$$…$$` in display mode', () => {
    const c = html(renderInlineMath('$$E = mc^2$$'));
    expect(c.querySelector('.katex-display')).not.toBeNull();
  });

  it('leaves prose currency like "$5 and $10" untouched', () => {
    const c = html(renderInlineMath('costs $5 and $10 total'));
    expect(c.querySelector('.katex')).toBeNull();
    expect(c.textContent).toBe('costs $5 and $10 total');
  });

  it('returns plain text when there is no math', () => {
    expect(renderInlineMath('no math here')).toBe('no math here');
  });
});
