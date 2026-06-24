import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PaperDetailIsland } from '@/components/PaperDetailIsland';

// PaperDetailIsland uses useRouter (anchor → in-app navigation to the 본문 route).
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

// 본문 / 본문 번역 navigate IN-APP to full-screen routes (same tab, each with its own ← back),
// not a browser tab and not inline — so the detail page shows in-app links (no target=_blank)
// and no longer mounts the figure/table gallery or an inline viewer.
describe('PaperDetailIsland — body opens as an in-app route', () => {
  it('renders in-app 본문 / 본문 번역 links (same tab), not an inline viewer/gallery', () => {
    render(<PaperDetailIsland paperId="2401.00001" version={1} />);

    const bodyLink = screen.getByTestId('open-doc-model');
    expect(bodyLink.getAttribute('href')).toBe('/paper/2401.00001/doc-model?version=1');
    expect(bodyLink.getAttribute('target')).toBeNull(); // in-app navigation, not a new tab

    const transLink = screen.getByTestId('open-full-translation');
    expect(transLink.getAttribute('href')).toBe('/paper/2401.00001/translate?version=1');
    expect(transLink.getAttribute('target')).toBeNull();

    // No inline rich view and no standalone figure/table gallery on the detail page.
    expect(screen.queryByTestId('docmodel-viewer')).toBeNull();
    expect(screen.queryByTestId('asset-item')).toBeNull();
  });
});
