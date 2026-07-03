import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// A controllable ApiClient stub (instead of the real MockTransport) so the removal-failure
// path (E4) can be scripted deterministically alongside the happy path. recordBehaviorEvent is
// stubbed too — the component's onToggle calls recordLibraryAdded/Removed (personalization),
// which reaches getApiClient().recordBehaviorEvent(); without a stub that throws synchronously
// and gets swallowed into the component's own catch, masking add/remove as a failure.
const addToLibrary = vi.fn();
const removeFromLibrary = vi.fn();
const recordBehaviorEvent = vi.fn().mockResolvedValue({ recorded: true, duplicate: false });
vi.mock('@/lib/api', () => ({
  getApiClient: () => ({ addToLibrary, removeFromLibrary, recordBehaviorEvent }),
}));

import { SaveToLibraryButton } from '@/components/SaveToLibraryButton';

const card = {
  arxivId: '2401.99999',
  title: 'Toggle test paper',
  authors: ['A. Author'],
  year: 2024,
};

describe('SaveToLibraryButton', () => {
  beforeEach(() => {
    addToLibrary.mockReset();
    removeFromLibrary.mockReset();
    recordBehaviorEvent.mockReset().mockResolvedValue({ recorded: true, duplicate: false });
  });

  it('saves on first press and un-saves on a second press', async () => {
    addToLibrary.mockResolvedValue({ id: 'lib1' });
    removeFromLibrary.mockResolvedValue(undefined);
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

  it('shows a visible, retryable failure when un-saving fails instead of silently reverting (E4, BR-U5-10)', async () => {
    addToLibrary.mockResolvedValue({ id: 'lib1' });
    removeFromLibrary.mockRejectedValueOnce(new Error('network'));
    removeFromLibrary.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();
    render(<SaveToLibraryButton card={card} />);
    const btn = screen.getByTestId('save-to-library');

    await user.click(btn); // save
    await waitFor(() => expect(btn).toHaveAttribute('aria-pressed', 'true'));

    await user.click(btn); // remove attempt #1 → fails
    await waitFor(() => expect(btn).toHaveAttribute('aria-label', '빼기 실패 — 다시 시도'));
    // Still shown/kept as saved (and pressable) — the old code silently reverted to 'saved'
    // with no distinguishable label, giving the user no feedback that the removal failed.
    expect(btn).toHaveAttribute('aria-pressed', 'true');
    expect(btn).not.toBeDisabled();

    await user.click(btn); // remove attempt #2 (retry) → succeeds
    await waitFor(() => expect(btn).toHaveAttribute('aria-label', '라이브러리에 담기'));
    expect(btn).toHaveAttribute('aria-pressed', 'false');
    expect(removeFromLibrary).toHaveBeenCalledTimes(2);
  });
});
