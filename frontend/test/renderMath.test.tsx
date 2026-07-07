import { describe, it, expect, beforeAll } from 'vitest';
import { render } from '@testing-library/react';
import fc from 'fast-check';
import {
  MathDisplay,
  renderInlineMath,
  renderInlineRich,
  renderRichText,
  preloadMathEngine,
} from '@/lib/renderMath';

// renderInlineMath turns TeX delimiters in plain text into MathJax markup. The arXiv abstract
// convention is `$…$` (inline) / `$$…$$` (display); the doc-model also uses `\(…\)`.
//
// Math rendering is lazy: MathJax is a code-split chunk fetched on first use. We warm it once here so
// each render sees the engine ready and produces its SVG synchronously (mjx-container). Until loaded a
// span shows a `.mathLoading` skeleton — never asserted against below because the engine is preloaded.
beforeAll(async () => {
  await preloadMathEngine();
});

function html(node: React.ReactNode): HTMLElement {
  const { container } = render(<>{node}</>);
  return container;
}

// MathJax (SVG) success marker; the failure marker is the `수식` fallback chip.
const MJX = 'mjx-container';

describe('fail-soft fallback (no raw backslash source on a parse error)', () => {
  it('renders a compact placeholder instead of the source when a display formula cannot parse', () => {
    // A bare `\derivative` (physics, needs operands) is a fatal parse error. It must NOT spill its
    // backslash source onto the page.
    const c = html(<MathDisplay latex={String.raw`\derivative`} />);
    expect(c.textContent).toBe('수식');
    expect(c.textContent).not.toContain('\\derivative');
    // Source is preserved for inspection in the tooltip, HTML-escaped (no injection).
    const chip = c.querySelector('[role="img"]') as HTMLElement;
    expect(chip.getAttribute('title')).toContain('\\derivative');
  });

  it('escapes angle brackets in the tooltip so a hostile source cannot inject markup', () => {
    const c = html(<MathDisplay latex={String.raw`\undefinedcmd{<}<script>`} />);
    expect(c.querySelector('script')).toBeNull();
    const chip = c.querySelector('[role="img"]') as HTMLElement;
    expect(chip.getAttribute('title')).toContain('<script>');
  });

  it('still renders valid math normally (fallback only on failure)', () => {
    const c = html(<MathDisplay latex={String.raw`\frac{a}{b}`} />);
    expect(c.querySelector(MJX)).not.toBeNull();
    expect(c.textContent).not.toBe('수식');
  });

  it('renders a formula whose alttext leaked a `\\cite` command (strip it, do not collapse)', () => {
    // Real @6 doc-model breakage: LaTeXML leaked a trailing `\cite[citep]{…}` (nested braces). The
    // leaked citation carries no math meaning → strip it and render the real expression.
    const latex = String.raw`\ln[2\pi I_{0}(c)]\quad\text{\cite[citep]{({A}{mardia2009}{{, }}{})}}`;
    const c = html(<MathDisplay latex={latex} />);
    expect(c.querySelector(MJX)).not.toBeNull();
    expect(c.textContent).not.toBe('수식');
  });

  it('renders a formula whose alttext leaked a two-arg `\\lx@cref` (strip both args)', () => {
    // Real @6 breakage: LaTeXML leaked its internal cleveref `\lx@cref{creftype~refnum}{key}` (TWO
    // brace args). Both arguments must be consumed, else the trailing `{key}` spills as stray text.
    const latex = String.raw`\delta(m - h(m,y,\alpha))\text{(by \lx@cref{creftype~refnum}{eq:equiv_bu})}`;
    const c = html(<MathDisplay latex={latex} />);
    expect(c.querySelector(MJX)).not.toBeNull();
    expect(c.textContent).not.toBe('수식');
    expect(c.textContent).not.toContain('eq:equiv_bu');
  });

  it.each([
    ['LaTeXML \\originalleft/right', String.raw`\originalleft(\frac{a}{b}\originalright)`],
    ['\\mathds indicator', String.raw`\mathds{1}[x>0]`],
    ['\\mathbbm indicator', String.raw`\mathbbm{1}_{A}`],
    ['\\textsc', String.raw`\textsc{Sample}+x`],
    ['\\nicefrac', String.raw`\nicefrac{1}{2}`],
    ['\\scalebox (drop scale, keep body)', String.raw`\scalebox{0.8}{\sum_{i} x_i}`],
    ['split environment', String.raw`\begin{split}a&=b\\&=c\end{split}`],
    ['\\nobreak spacing leak', String.raw`a=b\leavevmode\nobreak\ \text{where}\nobreak\ c`],
  ])('renders unsupported-package alttext leaks (%s) instead of collapsing', (_label, latex) => {
    const c = html(<MathDisplay latex={latex} />);
    expect(c.querySelector(MJX)).not.toBeNull();
    expect(c.textContent).not.toBe('수식');
  });
});

