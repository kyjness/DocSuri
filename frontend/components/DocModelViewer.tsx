'use client';

// DocModelViewer (자체 리치뷰, D4/Q5=C, BR-SF-11) — renders the structured doc-model:
// nested sections + TOC, MathJax formulas, structured tables (DATA, not crops — D8), and
// webp figures joined to the /assets signed urls by assetId (SEC-9 — the doc-model is
// url-free). OA-license-gated: license_unavailable → arXiv link-out. External text is
// escaped by React (BR-SF-9). Replaces the legacy plain-text full-text viewer.
//
// NOTE: a summary anchor carries the doc-model id its grounding gate resolved to, so it scrolls
// straight to that block/section. An anchor with no id (a caption-only float, or a summary cached
// before ids shipped) still matches by label — asset anchors ("Table 1"/"Figure 2"/"(1)") to a
// block's anchorLabel, section anchors to the section title. Span-precise inline highlight is a
// follow-up. (The math stylesheet is pulled in by the renderMath import below.)
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type {
  AnchorTargetVM,
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
  anchor?: AnchorTargetVM | null;
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

  // The assets fetch produces a user-facing message when it fails, but only the 'assets' outcome
  // was ever read — so the message was built and thrown away, and a failed manifest looked
  // identical to a paper with no figures. The body still reads fine without them, so this is a
  // notice with a retry, not a blocking error state.
  const assetsError =
    assetState.status === 'done' && assetState.outcome.kind === 'error'
      ? assetState.outcome.message
      : null;

  const docModel =
    state.status === 'done' && state.outcome.kind === 'page' ? state.outcome.docModel : null;

  // Scroll to + highlight the target (asset block or section) matching the selected anchor.
  useEffect(() => {
    if (!docModel || !anchor || !containerRef.current) return;
    const id = resolveAnchorId(docModel, anchor);
    if (!id) return;
    const root = containerRef.current;
    // Block ids and section ids share no values and render to distinct attributes (data-block vs
    // the dm- element id), so trying the block selector first tells the two apart from the DOM —
    // no need to classify the id by how it is spelled.
    const blockEl = root.querySelector<HTMLElement>(`[data-block="${CSS.escape(id)}"]`);
    const el = blockEl ?? root.querySelector<HTMLElement>(`#dm-${CSS.escape(id)}`);
    if (!el) return;
    // Sections read best jumped to their top (like the TOC); asset blocks center in view.
    el.scrollIntoView({ block: blockEl ? 'center' : 'start', behavior: 'smooth' });
    // Move focus (and SR reading position) to the jumped-to element, not just the scroll
    // position (D3, BR-U5-15) — every block root and section carries tabIndex={-1} for this.
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
          {assetsError ? (
            <p className={styles.assetsNotice} role="status" data-testid="docmodel-assets-error">
              {assetsError}
              <button type="button" onClick={() => void loadAssets(paperId, version)}>
                다시 시도
              </button>
            </p>
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
  anchor?: AnchorTargetVM | null;
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
  // Resolve the anchor to ONE doc-model id up front, so scroll and highlight point at the same
  // node. resolveAnchorId prefers the server-supplied blockId (when it still exists here) and
  // otherwise falls back to label matching — the highlight then keys off that single id.
  const activeId = useMemo(
    () => (anchor ? resolveAnchorId(docModel, anchor) : null),
    [docModel, anchor],
  );
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
            activeId={activeId}
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
  activeId,
  onZoom,
  macros,
}: {
  section: DocSection;
  depth: number;
  assetsById: Map<string, AssetRef>;
  /** The single doc-model id the anchor resolved to (block or section), or null. */
  activeId?: string | null;
  onZoom: (node: React.ReactNode) => void;
  macros?: MathMacros;
}) {
  const Heading = `h${Math.min(depth + 1, 6)}` as keyof React.JSX.IntrinsicElements;
  // The heading — the thing a section anchor points at — carries the highlight when its id is the
  // resolved target. Two subsections sharing a title stay distinguishable (the id is unique).
  const headingCls =
    section.id === activeId ? `${styles.heading} ${styles.active}` : styles.heading;
  return (
    // tabIndex=-1 (D3, BR-U5-15): programmatically focusable so a TOC/anchor jump moves keyboard/SR
    // focus here too, not just the viewport scroll position.
    <section id={`dm-${section.id}`} className={styles.section} tabIndex={-1}>
      {section.title ? (
        <Heading className={headingCls}>{renderInlineMath(section.title, macros)}</Heading>
      ) : null}
      {section.blocks.map((b) => (
        <BlockView
          key={b.id}
          block={b}
          assetsById={assetsById}
          active={b.id === activeId}
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
          activeId={activeId}
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
          <AssetImage src={asset.url} alt={alt} label="수식" />
        );
      }
      if (inner === null) {
        // Neither LaTeX nor a loadable crop image (crops are env-gated/best-effort, or the asset
        // is still building). Keep the numbered slot + anchor target instead of dropping the whole
        // block, so the equation number still lines up with in-text references and the anchor
        // still resolves — only the render source is missing, not the equation.
        return (
          <div className={`${cls} ${styles.formula}`} data-block={block.id} tabIndex={-1}>
            <AssetPlaceholder label="수식" />
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
                onZoom(
                  <AssetImage src={asset.url} alt={alt} label="그림" className={styles.zoomImg} />,
                )
              }
            >
              <AssetImage src={asset.url} alt={alt} label="그림" />
            </Zoomable>
          ) : (
            // No asset yet — the manifest is still loading, the crop is env-gated/best-effort, or
            // the fetch failed. Hold the slot the way the formula block does: dropping to a bare
            // caption leaves the reader with a caption for a figure that is not there, and makes
            // the page jump when the parallel assets fetch lands.
            <AssetPlaceholder label="그림" />
          )}
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
    case 'code': {
      // On the PDF/GROBID path a listing's text is an approximation of a picture, so it also
      // carries a page crop. Show the crop — it renders faithfully — and keep the text underneath
      // for copying and for screen readers. Listings from HTML sources have no crop and are text.
      const asset = block.assetRef ? assetsById.get(block.assetRef.assetId) : undefined;
      if (asset?.url) {
        return (
          <figure className={`${cls} ${styles.figure}`} data-block={block.id} tabIndex={-1}>
            <Zoomable
              onZoom={() =>
                onZoom(
                  <AssetImage
                    src={asset.url}
                    alt={block.text}
                    label="코드 이미지"
                    className={styles.zoomImg}
                  />,
                )
              }
            >
              <AssetImage src={asset.url} alt={block.text} label="코드 이미지" />
            </Zoomable>
            <details className={styles.code}>
              <summary>텍스트로 보기</summary>
              <pre>
                <code>{block.text}</code>
              </pre>
            </details>
          </figure>
        );
      }
      return (
        <pre className={`${cls} ${styles.code}`} data-block={block.id} tabIndex={-1}>
          <code>{block.text}</code>
        </pre>
      );
    }
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
      <AssetImage
        src={asset.url}
        alt={block.anchorLabel ?? '표 원본 이미지'}
        label="표 이미지"
      />
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

// The single source of truth for the section-anchor match rule (label ⇔ section title). Used by
// resolveAnchorId when an anchor carries no usable id, so the scroll target and the heading
// highlight (both keyed off the resolved id) can never drift apart.
function sectionMatchesLabel(section: DocSection, label: string): boolean {
  return Boolean(section.title && label && section.title.trim() === label.trim());
}

// Does any block or section in the doc carry this id? Guards the server-supplied blockId: a summary
// served stale under an older parser generation can name an id the rebuilt doc no longer has.
function docHasId(sections: DocSection[], id: string): boolean {
  return sections.some(
    (s) =>
      s.id === id ||
      s.blocks.some((b) => b.id === id) ||
      (s.sections ? docHasId(s.sections, id) : false),
  );
}

// Korean object particle: 을 after a final consonant (받침), 를 after a vowel. The label varies
// ("수식"/"그림"/"코드 이미지"/"표 이미지"), so the particle must agree with its last syllable — a
// fixed 을 reads as ungrammatical Korean for the vowel-ending 이미지 labels.
function objectParticle(word: string): string {
  const last = word.charCodeAt(word.length - 1);
  const isHangulSyllable = last >= 0xac00 && last <= 0xd7a3;
  const hasFinalConsonant = isHangulSyllable && (last - 0xac00) % 28 !== 0;
  return hasFinalConsonant ? '을' : '를';
}

// The labelled fallback shared by every missing-asset slot — a failed <img>, or a figure/formula
// whose crop is still building or env-gated. role="img" so the label is honored on a bare <span>
// (generic role); aria-label alone is unreliable there (D5, BR-U5-21, NFR-U5-U2).
function AssetPlaceholder({ label }: { label: string }) {
  return (
    <span
      role="img"
      className={styles.formulaPlaceholder}
      aria-label={`${label}${objectParticle(label)} 표시할 수 없습니다`}
    >
      [{label}]
    </span>
  );
}

/** An asset image that degrades to a labelled placeholder instead of the browser's broken-image
 * glyph. Asset urls are short-lived signed urls, so a reader who leaves the paper open past
 * expiry — or hits a 403 — would otherwise be left with a broken icon and nothing explaining it. */
function AssetImage({
  src,
  alt,
  label,
  className,
}: {
  src: string;
  alt: string;
  label: string;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  // A refreshed signed url is a new chance to load; without this the block would stay broken
  // for the rest of the mount.
  useEffect(() => setFailed(false), [src]);
  if (failed) return <AssetPlaceholder label={label} />;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- signed S3 url, not a static asset
    <img src={src} alt={alt} className={className} loading="lazy" onError={() => setFailed(true)} />
  );
}

// Resolve a summary anchor to the id of the block or section it points at; the caller finds that
// id in the DOM and derives whether it is a block or a section from which element carries it. The
// backend's grounding gate already resolved the anchor against the doc-model and reports the id it
// landed on, so an id anchor wins — but ONLY if that id still exists here. A summary served stale
// under an older parser generation can name an id the rebuilt doc renumbered or dropped; rather
// than dead-ending, fall back to label matching so the chip still jumps somewhere sensible.
//
// An anchor also carries no id when the gate resolved it to a caption-only float (no block behind
// it), or when it comes from a summary cached before ids shipped — those match by label the way
// every anchor did before: asset anchors ("Table 1"/"Figure 2"/"(1)") against a block's
// anchorLabel, section anchors against the section title, block winning as the more specific.
function resolveAnchorId(doc: DocModel, anchor: AnchorTargetVM): string | null {
  const id = anchor.blockId?.trim();
  if (id && docHasId(doc.sections, id)) return id;

  const needle = (anchor.label ?? '').trim();
  if (!needle) return null;
  const walkBlocks = (sections: DocSection[]): string | null => {
    for (const s of sections) {
      for (const b of s.blocks) {
        const l = 'anchorLabel' in b ? b.anchorLabel : undefined;
        if (l && l.trim() === needle) return b.id;
      }
      const nested = s.sections ? walkBlocks(s.sections) : null;
      if (nested) return nested;
    }
    return null;
  };
  const blockId = walkBlocks(doc.sections);
  if (blockId) return blockId;
  const walkSections = (sections: DocSection[]): string | null => {
    for (const s of sections) {
      if (sectionMatchesLabel(s, needle)) return s.id;
      const nested = s.sections ? walkSections(s.sections) : null;
      if (nested) return nested;
    }
    return null;
  };
  return walkSections(doc.sections);
}
