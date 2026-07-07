'use client';

// renderMath (D4 — doc-model rich view). Renders LaTeX with MathJax (SVG output). The doc-model
// carries formulas as LaTeX (display blocks) and inline math embedded as \( ... \) inside text.
//
// Why MathJax over KaTeX: papers pull in the long tail of TeX packages (physics, upgreek, bm, …)
// via their e-print preamble; KaTeX implements only a core subset, so an unhandled command collapses
// the whole formula to a placeholder. MathJax ships those packages, so far fewer formulas break.
//
// Cost: MathJax is ~9x KaTeX's size, so it is **lazy-loaded** — the ~600KB chunk is fetched only
// when a math-bearing view first mounts (code-split via dynamic import), never in the initial bundle.
// Until it resolves, each math span shows a neutral skeleton; when the engine is ready every span
// re-renders (subscribed via useSyncExternalStore).
//
// Output is SVG (glyph paths inlined) — self-contained, so no external web-font stylesheet is needed
// (CSP-safe) and the markup can be injected via dangerouslySetInnerHTML. Surrounding prose is rendered
// as React text nodes (escaped), never as HTML.
import './renderMath.css';
import { Fragment, useSyncExternalStore } from 'react';

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
const DEFAULT_MACROS: Record<string, string | [string, number]> = {
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
};