describe('renderInlineMath', () => {
  it('renders arXiv `$…$` inline math as MathJax, not raw source', () => {
    const c = html(renderInlineMath('a convex combination of $K$ base measures'));
    expect(c.querySelector(MJX)).not.toBeNull();
    expect(c.textContent).not.toContain('$K$');
    expect(c.textContent).toContain('base measures');
  });

  it('handles `$β\\leq 1$` (symbols + commands)', () => {
    const c = html(renderInlineMath('matches when $β\\leq 1$.'));
    expect(c.querySelector(MJX)).not.toBeNull();
    expect(c.textContent).not.toContain('\\leq');
  });

  it('still renders the doc-model `\\(…\\)` form', () => {
    const c = html(renderInlineMath('inline \\(x^2\\) here'));
    expect(c.querySelector(MJX)).not.toBeNull();
  });

  it('renders `$$…$$` in display mode', () => {
    const c = html(renderInlineMath('$$E = mc^2$$'));
    expect(c.querySelector(`${MJX}[display="true"]`)).not.toBeNull();
  });

  it('leaves prose currency like "$5 and $10" untouched', () => {
    const c = html(renderInlineMath('costs $5 and $10 total'));
    expect(c.querySelector(MJX)).toBeNull();
    expect(c.textContent).toBe('costs $5 and $10 total');
  });

  it('scans escaped characters in dollar math without regex backtracking', () => {
    const escaped = Array.from({ length: 200 }, () => '\\#').join('');
    const c = html(renderInlineMath(`noise $a ${escaped} b$ done`));
    expect(c.querySelector(MJX)).not.toBeNull();
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
          expect(c.querySelector(MJX)).not.toBeNull();
          expect(c.textContent).toContain('after');
          expect(c.textContent).not.toContain('$a');
        },
      ),
      { numRuns: 30 },
    );
  });

  it('returns plain text when there is no math', () => {
    expect(renderInlineMath('no math here')).toBe('no math here');
  });

  it('resolves a custom macro from meta.macros instead of showing the raw command', () => {
    // Without the macro map, `\myvec` is undefined → fail-soft placeholder (raw command kept in
    // the tooltip, never spilled onto the page). The e-print macro map expands it so it renders.
    const without = html(renderInlineMath('a \\(\\myvec\\) b'));
    expect(without.querySelector(MJX)).toBeNull();
    expect(without.querySelector('[role="img"]')?.getAttribute('title')).toContain('\\myvec');

    const withMacros = html(renderInlineMath('a \\(\\myvec\\) b', { '\\myvec': '\\vec{x}' }));
    expect(withMacros.querySelector(MJX)).not.toBeNull();
    expect(withMacros.textContent).not.toContain('\\myvec');
  });

  it('converts an author macro WITH arguments (KaTeX `#1` form → MathJax arity)', () => {
    // meta.macros carries KaTeX-shaped values (values use `#1`); we must pass the arity to MathJax
    // (`[template, argCount]`). A one-arg macro applied to `\mynorm{v}` should render, not collapse.
    // Without the arity, MathJax would treat it as a zero-arg macro and the `{v}` would spill.
    const c = html(
      renderInlineMath('\\(\\mynorm{v}\\)', { '\\mynorm': '\\left\\lVert #1 \\right\\rVert' }),
    );
    expect(c.querySelector(MJX)).not.toBeNull();
    expect(c.textContent).not.toBe('수식');
  });

  it('passes macros through MathDisplay (block formulas)', () => {
    const without = html(<MathDisplay latex={'\\myblockop'} />);
    expect(without.querySelector(MJX)).toBeNull();
    expect(without.querySelector('[role="img"]')?.getAttribute('title')).toContain('\\myblockop');

    const c = html(<MathDisplay latex={'\\myblockop'} macros={{ '\\myblockop': '\\oplus' }} />);
    expect(c.querySelector(MJX)).not.toBeNull();
    expect(c.textContent).not.toContain('\\myblockop');
  });

  it('resolves common blackboard-bold fallbacks (\\R) without any meta.macros', () => {
    const c = html(<MathDisplay latex={'x \\in \\R'} />);
    expect(c.querySelector(MJX)).not.toBeNull();
    expect(c.textContent).not.toBe('수식');
  });

  it('swallows non-math layout macros (\\centering) instead of collapsing', () => {
    const c = html(<MathDisplay latex={'\\centering x^2'} />);
    expect(c.querySelector(MJX)).not.toBeNull();
    expect(c.textContent).not.toBe('수식');
  });

  it('lets a paper macro override a fallback default', () => {
    const c = html(<MathDisplay latex={'\\R'} macros={{ '\\R': '\\mathbb{Q}' }} />);
    expect(c.querySelector(MJX)).not.toBeNull();
    expect(c.textContent).not.toContain('\\R');
  });

  it('isolates the macro-less default path across papers (no \\def leak)', () => {
    // The default (no meta.macros) path is shared by every abstract; a paper-local `\def` must not
    // carry into a LATER default-path render. A fresh MathJax document per default convert isolates it.
    html(renderInlineMath('\\(\\def\\leaktest{LEAKED}\\)'));
    const after = html(renderInlineMath('\\(\\leaktest\\)'));
    expect(after.textContent).not.toContain('LEAKED'); // definition must not have leaked
    // Isolated → `\leaktest` is undefined → fail-soft placeholder carrying the raw command in its tooltip.
    expect(after.querySelector('[role="img"]')?.getAttribute('title')).toContain('\\leaktest');
  });
});

