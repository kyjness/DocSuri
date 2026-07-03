'use client';

import { useCallback, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { getApiClient, UserFacingError, type SearchOutcome } from '@/lib/api';
import { usePaginatedList } from '@/lib/usePaginatedList';
import { StateView } from '../StateView';
import { LibraryTabs } from './LibraryTabs';
import { OutcomeView } from './OutcomeView';
import type { SavedSearchDTO } from '@/types/generated';
import styles from './Library.module.css';

// SavedSearchScreen (US-L1, FR-8) — list/delete/rerun saved searches. Rerun goes
// through the gateway (U6 -> U2) and renders the live result inline (BR-U5-9).
export function SavedSearchScreen({ showTabs = true }: { showTabs?: boolean } = {}) {
  const router = useRouter();
  const pathname = usePathname();
  const fetchPage = useCallback(
    (cursor?: string) => getApiClient().listSavedSearches({ cursor }),
    [],
  );
  const { items, status, error, hasMore, loadMore, reload, removeLocal } =
    usePaginatedList<SavedSearchDTO>(fetchPage);

  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [rerun, setRerun] = useState<{ id: string; outcome: SearchOutcome } | null>(null);
  const [rerunId, setRerunId] = useState<string | null>(null);

  const onDelete = async (item: SavedSearchDTO) => {
    const itemId = String(item.id);
    setBusyId(itemId);
    setActionError(null);
    try {
      await getApiClient().deleteSavedSearch(itemId);
      removeLocal((it) => String(it.id) === itemId);
      if (rerun?.id === itemId) setRerun(null);
    } catch (e) {
      if (e instanceof UserFacingError && e.isAuth) {
        router.push(`/login?redirect=${encodeURIComponent(pathname)}`);
        return;
      }
      setActionError('삭제하지 못했습니다. 다시 시도해 주세요.');
    } finally {
      setBusyId(null);
    }
  };

  const onRerun = async (item: SavedSearchDTO) => {
    const itemId = String(item.id);
    setRerunId(itemId);
    setActionError(null);
    try {
      const outcome = await getApiClient().rerunSavedSearch(itemId);
      setRerun({ id: itemId, outcome });
    } catch (e) {
      if (e instanceof UserFacingError && e.isAuth) {
        // Session expired mid-list (BR-U5-15) — route to login rather than an inline error.
        router.push(`/login?redirect=${encodeURIComponent(pathname)}`);
        return;
      }
      setActionError(e instanceof UserFacingError ? e.message : '다시 실행하지 못했습니다.');
    } finally {
      setRerunId(null);
    }
  };

  return (
    <section className={styles.screen} data-testid="saved-screen">
      {showTabs ? <LibraryTabs active="saved" /> : null}
      {status === 'loading' ? <StateView kind="loading" /> : null}
      {status === 'error' ? (
        <StateView kind="error" message={error ?? undefined} onRetry={() => void reload()} />
      ) : null}
      {status !== 'loading' && status !== 'error' && items.length === 0 ? (
        <StateView
          kind="empty"
          message="저장한 검색이 없습니다. 검색 화면에서 검색을 저장해 보세요."
        />
      ) : null}

      {actionError ? (
        <p className={styles.panelTitle} role="alert" data-testid="saved-action-error">
          {actionError}
        </p>
      ) : null}

      {items.length > 0 ? (
        <ul className={styles.list}>
          {items.map((item) => {
            const itemId = String(item.id);
            return (
              <li key={itemId} className={styles.row} data-testid="saved-item">
                <span className={styles.rowQuery} data-testid="saved-query">
                  {item.label ?? item.query}
                </span>
                <span className={styles.rowMeta}>
                  {item.label ? <span data-testid="saved-subquery">{item.query}</span> : null}
                </span>
                <div className={styles.actions}>
                  <button
                    type="button"
                    className={styles.action}
                    disabled={rerunId === itemId}
                    onClick={() => void onRerun(item)}
                    data-testid="saved-rerun"
                  >
                    {rerunId === itemId ? '실행 중…' : '다시 검색'}
                  </button>
                  <button
                    type="button"
                    className={styles.danger}
                    disabled={busyId === itemId}
                    onClick={() => void onDelete(item)}
                    data-testid="saved-delete"
                  >
                    삭제
                  </button>
                </div>
                {rerun?.id === itemId ? (
                  <div className={styles.panel} data-testid="saved-rerun-result">
                    <p className={styles.panelTitle}>다시 검색 결과</p>
                    <OutcomeView outcome={rerun.outcome} />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}

      {hasMore ? (
        <button
          type="button"
          className={styles.more}
          onClick={() => void loadMore()}
          disabled={status === 'loadingMore'}
          data-testid="saved-more"
        >
          더 보기
        </button>
      ) : null}
    </section>
  );
}
