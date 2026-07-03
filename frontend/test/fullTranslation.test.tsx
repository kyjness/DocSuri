import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FullTranslationIsland } from '@/components/FullTranslationIsland';

// Uses the mock transport (NEXT_PUBLIC_DOCSURI_REAL_API unset) → fullTranslationResponse
// (task=translate, scope=full). Renders the translation full-page as a "translated doc-model"
// (BR-S18 — same rich viewer as the body: section headings, TOC, KaTeX, tables), no modal.
describe('FullTranslationIsland', () => {
  it('runs the full-text translation and renders the structured Korean body + kept terms', async () => {
    render(<FullTranslationIsland paperId="2401.00001" version={1} />);

    // Structured render: the translated section heading is present (also appears in the TOC).
    expect(await screen.findByRole('heading', { name: '모델 구조' })).toBeTruthy();
    // Glossary split into 표준 용어 (seed standard) and 원어 유지 용어 (BR-S4).
    expect(screen.getByRole('heading', { name: '표준 용어' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: '원어 유지 용어' })).toBeTruthy();
    // attention (mapping) and Transformer (keep-as-is) are both editable 표준 chips.
    expect(screen.getByRole('button', { name: 'attention' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Transformer' })).toBeInTheDocument();
  });
});
