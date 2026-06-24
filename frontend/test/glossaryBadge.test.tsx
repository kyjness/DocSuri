import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TranslationView } from '@/components/TranslationView';
import { resetMockGlossary } from '@/mocks/summarizeFixtures';
import type { TranslationVM } from '@/types/generated';

// 개인 용어집 Phase 1 — drives the real MockTransport (mock-first) end to end through
// TranslationView, which owns the open-editor state: tap a kept-term badge, type a
// rendering, save; only one editor opens at a time; an outside click dismisses it.

const translation: TranslationVM = {
  docModel: {
    meta: {
      paperId: '2401.1',
      version: 1,
      title: '',
      provenance: {
        sourceTier: 'ar5iv',
        parserVersion: 'test',
        schemaVersion: '1.0.0',
        generatedAt: '2026-06-23T00:00:00Z',
      },
    },
    sections: [
      {
        id: 's1',
        title: '',
        blocks: [{ id: 's1.p1', type: 'paragraph', text: '어텐션만으로 시퀀스를 변환한다.' }],
      },
    ],
  },
  keptTerms: ['attention', 'BLEU'],
};

function renderView() {
  return render(
    <div>
      <TranslationView translation={translation} showGlossary />
      <button type="button" data-testid="outside">바깥</button>
    </div>,
  );
}

describe('GlossaryTermBadge (via TranslationView)', () => {
  beforeEach(() => {
    resetMockGlossary();
  });

  it('opens an editor on tap and confirms after a successful save', async () => {
    const user = userEvent.setup();
    renderView();

    expect(screen.queryByTestId('glossary-input')).not.toBeInTheDocument();

    await user.click(screen.getAllByTestId('glossary-badge')[0]);
    const input = await screen.findByTestId('glossary-input');
    expect(screen.getByTestId('glossary-save')).toBeDisabled();

    await user.type(input, '주의집중');
    expect(screen.getByTestId('glossary-save')).toBeEnabled();

    await user.click(screen.getByTestId('glossary-save'));
    await waitFor(() => expect(screen.getByTestId('glossary-saved')).toBeInTheDocument());
  });

  it('keeps only one editor open at a time', async () => {
    const user = userEvent.setup();
    renderView();
    const [first, second] = screen.getAllByTestId('glossary-badge');

    await user.click(first);
    expect(await screen.findByTestId('glossary-input')).toBeInTheDocument();
    expect(screen.getAllByTestId('glossary-input')).toHaveLength(1);

    // Opening the second badge closes the first — still exactly one editor.
    await user.click(second);
    await waitFor(() => expect(screen.getAllByTestId('glossary-input')).toHaveLength(1));
  });

  it('closes the editor on an outside click', async () => {
    const user = userEvent.setup();
    renderView();

    await user.click(screen.getAllByTestId('glossary-badge')[0]);
    expect(await screen.findByTestId('glossary-input')).toBeInTheDocument();

    await user.click(screen.getByTestId('outside'));
    await waitFor(() => expect(screen.queryByTestId('glossary-input')).not.toBeInTheDocument());
  });

  it('pre-fills a previously saved rendering when reopened (Phase 2a round-trip)', async () => {
    const user = userEvent.setup();
    renderView();

    // Save a rendering for the first term…
    await user.click(screen.getAllByTestId('glossary-badge')[0]);
    await user.type(await screen.findByTestId('glossary-input'), '주의집중');
    await user.click(screen.getByTestId('glossary-save'));
    await waitFor(() => expect(screen.getByTestId('glossary-saved')).toBeInTheDocument());

    // …close, reopen: the input is pre-filled with the saved value (no blank restart).
    await user.click(screen.getByTestId('outside'));
    await user.click(screen.getAllByTestId('glossary-badge')[0]);
    const reopened = await screen.findByTestId('glossary-input');
    expect((reopened as HTMLInputElement).value).toBe('주의집중');
  });
});
