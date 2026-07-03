import { describe, it, expect } from 'vitest';
import { classifySearchResponse } from '@/lib/api/classify';
import {
  pageResponse,
  emptyResponse,
  abstainResponse,
  degradedResponse,
  validationErrorResponse,
} from '@/mocks/searchFixtures';

describe('classifySearchResponse', () => {
  it('classifies a result page', () => {
    expect(classifySearchResponse(pageResponse).kind).toBe('page');
  });

  it('classifies an empty page distinctly from abstain', () => {
    expect(classifySearchResponse(emptyResponse).kind).toBe('empty');
    expect(classifySearchResponse(abstainResponse).kind).toBe('abstain');
  });

  it('classifies a degraded response', () => {
    const out = classifySearchResponse(degradedResponse);
    expect(out.kind).toBe('degraded');
  });

  it('classifies a page-shaped body as degraded via meta.degraded even with no top-level mode (E5, BR-U5-8/12)', () => {
    // Same shape as pageResponse (cards + meta, no `mode` key), but meta signals degraded —
    // the old code only looked at the top-level `mode` key, so this used to fall through to
    // 'page' and silently hide the degradation from the UI.
    const out = classifySearchResponse({
      cards: pageResponse.cards,
      meta: { resultCount: pageResponse.cards.length, degraded: true },
    });
    expect(out.kind).toBe('degraded');
  });

  it('still classifies an empty degraded body as empty, not degraded (ordering)', () => {
    const out = classifySearchResponse({ cards: [], meta: { resultCount: 0, degraded: true } });
    expect(out.kind).toBe('empty');
  });

  it('classifies a validation error', () => {
    expect(classifySearchResponse(validationErrorResponse).kind).toBe('invalid');
  });

  it('fails closed on garbage', () => {
    expect(classifySearchResponse(null).kind).toBe('invalid');
    expect(classifySearchResponse(42).kind).toBe('invalid');
  });
});
