import { describe, it, expect, beforeEach } from 'vitest';
import { applyTheme, readStoredTheme } from '@/lib/theme';

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
});

describe('readStoredTheme', () => {
  it('returns null when nothing is stored', () => {
    expect(readStoredTheme()).toBeNull();
  });

  it('ignores a corrupted/unexpected stored value', () => {
    window.localStorage.setItem('docsuri-theme', 'sepia');
    expect(readStoredTheme()).toBeNull();
  });

  it('returns the stored theme', () => {
    window.localStorage.setItem('docsuri-theme', 'dark');
    expect(readStoredTheme()).toBe('dark');
  });
});

describe('applyTheme', () => {
  it('sets the data-theme attribute and persists the choice', () => {
    applyTheme('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(window.localStorage.getItem('docsuri-theme')).toBe('dark');
  });

  it('clears the override (falls back to OS preference) when passed null', () => {
    applyTheme('dark');
    applyTheme(null);
    expect(document.documentElement.getAttribute('data-theme')).toBeNull();
    expect(window.localStorage.getItem('docsuri-theme')).toBeNull();
  });
});
