import { describe, it, expect } from 'vitest';
import { classifySummarizeResponse } from '@/lib/api/classifySummarize';

// Test-only literal fixtures (real-first: no production mock adapter).
const summaryOk = {
  status: 'ok',
  task: 'summary',
  meta: { source: 'full_text' },
  cached: false,
  summary: {
    tldr: 't',
    contributions: ['c1'],
    method: 'm',
    results: 'r',
    limitations: 'l',
    reproducibility: { code: 'yes', data: 'yes' },
    anchors: [{ field: 'results', target: 'table', span: 's', label: '표 2' }],
  },
};
const translationOk = {
  status: 'ok',
  task: 'translate',
  meta: { source: 'abstract' },
  cached: true,
  translation: {
    docModel: {
      meta: { paperId: '1', version: 1, title: '', provenance: {} },
      sections: [{ id: 's1', title: '', blocks: [{ id: 's1.p1', type: 'paragraph', text: '한국어' }] }],
    },
    keptTerms: ['Transformer'],
  },
};

describe('classifySummarizeResponse — exhaustive status mapping (BR-SF-14)', () => {
  it('ok+summary -> summary', () => {
    const out = classifySummarizeResponse(summaryOk);
    expect(out.kind).toBe('summary');
    if (out.kind === 'summary') expect(out.summary.tldr).toBe('t');
  });

  it('ok+translation -> translation (with cached)', () => {
    const out = classifySummarizeResponse(translationOk);
    expect(out.kind).toBe('translation');
    if (out.kind === 'translation') expect(out.cached).toBe(true);
  });

  it('abstain / cost_degraded / source_unavailable map to distinct kinds', () => {
    expect(classifySummarizeResponse({ status: 'abstain', reason: 'x' }).kind).toBe('abstain');
    expect(classifySummarizeResponse({ status: 'cost_degraded', message: 'm' }).kind).toBe('degraded');
    expect(classifySummarizeResponse({ status: 'source_unavailable', reason: 'x' }).kind).toBe(
      'sourceUnavailable',
    );
  });

  it('pending -> pending with the poll-backoff hint (long summary background job)', () => {
    const out = classifySummarizeResponse({ status: 'pending', retryAfterMs: 3000 });
    expect(out.kind).toBe('pending');
    if (out.kind === 'pending') expect(out.retryAfterMs).toBe(3000);
    expect(classifySummarizeResponse({ status: 'pending' }).kind).toBe('pending');
  });

  it('validation error (message) -> invalid', () => {
    expect(classifySummarizeResponse({ field: 'task', message: 'bad' }).kind).toBe('invalid');
  });

  it('fails closed on garbage / unknown', () => {
    expect(classifySummarizeResponse(null).kind).toBe('error');
    expect(classifySummarizeResponse(42).kind).toBe('error');
    expect(classifySummarizeResponse({ status: 'ok' }).kind).toBe('error'); // ok without payload
    expect(classifySummarizeResponse({ status: 'weird' }).kind).toBe('error');
  });
});
