// mathEngine — the environment-agnostic core of the MathJax render path: the macro fallback set,
// the registered TeX package list, the author-macro normalizer, and the read-time LaTeX
// preprocessor. Deliberately free of React/CSS/browser imports so it is the SINGLE SOURCE OF TRUTH
// shared by two consumers that must stay in lockstep:
//   • `renderMath.tsx` — the browser renderer (lazy MathJax engine, React spans).
//   • `scripts/audit-math-render.mjs` — the headless corpus render sweep (Node MathJax) that hunts
//     for LaTeX constructs which collapse a formula, so a fix lands here and both paths get it.
// The MathJax engine wiring itself (dynamic import in the browser, static import in Node) stays in
// each consumer — only the drift-prone rules (macros / packages / preprocess) live here.

// A macro map (`\name` -> expansion) extracted by ingestion from the doc-model's e-print preamble
// (`meta.macros`), so author-defined commands resolve. Kept in KaTeX/preamble shape (keys carry the
// leading backslash, values may use `#1`) — the storage contract is unchanged; we convert to
// MathJax's macro form (`{ name: [tmpl, argc] }`) at render time (see toMathjaxMacros).
export type MathMacros = Record<string, string>;

// Always-on fallback macros (MathJax form), merged UNDER any per-paper author macros (author wins).
// Most of KaTeX's old fallback set is now redundant — MathJax's `physics`/`upgreek`/`mathtools`/`ams`
// packages resolve `\quantity`·`\upbeta`·`\tr`·… natively. What remains are (1) commands MathJax has
// no default for and (2) non-math layout tokens that ride into alttext/abstracts (defined as no-ops
// so an unhandled one does not collapse the whole formula).
// NOTE: keys are in MathJax's macro form — the command name WITHOUT its leading backslash (author
// macros from meta.macros are normalized to this shape in toMathjaxMacros).
export const DEFAULT_MACROS: Record<string, string | [string, number]> = {
  // `bm` package bold — MathJax has `\boldsymbol` but not `\bm`.
  bm: ['\\boldsymbol{#1}', 1],
  // End-of-proof symbol that occasionally leaks into a trailing math span.
  qed: '\\square',
  // Blackboard-bold sets papers usually `\newcommand` but that can be missing from the e-print
  // preamble (a `.sty` LaTeXML did not bundle). Author macros override these via the merge order.
  R: '\\mathbb{R}',
  N: '\\mathbb{N}',
  Z: '\\mathbb{Z}',
  Q: '\\mathbb{Q}',
  C: '\\mathbb{C}',
  // Blackboard-bold from `dsfont`/`bbm` (indicator `\mathds{1}`, `\mathbbm{1}`) — fold into `\mathbb`.
  mathds: '\\mathbb',
  mathbbm: '\\mathbb',
  // LaTeXML renames `\left`/`\right` to `\originalleft`/`\originalright` in some alttext — map back.
  originalleft: '\\left',
  originalright: '\\right',
  // Small-caps / nice-fraction text packages — degrade to plain text / a normal fraction.
  textsc: ['\\text{#1}', 1],
  nicefrac: ['\\frac{#1}{#2}', 2],
  // Vertical spacing that LaTeXML keeps in a display equation's alttext (e.g. a stored
  // `\displaystyle\vspace{-0.5em}\begin{split}…`). It carries no math meaning and MathJax has no
  // default for it, so an unhandled `\vspace{…}` throws "Undefined control sequence" and collapses
  // the WHOLE equation to the fallback chip. It takes a braced length arg → a 1-arg no-op that
  // swallows the length. `\hspace` is left alone (MathJax supports it and it can be meaningful).
  vspace: ['', 1],
  // Layout/spacing no-ops (carry no math meaning) that can ride into alttext/abstracts. The line-break
  // penalties (`\nobreak`·`\nolinebreak`·`\allowbreak`·`\linebreak`) leak from `\leavevmode\nobreak\ `
  // spacing that LaTeXML keeps in the alttext; MathJax has no default, so one collapses the formula.
  centering: '',
  raggedright: '',
  raggedleft: '',
  noindent: '',
  par: '',
  hfill: '',
  vfill: '',
  medskip: '',
  smallskip: '',
  bigskip: '',
  newline: '',
  protect: '',
  xspace: '',
  leavevmode: '',
  boldmath: '',
  nobreak: '',
  nolinebreak: '',
  allowbreak: '',
  linebreak: '',
  // Font-size switches (no math meaning) that leak into alttext — 0-arg no-ops.
  footnotesize: '',
  scriptsize: '',
  sc: '',
  // ── Additions from the corpus render sweep (scripts/audit-math-render.mjs) ──────────────────────
  // Script/calligraphic/blackboard/sans font commands authors `\newcommand` via packages LaTeXML did
  // not bundle (mathrsfs·pazo·bbold·…). Map each to a guaranteed-available MathJax font command: the
  // exact typeface may differ, but the symbol renders instead of collapsing the whole formula.
  mathscrsfs: ['\\mathcal{#1}', 1],
  pazocal: ['\\mathcal{#1}', 1],
  dutchcal: ['\\mathcal{#1}', 1],
  mathbbb: ['\\mathbb{#1}', 1],
  mymathbb: ['\\mathbb{#1}', 1],
  mathsfbi: ['\\boldsymbol{\\mathsf{#1}}', 1],
  mathbsf: ['\\mathsf{#1}', 1],
  widebar: ['\\overline{#1}', 1],
  // amsmath's limits-under form of `\operatorname`; a TeX-internal ∑ name that leaks from alttext.
  operatornamewithlimits: ['\\operatorname*{#1}', 1],
  sumop: '\\sum',
  // stmaryrd double brackets/angles (⟦ ⟧ ⟪ ⟫) built from base delimiters + negative thin space.
  llbracket: '[\\![',
  rrbracket: ']\\!]',
  llangle: '\\langle\\!\\langle',
  rrangle: '\\rangle\\!\\rangle',
  // mathtools centered colon (`\vcentcolon`, as in `\vcentcolon=`) — degrade to a plain colon.
  vcentcolon: ':',
  // Dotted/dashed underlines (ulem) degrade to a plain underline.
  dotuline: ['\\underline{#1}', 1],
  dashuline: ['\\underline{#1}', 1],
  // `\addcontentsline{toc}{section}{…}` — a TOC side effect with three braced args, no math. No-op.
  addcontentsline: ['', 3],
  // TeX no-op primitive — also what's left after the `\mathchar <n>` strip in preprocessLatex (a
  // stray `\mathchar 58\relax`), which MathJax otherwise reports as undefined.
  relax: '',
  // `\vbox{…}` — a vertical box; keep its content (no optional args, unlike \raisebox/\makebox).
  vbox: ['#1', 1],
  // Extensible long arrow (mathabx/extarrows) — degrade to amsmath's `\xrightarrow`.
  xlongrightarrow: ['\\xrightarrow{#1}', 1],
  // ulem underline variants → plain underline.
  uline: ['\\underline{#1}', 1],
  uwave: ['\\underline{#1}', 1],
  // `\textsubscript{i}` (text-mode subscript that leaks into math) → a math subscript.
  textsubscript: ['_{#1}', 1],
  // `\underaccent{\bar}{x}` (accents package) → the accent placed under the base.
  underaccent: ['\\underset{#1}{#2}', 2],
  // Extremely common operators many papers USE without `\DeclareMathOperator`-ing them (a paper that
  // does define them wins via the author-macro merge order). Limits-under form matches convention.
  argmin: '\\operatorname*{arg\\,min}',
  argmax: '\\operatorname*{arg\\,max}',
};

