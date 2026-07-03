'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';
import {
  PREVIEW_QUERY_FLAG,
  readStoredViewMode,
  storeViewMode,
  type ViewMode,
} from '@/lib/viewMode';
import styles from './ViewModePreview.module.css';

// Desktop-only web/mobile switch. The app itself is plain responsive web; the toggle
// flips the whole screen to the mobile version, rendered by loading the SAME app inside a
// phone-width iframe. The iframe has its own viewport, so the mobile layout renders
// correctly and stays isolated from the desktop layout — a real desktop redesign can't
// leak into it. In mobile mode the iframe takes over the screen (opaque, no web page
// behind, no modal dimming); the 웹 button switches back.
//
// Rendered once in the root layout (so it's also present inside the iframe document); it
// renders nothing when the `preview` flag is in the URL, which prevents a nested preview.
// Client-only (mounted gate) since it's non-critical chrome that reads localStorage/URL.

export function ViewModePreview() {
  const [mounted, setMounted] = useState(false);
  const [mode, setMode] = useState<ViewMode>('web');
  // Whether this instance is the one rendered INSIDE the preview iframe (the `preview` flag
  // is in its URL). The iframe shares localStorage with the outer document, so it reads the
  // same 'phone' mode — without this guard `open` would be true here too, and the effects
  // below (Esc handler) would run despite the component rendering nothing.
  const [isPreview, setIsPreview] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    setMounted(true);
    setIsPreview(new URLSearchParams(window.location.search).has(PREVIEW_QUERY_FLAG));
    setMode(readStoredViewMode());
  }, []);

  // Only the outer document drives the preview; the embedded iframe instance never "opens".
  const open = mode === 'phone' && !isPreview;

  // Esc returns to the web view.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setMode('web');
        storeViewMode('web');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  // Lock the background document's scroll while the opaque phone overlay covers it. Otherwise the
  // desktop page (a long search-results/detail screen) keeps its own scrollbar at the window edge,
  // but the wheel scrolls the phone iframe on top — so that outer scrollbar just sits there,
  // visible yet unusable ("dead" scrollbar). Restored to its prior value when the preview closes.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!mounted) return null;
  // Inside the preview iframe: render no chrome (no toggle, no nested preview).
  if (isPreview) return null;

  const set = (next: ViewMode) => {
    setMode(next);
    storeViewMode(next);
  };

  // Preview the screen the user is actually on — including its query (e.g. /search?q=…),
  // which usePathname() drops. Safe to read window here (past the mounted gate). The flag
  // suppresses the embedded chrome.
  const currentQuery = window.location.search; // "" or "?q=foo"
  const previewSrc = `${pathname || '/'}?${PREVIEW_QUERY_FLAG}=1${
    currentQuery ? `&${currentQuery.slice(1)}` : ''
  }`;

  return (
    <>
      <button
        type="button"
        className={styles.toggle}
        onClick={() => set(open ? 'web' : 'phone')}
        aria-label={open ? '웹 화면으로 전환' : '모바일 화면으로 전환'}
        title={open ? '웹 화면으로 전환' : '모바일 화면으로 전환'}
        aria-pressed={open}
      >
        <span aria-hidden="true">{open ? '🖥️' : '📱'}</span>
        {open ? '웹' : '폰'}
      </button>

      {open && (
        <div className={styles.stage} role="group" aria-label="모바일 화면">
          <iframe className={styles.frame} src={previewSrc} title="모바일 화면" />
        </div>
      )}
    </>
  );
}
