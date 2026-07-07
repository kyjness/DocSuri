'use client';

// DocModelViewer (자체 리치뷰, D4/Q5=C, BR-SF-11) — renders the structured doc-model:
// nested sections + TOC, MathJax formulas, structured tables (DATA, not crops — D8), and
// webp figures joined to the /assets signed urls by assetId (SEC-9 — the doc-model is
// url-free). OA-license-gated: license_unavailable → arXiv link-out. External text is
// escaped by React (BR-SF-9). Replaces the legacy plain-text full-text viewer.
//
// NOTE: anchor highlight matches the summary anchor's label ("Table 1"/"Figure 2") to a
// block's anchorLabel (the AnchorVM still carries a label, not a doc-model id — the
// id-based anchor contract is a follow-up). Span-precise inline highlight is a follow-up.
// (KaTeX stylesheet is pulled in by the renderMath import below.)
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type {
  AnchorVM,
  AssetRef,
  DocBlock,
  DocModel,
  DocSection,
  DocTableBlock,
} from '@/types/generated';
import { useDocModel } from '@/lib/useDocModel';
import { useAssets } from '@/lib/useAssets';
import { createPortal } from 'react-dom';
import { MathDisplay, renderInlineMath, type MathMacros } from '@/lib/renderMath';
import { StateView } from './StateView';
import { ScrollToTopButton } from './ScrollToTopButton';
import { recordReadCompleted } from '@/lib/personalization';
import styles from './DocModelViewer.module.css';

interface DocModelViewerProps {
  paperId: string;
  version: number;
  /** Summary source anchor to scroll to / highlight, if any (matched by label). */
  anchor?: AnchorVM | null;
  arxivUrl?: string;
  /** Skip the paper-title <h1> — used when embedded inline under a page that already shows
   *  the title (the desktop detail view), to avoid a duplicate heading. */
  hideTitle?: boolean;
}

export function DocModelViewer({
  paperId,
  version,
  anchor,
  arxivUrl,
  hideTitle,
}: DocModelViewerProps) {
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
    if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    // Move focus (and SR reading position) to the jumped-to block, not just the scroll
    // position (D3, BR-U5-15) — every block root carries tabIndex={-1} for this.
    el.focus({ preventScroll: true });
  }, [docModel, anchor]);

  // 완독 (read-completion, #346): when the end-of-body sentinel scrolls into view the reader has
  // reached the bottom → record a completion, once per (paper, version). IntersectionObserver's
  // default viewport root correctly accounts for the phone-frame scroll container's clipping. The
  // sentinel only exists once the page body renders, so this is a no-op until docModel is present.
  const completionRef = useRef<HTMLDivElement | null>(null);
  const readFiredRef = useRef<string | null>(null);
  useEffect(() => {
    const sentinel = completionRef.current;
    // IntersectionObserver is absent in SSR and the jsdom test env; skip completion tracking there.
    if (!docModel || !sentinel || typeof IntersectionObserver === 'undefined') return;
    const key = `${paperId}:${version}`;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting) && readFiredRef.current !== key) {
        readFiredRef.current = key;
        recordReadCompleted(paperId, version);
        observer.disconnect();
      }
    });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [docModel, paperId, version]);

  if (state.status === 'idle' || state.status === 'loading') {
    return <StateView kind="loading" title="전문 불러오는 중…" message="전문을 가져오고 있어요." />;
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
          title="전문 준비 중…"
          message="처음 여는 논문이라 전문을 만들고 있어요. 잠시만 기다려 주세요."
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
          {!hideTitle && outcome.docModel.meta.title ? (
            <h1 className={styles.paperTitle} data-testid="docmodel-title">
              {renderInlineMath(outcome.docModel.meta.title, outcome.docModel.meta.macros)}
            </h1>
          ) : null}
          <DocModelBody docModel={outcome.docModel} assetsById={assetsById} anchor={anchor} />
          {/* 완독 sentinel (#346): reaching it = read to the end. Empty/hidden — layout-neutral. */}
          <div ref={completionRef} aria-hidden="true" data-testid="docmodel-end-sentinel" />
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
  // scaled-to-fit overlay centred in the viewport (no scrollbars).
  const [zoom, setZoom] = useState<React.ReactNode | null>(null);
  // Author macros from the e-print preamble (meta.macros) — handed to every KaTeX render so
  // custom commands resolve instead of showing as red unsupported-command errors.
  const macros = docModel.meta.macros;
  // The abstract is its own surface (초록 / 초록 번역), so it is hidden from the full-text body and
  // TOC to avoid duplication. U1 emits the abstract as a dedicated section with id "s0" (real
  // content sections start at "s1"), so dropping "s0" removes only the abstract.
  const sections = docModel.sections.filter((s) => s.id !== 's0');
  return (
    <div className={styles.root} data-testid="docmodel-viewer">
      <DocTOC sections={sections} macros={macros} />
      <article className={styles.body}>
        {sections.map((s) => (
          <SectionView
            key={s.id}
            section={s}
            depth={1}
            assetsById={assetsById}
            anchor={anchor}
            onZoom={setZoom}
            macros={macros}
          />
        ))}
      </article>
      <ScrollToTopButton />
      {zoom ? <BlockZoomOverlay onClose={() => setZoom(null)}>{zoom}</BlockZoomOverlay> : null}
    </div>
  );
}

