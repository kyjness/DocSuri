'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { getApiClient } from '@/lib/api';
import { usePaginatedList } from '@/lib/usePaginatedList';
import { cardFromMeta } from '@/lib/library/cardFromMeta';
import { useSavedLibrary } from '@/lib/library/savedLibrary';
import { ResultCard } from '../ResultCard';
import { StateView } from '../StateView';
import { HistoryScreen } from '../library/HistoryScreen';
import { SavedSearchScreen } from '../library/SavedSearchScreen';
import styles from './MyPageScreen.module.css';
import type { LibraryItemDTO } from '@/types/generated';
import type { RecentlyViewedItemVM } from '@/types/mypage';

// MyPageLibraryScreen (U10) — 관심 논문(U4 library, real), 최근 본 논문(U9, mock until the
// paper_opened 이벤트가 머지됨), 저장한 검색/검색 이력(U4)을 한 화면의 상단 탭으로 묶는다.

type Tab = 'interest' | 'recent' | 'saved' | 'history';

const TABS: { key: Tab; label: string; testid: string }[] = [
  { key: 'interest', label: '관심 논문', testid: 'mypage-library-tab-interest' },
  { key: 'recent', label: '최근 본 논문', testid: 'mypage-library-tab-recent' },
  { key: 'saved', label: '저장한 검색', testid: 'mypage-library-tab-saved' },
  { key: 'history', label: '검색 이력', testid: 'mypage-library-tab-history' },
];

function LibraryTabsNav({ active, onSelect }: { active: Tab; onSelect: (tab: Tab) => void }) {
  return (
    <nav className={styles.tabs} aria-label="관심 논문 메뉴">
      {TABS.map((tab) => (
        <button
          key={tab.key}
          type="button"
          className={`${styles.tab} ${active === tab.key ? styles.tabActive : ''}`}
          aria-current={active === tab.key ? 'page' : undefined}
          onClick={() => onSelect(tab.key)}
          data-testid={tab.testid}
        >
          {tab.label}
        </button>
      ))}
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
  const [currentTab, setCurrentTab] = useState<Tab>(active);

  return (
    <section className={styles.screen} data-testid="mypage-library-screen">
      <LibraryTabsNav active={currentTab} onSelect={setCurrentTab} />
      {currentTab === 'interest' ? <InterestTab /> : null}
      {currentTab === 'recent' ? <RecentTab /> : null}
      {currentTab === 'saved' ? <SavedSearchScreen showTabs={false} /> : null}
      {currentTab === 'history' ? <HistoryScreen showTabs={false} /> : null}
    </section>
  );
}
