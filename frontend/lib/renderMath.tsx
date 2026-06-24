'use client';

// renderMath (D4 — doc-model rich view). Renders LaTeX with KaTeX. The doc-model carries
// formulas as LaTeX (display blocks) and inline math embedded as \( ... \) inside text.
// XSS: KaTeX escapes its input and emits trusted markup; `throwOnError: false` degrades a
// malformed expression to its (escaped) source instead of throwing. Surrounding prose is
// rendered as React text nodes (escaped), never as HTML.
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

const INLINE_MATH = /\\\(([\s\S]*?)\\\)/g;

/** Render text that may contain inline math (`\( ... \)`) into React nodes. Prose segments
 * stay React-escaped; only the math segments become KaTeX markup. */
export function renderInlineMath(text: string): React.ReactNode {
  if (!text.includes('\\(')) return text;
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of text.matchAll(INLINE_MATH)) {
    const idx = m.index ?? 0;
    if (idx > last) nodes.push(<Fragment key={key++}>{text.slice(last, idx)}</Fragment>);
    nodes.push(
      <span key={key++} dangerouslySetInnerHTML={{ __html: toHtml(m[1], false) }} />,
    );
    last = idx + m[0].length;
  }
  if (last < text.length) nodes.push(<Fragment key={key++}>{text.slice(last)}</Fragment>);
  return nodes;
}
