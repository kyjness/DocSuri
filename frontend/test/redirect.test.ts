import { describe, it, expect } from 'vitest';
import { safeRedirect } from '@/lib/redirect';

// safeRedirect (BR-U5-15, SEC-8) — LoginForm's `?redirect` used to be router.push'd
// unvalidated, letting an attacker send an authenticated user off-site
// (?redirect=https://evil.example). Only a single-leading-slash, same-origin path
// is honored; everything else falls back.
describe('safeRedirect', () => {
  it('preserves a same-origin path', () => {
    expect(safeRedirect('/library')).toBe('/library');
  });

  it('falls back on an absolute URL (open-redirect attempt)', () => {
    expect(safeRedirect('https://evil.example')).toBe('/search');
  });

  it('falls back on a protocol-relative URL (//host)', () => {
    expect(safeRedirect('//evil.example')).toBe('/search');
  });

  it('falls back on a backslash trick (/\\host, browser-normalized to //host)', () => {
    expect(safeRedirect('/\\evil.example')).toBe('/search');
  });

  it('falls back on null/undefined/empty', () => {
    expect(safeRedirect(null)).toBe('/search');
    expect(safeRedirect(undefined)).toBe('/search');
    expect(safeRedirect('')).toBe('/search');
  });

  it('honors a custom fallback', () => {
    expect(safeRedirect('javascript:alert(1)', '/home')).toBe('/home');
  });
});
