import { describe, it, expect } from 'vitest';
import { classifyDocModelResponse } from '@/lib/api/classifySummarize';

describe('classifyDocModelResponse', () => {
  it('maps ok → page with docModel + cached', () => {
    const out = classifyDocModelResponse({
      status: 'ok',
      cached: true,
      docModel: { meta: { paperId: 'x', version: 1 }, fullText: '', sections: [] },
    });
    expect(out.kind).toBe('page');
    if (out.kind === 'page') {
      expect(out.cached).toBe(true);
      expect(out.docModel.meta.paperId).toBe('x');
    }
  });

  it('maps building → building with the poll-backoff hint (lazy build in flight)', () => {
    const out = classifyDocModelResponse({ status: 'building', retryAfterMs: 1500 });
    expect(out.kind).toBe('building');
    if (out.kind === 'building') expect(out.retryAfterMs).toBe(1500);
    // hint is optional — absence must not break classification.
    expect(classifyDocModelResponse({ status: 'building' }).kind).toBe('building');
  });

  it('maps license_unavailable / source_unavailable to their states', () => {
    expect(classifyDocModelResponse({ status: 'license_unavailable' }).kind).toBe(
      'licenseUnavailable',
    );
    expect(classifyDocModelResponse({ status: 'source_unavailable' }).kind).toBe(
      'sourceUnavailable',
    );
  });

  it('falls back to error on an unknown status or non-object body', () => {
    expect(classifyDocModelResponse({ status: 'weird' }).kind).toBe('error');
    expect(classifyDocModelResponse(null).kind).toBe('error');
    // ok without a docModel payload is not renderable → error.
    expect(classifyDocModelResponse({ status: 'ok' }).kind).toBe('error');
  });
});
