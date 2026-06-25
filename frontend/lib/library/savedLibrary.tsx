'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { getApiClient } from '@/lib/api';
import { useSession } from '@/components/session/SessionContext';
import type { LibraryItemDTO } from '@/types/generated';

// SavedLibrary (US-L2, FR-9) — a session-scoped arXivId → library-item-id map so a bookmark
// button can render the *real* saved state on first paint instead of always starting empty.
// Loaded once per authenticated session (lazy, all cursor pages, bounded), then kept in sync by
// the bookmark toggles. Best-effort: if the load fails the buttons just fall back to the old
// "start idle" behavior — bookmark fill is a nicety, not load-bearing.

interface SavedLibraryValue {
  /** true once the initial saved set finished loading (so "not in the map" means "not saved"). */
  ready: boolean;
  /** The saved item's id for un-saving, or null when not saved / not yet loaded. */
  itemIdFor: (arxivId: string) => string | null;
  markSaved: (arxivId: string, itemId: string) => void;
  markRemoved: (arxivId: string) => void;
}

// Default (no provider): inert — buttons behave exactly as before. Keeps SaveToLibraryButton
// usable in isolation (unit tests, standalone renders) without a provider.
const DEFAULT: SavedLibraryValue = {
  ready: false,
  itemIdFor: () => null,
  markSaved: () => {},
  markRemoved: () => {},
};

const SavedLibraryContext = createContext<SavedLibraryValue>(DEFAULT);

// Library is capped at 1000 items/owner (BR-L4); bound the page loop so a bad cursor can't loop.
const MAX_PAGES = 25;

export function SavedLibraryProvider({ children }: { children: React.ReactNode }) {
  const { status } = useSession();
  const [map, setMap] = useState<Map<string, string>>(() => new Map());
  const [ready, setReady] = useState(false);
  const loadedFor = useRef<string | null>(null); // guards one load per authenticated session

  useEffect(() => {
    if (status === 'anonymous') {
      // Logged out → drop any saved state so the next user doesn't inherit it.
      loadedFor.current = null;
      setMap(new Map());
      setReady(false);
      return;
    }
    if (status !== 'authenticated' || loadedFor.current === 'authenticated') return;
    loadedFor.current = 'authenticated';

    let cancelled = false;
    void (async () => {
      const next = new Map<string, string>();
      try {
        let cursor: string | undefined;
        for (let i = 0; i < MAX_PAGES; i += 1) {
          // Page at the max size (100) so MAX_PAGES fully covers the 1000-item cap (BR-L4) —
          // the default size (20) would only reach 500 and leave the upper half un-hydrated.
          const page = await getApiClient().listLibrary({ limit: 100, ...(cursor ? { cursor } : {}) });
          for (const it of page.items as LibraryItemDTO[]) {
            next.set(it.arXivId, String(it.id));
          }
          cursor = page.nextCursor ?? undefined;
          if (!cursor) break;
        }
      } catch {
        // best-effort; leave whatever we gathered and mark ready so toggles still sync.
      }
      if (!cancelled) {
        setMap(next);
        setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status]);

  const itemIdFor = useCallback((arxivId: string) => map.get(arxivId) ?? null, [map]);
  const markSaved = useCallback((arxivId: string, itemId: string) => {
    setMap((prev) => new Map(prev).set(arxivId, itemId));
  }, []);
  const markRemoved = useCallback((arxivId: string) => {
    setMap((prev) => {
      if (!prev.has(arxivId)) return prev;
      const nextMap = new Map(prev);
      nextMap.delete(arxivId);
      return nextMap;
    });
  }, []);

  const value = useMemo<SavedLibraryValue>(
    () => ({ ready, itemIdFor, markSaved, markRemoved }),
    [ready, itemIdFor, markSaved, markRemoved],
  );

  return <SavedLibraryContext.Provider value={value}>{children}</SavedLibraryContext.Provider>;
}

export function useSavedLibrary(): SavedLibraryValue {
  return useContext(SavedLibraryContext);
}
