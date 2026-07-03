import { useState } from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TranslationView } from '@/components/TranslationView';
import { ApiClient } from '@/lib/api';
import { resetMockGlossary } from '@/mocks/summarizeFixtures';
import type { TranslationVM } from '@/types/generated';

// 개인 용어집 (BR-S4) — drives the real MockTransport through TranslationView, which shows 원어 유지
// 용어 (kept → weak) then 표준 용어 (seed standard: keep-as-is + mapping chips → strong). Editing a
// chip only STAGES the rendering (per-paper draft, sessionStorage) — nothing hits the server until the
// group's own "반영" button is pressed, and the two groups apply independently.

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
    fullText: '어텐션만으로 시퀀스를 변환한다.',
    sections: [
      {
        id: 's1',
        title: '',
        blocks: [{ id: 's1.p1', type: 'paragraph', text: '어텐션만으로 시퀀스를 변환한다.' }],
      },
    ],
  },
  keptTerms: ['Transformer', 'encoder', 'BLEU'],
  standardGlossary: [
    { term: 'Transformer' }, // keep-as-is standard → strong badge
    { term: 'BLEU' }, // keep-as-is standard → strong badge
    { term: 'attention', translated: '어텐션' }, // mapping → editable strong (pre-filled 어텐션)
  ],
};

// Badges are selected by term (order-independent): encoder (원어 유지 → weak), Transformer / BLEU /
// attention (표준 → strong).
const badge = (term: string) => screen.getByRole('button', { name: term });

function renderView(onRegenerate: () => void = () => {}) {
  return render(
    <div>
      <TranslationView translation={translation} showGlossary onRegenerate={onRegenerate} />
      <button type="button" data-testid="outside">
        바깥
      </button>
    </div>,
  );
}

