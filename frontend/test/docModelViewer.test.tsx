import { describe, it, expect, beforeAll } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { DocModelViewer, DocModelBody } from '@/components/DocModelViewer';
import { preloadMathEngine } from '@/lib/renderMath';
import { docModelResponse } from '@/mocks/summarizeFixtures';

// Uses the mock transport (NEXT_PUBLIC_DOCSURI_REAL_API unset) → docModelResponse +
// assetsResponse (figure assetId 2401.00001:v1:figure:0 joins across both fixtures).

// Math is rendered lazily by MathJax — warm the engine so formulas emit their SVG (mjx-container)
// synchronously within each render.
beforeAll(async () => {
  await preloadMathEngine();
});

describe('DocModelViewer', () => {
  it('renders the section tree, TOC, structured table data, and a joined figure', async () => {
    render(<DocModelViewer paperId="2401.00001" version={1} anchor={null} />);

    // Section headings (nested tree).
    expect(await screen.findByRole('heading', { name: 'Model Architecture' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Why Self-Attention' })).toBeTruthy();

    // TOC has an anchor-jump entry per section.
    const toc = screen.getByTestId('docmodel-toc');
    expect(within(toc).getByText('Model Architecture')).toBeTruthy();

    // Table is rendered as DATA (numbers/cells visible, not a crop image — D8).
    const table = screen.getByRole('table');
    expect(table).toBeTruthy();
    expect(screen.getByText('Self-Attention')).toBeTruthy();
    expect(screen.getByText('Layer Type')).toBeTruthy();
    // D1 regression guard: the table must stay directly in the a11y tree — no ancestor
    // wraps it in role="button" (the old ZoomTrigger swallowed the whole block into one
    // opaque, unlabeled control and screen readers lost every cell).
    expect(table.closest('[role="button"]')).toBeNull();

    // Figure joins the /assets signed url by assetId. Scoped to actual <img> tags: the
    // formula-fallback placeholder also carries role="img" (D5), so a plain findByRole('img')
    // is ambiguous once that fix landed. The placeholder renders synchronously while the figure
    // <img> only appears after the async assets fetch resolves — so poll for the real <img>
    // rather than `findAllByRole` (which returns as soon as the placeholder shows → flaky).
    const img = await waitFor(() => {
      const el = screen.getAllByRole('img').find((e) => e.tagName === 'IMG');
      expect(el).toBeTruthy();
      return el!;
    });
    expect(img!.getAttribute('src')).toContain('data:image/svg');
    expect(img!.getAttribute('loading')).toBe('lazy');
    expect(img!.closest('[role="button"]')).toBeNull();

    // Display formula rendered by MathJax (emits mjx-container markup).
    expect(document.querySelector('mjx-container')).toBeTruthy();

    // Each table/figure/formula gets its OWN adjacent zoom button (D1, BR-U5-22) rather than
    // the content itself being the trigger.
    expect(screen.getAllByTestId('docmodel-zoom-trigger').length).toBeGreaterThan(0);
  });

  it('renders inline math in section titles and the TOC, not raw \\(…\\) source', () => {
    // Section titles (heading + TOC) carry inline math the same way body text does — the
    // ar5iv/arXiv title strings keep literal `\(…\)` / `$…$`, so the viewer must run them
    // through MathJax instead of printing the delimiters verbatim.
    const base = docModelResponse.docModel;
    const docModel = {
      ...base,
      sections: base.sections.map((s) =>
        s.id === 's3' ? { ...s, title: 'Bayesian Update \\(h(\\bm{\\theta})\\)' } : s,
      ),
    };
    render(<DocModelBody docModel={docModel} assetsById={new Map()} />);

    // TOC has no formula blocks, so any MathJax markup there comes from the title math — and the
    // raw delimiters must not leak into the visible text.
    const toc = screen.getByTestId('docmodel-toc');
    expect(toc.querySelector('mjx-container')).toBeTruthy();
    expect(toc.textContent).not.toContain('\\(');

    // The section heading itself renders the math too (no verbatim `\(`).
    const mathHeading = screen.getAllByRole('heading').find((h) => h.querySelector('mjx-container'));
    expect(mathHeading).toBeTruthy();
    expect(mathHeading!.textContent).not.toContain('\\(');
  });

  it('keeps a numbered formula as a placeholder when it has neither LaTeX nor a crop image', async () => {
    render(<DocModelViewer paperId="2401.00001" version={1} anchor={null} />);
    await screen.findByRole('heading', { name: 'Model Architecture' });

    // The image-fallback equation (2) has no LaTeX and no loadable asset — it degrades to a
    // placeholder, but the equation number survives so the anchor target + in-text reference
    // alignment are preserved (the whole block must NOT disappear).
    const placeholder = screen.getByLabelText('수식을 표시할 수 없습니다');
    expect(placeholder).toBeTruthy();
    expect(screen.getByText('(2)')).toBeTruthy();
  });

  it('reveals the "맨 위로" button once the reading surface scrolls past the threshold', async () => {
    render(<DocModelViewer paperId="2401.00001" version={1} anchor={null} />);
    await screen.findByRole('heading', { name: 'Model Architecture' });
    const toTop = document.querySelector('button[aria-label="맨 위로"]');
    expect(toTop).toBeTruthy();
    // Inert until the reader scrolls down.
    expect(toTop).toHaveAttribute('aria-hidden', 'true');
    expect(toTop).toHaveAttribute('tabindex', '-1');

    // A scroll on any container (captured at document) past the threshold reveals it. This is
    // detection-agnostic — it works whichever element actually scrolls (.page / frame / window).
    const scroller = screen.getByTestId('docmodel-viewer');
    Object.defineProperty(scroller, 'scrollTop', { value: 400, configurable: true });
    // Re-fire inside waitFor: the reveal listener is attached in a useEffect, so a single
    // synchronous scroll can race the effect (the dispatch is missed → button stays inert).
    // Polling re-dispatches until the listener is live and flips aria-hidden.
    await waitFor(() => {
      fireEvent.scroll(scroller);
      expect(toTop).toHaveAttribute('aria-hidden', 'false');
    });
    expect(toTop).toHaveAttribute('tabindex', '0');
  });

  it('opens the block-zoom overlay over a tapped block and manages focus (D2)', async () => {
    render(<DocModelViewer paperId="2401.00001" version={1} anchor={null} />);
    await screen.findByRole('heading', { name: 'Model Architecture' });
    expect(screen.queryByTestId('block-zoom')).toBeNull();
    // Each figure/table/formula has an adjacent "크게 보기" zoom button (D1).
    const triggers = screen.getAllByRole('button', { name: '크게 보기' });
    triggers[0].focus();
    fireEvent.click(triggers[0]);
    expect(screen.getByTestId('block-zoom')).toBeTruthy();

    // Opening the dialog moves focus to its close button (D2, BR-U5-20).
    const closeButton = screen.getByTestId('block-zoom-close');
    expect(document.activeElement).toBe(closeButton);

    // Closing it restores focus to the trigger that opened it.
    fireEvent.click(closeButton);
    expect(screen.queryByTestId('block-zoom')).toBeNull();
    expect(document.activeElement).toBe(triggers[0]);
  });

  it('jumps to the section and highlights its heading for a section-type summary anchor', async () => {
    // Section anchors are the common case: the grounding gate rewrites the label to the section
    // title ("Model Architecture"). No block carries that as an anchorLabel, so the viewer must
    // fall back to the section element (dm-{id}) — the regression that made source chips no-op.
    const anchor = {
      field: 'method',
      target: 'section' as const,
      span: 'scaled dot-product attention',
      label: 'Model Architecture',
    };
    render(<DocModelViewer paperId="2401.00001" version={1} anchor={anchor} />);
    const heading = await screen.findByRole('heading', { name: 'Model Architecture' });

    // Focus (and the scroll target) moves to the matched <section id="dm-s3">.
    const section = document.getElementById('dm-s3');
    expect(section).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(section));

    // The heading of that section carries the anchor highlight.
    expect(heading.className).toContain('active');
  });

  it('jumps to and highlights the matching asset block for an asset-type summary anchor', async () => {
    // Regression guard: table/figure/formula anchors still resolve by block anchorLabel.
    const anchor = {
      field: 'results',
      target: 'table' as const,
      span: 'per-layer complexity',
      label: 'Table 1',
    };
    render(<DocModelViewer paperId="2401.00001" version={1} anchor={anchor} />);
    await screen.findByRole('heading', { name: 'Why Self-Attention' });

    const block = document.querySelector('[data-block="s3.2.tbl1"]');
    expect(block).toBeTruthy();
    await waitFor(() => expect(document.activeElement).toBe(block));
    expect((block as HTMLElement).className).toContain('active');
  });

  it('moves focus to the target section when a TOC link is activated (D3)', async () => {
    render(<DocModelViewer paperId="2401.00001" version={1} anchor={null} />);
    await screen.findByRole('heading', { name: 'Model Architecture' });
    const tocLink = screen.getAllByTestId('docmodel-toc-link')[0];
    fireEvent.click(tocLink);
    const href = tocLink.getAttribute('href') ?? '';
    const target = document.getElementById(href.slice(1));
    expect(target).toBeTruthy();
    expect(document.activeElement).toBe(target);
  });
});
