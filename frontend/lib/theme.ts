// Manual light/dark theme override (U10 마이페이지 설정). Persists per-browser only
// (localStorage) — no account sync, no backend column (Q: 기기별 저장으로 결정).
// Absent storage ⇒ falls back to the OS `prefers-color-scheme` (app/globals.css).

export type Theme = 'light' | 'dark';

const THEME_STORAGE_KEY = 'docsuri-theme';

export function readStoredTheme(): Theme | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return stored === 'light' || stored === 'dark' ? stored : null;
  } catch {
    return null;
  }
}

/** Applies the theme to the document and persists it. Pass `null` to clear the
 * override and fall back to the OS preference. */
export function applyTheme(theme: Theme | null): void {
  try {
    if (theme) {
      document.documentElement.setAttribute('data-theme', theme);
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } else {
      document.documentElement.removeAttribute('data-theme');
      window.localStorage.removeItem(THEME_STORAGE_KEY);
    }
  } catch {
    // localStorage unavailable (private mode/quota) — theme just won't persist.
  }
}

/** Inline script source for `app/layout.tsx`: applies the stored theme before
 * React hydrates, so there is no flash of the wrong theme on load. */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem('${THEME_STORAGE_KEY}');if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`;
