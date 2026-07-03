// Desktop "view mode": the app is a pure responsive site (mobile on narrow widths,
// web layout from tablet up). On desktop the user can additionally open a faithful
// phone preview, which loads the same app inside a 412px-wide iframe — the iframe gives
// the inner page its own viewport, so the mobile styles apply correctly and stay
// isolated from the desktop layout (CSS media queries measure the iframe, not the
// outer window). This module only remembers whether that preview is open.
//
// Persisted per-browser (localStorage) only — no account sync. The preview is a
// desktop affordance; it has no effect on phones (the toggle/overlay are hidden <768px).

export type ViewMode = 'web' | 'phone';

const VIEW_MODE_STORAGE_KEY = 'docsuri-view-mode';

/** Reads whether the phone preview was left open. Anything but an explicit 'phone'
 * is 'web' (preview closed), so unset storage defaults to the plain web view. */
export function readStoredViewMode(): ViewMode {
  try {
    return window.localStorage.getItem(VIEW_MODE_STORAGE_KEY) === 'phone' ? 'phone' : 'web';
  } catch {
    return 'web';
  }
}

/** Persists the phone-preview open/closed choice. */
export function storeViewMode(mode: ViewMode): void {
  try {
    window.localStorage.setItem(VIEW_MODE_STORAGE_KEY, mode);
  } catch {
    // localStorage unavailable (private mode/quota) — the choice just won't persist.
  }
}

/** Query flag added to the iframe's src so the embedded app skips rendering its own
 * preview chrome (prevents a preview-inside-preview and any recursion). */
export const PREVIEW_QUERY_FLAG = 'preview';
