// PaperMetaVM — hand-authored view model for paper header metadata
// (title/authors/year/abstract) shown on the detail route.
//
// Hand-authored, NOT codegen'd (yet): the backend endpoint exists — discovery (U2)
// GET /api/papers/{id} — and this mirrors its PaperMetaDTO 1:1. It stays hand-authored until
// the contract is promoted to a shared schema (shared/dtos) and regenerated; at that point
// replace this with the generated type.
export interface PaperMetaVM {
  arxivId: string;
  title: string;
  authors: string[];
  year?: number;
  abstract: string;
  /** Canonical arXiv abstract page; rendered as a safe external link-out. */
  arxivUrl?: string;
  /** Phase 2 (Q2). Discovery source label (arXiv / Semantic Scholar / OpenAlex) — agrees with
   * the search card. Optional/additive. */
  sourceName?: string;
  /** Phase 2 (Q2). Source-neutral resolvable link-out (arXiv=arxivUrl, non-arXiv=sourceUrl/DOI). */
  sourceUrl?: string;
}
