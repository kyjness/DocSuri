import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { MathDisplay, renderInlineMath } from '@/lib/renderMath';

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

  it('resolves a custom macro from meta.macros instead of showing the raw command', () => {
    // KaTeX (throwOnError:false) renders an undefined command as its red source text. The
    // e-print macro map expands it instead, so the literal `\myvec` no longer appears.
    const without = html(renderInlineMath('a \\(\\myvec\\) b'));
    expect(without.textContent).toContain('\\myvec');

    const withMacros = html(renderInlineMath('a \\(\\myvec\\) b', { '\\myvec': '\\vec{x}' }));
    expect(withMacros.querySelector('.katex')).not.toBeNull();
    expect(withMacros.textContent).not.toContain('\\myvec');
  });

  it('passes macros through MathDisplay (block formulas)', () => {
    const without = html(<MathDisplay latex={'\\myop'} />);
    expect(without.textContent).toContain('\\myop');

    const c = html(<MathDisplay latex={'\\myop'} macros={{ '\\myop': '\\oplus' }} />);
    expect(c.querySelector('.katex')).not.toBeNull();
    expect(c.textContent).not.toContain('\\myop');
  });

  it('resolves common blackboard-bold fallbacks (\\R) without any meta.macros', () => {
    // \R is not a KaTeX builtin; without the fallback map it would render as red source text.
    const c = html(<MathDisplay latex={'x \\in \\R'} />);
    expect(c.querySelector('.katex')).not.toBeNull();
    expect(c.textContent).not.toContain('\\R');
    expect(c.querySelector('.katex-error')).toBeNull();
  });

  it('swallows non-math layout macros (\\centering) instead of red-flagging them', () => {
    const c = html(<MathDisplay latex={'\\centering x^2'} />);
    expect(c.querySelector('.katex')).not.toBeNull();
    expect(c.textContent).not.toContain('\\centering');
    expect(c.querySelector('.katex-error')).toBeNull();
  });

  it('lets a paper macro override a fallback default', () => {
    const c = html(<MathDisplay latex={'\\R'} macros={{ '\\R': '\\mathbb{Q}' }} />);
    expect(c.querySelector('.katex')).not.toBeNull();
    expect(c.textContent).not.toContain('\\R');
  });

  it('does not leak a \\gdef across macro-less renders (isolated default macros)', () => {
    // KaTeX mutates the macro object it is given — a \gdef writes a global into it. The default
    // (no meta.macros) path is shared by every abstract; a single mutable object would carry one
    // paper's \gdef into every later render. Each default-path render gets a fresh copy instead.
    html(<MathDisplay latex={'\\gdef\\leaktest{LEAKED}'} />);
    const after = html(<MathDisplay latex={'\\leaktest'} />);
    expect(after.textContent).not.toContain('LEAKED'); // definition must not have leaked
    expect(after.textContent).toContain('\\leaktest'); // shows the raw, undefined command
  });
});
