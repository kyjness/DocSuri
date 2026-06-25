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
}

let snapshot: SearchSnapshot | null = null;

export function getSearchSnapshot(): SearchSnapshot | null {
  return snapshot;
}

export function setSearchSnapshot(next: SearchSnapshot): void {
  snapshot = next;
}

export function clearSearchSnapshot(): void {
  snapshot = null;
}