describe('GlossaryTermBadge (via TranslationView)', () => {
  beforeEach(() => {
    resetMockGlossary();
    sessionStorage.clear(); // start with no pending draft
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders both groups; the mapping is an editable 표준 badge', () => {
    renderView();
    expect(screen.getByRole('heading', { name: '원어 유지 용어' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '표준 용어' })).toBeInTheDocument();
    // encoder (원어 유지) + Transformer, BLEU, attention (표준) — attention is editable now too.
    expect(screen.getAllByTestId('glossary-badge')).toHaveLength(4);
    expect(badge('attention')).toBeInTheDocument();
    expect(badge('encoder')).not.toHaveAttribute('data-saved'); // unedited → no marker
  });

  it('hides the 표준 용어 group when the paper has no standard terms', () => {
    render(<TranslationView translation={{ ...translation, standardGlossary: [] }} showGlossary />);
    expect(screen.queryByRole('heading', { name: '표준 용어' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '원어 유지 용어' })).toBeInTheDocument();
    expect(screen.getAllByTestId('glossary-badge')).toHaveLength(3);
  });

  it('no apply button until something is staged', () => {
    renderView();
    expect(screen.queryByTestId('glossary-apply-weak')).not.toBeInTheDocument();
    expect(screen.queryByTestId('glossary-apply-strong')).not.toBeInTheDocument();
  });

  it('staging a 원어 유지 term stages it and reveals the weak apply button (no server call yet)', async () => {
    const user = userEvent.setup();
    renderView();

    await user.click(badge('encoder'));
    const input = await screen.findByTestId('glossary-input');
    expect(screen.getByTestId('glossary-save')).toBeDisabled();

    await user.type(input, '인코더');
    expect(screen.getByTestId('glossary-save')).toBeEnabled();
    await user.click(screen.getByTestId('glossary-save'));

    // Staged, not saved to the server — the note points at the button, and the chip is now marked.
    expect(screen.getByTestId('glossary-saved')).toHaveTextContent('지정됨');
    expect(badge('encoder')).toHaveAttribute('data-saved', 'true');
    expect(await screen.findByTestId('glossary-apply-weak')).toBeInTheDocument();
    // Strong group untouched → no strong apply button.
    expect(screen.queryByTestId('glossary-apply-strong')).not.toBeInTheDocument();
  });

  it('a mapping (attention) pre-fills the standard rendering, then stages under the strong button', async () => {
    const user = userEvent.setup();
    renderView();

    await user.click(badge('attention'));
    const input = (await screen.findByTestId('glossary-input')) as HTMLInputElement;
    expect(input.value).toBe('어텐션'); // standard rendering pre-filled (defaultValue)

    await user.clear(input);
    await user.type(input, '주목');
    await user.click(screen.getByTestId('glossary-save'));

    expect(screen.getByTestId('glossary-saved')).toHaveTextContent('지정됨');
    expect(await screen.findByTestId('glossary-apply-strong')).toBeInTheDocument();
    expect(screen.queryByTestId('glossary-apply-weak')).not.toBeInTheDocument();
  });

  it('applies ONE group independently: pressing 반영 persists+re-runs only that group', async () => {
    const user = userEvent.setup();
    const onRegenerate = vi.fn();
    renderView(onRegenerate);

    // Stage one weak (encoder) and one strong (Transformer) edit → both apply buttons appear.
    await user.click(badge('encoder'));
    await user.type(await screen.findByTestId('glossary-input'), '인코더');
    await user.click(screen.getByTestId('glossary-save'));

    await user.click(badge('Transformer'));
    await user.type(await screen.findByTestId('glossary-input'), '트랜스포머');
    await user.click(screen.getByTestId('glossary-save'));

    expect(await screen.findByTestId('glossary-apply-weak')).toBeInTheDocument();
    expect(await screen.findByTestId('glossary-apply-strong')).toBeInTheDocument();

    // Apply ONLY the weak group.
    await user.click(screen.getByTestId('glossary-apply-weak'));
    await waitFor(() => expect(onRegenerate).toHaveBeenCalledTimes(1));
    // Weak button gone (its edit applied); the strong edit is still pending, its button remains.
    await waitFor(() =>
      expect(screen.queryByTestId('glossary-apply-weak')).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId('glossary-apply-strong')).toBeInTheDocument();
  });

  it('applies in one press even though the re-run unmounts the view (no double-press)', async () => {
    const user = userEvent.setup();
    // Mirrors FullTranslationIsland: applying re-runs the translation, which swaps this view out for
    // a loading surface (unmount) and back. The applied edit must already be cleared from storage,
    // or it rehydrates on remount and the button reappears — forcing a pointless second press.
    function Harness() {
      const [loading, setLoading] = useState(false);
      return loading ? (
        <button type="button" data-testid="remount" onClick={() => setLoading(false)}>
          done
        </button>
      ) : (
        <TranslationView
          translation={translation}
          showGlossary
          onRegenerate={() => setLoading(true)}
        />
      );
    }
    render(<Harness />);

    await user.click(badge('encoder'));
    await user.type(await screen.findByTestId('glossary-input'), '인코더');
    await user.click(screen.getByTestId('glossary-save'));
    await user.click(await screen.findByTestId('glossary-apply-weak'));

    // Re-run unmounted the view; remount as if the fresh translation arrived.
    await user.click(await screen.findByTestId('remount'));
    await waitFor(() =>
      expect(screen.queryByTestId('glossary-apply-weak')).not.toBeInTheDocument(),
    );
  });

  it('stages with NO network call, and applies via POST with the right promptEnforced flag', async () => {
    const user = userEvent.setup();
    // Spy the real ApiClient so we assert the network contract (not just UI state).
    const upsert = vi
      .spyOn(ApiClient.prototype, 'upsertGlossaryTerm')
      .mockResolvedValue({ status: 'ok', glossaryVer: 1 });
    vi.spyOn(ApiClient.prototype, 'listGlossaryTerms').mockResolvedValue([]);
    renderView(); // onRegenerate is a no-op here, so the view stays mounted after apply

    // (1) Saving a term only STAGES it — no POST yet.
    await user.click(badge('encoder')); // 원어 유지 → weak
    await user.type(await screen.findByTestId('glossary-input'), '인코더');
    await user.click(screen.getByTestId('glossary-save'));
    expect(upsert).not.toHaveBeenCalled();

    // (2) Applying the 원어 유지 group POSTs it as WEAK (promptEnforced: false).
    await user.click(await screen.findByTestId('glossary-apply-weak'));
    await waitFor(() =>
      expect(upsert).toHaveBeenCalledWith({
        termFrom: 'encoder',
        termTo: '인코더',
        promptEnforced: false,
      }),
    );

    // (3) A 표준 용어 applies as STRONG (promptEnforced: true).
    upsert.mockClear();
    await user.click(badge('Transformer'));
    await user.type(await screen.findByTestId('glossary-input'), '트랜스포머');
    await user.click(screen.getByTestId('glossary-save'));
    expect(upsert).not.toHaveBeenCalled(); // still staging-only
    await user.click(await screen.findByTestId('glossary-apply-strong'));
    await waitFor(() =>
      expect(upsert).toHaveBeenCalledWith({
        termFrom: 'Transformer',
        termTo: '트랜스포머',
        promptEnforced: true,
      }),
    );
  });

  it('keeps only one editor open at a time', async () => {
    const user = userEvent.setup();
    renderView();

    await user.click(badge('encoder'));
    expect(await screen.findByTestId('glossary-input')).toBeInTheDocument();
    expect(screen.getAllByTestId('glossary-input')).toHaveLength(1);

    await user.click(badge('Transformer'));
    await waitFor(() => expect(screen.getAllByTestId('glossary-input')).toHaveLength(1));
  });

  it('closes the editor on an outside click', async () => {
    const user = userEvent.setup();
    renderView();

    await user.click(badge('encoder'));
    expect(await screen.findByTestId('glossary-input')).toBeInTheDocument();

    await user.click(screen.getByTestId('outside'));
    await waitFor(() => expect(screen.queryByTestId('glossary-input')).not.toBeInTheDocument());
  });

  it('auto-dismisses the staged confirmation after a moment', async () => {
    const user = userEvent.setup();
    renderView();

    await user.click(badge('encoder'));
    await user.type(await screen.findByTestId('glossary-input'), '인코더');
    await user.click(screen.getByTestId('glossary-save'));
    expect(screen.getByTestId('glossary-saved')).toBeInTheDocument();

    // The editor closes itself shortly after (the durable cue is the apply button, which stays).
    await waitFor(() => expect(screen.queryByTestId('glossary-saved')).not.toBeInTheDocument(), {
      timeout: 4000,
    });
    expect(screen.getByTestId('glossary-apply-weak')).toBeInTheDocument();
  });

  it('un-stages a pending edit via 지우기 (removes the edit and its button)', async () => {
    const user = userEvent.setup();
    renderView();

    await user.click(badge('encoder'));
    await user.type(await screen.findByTestId('glossary-input'), '인코더');
    await user.click(screen.getByTestId('glossary-save'));
    expect(await screen.findByTestId('glossary-apply-weak')).toBeInTheDocument();
    expect(badge('encoder')).toHaveAttribute('data-saved', 'true');

    // Reopen the (pending) badge → the editor now offers 지우기; clearing un-stages it.
    await user.click(screen.getByTestId('outside'));
    await user.click(badge('encoder'));
    await user.click(await screen.findByTestId('glossary-clear'));

    await waitFor(() =>
      expect(screen.queryByTestId('glossary-apply-weak')).not.toBeInTheDocument(),
    );
    expect(badge('encoder')).not.toHaveAttribute('data-saved'); // reverted to unmarked
  });

  it('pre-fills a staged rendering when the badge is reopened', async () => {
    const user = userEvent.setup();
    renderView();

    await user.click(badge('encoder'));
    await user.type(await screen.findByTestId('glossary-input'), '인코더');
    await user.click(screen.getByTestId('glossary-save'));

    await user.click(screen.getByTestId('outside'));
    await user.click(badge('encoder'));
    const reopened = (await screen.findByTestId('glossary-input')) as HTMLInputElement;
    expect(reopened.value).toBe('인코더');
  });

  it('keeps the pending edit and its button across a remount (sessionStorage)', async () => {
    const user = userEvent.setup();
    const { unmount } = renderView();

    await user.click(badge('encoder'));
    await user.type(await screen.findByTestId('glossary-input'), '인코더');
    await user.click(screen.getByTestId('glossary-save'));
    expect(await screen.findByTestId('glossary-apply-weak')).toBeInTheDocument();

    // Simulate leaving and re-entering the page — the draft rehydrates from sessionStorage.
    unmount();
    render(<TranslationView translation={translation} showGlossary onRegenerate={() => {}} />);

    expect(await screen.findByTestId('glossary-apply-weak')).toBeInTheDocument();
    expect(badge('encoder')).toHaveAttribute('data-saved', 'true'); // still marked from the draft
  });
});
