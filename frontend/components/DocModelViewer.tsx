'use client';

// DocModelViewer (자체 리치뷰, D4/Q5=C, BR-SF-11) — renders the structured doc-model:
// nested sections + TOC, KaTeX formulas, structured tables (DATA, not crops — D8), and
// webp figures joined to the /assets signed urls by assetId (SEC-9 — the doc-model is
// url-free). OA-license-gated: license_unavailable → arXiv link-out. External text is
// escaped by React (BR-SF-9). Replaces the legacy plain-text full-text viewer.
//
// NOTE: anchor highlight matches the summary anchor's label ("Table 1"/"Figure 2") to a
// block's anchorLabel (the AnchorVM still carries a label, not a doc-model id — the
// id-based anchor contract is a follow-up). Span-precise inline highlight is a follow-up.
// (KaTeX stylesheet is pulled in by the renderMath import below.)
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { AnchorVM, AssetRef, DocBlock, DocModel, DocSection } from '@/types/generated';
import { useDocModel } from '@/lib/useDocModel';
import { useAssets } from '@/lib/useAssets';
import { MathDisplay, renderInlineMath } from '@/lib/renderMath';
import { StateView } from './StateView';
import styles from './DocModelViewer.module.css';

interface DocModelViewerProps {
  paperId: string;
  version: number;
  /** Summary source anchor to scroll to / highlight, if any (matched by label). */
  anchor?: AnchorVM | null;
  arxivUrl?: string;
}

