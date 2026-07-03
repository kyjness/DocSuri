'use client';

// useGlossaryTerms (개인 용어집 Phase 2a) — fetch the user's saved personal terms once as a
// termFrom→termTo map, to pre-fill the badge editor and mark personalized chips. Pre-fill is
// optional, so any failure (network, 401 when anonymous, 503) degrades silently to an empty map.
// `setTerm` keeps the map in sync after a save so reopening a badge shows the just-saved value
// without a refetch. (Strong vs weak is decided by group placement, not stored here.)
import { useCallback, useEffect, useState } from 'react';
import { getApiClient } from '@/lib/api';

export function useGlossaryTerms() {
  const [terms, setTerms] = useState<Record<string, string>>({});

  useEffect(() => {
    let alive = true;
    getApiClient()
      .listGlossaryTerms()
      .then(
        (list) => {
          if (alive) setTerms(Object.fromEntries(list.map((t) => [t.termFrom, t.termTo])));
        },
        () => {
          /* degrade: no pre-fill */
        },
      );
    return () => {
      alive = false;
    };
  }, []);

  const setTerm = useCallback((termFrom: string, termTo: string) => {
    setTerms((prev) => ({ ...prev, [termFrom]: termTo }));
  }, []);

  return { terms, setTerm };
}
