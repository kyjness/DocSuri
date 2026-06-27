'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { getApiClient } from '@/lib/api';
import { usePaginatedList } from '@/lib/usePaginatedList';
import { cardFromMeta } from '@/lib/library/cardFromMeta';
import { useSavedLibrary } from '@/lib/library/savedLibrary';
import { ResultCard } from '../ResultCard';
import { StateView } from '../StateView';
import styles from './MyPageScreen.module.css';
import type { LibraryItemDTO } from '@/types/generated';
import type { RecentlyViewedItemVM } from '@/types/mypage';

// MyPageLibraryScreen (U10) — 관심 논문(U4 library, real)과 최근 본 논문(U9, mock until the
// paper_opened 이벤트가 머지됨)을 상단 탭으로 묶은 화면. "저장한 검색"/"검색 이력"(U4)은 별도
// 기능이라 탭으로 합치지 않고, 관심 탭에서 /library로 빠져나가는 링크만 둔다.

type Tab = 'interest' | 'recent';

function LibraryTabsNav({ active }: { active: Tab }) {
  return (
    <nav className={styles.tabs} aria-label="관심 논문 메뉴">
      <Link
        href="/mypage/library"
        className={`${styles.tab} ${active === 'interest' ? styles.tabActive : ''}`}
        aria-current={active === 'interest' ? 'page' : undefined}
        data-testid="mypage-library-tab-interest"
      >
        관심
      </Link>
      <Link
        href="/mypage/library/recent"
        className={`${styles.tab} ${active === 'recent' ? styles.tabActive : ''}`}
        aria-current={active === 'recent' ? 'page' : undefined}
        data-testid="mypage-library-tab-recent"
      >
        최근 본
      </Link>
    </nav>
  );
}

function InterestTab() {
  const fetchPage = useCallback((cursor?: string) => getApiClient().listLibrary({ cursor }), []);
  const { items, status, error, hasMore, loadMore, reload, removeLocal } =
    usePaginatedList<LibraryItemDTO>(fetchPage);
  const savedLibrary = useSavedLibrary();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const onRemove = async (item: LibraryItemDTO) => {
    const itemId = String(item.id);
    setBusyId(itemId);
    setActionError(null);
    try {
      await getApiClient().removeFromLibrary(itemId);
      removeLocal((it) => String(it.id) === itemId);
      savedLibrary.markRemoved(item.arXivId);
    } catch {
      setActionError('제거하지 못했습니다. 다시 시도해 주세요.');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      <Link href="/library" className={styles.more} data-testid="mypage-library-saved-history">
        저장한 검색 · 검색 이력 보기
      </Link>

      {status === 'loading' ? <StateView kind="loading" /> : null}
      {status === 'error' ? (
        <StateView kind="error" message={error ?? undefined} onRetry={() => void reload()} />
      ) : null}
      {status !== 'loading' && status !== 'error' && items.length === 0 ? (
        <StateView kind="empty" message="아직 관심 논문이 없습니다. 검색 결과에서 논문을 담아보세요." />
      ) : null}

      {actionError ? (
        <p className={styles.error} role="alert" data-testid="mypage-library-action-error">
          {actionError}
        </p>
      ) : null}

      {items.length > 0 ? (
        <ul className={styles.plainList}>
          {items.map((item) => (
            <li key={String(item.id)} data-testid="mypage-library-item">
              <ResultCard
                card={cardFromMeta(item.meta)}
                action={
                  <button
                    type="button"
                    className={styles.danger}
                    disabled={busyId === String(item.id)}
                    onClick={() => void onRemove(item)}
                    data-testid="mypage-library-remove"
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
          className={styles.action}
          onClick={() => void loadMore()}
          disabled={status === 'loadingMore'}
          data-testid="mypage-library-more"
        >
          더 보기
        </button>
      ) : null}
    </>
  );
}

function RecentTab() {
  const [items, setItems] = useState<RecentlyViewedItemVM[] | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');

  const load = useCallback(async () => {
    setStatus('loading');
    try {
      const recentlyViewed = await getApiClient().getRecentlyViewed();
      setItems(recentlyViewed);
      setStatus('ready');
    } catch {
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (status === 'loading') return <StateView kind="loading" />;
  if (status === 'error') return <StateView kind="error" onRetry={() => void load()} />;
  if (!items || items.length === 0) {
    return <StateView kind="empty" message="최근 본 논문이 없습니다." />;
  }

  return (
    <ul className={styles.plainList} data-testid="mypage-recent-list">
      {items.map((item) => (
        <li key={item.arxivId} data-testid="mypage-recent-item">
          <Link href={`/paper/${encodeURIComponent(item.arxivId)}`}>{item.title}</Link>
          <p className={styles.muted}>{new Date(item.viewedAt).toLocaleDateString('ko-KR')}</p>
        </li>
      ))}
    </ul>
  );
}

export function MyPageLibraryScreen({ active }: { active: Tab }) {
  return (
    <section className={styles.screen} data-testid="mypage-library-screen">
      <LibraryTabsNav active={active} />
      {active === 'interest' ? <InterestTab /> : <RecentTab />}
    </section>
  );
}
