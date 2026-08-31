import type { SearchOutcome } from '@/lib/api';

// Session-scoped search snapshot (US-H1/D1). Held at module scope so it survives client-side
// navigation within the tab (the JS module stays loaded): going to a paper detail and pressing
// back restores the exact result list + sort + input without a re-query. It is intentionally
// NOT persisted — a full reload or a new tab starts blank — and is cleared when the user clears
// the search box (✕), matching how a search is expected to "stick" until explicitly dropped.
//
// No hydration risk: a fresh page load gets a fresh module (snapshot === null), so SSR and the
// first client render agree; the snapshot only ever exists after a client-side search.

export type SearchSort = 'relevance' | 'recent';

export interface SearchSnapshot {
  query: string;
  executedQuery: string;
  outcome: SearchOutcome;
  sort: SearchSort;
  /**
   * 떠날 때 보고 있던 스크롤 위치. 결과 목록만 되살리고 이것을 빼면 화면은 복원되는데
   * 스크롤만 0이 되어, 스무 번째 카드를 눌렀다 돌아온 사람이 매번 맨 위에서 다시 내려와야
   * 한다. 목록과 함께 저장돼야 "누르기 직전 그대로"가 성립한다.
   */
  scrollY: number;
}

let snapshot: SearchSnapshot | null = null;

export function getSearchSnapshot(): SearchSnapshot | null {
  return snapshot;
}

/**
 * 결과·정렬·입력을 갱신한다. 스크롤 위치는 **덮지 않는다** — 이 함수는 화면이 그려질 때마다
 * 불리는데 여기서 0으로 되돌리면 떠나기 직전에 적어 둔 위치가 매번 지워진다. 다만 실행한
 * 질의가 바뀌면(= 새 검색) 위치를 버린다: 새 결과는 맨 위에서 시작하는 것이 맞다.
 */
export function setSearchSnapshot(next: Omit<SearchSnapshot, 'scrollY'>): void {
  const carried = snapshot?.executedQuery === next.executedQuery ? snapshot.scrollY : 0;
  snapshot = { ...next, scrollY: carried };
}

/** 현재 스크롤 위치만 갱신한다(스냅샷이 없으면 무시). */
export function setSearchScrollY(scrollY: number): void {
  if (snapshot) snapshot = { ...snapshot, scrollY };
}

export function clearSearchSnapshot(): void {
  snapshot = null;
}
