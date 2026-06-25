'use client';

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import styles from './SearchScreen.module.css';
import {
  clearSearchSnapshot,
  getSearchSnapshot,
  setSearchSnapshot,
  type SearchSort,
} from '@/lib/search/searchCache';
import { StateView } from './StateView';
import { ResultList } from './ResultList';
import { SaveToLibraryButton } from './SaveToLibraryButton';
import { SaveSearchButton } from './SaveSearchButton';
import { getApiClient, UserFacingError, type SearchOutcome } from '@/lib/api';
import { validateQuery, MAX_QUERY_LENGTH } from '@/lib/api/validate';
import { recordSearchExecuted } from '@/lib/personalization';
import type { ResultCardVM } from '@/types/generated';

// Per-card save control (US-L2/S1, Q2=A): a bookmark icon on the card's top-right.
const renderBookmark = (card: ResultCardVM) => <SaveToLibraryButton card={card} />;

// Result sort (client-side, over the received top-N): relevance = the ranking order
// U2 returned (PBT-03); recent = publication year desc. This only re-orders what was
// returned — it does not re-query the corpus.
type SortKey = SearchSort;

function sortCards(cards: ResultCardVM[], sort: SortKey): ResultCardVM[] {
  if (sort !== 'recent') return cards;
  // Decorate-sort-undecorate keeps it stable: received order breaks year ties and
  // keeps missing-year cards in their original relative position.
  return cards
    .map((c, i) => [c, i] as const)
    .sort(([a, ai], [b, bi]) => (b.year ?? 0) - (a.year ?? 0) || ai - bi)
    .map(([c]) => c);
}

// SearchScreen (LC-1/6, US-H1/D1, FR-1/11) — the hero surface. Owns the search
// state machine and branches the SearchResponse union. Single request/response
// with in-flight lock (NFR-P1, BR-U5-18). Client validation is a UX aid; the
// backend ValidationErrorDTO is also honored (BR-U5-3).

type ScreenState =
  | { tag: 'idle' }
  | { tag: 'loading' }
  | { tag: 'outcome'; outcome: SearchOutcome }
  | { tag: 'error'; message: string };

