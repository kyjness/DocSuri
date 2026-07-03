'use client';

import { useCallback, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { getApiClient, UserFacingError, type SearchOutcome } from '@/lib/api';
import { usePaginatedList } from '@/lib/usePaginatedList';
import { StateView } from '../StateView';
import { LibraryTabs } from './LibraryTabs';
import { OutcomeView } from './OutcomeView';
import type { HistoryEntry } from '@/types/generated';
import styles from './Library.module.css';

// HistoryScreen (US-L3, FR-10) — recent searches (async-recorded). Rerun renders
// the live result inline; "이력 비우기" clears all (BR-U5). Cursor "더 보기".
export function HistoryScreen({ showTabs = true }: { showTabs?: boolean } = {}) {
  const router = useRouter();
  const pathname = usePathname();
  const fetchPage = useCallback((cursor?: string) => getApiClient().listHistory({ cursor }), []);
  const { items, status, error, hasMore, loadMore, reload } =
    usePaginatedList<HistoryEntry>(fetchPage);

  const [rerunId, setRerunId] = useState<string | null>(null);
  const [rerun, setRerun] = useState<{ id: string; outcome: SearchOutcome } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  const onRerun = async (item: HistoryEntry) => {
    const itemId = String(item.id);
    setRerunId(itemId);
    setActionError(null);
    try {
      const outcome = await getApiClient().rerunHistory(itemId);
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

  const onClear = async () => {
    if (clearing) return;
    setClearing(true);
    setActionError(null);
    try {
      await getApiClient().clearHistory();
      setRerun(null);
      await reload();
    } catch (e) {
      if (e instanceof UserFacingError && e.isAuth) {
        router.push(`/login?redirect=${encodeURIComponent(pathname)}`);
        return;
      }
      setActionError('이력을 비우지 못했습니다. 다시 시도해 주세요.');
    } finally {
      setClearing(false);
    }
  };

  return (
    <section className={styles.screen} data-testid="history-screen">
      {showTabs ? <LibraryTabs active="history" /> : null}

      {items.length > 0 ? (
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.danger}
            onClick={() => void onClear()}
            disabled={clearing}
            data-testid="history-clear"
          >
            이력 비우기
          </button>
        </div>
      ) : null}

      {status === 'loading' ? <StateView kind="loading" /> : null}
      {status === 'error' ? (
        <StateView kind="error" message={error ?? undefined} onRetry={() => void reload()} />
      ) : null}
      {status !== 'loading' && status !== 'error' && items.length === 0 ? (
        <StateView kind="empty" message="검색 이력이 없습니다." />
      ) : null}

      {actionError ? (
        <p className={styles.panelTitle} role="alert" data-testid="history-action-error">
          {actionError}
        </p>
      ) : null}

      {items.length > 0 ? (
        <ul className={styles.list}>
          {items.map((item) => {
            const itemId = String(item.id);
            return (
              <li key={itemId} className={styles.row} data-testid="history-item">
                <span className={styles.rowQuery} data-testid="history-query">
                  {item.query}
                </span>
                <span className={styles.rowMeta}>
                  <span data-testid="history-count">{item.resultCount}건</span>
                  <span aria-hidden="true">·</span>
                  <span>{new Date(item.executedAt).toLocaleString('ko-KR')}</span>
                </span>
                <div className={styles.actions}>
                  <button
                    type="button"
                    className={styles.action}
                    disabled={rerunId === itemId}
                    onClick={() => void onRerun(item)}
                    data-testid="history-rerun"
                  >
                    {rerunId === itemId ? '실행 중…' : '다시 검색'}
                  </button>
                </div>
                {rerun?.id === itemId ? (
                  <div className={styles.panel} data-testid="history-rerun-result">
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
          data-testid="history-more"
        >
          더 보기
        </button>
      ) : null}
    </section>
  );
}
