import { describe, it, expect } from 'vitest';
import { arxivVersion } from '@/lib/arxivVersion';

describe('arxivVersion', () => {
  it('parses the trailing arXiv revision from a versioned id', () => {
    expect(arxivVersion('2304.10557v6')).toBe(6);
    expect(arxivVersion('2401.00001v12')).toBe(12);
  });

  it('defaults a bare id (no explicit revision) to 1', () => {
    expect(arxivVersion('2401.00001')).toBe(1);
    expect(arxivVersion('1706.03762')).toBe(1);
  });

  it('only treats a trailing vN as the revision', () => {
    // a digit-ending id that is not a vN suffix must not be misread
    expect(arxivVersion('2207.09238')).toBe(1);
  });
});