export function SearchScreen() {
  const router = useRouter();
  // Restore the last in-session search (set when navigating away to a paper detail). A fresh
  // page load has no snapshot → starts idle, so SSR and first client render agree.
  const [query, setQuery] = useState(() => getSearchSnapshot()?.query ?? '');
  const [state, setState] = useState<ScreenState>(() => {
    const snap = getSearchSnapshot();
    return snap ? { tag: 'outcome', outcome: snap.outcome } : { tag: 'idle' };
  });
  const [executedQuery, setExecutedQuery] = useState<string | null>(
    () => getSearchSnapshot()?.executedQuery ?? null,
  );
  const [inlineError, setInlineError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey>(() => getSearchSnapshot()?.sort ?? 'relevance');
  const inFlight = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();

  // Keep the snapshot in sync with the visible results/sort so a later back-navigation restores
  // exactly what's on screen now (see searchCache).
  useEffect(() => {
    if (state.tag === 'outcome' && executedQuery) {
      // Restore the executed query (not the live input), so a back-navigation shows an input
      // that matches the results even if the user edited the box without re-searching.
      setSearchSnapshot({ query: executedQuery, executedQuery, outcome: state.outcome, sort });
    }
  }, [state, executedQuery, sort]);

  const clearQuery = useCallback(() => {
    // ✕ dismisses the whole search — input, results, sort, and the saved snapshot — so a later
    // back-navigation starts blank. (Leaving the tab/site likewise drops the in-memory snapshot.)
    setQuery('');
    setInlineError(null);
    setExecutedQuery(null);
    setSort('relevance');
    setState({ tag: 'idle' });
    clearSearchSnapshot();
    inputRef.current?.focus();
  }, []);

  const runSearch = useCallback(async () => {
    if (inFlight.current) return;
    const result = validateQuery(query);
    if (!result.ok) {
      setInlineError(result.message);
      return;
    }
    setInlineError(null);
    inFlight.current = true;
    setState({ tag: 'loading' });
    try {
      const outcome = await getApiClient().search(result.value);
      setExecutedQuery(result.value);
      if (outcome.kind === 'invalid') {
        setInlineError(outcome.message);
      } else {
        setInlineError(null);
      }
      setState({ tag: 'outcome', outcome });
      recordSearchExecuted(result.value, resultCount(outcome));
    } catch (err) {
      if (err instanceof UserFacingError && err.isAuth) {
        router.push('/login?redirect=/search');
        return;
      }
      const message = err instanceof UserFacingError ? err.message : '문제가 발생했습니다. 다시 시도해 주세요.';
      setState({ tag: 'error', message });
    } finally {
      inFlight.current = false;
    }
  }, [query, router]);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    void runSearch();
  };

  const cards =
    state.tag === 'outcome' && (state.outcome.kind === 'page' || state.outcome.kind === 'degraded')
      ? state.outcome.cards
      : null;

  return (
    <div className={styles.root}>
      <form className={styles.form} onSubmit={onSubmit} data-testid="search-form" role="search">
        <div className={styles.row}>
          <div className={styles.inputWrap}>
            <input
              ref={inputRef}
              id={inputId}
              className={styles.input}
              type="text"
              aria-label="논문 검색"
              value={query}
              maxLength={MAX_QUERY_LENGTH}
              placeholder="무엇이 궁금한가요?"
              spellCheck={false}
              autoCapitalize="none"
              autoCorrect="off"
              onChange={(e) => setQuery(e.target.value)}
              aria-invalid={inlineError ? true : undefined}
              aria-describedby={inlineError ? `${inputId}-err` : undefined}
              data-testid="search-input"
            />
            <button
              type="button"
              className={styles.clear}
              onClick={clearQuery}
              disabled={!query}
              aria-hidden={query ? undefined : true}
              aria-label="검색어 지우기"
              data-testid="search-clear"
            >
              ✕
            </button>
          </div>
          <button
            type="submit"
            className={styles.submit}
            disabled={state.tag === 'loading'}
            data-testid="search-submit"
          >
            검색
          </button>
        </div>
        {inlineError ? (
          <p id={`${inputId}-err`} className={styles.inlineError} role="alert" data-testid="search-inline-error">
            {inlineError}
          </p>
        ) : null}
      </form>

      {state.tag === 'outcome' && executedQuery ? (
        <div className={styles.toolbar} data-testid="search-actions">
          <SaveSearchButton key={executedQuery} query={executedQuery} />
          {cards && cards.length > 0 ? <SortControl sort={sort} onChange={setSort} /> : null}
        </div>
      ) : null}

      <div className={styles.results} aria-live="polite">
        {renderState(state, sort, () => void runSearch())}
      </div>
    </div>
  );
}

function resultCount(outcome: SearchOutcome): number {
  if (outcome.kind === 'page' || outcome.kind === 'degraded') {
    return outcome.meta.resultCount ?? outcome.cards.length;
  }
  return 0;
}

function SortControl({ sort, onChange }: { sort: SortKey; onChange: (s: SortKey) => void }) {
  const options: [SortKey, string][] = [
    ['relevance', '관련도순'],
    ['recent', '최신순'],
  ];
  return (
    <div className={styles.sort} role="group" aria-label="결과 정렬" data-testid="result-sort">
      {options.map(([key, label]) => (
        <button
          key={key}
          type="button"
          className={styles.sortOption}
          data-active={sort === key}
          aria-pressed={sort === key}
          onClick={() => onChange(key)}
          data-testid={`result-sort-${key}`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function renderState(state: ScreenState, sort: SortKey, onRetry: () => void) {
  if (state.tag === 'idle') return null;
  if (state.tag === 'loading') return <StateView kind="loading" />;
  if (state.tag === 'error') return <StateView kind="error" message={state.message} onRetry={onRetry} />;

  const { outcome } = state;
  switch (outcome.kind) {
    case 'page':
      return <ResultList cards={sortCards(outcome.cards, sort)} renderBookmark={renderBookmark} />;
    case 'degraded':
      return <ResultList cards={sortCards(outcome.cards, sort)} degraded renderBookmark={renderBookmark} />;
    case 'empty':
      return <StateView kind="empty" />;
    case 'abstain':
      return <StateView kind="abstain" />;
    case 'invalid':
      return <StateView kind="invalid" message={outcome.message} field={outcome.field} />;
    default: {
      const _exhaustive: never = outcome;
      return _exhaustive;
    }
  }
}