// ---- table of contents (anchor jump) ------------------------------------

function DocTOC({ sections, macros }: { sections: DocSection[]; macros?: MathMacros }) {
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
              data-testid="docmodel-toc-link"
              onClick={(ev) => {
                ev.preventDefault();
                const target = document.getElementById(`dm-${e.id}`);
                target?.scrollIntoView({ block: 'start', behavior: 'smooth' });
                // Move focus (and SR reading position) to the jumped-to section, not just the
                // scroll position (D3, BR-U5-15) — the section carries tabIndex={-1} for this.
                target?.focus({ preventScroll: true });
              }}
            >
              {renderInlineMath(e.title, macros)}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

// ---- tap-to-enlarge (figures / tables / formulas) -----------------------

// Tap-to-enlarge (D1, BR-U5-21). Tapping anywhere on the figure/table/formula zooms it — no visible
// button chrome. The pointer affordance lives on the WRAPPER's onClick (a scroll drag on a wide
// formula/table produces no click, so horizontal scrolling still works — the overlay button was
// eating those drags), while a real transparent, keyboard-focusable <button> is kept purely for
// keyboard/screen-reader access. The button is `pointer-events: none` (see CSS) so it never blocks
// touch scroll; it sits as a SIBLING (not a wrapper) so the block's own markup (table cells, figure
// alt, formula) stays directly in the accessibility tree (never swallowed — the D1 regression).
function Zoomable({ onZoom, children }: { onZoom: () => void; children: React.ReactNode }) {
  return (
    <div className={styles.zoomable} onClick={onZoom}>
      {children}
      <ZoomButton onZoom={onZoom} />
    </div>
  );
}

function ZoomButton({ onZoom }: { onZoom: () => void }) {
  return (
    <button
      type="button"
      className={styles.zoomTapTarget}
      // Keyboard activation only (pointer taps are handled by the wrapper); stop the resulting click
      // from bubbling to the wrapper's onClick so a keypress doesn't zoom twice.
      onClick={(e) => {
        e.stopPropagation();
        onZoom();
      }}
      title="탭하면 크게 볼 수 있어요"
      aria-label="크게 보기"
      data-testid="docmodel-zoom-trigger"
    />
  );
}

// Overlay that enlarges the tapped block, centred in the VIEWPORT, scaled to fit (enlarging
// small content up to a cap, shrinking large). It is portalled to document.body so its
// `position: fixed` resolves against the real viewport — NOT the phone-mockup frame, whose
// `contain: layout` would otherwise become the containing block and pin the overlay to the
// frame's box (which made a block tapped low on a desktop page pop up at the top). Transform is
// visual only, so the measured natural size is stable. Tap the backdrop / ✕ / Esc to close.
const _ZOOM_MAX_SCALE = 3;

function BlockZoomOverlay({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
}) {
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  // The element that had focus before the overlay opened (e.g. the ZoomButton that
  // triggered it) — restored on close (D2, BR-U5-20).
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const [scale, setScale] = useState(1);

  useLayoutEffect(() => {
    const content = contentRef.current;
    const overlay = overlayRef.current;
    if (!content || !overlay) return;
    const measure = () => {
      // Available area = the overlay's own box (the viewport, since it is portalled to body).
      const availW = overlay.clientWidth * 0.94;
      const availH = overlay.clientHeight * 0.9;
      const w = content.scrollWidth || 1;
      const h = content.scrollHeight || 1;
      setScale(Math.min(availW / w, availH / h, _ZOOM_MAX_SCALE));
    };
    measure();
    // The content's natural size settles after the first paint — a formula reflows when the
    // lazy MathJax engine loads and replaces its placeholder, a figure resizes when its <img>
    // loads — and the viewport can
    // change (orientation / resize). A ResizeObserver on both re-measures on any such change.
    // The scale is a transform (visual only), so it never changes either measured box.
    const ro = new ResizeObserver(measure);
    ro.observe(content);
    ro.observe(overlay);
    return () => ro.disconnect();
  }, [children]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
        return;
      }
      // Trap Tab within the dialog while it's open (D2, BR-U5-20) — otherwise focus can
      // escape to the (visually hidden, behind the backdrop) page content behind it.
      if (e.key === 'Tab') {
        const overlay = overlayRef.current;
        if (!overlay) return;
        const focusables = overlay.querySelectorAll<HTMLElement>(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
        );
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Focus management (D2, BR-U5-20): move focus into the dialog (its close button) on open,
  // and restore focus to whatever triggered it (the ZoomButton) when the overlay unmounts.
  useEffect(() => {
    previouslyFocusedRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();
    return () => {
      previouslyFocusedRef.current?.focus();
    };
  }, []);

  // Portalled to body: the backdrop covers the whole viewport and the content centres on the
  // user's screen wherever they have scrolled to.
  if (typeof document === 'undefined') return null;
  return createPortal(
    <div
      ref={overlayRef}
      className={styles.zoomOverlay}
      role="dialog"
      aria-modal="true"
      aria-label="크게 보기"
      onClick={onClose}
      data-testid="block-zoom"
    >
      <button
        ref={closeButtonRef}
        type="button"
        className={styles.zoomClose}
        onClick={onClose}
        aria-label="닫기"
        data-testid="block-zoom-close"
      >
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
    </div>,
    document.body,
  );
}

// ---- section + block rendering ------------------------------------------

function SectionView({
  section,
  depth,
  assetsById,
  anchor,
  onZoom,
  macros,
}: {
  section: DocSection;
  depth: number;
  assetsById: Map<string, AssetRef>;
  anchor?: AnchorVM | null;
  onZoom: (node: React.ReactNode) => void;
  macros?: MathMacros;
}) {
  const Heading = `h${Math.min(depth + 1, 6)}` as keyof React.JSX.IntrinsicElements;
  return (
    // tabIndex=-1 (D3, BR-U5-15): programmatically focusable so a TOC jump moves keyboard/SR
    // focus here too, not just the viewport scroll position.
    <section id={`dm-${section.id}`} className={styles.section} tabIndex={-1}>
      {section.title ? (
        <Heading className={styles.heading}>{renderInlineMath(section.title, macros)}</Heading>
      ) : null}
      {section.blocks.map((b) => (
        <BlockView
          key={b.id}
          block={b}
          assetsById={assetsById}
          active={isActive(b, anchor)}
          onZoom={onZoom}
          macros={macros}
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
          macros={macros}
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
  macros,
}: {
  block: DocBlock;
  assetsById: Map<string, AssetRef>;
  active: boolean;
  onZoom: (node: React.ReactNode) => void;
  macros?: MathMacros;
}) {
  const cls = active ? `${styles.block} ${styles.active}` : styles.block;
  switch (block.type) {
    case 'paragraph':
      return (
        <p className={cls} data-block={block.id} tabIndex={-1}>
          {renderInlineMath(block.text, macros)}
        </p>
      );
    case 'formula': {
      // LaTeX is the preferred render source; when absent (PDF/GROBID path) the equation
      // degrades to a page-crop image referenced by assetRef (display-only).
      const asset = block.assetRef ? assetsById.get(block.assetRef.assetId) : undefined;
      let inner: React.ReactNode = null;
      if (block.latex) {
        inner = <MathDisplay latex={block.latex} macros={macros} />;
      } else if (asset?.url) {
        const alt = block.anchorLabel ?? '수식';
        inner = (
          // eslint-disable-next-line @next/next/no-img-element -- signed S3 url, not a static asset
          <img src={asset.url} alt={alt} loading="lazy" />
        );
      }
      if (inner === null) {
        // Neither LaTeX nor a loadable crop image (crops are env-gated/best-effort, or the asset
        // is still building). Keep the numbered slot + anchor target instead of dropping the whole
        // block, so the equation number still lines up with in-text references and the anchor
        // still resolves — only the render source is missing, not the equation.
        return (
          <div className={`${cls} ${styles.formula}`} data-block={block.id} tabIndex={-1}>
            {/* role="img" so the label is honored on a bare <span> (generic role) — aria-label
                alone is unreliable there (D5, BR-U5-21, NFR-U5-U2). */}
            <span
              role="img"
              className={styles.formulaPlaceholder}
              aria-label="수식을 표시할 수 없습니다"
            >
              [수식]
            </span>
            {block.anchorLabel ? <span className={styles.eqno}>{block.anchorLabel}</span> : null}
          </div>
        );
      }
      return (
        <div className={`${cls} ${styles.formula}`} data-block={block.id} tabIndex={-1}>
          <Zoomable onZoom={() => onZoom(inner)}>
            <div className={styles.formulaInner}>{inner}</div>
          </Zoomable>
          {block.anchorLabel ? <span className={styles.eqno}>{block.anchorLabel}</span> : null}
        </div>
      );
    }
    case 'table':
      return (
        <TableBlockView
          block={block}
          assetsById={assetsById}
          cls={cls}
          onZoom={onZoom}
          macros={macros}
        />
      );
    case 'figure': {
      const asset = assetsById.get(block.assetRef.assetId);
      const alt = block.caption ?? block.anchorLabel ?? '그림';
      return (
        <figure className={`${cls} ${styles.figure}`} data-block={block.id} tabIndex={-1}>
          {asset?.url ? (
            <Zoomable
              onZoom={() =>
                // eslint-disable-next-line @next/next/no-img-element -- signed S3 url
                onZoom(<img src={asset.url} alt={alt} className={styles.zoomImg} />)
              }
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- signed S3 url, not a static asset */}
              <img src={asset.url} alt={alt} loading="lazy" />
            </Zoomable>
          ) : null}
          {caption(block.anchorLabel, block.caption, macros)}
        </figure>
      );
    }
    case 'list':
      return block.ordered ? (
        <ol className={cls} data-block={block.id} tabIndex={-1}>
          {block.items.map((it, i) => (
            <li key={i}>{renderInlineMath(it.text, macros)}</li>
          ))}
        </ol>
      ) : (
        <ul className={cls} data-block={block.id} tabIndex={-1}>
          {block.items.map((it, i) => (
            <li key={i}>{renderInlineMath(it.text, macros)}</li>
          ))}
        </ul>
      );
    case 'code':
      return (
        <pre className={`${cls} ${styles.code}`} data-block={block.id} tabIndex={-1}>
          <code>{block.text}</code>
        </pre>
      );
  }
}

// A table renders as STRUCTURED DATA (rows/cells) so its numbers stay visible to grounding and
// the summary LLM (D8). A page-crop image may be carried in `assetRef` as a last-resort fallback
// (e.g. low-confidence GROBID parse on a PDF source). When both exist the reader can toggle to the
// original image; when the structured rows are empty we auto-show the image so the table isn't blank.
function TableBlockView({
  block,
  assetsById,
  cls,
  onZoom,
  macros,
}: {
  block: DocTableBlock;
  assetsById: Map<string, AssetRef>;
  cls: string;
  onZoom: (node: React.ReactNode) => void;
  macros?: MathMacros;
}) {
  const asset = block.assetRef ? assetsById.get(block.assetRef.assetId) : undefined;
  const hasRows = block.rows.length > 0;
  // null = follow the default (structured unless the parse produced no rows); a tap sets it explicitly.
  const [override, setOverride] = useState<boolean | null>(null);
  const showImage = (override ?? !hasRows) && Boolean(asset?.url);
  const image =
    asset?.url != null ? (
      // eslint-disable-next-line @next/next/no-img-element -- signed S3 url, not a static asset
      <img src={asset.url} alt={block.anchorLabel ?? '표 원본 이미지'} loading="lazy" />
    ) : null;
  const table = (
    <table className={styles.table}>
      <tbody>
        {block.rows.map((row, ri) => (
          <tr key={ri}>
            {row.cells.map((cell, ci) =>
              cell.isHeader ? (
                <th key={ci} colSpan={cell.colspan} rowSpan={cell.rowspan}>
                  {renderInlineMath(cell.text, macros)}
                </th>
              ) : (
                <td key={ci} colSpan={cell.colspan} rowSpan={cell.rowspan}>
                  {renderInlineMath(cell.text, macros)}
                </td>
              ),
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
  const shown = showImage && image ? image : table;
  // Only offer the toggle when there is a real choice (both a structured table and an image).
  const canToggle = hasRows && Boolean(asset?.url);
  return (
    <figure className={cls} data-block={block.id} tabIndex={-1}>
      <Zoomable onZoom={() => onZoom(shown)}>
        <div className={styles.tableWrap}>{shown}</div>
      </Zoomable>
      {canToggle ? (
        <button
          type="button"
          className={styles.originalToggle}
          aria-pressed={showImage}
          onClick={() => setOverride(!showImage)}
          data-testid="docmodel-table-toggle"
        >
          {showImage ? '구조화 표 보기' : '원본 이미지 보기'}
        </button>
      ) : null}
      {caption(block.anchorLabel, block.caption, macros)}
    </figure>
  );
}

function caption(label?: string, text?: string, macros?: MathMacros) {
  if (!label && !text) return null;
  return (
    <figcaption className={styles.caption}>
      {label ? <strong>{label}</strong> : null}
      {label && text ? ' ' : null}
      {text ? renderInlineMath(text, macros) : null}
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
