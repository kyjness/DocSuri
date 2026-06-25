import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
});

// jsdom's `window.localStorage` is unreliable across Node versions (under Node 25 it resolves
// to an object with no methods — likely jsdom racing Node's own experimental global Storage).
// No test used localStorage before U10's dark-mode toggle, so this never surfaced until now.
// A minimal in-memory Storage polyfill keeps tests deterministic regardless of the host's
// jsdom/Node combination.
class MemoryStorage implements Storage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }

  clear(): void {
    this.store.clear();
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null;
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.store.delete(key);
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

if (typeof window.localStorage?.setItem !== 'function') {
  Object.defineProperty(window, 'localStorage', { value: new MemoryStorage() });
}

// jsdom doesn't implement `window.matchMedia` at all (unrelated to the localStorage gap above —
// this one is a long-standing, well-known jsdom limitation). U10's dark-mode toggle reads
// `prefers-color-scheme` once on mount, so any test that mounts inside `ThemeProvider` needs
// this defined. Defaults to "no preference" (matches: false); tests that care about the
// system-dark case override `window.matchMedia` themselves.
if (typeof window.matchMedia !== 'function') {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}
