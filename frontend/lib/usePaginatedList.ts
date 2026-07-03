'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { UserFacingError } from '@/lib/api';

// usePaginatedList (BR-U5, NFR-U5) — cursor-based list state shared by the
// library/saved/history screens. NEVER assumes offset/total count; "더 보기"
// appends the next cursor page. Loading/empty/error are the caller's to render.

export interface Page<T> {
  items: T[];
  nextCursor?: string;
}

export type ListStatus = 'loading' | 'ready' | 'loadingMore' | 'error';

export interface PaginatedList<T> {
  items: T[];
  status: ListStatus;
  error: string | null;
  hasMore: boolean;
  loadMore: () => Promise<void>;
  reload: () => Promise<void>;
  /** Optimistic local removal after a successful server delete. */
  removeLocal: (pred: (item: T) => boolean) => void;
}

export function usePaginatedList<T>(
  fetchPage: (cursor?: string) => Promise<Page<T>>,
): PaginatedList<T> {
  const router = useRouter();
  const pathname = usePathname();
  // Latest router/pathname via refs, NOT as reload/loadMore dependencies (BR-U5-15). reload is
  // also the mount-effect trigger below; if its identity depended on router/pathname directly,
  // any upstream identity change unrelated to the actual list (e.g. a navigation object that
  // isn't referentially stable across renders) would recreate reload and re-fire that effect,
  // reloading in a loop. Refs let the auth-redirect always see the latest values without that
  // risk.
  const routerRef = useRef(router);
  routerRef.current = router;
  const pathnameRef = useRef(pathname);
  pathnameRef.current = pathname;
  const [items, setItems] = useState<T[]>([]);
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [status, setStatus] = useState<ListStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  // Reentrancy guard for loadMore (BR-U5-18): a fast double-tap on "더 보기" before the first
  // page lands must not append the same cursor page twice.
  const loadingRef = useRef(false);

  const reload = useCallback(async () => {
    setStatus('loading');
    setError(null);
    try {
      const page = await fetchPage(undefined);
      setItems(page.items);
      setCursor(page.nextCursor);
      setStatus('ready');
    } catch (e) {
      if (e instanceof UserFacingError && e.isAuth) {
        // Session expired mid-list (BR-U5-15): route to login instead of an inline error the
        // user has no recourse for. `pathname` is our own route, so it's already safe to embed.
        routerRef.current.push(`/login?redirect=${encodeURIComponent(pathnameRef.current)}`);
        return;
      }
      setError(e instanceof UserFacingError ? e.message : '목록을 불러오지 못했습니다.');
      setStatus('error');
    }
  }, [fetchPage]);

  const loadMore = useCallback(async () => {
    if (!cursor || loadingRef.current) return;
    loadingRef.current = true;
    setStatus('loadingMore');
    setError(null);
    try {
      const page = await fetchPage(cursor);
      setItems((prev) => [...prev, ...page.items]);
      setCursor(page.nextCursor);
      setStatus('ready');
    } catch (e) {
      if (e instanceof UserFacingError && e.isAuth) {
        routerRef.current.push(`/login?redirect=${encodeURIComponent(pathnameRef.current)}`);
        return;
      }
      setError(e instanceof UserFacingError ? e.message : '더 불러오지 못했습니다.');
      setStatus('error');
    } finally {
      loadingRef.current = false;
    }
  }, [cursor, fetchPage]);

  const removeLocal = useCallback((pred: (item: T) => boolean) => {
    setItems((prev) => prev.filter((it) => !pred(it)));
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { items, status, error, hasMore: Boolean(cursor), loadMore, reload, removeLocal };
}
