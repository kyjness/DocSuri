import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// useAssets builds a user-facing message when the figure/table manifest fails, but the viewer read
// only the success outcome — so the message was constructed and dropped, and a failed manifest was
// indistinguishable from a paper with no figures. Forcing the error state is the only way to cover
// that path, and vi.mock hoists per FILE, so this lives apart from the main viewer suite (whose
// tests need the real hook to join figures to their signed urls).
const load = vi.fn();
vi.mock('@/lib/useAssets', () => ({
  useAssets: () => ({
    state: { status: 'done', outcome: { kind: 'error', message: '그림·도표를 불러올 수 없어요.' } },
    load,
  }),
}));

import { DocModelViewer } from '@/components/DocModelViewer';

describe('DocModelViewer — assets failure', () => {
  it('surfaces the assets error with a retry, and still renders the body', async () => {
    render(<DocModelViewer paperId="2401.00001" version={1} anchor={null} />);

    const notice = await screen.findByTestId('docmodel-assets-error');
    expect(notice.textContent).toContain('그림·도표를 불러올 수 없어요.');

    // The paper still reads without its figures, so this must not replace the body.
    expect(screen.getByRole('heading', { name: 'Model Architecture' })).toBeTruthy();

    load.mockClear();
    screen.getByRole('button', { name: '다시 시도' }).click();
    await waitFor(() => expect(load).toHaveBeenCalledWith('2401.00001', 1));
  });
});
