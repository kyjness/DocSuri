import { describe, it, expect } from 'vitest';
import {
  classifyAssetsResponse,
  classifySummarizeResponse,
} from '@/lib/api/classifySummarize';

// FR-17 assets + gap #2/#3 status mapping (BR-S17).

describe('classifyAssetsResponse', () => {
  it('maps ok to assets', () => {
    const out = classifyAssetsResponse({
      status: 'ok',
      assets: [
        { assetId: 'a1', type: 'figure', ordinal: 0, caption: 'Figure 1', sourceMode: 'page-crop', url: 'https://s/x' },
      ],
    });
    expect(out.kind).toBe('assets');
    if (out.kind === 'assets') {
      expect(out.assets).toHaveLength(1);
      expect(out.assets[0].assetId).toBe('a1');
    }
  });

  it('maps license_unavailable and unauthorized', () => {
    expect(classifyAssetsResponse({ status: 'license_unavailable' }).kind).toBe('licenseUnavailable');
    expect(classifyAssetsResponse({ status: 'unauthorized' }).kind).toBe('unauthorized');
  });

  it('fails closed on unknown shapes', () => {
    expect(classifyAssetsResponse(null).kind).toBe('error');
    expect(classifyAssetsResponse({ status: 'weird' }).kind).toBe('error');
  });
});

describe('classifySummarizeResponse gap #2/#3', () => {
  it('validation_error with message -> invalid (check your input)', () => {
    const out = classifySummarizeResponse({ status: 'validation_error', message: '요청을 확인해 주세요.' });
    expect(out.kind).toBe('invalid');
    if (out.kind === 'invalid') expect(out.message).toBe('요청을 확인해 주세요.');
  });

  it('unauthorized -> auth-specific error message', () => {
    const out = classifySummarizeResponse({ status: 'unauthorized' });
    expect(out.kind).toBe('error');
    if (out.kind === 'error') expect(out.message).toBe('로그인이 필요합니다.');
  });
});