// Convert an author MathMacros map (KaTeX/preamble shape) to MathJax's macro form: strip the leading
// backslash from the key, and when the value uses `#n` arguments pass `[template, argCount]` (MathJax
// requires the arity explicitly, unlike KaTeX which infers it).
export function toMathjaxMacros(macros?: MathMacros): Record<string, string | [string, number]> {
  const out: Record<string, string | [string, number]> = { ...DEFAULT_MACROS };
  if (macros) {
    for (const [key, value] of Object.entries(macros)) {
      const name = key.replace(/^\\/, '');
      let maxArg = 0;
      for (const m of value.matchAll(/#(\d)/g)) maxArg = Math.max(maxArg, Number(m[1]));
      out[name] = maxArg > 0 ? [value, maxArg] : value;
    }
  }
  return out;
}

// The TeX packages we register — the standard set MINUS `mhchem` (chemistry), `bussproofs` (proof
// trees) and `html` (raw-HTML injection, an XSS surface). Verified to render 100% of a math-heavy
// arXiv paper's formulas; excluding those keeps the on-demand chunk smaller and the surface safer.
// The corresponding Configuration side-effect imports live in each consumer (they must be static for
// the bundler); the NAMES here must match that import set.
export const PACKAGES = [
  'base', 'ams', 'amscd', 'boldsymbol', 'braket', 'cancel', 'cases', 'centernot', 'color',
  'configmacros', 'enclose', 'extpfeil', 'gensymb', 'mathtools', 'newcommand', 'physics',
  'textcomp', 'textmacros', 'unicode', 'upgreek',
];

// ---------------------------------------------------------------------------
// preprocessLatex — small read-time normalizations for constructs MathJax has no equivalent for or
// that are not math at all. (The physics `\matrixquantity`/`\derivative` rewriters KaTeX needed are
// gone: MathJax's `physics` package handles them natively.)

// From an opening delimiter at `s[i]` (`(`, `[`, or `{`), return the substring up to its matching
// close and the index just past it — tracking nesting of the SAME delimiter and skipping over `{…}`
// groups and backslash-escaped chars. Null if unbalanced.
function readDelimGroup(s: string, i: number): { inner: string; end: number } | null {
  const open = s[i];
  const close = open === '(' ? ')' : open === '[' ? ']' : open === '{' ? '}' : '';
  if (!close) return null;
  if (open === '{') {
    let depth = 0;
    for (let j = i; j < s.length; j += 1) {
      const c = s[j];
      if (c === '\\') { j += 1; continue; }
      if (c === '{') depth += 1;
      else if (c === '}') { depth -= 1; if (depth === 0) return { inner: s.slice(i + 1, j), end: j + 1 }; }
    }
    return null;
  }
  let depth = 0;
  let brace = 0;
  for (let j = i; j < s.length; j += 1) {
    const c = s[j];
    if (c === '\\') { j += 1; continue; }
    if (c === '{') brace += 1;
    else if (c === '}') brace -= 1;
    else if (brace === 0) {
      if (c === open) depth += 1;
      else if (c === close) { depth -= 1; if (depth === 0) return { inner: s.slice(i + 1, j), end: j + 1 }; }
    }
  }
  return null;
}

function skipSpace(s: string, i: number): number {
  while (i < s.length && /\s/.test(s[i])) i += 1;
  return i;
}

// LaTeXML sometimes leaks a reference/citation command into a formula's alttext (a `\cite`/`\ref`, or
// a LaTeXML-internal `\lx@cref` cleveref taking TWO args). These carry no math meaning and would throw,
// so strip the command plus its optional `[…]` and ALL of its balanced `{…}` arguments.
const LEAKED_REF_RE = /\\(?:cite[a-z]*|ref|eqref|autoref|label|footnote|lx@[a-zA-Z@]+)\b/g;
function stripLeakedRefs(latex: string): string {
  let out = '';
  let last = 0;
  let m: RegExpExecArray | null;
  LEAKED_REF_RE.lastIndex = 0;
  while ((m = LEAKED_REF_RE.exec(latex))) {
    out += latex.slice(last, m.index);
    let i = skipSpace(latex, m.index + m[0].length);
    if (latex[i] === '[') {
      const g = readDelimGroup(latex, i);
      if (g) i = g.end;
    }
    for (;;) {
      const j = skipSpace(latex, i);
      if (latex[j] !== '{') break;
      const g = readDelimGroup(latex, j);
      if (!g) break;
      i = g.end;
    }
    last = i;
    LEAKED_REF_RE.lastIndex = i;
  }
  return out + latex.slice(last);
}

// `\scalebox{factor}{content}` / `\resizebox{w}{h}{content}` carry display-only sizing MathJax has no
// equivalent for. Keep the content group (the last argument), drop the size args.
function rewriteScalebox(s: string): string {
  const re = /\\(scalebox|resizebox)\b\s*/g;
  let out = '';
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    const argc = m[1] === 'resizebox' ? 3 : 2;
    let i = m.index + m[0].length;
    const groups: { inner: string; end: number }[] = [];
    for (let k = 0; k < argc; k += 1) {
      i = skipSpace(s, i);
      if (s[i] !== '{') break;
      const g = readDelimGroup(s, i);
      if (!g) break;
      groups.push(g);
      i = g.end;
    }
    if (groups.length !== argc) continue;
    out += s.slice(last, m.index) + `{${groups[argc - 1].inner}}`;
    last = i;
    re.lastIndex = i;
  }
  return out + s.slice(last);
}

// `physics` redefines these plain function operators to CAPTURE and auto-size a following
// parenthesis group (its `'Expression'` handler). An unbalanced paren — an author typo, or an
// `align` line we split mid-group so `(` and `)` land on different lines — then throws a fatal parse
// error that collapses the WHOLE formula to the `수식` chip (arXiv:2502.02016v1 eq(29):
// `\exp(c\cos((x-m))` has three `(` and two `)`). Routing each to `\operatorname{name}` (identical
// glyph + spacing, minus physics' paren capture) makes the paren an ordinary character, so a
// mismatched paren renders literally instead of nuking the line. Two groups because physics reads an
// optional `[power]` ONLY on the trig family (its `opt=true`), rendering `\sin[2](x)` as sin²(x) — we
// preserve that as `^{power}`; the non-trig operators take no such bracket. `\trace`/`\Trace` render
// as `tr`/`Tr` in physics, so they map to those names, not literally. Excluded on purpose: `\div`
// (handled above) and `\curl`/`\laplacian`/`\Res`/`\Re`/`\Im`, whose output ≠ their name. Longest
// names first so the `(?![a-zA-Z])` boundary picks e.g. `\arcsin` over `\sin`.
const PHYSICS_TRIG_RE =
  /\\(arcsin|arccos|arctan|arccsc|arcsec|arccot|sinh|cosh|tanh|csch|sech|coth|asin|acos|atan|acsc|asec|acot|sin|cos|tan|csc|sec|cot)(?![a-zA-Z])(\[[^\]]*\])?/g;
