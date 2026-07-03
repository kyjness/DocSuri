import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import fc from 'fast-check';
import { MathDisplay, renderInlineMath, renderInlineRich, renderRichText } from '@/lib/renderMath';

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

  it('scans escaped characters in dollar math without regex backtracking', () => {
    const escaped = Array.from({ length: 200 }, () => '\\#').join('');
    const c = html(renderInlineMath(`noise $a ${escaped} b$ done`));
    expect(c.querySelector('.katex')).not.toBeNull();
    expect(c.textContent).toContain('done');
  });

  it('keeps bounded escaped dollar math renderable across generated inputs', () => {
    fc.assert(
      fc.property(
        fc.array(fc.constantFrom('\\#', '\\$', '\\_', 'x', ' ', '+'), {
          maxLength: 80,
        }),
        (parts) => {
          const c = html(renderInlineMath(`before $a${parts.join('')}b$ after`));
          expect(c.querySelector('.katex')).not.toBeNull();
          expect(c.textContent).toContain('after');
          expect(c.textContent).not.toContain('$a');
        },
      ),
      { numRuns: 50 },
    );
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

describe('renderRichText (summary fields: markdown + math)', () => {
  it('renders **bold** as <strong>', () => {
    const c = html(renderRichText('훈련 방법 **분류**를 제안'));
    expect(c.querySelector('strong')?.textContent).toBe('분류');
    expect(c.textContent).not.toContain('**');
  });

  it('renders `- ` bullet lines as a <ul><li> list', () => {
    const c = html(renderRichText('- 첫째 항목\n- 둘째 항목'));
    const items = c.querySelectorAll('li');
    expect(items.length).toBe(2);
    expect(items[0].textContent).toContain('첫째 항목');
  });

  it('splits blank-line paragraphs and does not show literal \\n\\n', () => {
    const c = html(renderRichText('첫 문단\\n\\n둘째 문단'));
    expect(c.querySelectorAll('p').length).toBe(2);
    expect(c.textContent).not.toContain('\\n');
  });

  it('renders math inside a bullet item, and preserves LaTeX commands (\\nabla)', () => {
    const c = html(renderRichText('- 힘은 $F=-\\nabla_r E$ 로 산출'));
    expect(c.querySelector('li .katex')).not.toBeNull();
    expect(c.textContent).not.toContain('$F='); // math consumed, not shown raw
  });

  it('combines bold + inline math in one line', () => {
    const c = html(renderRichText('**핵심**: $\\lambda_E=5$'));
    expect(c.querySelector('strong')).not.toBeNull();
    expect(c.querySelector('.katex')).not.toBeNull();
  });
});

describe('renderInlineRich (inline summary fields)', () => {
  it('normalizes a literal \\n into a real break (not shown as text)', () => {
    const c = html(renderInlineRich('첫 줄\\n둘째 줄'));
    expect(c.textContent).not.toContain('\\n');
    expect(c.textContent).toContain('둘째 줄');
  });

  it('preserves LaTeX commands and renders inline math (\\nabla)', () => {
    const c = html(renderInlineRich('기울기 $\\nabla f$ 사용'));
    expect(c.querySelector('.katex')).not.toBeNull();
    expect(c.textContent).not.toContain('$\\nabla');
  });

  it('renders **bold** inline', () => {
    const c = html(renderInlineRich('코드 **공개**'));
    expect(c.querySelector('strong')?.textContent).toBe('공개');
  });
});
