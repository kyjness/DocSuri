'use client';

import { useCallback, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { getApiClient, UserFacingError } from '@/lib/api';
import { usePaginatedList } from '@/lib/usePaginatedList';
import { cardFromMeta } from '@/lib/library/cardFromMeta';
import { ResultCard } from '../ResultCard';
import { StateView } from '../StateView';
import { LibraryTabs } from './LibraryTabs';
import type { LibraryItemDTO } from '@/types/generated';
import styles from './Library.module.css';

// LibraryScreen (US-L2, FR-9) — the user's saved papers, rendered from preserved
// meta snapshots (no live index). Remove is optimistic after a 2xx; cursor "더 보기".
export function LibraryScreen() {
  const router = useRouter();
  const pathname = usePathname();
  const fetchPage = useCallback((cursor?: string) => getApiClient().listLibrary({ cursor }), []);
  const { items, status, error, hasMore, loadMore, reload, removeLocal } =
    usePaginatedList<LibraryItemDTO>(fetchPage);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const onRemove = async (item: LibraryItemDTO) => {
    const itemId = String(item.id);
    setBusyId(itemId);
    setActionError(null);
    try {
      await getApiClient().removeFromLibrary(itemId);
      removeLocal((it) => String(it.id) === itemId);
    } catch (e) {
      if (e instanceof UserFacingError && e.isAuth) {
        router.push(`/login?redirect=${encodeURIComponent(pathname)}`);
        return;
      }
      setActionError('제거하지 못했습니다. 다시 시도해 주세요.');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className={styles.screen} data-testid="library-screen">
      <LibraryTabs active="library" />
      {status === 'loading' ? <StateView kind="loading" /> : null}
      {status === 'error' ? (
        <StateView kind="error" message={error ?? undefined} onRetry={() => void reload()} />
      ) : null}
      {status !== 'loading' && status !== 'error' && items.length === 0 ? (
        <StateView
          kind="empty"
          message="라이브러리가 비어 있습니다. 검색 결과에서 논문을 담아보세요."
        />
      ) : null}

      {actionError ? (
        <p className={styles.panelTitle} role="alert" data-testid="library-action-error">
          {actionError}
        </p>
      ) : null}

      {items.length > 0 ? (
        <ul className={styles.list}>
          {items.map((item) => (
            <li key={String(item.id)} data-testid="library-item">
              <ResultCard
                card={cardFromMeta(item.meta)}
                action={
                  <button
                    type="button"
                    className={styles.danger}
                    disabled={busyId === String(item.id)}
                    onClick={() => void onRemove(item)}
                    data-testid="library-remove"
                  >
                    제거
                  </button>
                }
              />
            </li>
          ))}
        </ul>
      ) : null}

      {hasMore ? (
        <button
          type="button"
          className={styles.more}
          onClick={() => void loadMore()}
          disabled={status === 'loadingMore'}
          data-testid="library-more"
        >
          더 보기
        </button>
      ) : null}
    </section>
  );
}
