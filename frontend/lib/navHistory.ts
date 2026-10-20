// In-app back navigation (LC-1). The header's ← should behave like the browser's back: return to
// the screen the user came from, and leave the history stack as it would be after a real back.
// Navigating FORWARD to a fixed parent instead (the old behaviour) pushed a fresh entry on every
// tap, so search → A → ← → B → ← left [search, A, search, B, search] behind, and the phone's own
// back gesture then walked through every paper opened earlier.
//
// Going back is only safe when the entry behind this one is an app screen the user would expect
// to return to. That is not knowable from `history` itself (no index, no peek), so each entry is
// stamped once with the app path that was on screen when it was created. Next.js keeps a custom
// key in `history.state` across back/forward, so the stamp is read back on the entry it belongs to.

const STATE_KEY = '__docsuriFrom';

// Auth screens are a detour, never a destination: returning to the login form after signing in
// (or to the screen a session expiry bounced away from) is what a fixed parent exists to avoid.
const AUTH_PREFIXES = ['/login', '/signup', '/reset-password', '/social-link-required', '/verify-email'];

export function isAuthPath(path: string): boolean {
  return AUTH_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`));
}

// Path rendered before the current one in this document. Module state: it lives exactly as long
// as the client-side app does, so a full reload (or a deep link) starts with nothing behind it.
let lastPath: string | null = null;

/** Stamp the current history entry with where it was entered from (once per entry). */
export function recordEntry(path: string): void {
  if (typeof window === 'undefined') return;
  const state = (window.history.state ?? {}) as Record<string, unknown>;
  // A stamped entry is one being revisited (back/forward): its origin is already known. The same
  // path re-rendering is not a new screen either.
  if (!(STATE_KEY in state) && path !== lastPath) {
    // Spreading the existing state keeps Next.js's internal keys, which it requires to treat the
    // entry as its own (its patched replaceState passes such state through untouched).
    window.history.replaceState({ ...state, [STATE_KEY]: lastPath }, '');
  }
  lastPath = path;
}

/** True when going back lands on an app screen (not off-site, not an auth detour). */
export function canGoBackInApp(): boolean {
  if (typeof window === 'undefined') return false;
  const from = (window.history.state as Record<string, unknown> | null)?.[STATE_KEY];
  if (typeof from !== 'string') return false;
  return !isAuthPath(from) && !isAuthPath(window.location.pathname);
}
