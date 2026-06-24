import { describe, it, expect } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SaveToLibraryButton } from '@/components/SaveToLibraryButton';

// Mock transport (NEXT_PUBLIC_DOCSURI_REAL_API unset in tests). A unique arXiv id avoids
// colliding with the seeded library fixtures.
const card = {
  arxivId: '2401.99999',
  title: 'Toggle test paper',
  authors: ['A. Author'],
  year: 2024,
};

describe('SaveToLibraryButton', () => {
  it('saves on first press and un-saves on a second press', async () => {
    const user = userEvent.setup();
    render(<SaveToLibraryButton card={card} />);
    const btn = screen.getByTestId('save-to-library');
    expect(btn).toHaveAttribute('aria-pressed', 'false');

    // First press → saved (icon fills, label flips to the un-save action).
    await user.click(btn);
    await waitFor(() => expect(btn).toHaveAttribute('aria-pressed', 'true'));
    expect(btn).toHaveAttribute('aria-label', '라이브러리에서 빼기');
    // A saved paper stays pressable so it can be un-saved (the previous bug disabled it).
    expect(btn).not.toBeDisabled();

    // Second press → removed (back to the unsaved state). Wait for the label to settle
    // past the transient '빼는 중' so we observe the final idle state.
    await user.click(btn);
    await waitFor(() => expect(btn).toHaveAttribute('aria-label', '라이브러리에 담기'));
    expect(btn).toHaveAttribute('aria-pressed', 'false');
  });
});
