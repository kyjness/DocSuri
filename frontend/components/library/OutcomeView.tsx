'use client';

import { ResultList } from '../ResultList';
import { StateView } from '../StateView';
import { SaveToLibraryButton } from '../SaveToLibraryButton';
import type { SearchOutcome } from '@/lib/api';
import type { ResultCardVM } from '@/types/generated';

// Per-card save control on library rerun results too (US-L2): bookmark top-right.
const renderBookmark = (card: ResultCardVM) => <SaveToLibraryButton card={card} />;

// OutcomeView (US-D7) — renders a classified SearchOutcome (used by saved-search
// and history rerun). Mirrors the search state machine's terminal branches so
// abstain stays distinct from empty (BR-U5-9). Exhaustive over the union.
export function OutcomeView({ outcome }: { outcome: SearchOutcome }) {
  switch (outcome.kind) {
    case 'page':
      return <ResultList cards={outcome.cards} renderBookmark={renderBookmark} />;
    case 'degraded':
      return <ResultList cards={outcome.cards} degraded renderBookmark={renderBookmark} />;
    case 'empty':
      return <StateView kind="empty" />;
    case 'abstain':
      return <StateView kind="abstain" />;
    case 'invalid':
      return <StateView kind="invalid" message={outcome.message} />;
    default: {
      const _exhaustive: never = outcome;
      return _exhaustive;
    }
  }
}