const PHYSICS_FN_RE = /\\(exp|log|ln|det|Pr|tr|Tr|erf)(?![a-zA-Z])/g;

export function preprocessLatex(latex: string): string {
  // Drop leaked citation/ref commands (a `\cite` inside a `\text{}` would otherwise throw), unwrap
  // `\scalebox`/`\resizebox` to their content, restore `\div` to the DIVISION sign (the `physics`
  // package — loaded for `\quantity`/`\derivative`/… — redefines it as the *divergence* operator ∇·,
  // mis-rendering the far more common `a \div b`), and defuse physics' function paren-capture (see
  // `PHYSICS_TRIG_RE`/`PHYSICS_FN_RE`) so an unbalanced paren no longer collapses the whole formula.
  return rewriteScalebox(stripLeakedRefs(latex))
    .replace(/\\div(?![a-zA-Z])/g, '\\mathbin{÷}')
    .replace(PHYSICS_TRIG_RE, (_m, name, power) =>
      power ? `\\operatorname{${name}}^{${power.slice(1, -1)}}` : `\\operatorname{${name}}`,
    )
    .replace(PHYSICS_FN_RE, '\\operatorname{$1}')
    .replace(/\\trace(?![a-zA-Z])/g, '\\operatorname{tr}')
    .replace(/\\Trace(?![a-zA-Z])/g, '\\operatorname{Tr}')
    // Glue/penalty/mathchar primitives (from the corpus render sweep) take a NON-braced arg — a
    // dimension or a number — so a no-op macro can't swallow it (the number would render as literal
    // text). Strip the command AND its argument. MathJax has no default for any of these, so an
    // unhandled one collapses the whole formula.
    .replace(/\\vskip\s*-?[\d.]+\s*[a-z]{0,2}/g, '') // \vskip 5.69pt  (vertical glue — drop)
    .replace(/\\penalty\s*-?\d+/g, '') //               \penalty 10000 (line-break penalty — drop)
    .replace(/\\mathchar\s*"?[0-9A-Fa-f]+/g, '') //     \mathchar 58   (raw char code — drop)
    .replace(/\\@(?![a-zA-Z])/g, '') //                 \@             (sentence-end spacing — drop)
    // Color commands (from the sweep) carry no math meaning in our display-only render and their
    // `[model]{spec}` args need color models MathJax doesn't define by default (→ "Color model not
    // defined"). Drop the color SWITCHES and definitions, keeping the content they would have tinted.
    // `\textcolor{c}{content}` is NOT matched (different name) — MathJax's color package handles it.
    .replace(/\\definecolor\s*\{[^}]*\}\s*\{[^}]*\}\s*\{[^}]*\}/g, '') // \definecolor{n}{model}{spec}
    .replace(/\\pagecolor(?![a-zA-Z])\s*(\[[^\]]*\])?\s*\{[^}]*\}/g, '') // \pagecolor[model]{spec}
    .replace(/\\color(?![a-zA-Z])\s*(\[[^\]]*\])?\s*\{[^}]*\}/g, ''); //   \color[model]{spec}
}
