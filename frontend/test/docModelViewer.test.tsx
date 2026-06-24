import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
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
});