// Convert an author MathMacros map (KaTeX/preamble shape) to MathJax's macro form: strip the leading
// backslash from the key, and when the value uses `#n` arguments pass `[template, argCount]` (MathJax
// requires the arity explicitly, unlike KaTeX which infers it).
function toMathjaxMacros(macros?: MathMacros): Record<string, string | [string, number]> {
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

// ---------------------------------------------------------------------------
// Lazy MathJax engine. Loaded once per session on first use; a tiny external store lets every mounted
// math span re-render when it becomes ready (useSyncExternalStore).

type Engine = {
  outerHTML: (node: unknown) => string;
  makeDoc: (macros: Record<string, string | [string, number]>) => {
    convert: (latex: string, opts: { display: boolean }) => unknown;
  };
};

let engine: Engine | null = null;
let loadPromise: Promise<void> | null = null;
let loadFailed = false;
const listeners = new Set<() => void>();

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

// Three states so a span can distinguish "still loading" from "load failed" — a failed chunk must
// degrade to the source fallback, never hang on the skeleton forever (frontend 무한 로딩 금지).
type EngineStatus = 'loading' | 'ready' | 'error';
function getSnapshot(): EngineStatus {
  if (engine) return 'ready';
  if (loadFailed) return 'error';
  return 'loading';
}
function getServerSnapshot(): EngineStatus {
  return 'loading'; // SSR renders the placeholder; the engine is a browser-only, on-demand chunk.
}

// The TeX packages we register — the standard set MINUS `mhchem` (chemistry), `bussproofs` (proof
// trees) and `html` (raw-HTML injection, an XSS surface). Verified to render 100% of a math-heavy
// arXiv paper's formulas; excluding those keeps the on-demand chunk smaller and the surface safer.
const PACKAGES = [
  'base', 'ams', 'amscd', 'boldsymbol', 'braket', 'cancel', 'cases', 'centernot', 'color',
  'configmacros', 'enclose', 'extpfeil', 'gensymb', 'mathtools', 'newcommand', 'physics',
  'textcomp', 'textmacros', 'unicode', 'upgreek',
];

/** Load the MathJax engine (idempotent). Exposed so a consumer can warm the chunk ahead of paint,
 * and so tests can await readiness before asserting rendered output. On failure it clears its cached
 * promise so a later mount can retry, flips the error state (spans fall back to the source), and
 * rethrows so an awaiting caller (e.g. a test) sees it. */
export function preloadMathEngine(): Promise<void> {
  if (engine) return Promise.resolve();
  if (loadPromise) return loadPromise;
  loadFailed = false;
  loadPromise = (async () => {
    const [{ mathjax }, { TeX }, { SVG }, { liteAdaptor }, { RegisterHTMLHandler }] =
      await Promise.all([
        import('mathjax-full/js/mathjax.js'),
        import('mathjax-full/js/input/tex.js'),
        import('mathjax-full/js/output/svg.js'),
        import('mathjax-full/js/adaptors/liteAdaptor.js'),
        import('mathjax-full/js/handlers/html.js'),
      ]);
    // Registering each package's Configuration (side-effect import) is what makes its name usable in
    // `PACKAGES`. `physics` is not part of AllPackages, so it MUST be registered here alongside the rest.
    await Promise.all([
      import('mathjax-full/js/input/tex/base/BaseConfiguration.js'),
      import('mathjax-full/js/input/tex/ams/AmsConfiguration.js'),
      import('mathjax-full/js/input/tex/amscd/AmsCdConfiguration.js'),
      import('mathjax-full/js/input/tex/boldsymbol/BoldsymbolConfiguration.js'),
      import('mathjax-full/js/input/tex/braket/BraketConfiguration.js'),
      import('mathjax-full/js/input/tex/cancel/CancelConfiguration.js'),
      import('mathjax-full/js/input/tex/cases/CasesConfiguration.js'),
      import('mathjax-full/js/input/tex/centernot/CenternotConfiguration.js'),
      import('mathjax-full/js/input/tex/color/ColorConfiguration.js'),
      import('mathjax-full/js/input/tex/configmacros/ConfigMacrosConfiguration.js'),
      import('mathjax-full/js/input/tex/enclose/EncloseConfiguration.js'),
      import('mathjax-full/js/input/tex/extpfeil/ExtpfeilConfiguration.js'),
      import('mathjax-full/js/input/tex/gensymb/GensymbConfiguration.js'),
      import('mathjax-full/js/input/tex/mathtools/MathtoolsConfiguration.js'),
      import('mathjax-full/js/input/tex/newcommand/NewcommandConfiguration.js'),
      import('mathjax-full/js/input/tex/physics/PhysicsConfiguration.js'),
      import('mathjax-full/js/input/tex/textcomp/TextcompConfiguration.js'),
      import('mathjax-full/js/input/tex/textmacros/TextMacrosConfiguration.js'),
      import('mathjax-full/js/input/tex/unicode/UnicodeConfiguration.js'),
      import('mathjax-full/js/input/tex/upgreek/UpgreekConfiguration.js'),
    ]);
    const adaptor = liteAdaptor();
    RegisterHTMLHandler(adaptor);
    engine = {
      outerHTML: (node) => adaptor.outerHTML(node as never),
      makeDoc: (macros) => {
        // formatError THROWS so an undefined command surfaces as a caught exception (→ fallback chip),
        // instead of MathJax's default inline `<merror>` red box which would read as broken.
        const tex = new TeX({ packages: PACKAGES, macros, formatError: (_jax: unknown, err: Error) => {
          throw err;
        } });
        const svg = new SVG({ fontCache: 'none' }); // self-contained per-formula SVG (CSP-safe)
        return mathjax.document('', { InputJax: tex, OutputJax: svg }) as never;
      },
    };
    listeners.forEach((cb) => cb());
  })().catch((err) => {
    // Chunk load / init failed (stale hashes after a deploy, offline, …). Flip to the error state so
    // mounted spans degrade to the source fallback instead of an infinite skeleton, and null the
    // cached promise so a future mount (e.g. a later navigation) can retry rather than being stuck.
    loadFailed = true;
    loadPromise = null;
    listeners.forEach((cb) => cb());
    throw err;
  });
  return loadPromise;
}

// ---------------------------------------------------------------------------
// Fail-soft fallback: author LaTeX can carry a construct MathJax still rejects (an unknown macro, a
// stray delimiter, …). With formatError throwing, we catch it and emit a compact, intentional-looking
// placeholder carrying the source in its tooltip (hover/long-press to inspect) — never a wall of
// backslashes. Ingestion strips the known offenders, but the input is open-ended, so this guarantees
// no formula ever renders as broken source regardless of what slips through.
function escapeHtmlAttr(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fallbackHtml(latex: string, displayMode: boolean): string {
  const title = escapeHtmlAttr(latex);
  // Inline styles (not a CSS-module class) because this HTML is injected via dangerouslySetInnerHTML
  // into several consumers with independent stylesheets; inline keeps it self-contained + CSP-safe.
  const shared =
    'color:#6b7280;font-size:0.9em;border:1px dashed currentColor;border-radius:4px;' +
    'padding:0 0.35em;cursor:help;white-space:nowrap;';
  const style = displayMode ? `display:inline-block;${shared}` : shared;
  return (
    `<span role="img" aria-label="수식 (표시할 수 없음)" title="${title}" style="${style}">` +
    `수식</span>`
  );
}

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

function preprocessLatex(latex: string): string {
  // Drop leaked citation/ref commands (a `\cite` inside a `\text{}` would otherwise throw), unwrap
  // `\scalebox`/`\resizebox` to their content, and restore `\div` to the DIVISION sign. The `physics`
  // package (loaded for its `\quantity`/`\derivative`/… support) redefines `\div` as the *divergence*
  // operator (∇·), which would silently mis-render the far more common `a \div b` division; rewriting
  // `\div` (not `\divergence`/`\divideontimes`) back to `÷` keeps standard LaTeX semantics.
  return rewriteScalebox(stripLeakedRefs(latex)).replace(/\\div(?![a-zA-Z])/g, '\\mathbin{÷}');
}

// ---------------------------------------------------------------------------
// Render + memoize. katex.renderToString was synchronous; MathJax's document.convert is too (after the
// engine loads), so the same string cache applies. Keyed by (displayMode, latex) per macro map; the
// input space is bounded by a paper's distinct expressions.
type MacroEntry = { doc: ReturnType<Engine['makeDoc']> | null; mj: Record<string, string | [string, number]>; cache: Map<string, string> };

const _defaultEntry: MacroEntry = { doc: null, mj: DEFAULT_MACROS, cache: new Map() };
const _byMacros = new WeakMap<MathMacros, MacroEntry>();

// Per-entry render-cache cap. The macro-less default cache is shared across every paper's abstracts/
// summaries in a session, so an uncapped Map would grow without bound; evict oldest-first (Map keeps
// insertion order) past the cap. A paper has at most a few hundred distinct expressions.
const MAX_CACHE = 800;
function cacheSet(cache: Map<string, string>, key: string, value: string): void {
  if (cache.size >= MAX_CACHE) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
  cache.set(key, value);
}

function entryFor(macros?: MathMacros): MacroEntry {
  if (!macros) return _defaultEntry;
  let entry = _byMacros.get(macros);
  if (!entry) {
    entry = { doc: null, mj: toMathjaxMacros(macros), cache: new Map() };
    _byMacros.set(macros, entry);
  }
  return entry;
}

// A macro-DEFINING command persists in MathJax's TeX jax across convert() calls on the same document.
// Only such an expression needs an isolated throwaway document (see below); everything else can reuse.
const DEFINES_RE = /\\(?:x?def|gdef|edef|let|(?:re|provide)?newcommand|DeclareMathOperator)\b/;

// Precondition: the engine is loaded (only called from a Math span that has observed readiness).
function toHtml(latex: string, displayMode: boolean, macros?: MathMacros): string {
  const eng = engine!;
  const entry = entryFor(macros);
  const cacheKey = `${displayMode ? 'd' : 'i'}:${latex}`;
  const hit = entry.cache.get(cacheKey);
  if (hit !== undefined) return hit;
  let html: string;
  try {
    // Author-macro entries belong to ONE paper: reuse one document (a paper's own defs applying to its
    // own formulas is correct). The macro-less DEFAULT entry is shared across DIFFERENT papers'
    // abstracts, so a stray `\def` must NOT leak between them — but a `\def` in an abstract is almost
    // never present, so only isolate (throwaway document) the expressions that actually define a macro;
    // all others reuse the entry's document, avoiding a fresh TeX+SVG build per formula. Kept inside the
    // try so a bad macro set degrades to the placeholder rather than crashing the render tree.
    const needsIsolation = !macros && DEFINES_RE.test(latex);
    const doc = needsIsolation ? eng.makeDoc(entry.mj) : (entry.doc ??= eng.makeDoc(entry.mj));
    const node = doc.convert(preprocessLatex(latex), { display: displayMode });
    html = eng.outerHTML(node);
  } catch {
    // Tooltip carries the ORIGINAL source (pre-rewrite), so a hover shows what the author wrote.
    html = fallbackHtml(latex, displayMode);
  }
  cacheSet(entry.cache, cacheKey, html);
  return html;
}

// A single math span. Subscribes to engine readiness; shows a neutral skeleton until the MathJax chunk
// has loaded, then re-renders to the (cached) SVG. If the chunk fails to load it degrades to the source
// fallback chip (never an infinite skeleton). Kicks off the load on first mount (browser only).
// (Named MathSpan, not Math — the latter would shadow the global `Math` at module scope.)
function MathSpan({ latex, display, macros }: { latex: string; display: boolean; macros?: MathMacros }) {
  const status = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  if (status === 'ready') {
    return <span dangerouslySetInnerHTML={{ __html: toHtml(latex, display, macros) }} />;
  }
  if (status === 'error') {
    // Chunk load failed — show the source in the fallback chip rather than hang on the skeleton.
    return <span dangerouslySetInnerHTML={{ __html: fallbackHtml(latex, display) }} />;
  }
  // loading: kick off the (idempotent) load; swallow rejection here (the error state, set inside
  // preloadMathEngine, drives the fallback above — this only avoids an unhandled-rejection warning).
  if (typeof window !== 'undefined') void preloadMathEngine().catch(() => {});
  return (
    <span
      className={display ? 'mathLoading mathLoadingDisplay' : 'mathLoading'}
      role="img"
      aria-label="수식 로딩 중"
    />
  );
}

/** A display (block-level) equation. */
export function MathDisplay({ latex, macros }: { latex: string; macros?: MathMacros }) {
  return <MathSpan latex={latex} display macros={macros} />;
}

type MathToken = { start: number; end: number; latex: string; display: boolean };

function isWhitespace(char: string | undefined): boolean {
  return char === undefined || /\s/.test(char);
}

function findClosingDollar(text: string, from: number): number {
  for (let i = from; i < text.length; i += 1) {
    if (text[i] === '$' && text[i - 1] !== '\\' && !isWhitespace(text[i - 1])) return i;
  }
  return -1;
}

// Math delimiters, in match-priority order: display `$$…$$` / `\[…\]`, then inline `\(…\)`
// / `$…$`. Scanning avoids regex backtracking on LaTeX-heavy strings with many escaped chars.
function findNextMath(text: string, from: number): MathToken | null {
  for (let i = from; i < text.length; i += 1) {
    if (text.startsWith('$$', i)) {
      const end = text.indexOf('$$', i + 2);
      if (end !== -1)
        return { start: i, end: end + 2, latex: text.slice(i + 2, end), display: true };
      i += 1;
      continue;
    }
    if (text.startsWith('\\[', i)) {
      const end = text.indexOf('\\]', i + 2);
      if (end !== -1)
        return { start: i, end: end + 2, latex: text.slice(i + 2, end), display: true };
      i += 1;
      continue;
    }
    if (text.startsWith('\\(', i)) {
      const end = text.indexOf('\\)', i + 2);
      if (end !== -1)
        return { start: i, end: end + 2, latex: text.slice(i + 2, end), display: false };
      i += 1;
      continue;
    }
    if (text[i] === '$' && !isWhitespace(text[i + 1])) {
      const end = findClosingDollar(text, i + 1);
      if (end !== -1)
        return { start: i, end: end + 1, latex: text.slice(i + 1, end), display: false };
    }
  }
  return null;
}

/** Render text that may contain inline/display math (`$…$`, `$$…$$`, `\(…\)`, `\[…\]`) into
 * React nodes. Prose segments stay React-escaped; only the math segments become KaTeX/MathJax markup. */
export function renderInlineMath(text: string, macros?: MathMacros): React.ReactNode {
  if (!text.includes('$') && !text.includes('\\(') && !text.includes('\\[')) return text;
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  while (last < text.length) {
    const token = findNextMath(text, last);
    if (!token) break;
    if (token.start > last)
      nodes.push(<Fragment key={key++}>{text.slice(last, token.start)}</Fragment>);
    nodes.push(
      <MathSpan key={key++} latex={token.latex} display={token.display} macros={macros} />,
    );
    last = token.end;
  }
  if (last === 0) return text; // no delimiter actually matched (e.g. a lone `$`)
  if (last < text.length) nodes.push(<Fragment key={key++}>{text.slice(last)}</Fragment>);
  return nodes;
}

// **bold** spans (non-greedy). Bold may wrap math, so each part is still run through
// renderInlineMath. Used inside renderRichText for LLM summary prose.
const BOLD = /\*\*([\s\S]+?)\*\*/g;

/** Normalize the literal `\n`/`\t` escape artifacts that the backend's JSON re-escaping leaves in
 * math-heavy fields, back into a real newline / space — but NOT when the backslash starts a LaTeX
 * command (`\nabla`, `\theta`, `\times`), so math survives. */
function normalizeEscapeArtifacts(text: string): string {
  return text.replace(/\\n(?![a-zA-Z])/g, '\n').replace(/\\t(?![a-zA-Z])/g, ' ');
}

/** Inline render: `**bold**` + math, no block structure. For short single-line fields and list
 * items (already inside an <li>). */
export function renderInlineRich(text: string, macros?: MathMacros): React.ReactNode {
  const t = normalizeEscapeArtifacts(text);
  if (!t.includes('**')) return renderInlineMath(t, macros);
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of t.matchAll(BOLD)) {
    const idx = m.index ?? 0;
    if (idx > last) {
      nodes.push(<Fragment key={key++}>{renderInlineMath(t.slice(last, idx), macros)}</Fragment>);
    }
    nodes.push(<strong key={key++}>{renderInlineMath(m[1], macros)}</strong>);
    last = idx + m[0].length;
  }
  if (last < t.length) {
    nodes.push(<Fragment key={key++}>{renderInlineMath(t.slice(last), macros)}</Fragment>);
  }
  return nodes;
}

/** Render an LLM summary field as lightweight markdown + math: blank-line paragraphs, `-`/`*`
 * bullet lists, `**bold**`, and inline/display math. Also normalizes literal `\n`/`\t` escape
 * artifacts (left by re-escaping math-heavy JSON) into real breaks/space — but NOT when they start
 * a LaTeX command (`\nabla`, `\theta`, `\times`), so math survives. Returns block elements, so the
 * caller must place it in a block container (a <div>, not a <p>). */
export function renderRichText(text: string, macros?: MathMacros): React.ReactNode {
  if (!text) return null;
  const normalized = normalizeEscapeArtifacts(text);
  const blocks = normalized
    .split(/\n{2,}/)
    .map((b) => b.trim())
    .filter(Boolean);
  if (blocks.length === 0) return null;
  return blocks.map((block, bi) => {
    const lines = block.split('\n').map((l) => l.trimEnd());
    const nonEmpty = lines.filter((l) => l.trim());
    const isBullets = nonEmpty.length > 0 && nonEmpty.every((l) => /^\s*[-*•]\s+/.test(l));
    if (isBullets) {
      const items = nonEmpty.map((l) => l.replace(/^\s*[-*•]\s+/, ''));
      return (
        <ul key={bi}>
          {items.map((it, ii) => (
            <li key={ii}>{renderInlineRich(it, macros)}</li>
          ))}
        </ul>
      );
    }
    return (
      <p key={bi}>
        {lines.map((l, li) => (
          <Fragment key={li}>
            {li > 0 ? <br /> : null}
            {renderInlineRich(l, macros)}
          </Fragment>
        ))}
      </p>
    );
  });
}