export function DocModelViewer({ paperId, version, anchor, arxivUrl }: DocModelViewerProps) {
  const { state, load } = useDocModel();
  const { state: assetState, load: loadAssets } = useAssets();
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    void load({ paperId, version });
    void loadAssets(paperId, version); // figures join these signed urls by assetId
  }, [paperId, version, load, loadAssets]);

  const assetsById = useMemo(() => {
    const map = new Map<string, AssetRef>();
    if (assetState.status === 'done' && assetState.outcome.kind === 'assets') {
      for (const a of assetState.outcome.assets) map.set(a.assetId, a);
    }
    return map;
  }, [assetState]);

  const docModel =
    state.status === 'done' && state.outcome.kind === 'page' ? state.outcome.docModel : null;

  // Scroll to + highlight the block whose anchorLabel matches the selected anchor.
  useEffect(() => {
    if (!docModel || !anchor || !containerRef.current) return;
    const id = findBlockIdByLabel(docModel, anchor.label);
    if (!id) return;
    const el = containerRef.current.querySelector<HTMLElement>(`[data-block="${CSS.escape(id)}"]`);
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [docModel, anchor]);

  if (state.status === 'idle' || state.status === 'loading') {
    return <StateView kind="loading" title="본문 불러오는 중…" message="본문을 가져오고 있어요." />;
  }

  const { outcome } = state;
  const safeArxivUrl =
    arxivUrl && (arxivUrl.startsWith('http://') || arxivUrl.startsWith('https://'))
      ? arxivUrl
      : undefined;

  switch (outcome.kind) {
    case 'building':
      // Lazy build in flight (BR-30/D6): the hook is polling — show a "preparing" loader.
      return (
        <StateView
          kind="loading"
          title="본문 준비 중…"
          message="처음 여는 논문이라 본문을 만들고 있어요. 잠시만 기다려 주세요."
        />
      );
    case 'licenseUnavailable':
      return (
        <div className={styles.gate} data-testid="docmodel-license">
          <StateView kind="licenseUnavailable" />
          {safeArxivUrl ? (
            <a
              className={styles.link}
              href={safeArxivUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              arXiv에서 원문 보기
            </a>
          ) : null}
        </div>
      );
    case 'sourceUnavailable':
      return <StateView kind="sourceUnavailable" />;
    case 'error':
      return (
        <StateView
          kind="error"
          message={outcome.message}
          onRetry={() => load({ paperId, version })}
        />
      );
    case 'page':
      return (
        <div ref={containerRef}>
          <DocModelBody docModel={outcome.docModel} assetsById={assetsById} anchor={anchor} />
        </div>
      );
  }
}

// Presentational doc-model render (TOC + nested section/block tree). Reused by the full-text
// viewer and the structured translation view (BR-S18): both render the SAME structure — only
// the text differs (original vs Korean). External text is escaped by React (BR-SF-9).
export function DocModelBody({
  docModel,
  assetsById,
  anchor,
}: {
  docModel: DocModel;
  assetsById: Map<string, AssetRef>;
  anchor?: AnchorVM | null;
}) {
  // Tap-to-enlarge: figures/tables/formulas are shown fit-to-width inline and open a
  // full-screen, scaled-to-fit overlay on tap (no scrollbars).
  const [zoom, setZoom] = useState<React.ReactNode | null>(null);
  return (
    <div className={styles.root} data-testid="docmodel-viewer">
      <DocTOC sections={docModel.sections} />
      <article className={styles.body}>
        {docModel.sections.map((s) => (
          <SectionView
            key={s.id}
            section={s}
            depth={1}
            assetsById={assetsById}
            anchor={anchor}
            onZoom={setZoom}
          />
        ))}
      </article>
      {zoom ? <BlockZoomOverlay onClose={() => setZoom(null)}>{zoom}</BlockZoomOverlay> : null}
    </div>
  );
}

// ---- table of contents (anchor jump) ------------------------------------

function DocTOC({ sections }: { sections: DocSection[] }) {
  // Only titled sections are navigable; a TOC is useful with at least two of them. So an
  // abstract translation (one untitled section) or a single-section doc shows no TOC.
  const entries = useMemo(
    () => flattenToc(sections).filter((e) => e.title.trim().length > 0),
    [sections],
  );
  if (entries.length < 2) return null;
  return (
    <nav className={styles.toc} aria-label="목차" data-testid="docmodel-toc">
      <p className={styles.tocTitle}>목차</p>
      <ul>
        {entries.map((e) => (
          <li key={e.id} style={{ paddingInlineStart: `${(e.depth - 1) * 12}px` }}>
            <a
              href={`#dm-${e.id}`}
              onClick={(ev) => {
                ev.preventDefault();
                document
                  .getElementById(`dm-${e.id}`)
                  ?.scrollIntoView({ block: 'start', behavior: 'smooth' });
              }}
            >
              {e.title}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

// ---- tap-to-enlarge (figures / tables / formulas) -----------------------

// Wraps a block so a tap/click/Enter opens the zoom overlay. `role=button` (not <button>)
// so block content like <table> stays valid inside it.
function ZoomTrigger({
  children,
  onZoom,
  className,
}: {
  children: React.ReactNode;
  onZoom: () => void;
  className?: string;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      className={className ? `${styles.zoomTrigger} ${className}` : styles.zoomTrigger}
      onClick={onZoom}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onZoom();
        }
      }}
      title="탭하면 크게 볼 수 있어요"
      aria-label="크게 보기"
    >
      {children}
    </div>
  );
}

// Full-screen overlay that scales the content to FIT the available area (enlarging small
// content, shrinking large) so the whole thing is visible with no scrollbars. Transform is
// visual only, so the measured natural size is stable. Tap the backdrop / ✕ / Esc to close.
function BlockZoomOverlay({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
}) {
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);

  useLayoutEffect(() => {
    const content = contentRef.current;
    const overlay = overlayRef.current;
    if (!content || !overlay) return;
    const measure = () => {
      // Available area = the overlay's OWN box, not the window. The overlay is
      // `position: fixed; inset: 0`, but on desktop the phone mockup frame (`contain: layout`)
      // is the containing block, so the overlay is confined to that frame — not the desktop
      // window. Measuring against `window.innerWidth/Height` would over-scale the content and
      // clip it inside the frame; the overlay's own size is correct in both cases (it spans
      // the full viewport full-bleed on phones).
      const availW = overlay.clientWidth * 0.94;
      const availH = overlay.clientHeight * 0.84;
      const w = content.scrollWidth || 1;
      const h = content.scrollHeight || 1;
      setScale(Math.min(availW / w, availH / h));
    };
    measure();
    // The content's natural size settles after the first paint — a KaTeX formula reflows once
    // its web fonts load (until then glyphs use narrow fallback metrics and measure too
    // small), and a figure resizes when its <img> loads — and the overlay box itself can
    // change (orientation / frame resize). A ResizeObserver on both re-measures on any such
    // change. The scale is applied as a transform (visual only), so it never changes either
    // measured box and can't drive an observer loop.
    const ro = new ResizeObserver(measure);
    ro.observe(content);
    ro.observe(overlay);
    return () => ro.disconnect();
  }, [children]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      ref={overlayRef}
      className={styles.zoomOverlay}
      role="dialog"
      aria-modal="true"
      aria-label="크게 보기"
      onClick={onClose}
      data-testid="block-zoom"
    >
      <button type="button" className={styles.zoomClose} onClick={onClose} aria-label="닫기">
        ✕
      </button>
      <div
        ref={contentRef}
        className={styles.zoomContent}
        style={{ transform: `scale(${scale})` }}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

// ---- section + block rendering ------------------------------------------

function SectionView({
  section,
  depth,
  assetsById,
  anchor,
  onZoom,
}: {
  section: DocSection;
  depth: number;
  assetsById: Map<string, AssetRef>;
  anchor?: AnchorVM | null;
  onZoom: (node: React.ReactNode) => void;
}) {
  const Heading = `h${Math.min(depth + 1, 6)}` as keyof React.JSX.IntrinsicElements;
  return (
    <section id={`dm-${section.id}`} className={styles.section}>
      {section.title ? <Heading className={styles.heading}>{section.title}</Heading> : null}
      {section.blocks.map((b) => (
        <BlockView
          key={b.id}
          block={b}
          assetsById={assetsById}
          active={isActive(b, anchor)}
          onZoom={onZoom}
        />
      ))}
      {(section.sections ?? []).map((s) => (
        <SectionView
          key={s.id}
          section={s}
          depth={depth + 1}
          assetsById={assetsById}
          anchor={anchor}
          onZoom={onZoom}
        />
      ))}
    </section>
  );
}

function BlockView({
  block,
  assetsById,
  active,
  onZoom,
}: {
  block: DocBlock;
  assetsById: Map<string, AssetRef>;
  active: boolean;
  onZoom: (node: React.ReactNode) => void;
}) {
  const cls = active ? `${styles.block} ${styles.active}` : styles.block;
  switch (block.type) {
    case 'paragraph':
      return (
        <p className={cls} data-block={block.id}>
          {renderInlineMath(block.text)}
        </p>
      );
    case 'formula': {
      const math = <MathDisplay latex={block.latex} />;
      return (
        <div className={`${cls} ${styles.formula}`} data-block={block.id}>
          <ZoomTrigger className={styles.formulaInner} onZoom={() => onZoom(math)}>
            {math}
          </ZoomTrigger>
          {block.anchorLabel ? <span className={styles.eqno}>{block.anchorLabel}</span> : null}
        </div>
      );
    }
    case 'table': {
      const table = (
        <table className={styles.table}>
          <tbody>
            {block.rows.map((row, ri) => (
              <tr key={ri}>
                {row.cells.map((cell, ci) =>
                  cell.isHeader ? (
                    <th key={ci} colSpan={cell.colspan} rowSpan={cell.rowspan}>
                      {renderInlineMath(cell.text)}
                    </th>
                  ) : (
                    <td key={ci} colSpan={cell.colspan} rowSpan={cell.rowspan}>
                      {renderInlineMath(cell.text)}
                    </td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      );
      return (
        <figure className={cls} data-block={block.id}>
          <ZoomTrigger className={styles.tableWrap} onZoom={() => onZoom(table)}>
            {table}
          </ZoomTrigger>
          {caption(block.anchorLabel, block.caption)}
        </figure>
      );
    }
    case 'figure': {
      const asset = assetsById.get(block.assetRef.assetId);
      const alt = block.caption ?? block.anchorLabel ?? '그림';
      return (
        <figure className={`${cls} ${styles.figure}`} data-block={block.id}>
          {asset?.url ? (
            <ZoomTrigger
              onZoom={() =>
                // eslint-disable-next-line @next/next/no-img-element -- signed S3 url
                onZoom(<img src={asset.url} alt={alt} className={styles.zoomImg} />)
              }
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- signed S3 url, not a static asset */}
              <img src={asset.url} alt={alt} loading="lazy" />
            </ZoomTrigger>
          ) : null}
          {caption(block.anchorLabel, block.caption)}
        </figure>
      );
    }
    case 'list':
      return block.ordered ? (
        <ol className={cls} data-block={block.id}>
          {block.items.map((it, i) => (
            <li key={i}>{renderInlineMath(it.text)}</li>
          ))}
        </ol>
      ) : (
        <ul className={cls} data-block={block.id}>
          {block.items.map((it, i) => (
            <li key={i}>{renderInlineMath(it.text)}</li>
          ))}
        </ul>
      );
    case 'code':
      return (
        <pre className={`${cls} ${styles.code}`} data-block={block.id}>
          <code>{block.text}</code>
        </pre>
      );
  }
}

function caption(label?: string, text?: string) {
  if (!label && !text) return null;
  return (
    <figcaption className={styles.caption}>
      {label ? <strong>{label}</strong> : null}
      {label && text ? ' ' : null}
      {text ? renderInlineMath(text) : null}
    </figcaption>
  );
}

// ---- helpers ------------------------------------------------------------

interface TocEntry {
  id: string;
  title: string;
  depth: number;
}

function flattenToc(sections: DocSection[], depth = 1, out: TocEntry[] = []): TocEntry[] {
  for (const s of sections) {
    out.push({ id: s.id, title: s.title, depth });
    if (s.sections?.length) flattenToc(s.sections, depth + 1, out);
  }
  return out;
}

function isActive(block: DocBlock, anchor?: AnchorVM | null): boolean {
  if (!anchor) return false;
  const label = 'anchorLabel' in block ? block.anchorLabel : undefined;
  return Boolean(label && anchor.label && label === anchor.label);
}

function findBlockIdByLabel(doc: DocModel, label: string): string | null {
  if (!label) return null;
  const walk = (sections: DocSection[]): string | null => {
    for (const s of sections) {
      for (const b of s.blocks) {
        const l = 'anchorLabel' in b ? b.anchorLabel : undefined;
        if (l && l === label) return b.id;
      }
      const nested = s.sections ? walk(s.sections) : null;
      if (nested) return nested;
    }
    return null;
  };
  return walk(doc.sections);
}
