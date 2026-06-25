'use client';

// renderMath (D4 — doc-model rich view). Renders LaTeX with KaTeX. The doc-model carries
// formulas as LaTeX (display blocks) and inline math embedded as \( ... \) inside text.
// XSS: KaTeX escapes its input and emits trusted markup; `throwOnError: false` degrades a
// malformed expression to its (escaped) source instead of throwing. Surrounding prose is
// rendered as React text nodes (escaped), never as HTML.
//
// The KaTeX stylesheet lives here, not in each consumer — any view that renders math (the
// doc-model viewer, the paper-detail abstract) gets it by importing this module, so math is
// never shown with the unstyled fallback.
import 'katex/dist/katex.min.css';
import { Fragment } from 'react';
import katex from 'katex';

// Memoize rendered LaTeX — katex.renderToString is a synchronous parse and the same
// expression re-renders on every parent re-render (e.g. when figure assets resolve, or a
// results table with many math cells re-renders). Keyed by (displayMode, latex); the input
// space is bounded by the paper's distinct expressions.
const _cache = new Map<string, string>();

function toHtml(latex: string, displayMode: boolean): string {
  const cacheKey = `${displayMode ? 'd' : 'i'}:${latex}`;
  const hit = _cache.get(cacheKey);
  if (hit !== undefined) return hit;
  const html = katex.renderToString(latex, { displayMode, throwOnError: false, output: 'html' });
  _cache.set(cacheKey, html);
  return html;
}

/** A display (block-level) equation. */
export function MathDisplay({ latex }: { latex: string }) {
  return <span dangerouslySetInnerHTML={{ __html: toHtml(latex, true) }} />;
}

// Math delimiters, in match-priority order: display `$$…$$` / `\[…\]`, then inline `\(…\)`
// / `$…$`. arXiv abstracts use TeX `$…$` (e.g. "$K$", "$\beta\leq 1$"), the doc-model uses
// `\(…\)` — both are supported. The `$…$` arm forbids whitespace just inside the delimiters
// (`(?!\s)` / `(?<!\s)`) so prose prices like "$5 and $10" don't get parsed as math.
// Group: 1=$$ display, 2=\[ display, 3=\( inline, 4=$ inline.
const MATH =
  /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$(?!\s)((?:\\.|[^$])+?)(?<!\s)\$/g;

/** Render text that may contain inline/display math (`$…$`, `$$…$$`, `\(…\)`, `\[…\]`) into
 * React nodes. Prose segments stay React-escaped; only the math segments become KaTeX markup. */
export function renderInlineMath(text: string): React.ReactNode {
  if (!text.includes('$') && !text.includes('\\(') && !text.includes('\\[')) return text;
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of text.matchAll(MATH)) {
    const idx = m.index ?? 0;
    if (idx > last) nodes.push(<Fragment key={key++}>{text.slice(last, idx)}</Fragment>);
    const display = m[1] !== undefined || m[2] !== undefined;
    const latex = m[1] ?? m[2] ?? m[3] ?? m[4] ?? '';
    nodes.push(<span key={key++} dangerouslySetInnerHTML={{ __html: toHtml(latex, display) }} />);
    last = idx + m[0].length;
  }
  if (last === 0) return text; // no delimiter actually matched (e.g. a lone `$`)
  if (last < text.length) nodes.push(<Fragment key={key++}>{text.slice(last)}</Fragment>);
  return nodes;
}