describe('physics package (KaTeX had no default → whole-formula collapse; MathJax renders natively)', () => {
  // Renders to real MathJax (not the 수식 placeholder) and does not leak the raw command.
  function rendersCleanly(latex: string) {
    const c = html(<MathDisplay latex={latex} />);
    expect(c.querySelector(MJX), latex).not.toBeNull();
    expect(c.textContent, latex).not.toBe('수식');
    return c;
  }

  it('renders \\quantity', () => {
    const c = rendersCleanly(String.raw`\quantity(x_{i})_{i\in S}`);
    expect(c.textContent).not.toContain('\\quantity');
  });

  it('renders \\tr and \\rank as operators', () => {
    rendersCleanly(String.raw`\tr(A^{\top}A)`);
    rendersCleanly(String.raw`\rank(C)=\rank(CC^{\top})`);
  });

  it('renders \\matrixquantity[...] with nested brackets intact', () => {
    rendersCleanly(String.raw`\matrixquantity[a&b\\ c&[C]^{-1}]`);
  });

  it('fails soft on a nested (block) \\matrixquantity (physics does not support it)', () => {
    // MathJax's physics package does not handle a matrix nested inside a bracketed matrixquantity
    // (throws on the inner delimiter). It must degrade to the placeholder, never spill raw source.
    const c = html(<MathDisplay latex={String.raw`\matrixquantity[\matrixquantity[a&b]\\ c]`} />);
    expect(c.textContent).toBe('수식');
    expect(c.textContent).not.toContain('\\matrixquantity');
  });

  it('renders \\derivative in operator and operand forms', () => {
    rendersCleanly(String.raw`\derivative[\alpha]{\boldsymbol{x}}{t}=A`);
    rendersCleanly(String.raw`\ker\quantity(\derivative{f}{t})`);
  });

  it('renders the broader physics set (operators, vector calc, abs/norm, brackets, order)', () => {
    for (const latex of [
      String.raw`\Tr(\rho)`,
      String.raw`\grad f + \curl \vec{F} - \divergence \vec{G} + \laplacian \psi`,
      String.raw`\abs{x} + \norm{v}`,
      String.raw`\comm{A}{B} = -\acomm{B}{A}`,
      String.raw`\order{x^2}`,
      String.raw`\int f \dd x`,
      String.raw`\vb{a}\cdot\vu{n}`,
    ]) {
      rendersCleanly(latex);
    }
  });

  it('renders \\pdv (partial) and \\smqty (small matrix)', () => {
    rendersCleanly(String.raw`\pdv[2]{f}{x}`);
    rendersCleanly(String.raw`\smqty[a & b \\ c & d]`);
  });

  it('restores \\div to the DIVISION sign (physics would otherwise make it divergence ∇·)', () => {
    // physics redefines \div as divergence; preprocessLatex rewrites it back to ÷ (U+00F7). The SVG
    // glyph carries the codepoint in data-c, so we can assert the division sign, not ∇· (2207).
    const c = rendersCleanly(String.raw`a \div b`);
    expect(c.querySelector('[data-c="F7"]')).not.toBeNull(); // ÷ present
    expect(c.querySelector('[data-c="2207"]')).toBeNull(); // ∇ (divergence) absent
  });

  it('collapses an unrecognised \\derivative shape (fail-soft, no crash)', () => {
    const c = html(<MathDisplay latex={String.raw`\derivative`} />);
    expect(c.textContent).toBe('수식');
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
    expect(c.querySelector(`li ${MJX}`)).not.toBeNull();
    expect(c.textContent).not.toContain('$F='); // math consumed, not shown raw
  });

  it('combines bold + inline math in one line', () => {
    const c = html(renderRichText('**핵심**: $\\lambda_E=5$'));
    expect(c.querySelector('strong')).not.toBeNull();
    expect(c.querySelector(MJX)).not.toBeNull();
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
    expect(c.querySelector(MJX)).not.toBeNull();
    expect(c.textContent).not.toContain('$\\nabla');
  });

  it('renders **bold** inline', () => {
    const c = html(renderInlineRich('코드 **공개**'));
    expect(c.querySelector('strong')?.textContent).toBe('공개');
  });
});
