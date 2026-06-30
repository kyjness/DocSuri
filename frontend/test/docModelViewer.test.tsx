import { describe, it, expect } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { DocModelViewer } from '@/components/DocModelViewer';

// Uses the mock transport (NEXT_PUBLIC_DOCSURI_REAL_API unset) → docModelResponse +
// assetsResponse (figure assetId 2401.00001:v1:figure:0 joins across both fixtures).

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
    expect(screen.getByRole('table')).toBeTruthy();
    expect(screen.getByText('Self-Attention')).toBeTruthy();
    expect(screen.getByText('Layer Type')).toBeTruthy();

    // Figure joins the /assets signed url by assetId.
    const img = await screen.findByRole('img');
    expect(img.getAttribute('src')).toContain('data:image/svg');
    expect(img.getAttribute('loading')).toBe('lazy');

    // Display formula rendered by KaTeX (emits .katex markup).
    expect(document.querySelector('.katex')).toBeTruthy();
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

  it('opens the block-zoom overlay over a tapped block', async () => {
    render(<DocModelViewer paperId="2401.00001" version={1} anchor={null} />);
    await screen.findByRole('heading', { name: 'Model Architecture' });
    expect(screen.queryByTestId('block-zoom')).toBeNull();
    // Each figure/table/formula is wrapped in a "크게 보기" zoom trigger.
    const triggers = screen.getAllByRole('button', { name: '크게 보기' });
    fireEvent.click(triggers[0]);
    expect(screen.getByTestId('block-zoom')).toBeTruthy();
  });
});
