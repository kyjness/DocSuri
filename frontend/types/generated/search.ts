/* Curated from shared/dtos/search.schema.json (exposed contract). Run `pnpm gen:types`
 * to refresh the raw schema dump under types/.schema-raw/ for drift review.
 * Producer: U2 Discovery. Consumer: U5. SEC-9: only the fields below are exposed. */

/**
 * Degradation/fallback mode hint (e.g. lexical-only fallback when the cost
 * circuit is OPEN). Internal hint — NOT surfaced verbatim to the user (SEC-9).
 */
export type DegradationMode = string;

/** Single-paper phone card view-model — external-exposure fields (FR-4);
 * Phase 2 adds source-neutral sourceName/sourceUrl for the multi-source corpus (Q2). */
export interface ResultCardVM {
  title: string;
  authors: string[];
  year: number;
  arxivId: string;
  abstractSnippet: string;
  /** Display-only relevance (ranking order / grade). Raw scores NOT exposed (SEC-9). */
  relevance: unknown;
  arxivUrl: string;
  /** Phase 2 (Q2). Source label (arXiv / Semantic Scholar / OpenAlex). Optional, additive. */
  sourceName?: string;
  /** Phase 2 (Q2). Source-neutral resolvable link (arXiv=arxivUrl, non-arXiv=sourceUrl/DOI). */
  sourceUrl?: string;
}

/** Result-count and degradation banner hints. */
export interface ResultMeta {
  resultCount: number;
  degraded: boolean;
  degradationMode?: DegradationMode;
  /** US-P4 (#155). True when the personalization re-rank actually boosted this page
   * ('내 관심 주제 반영' indicator + settings off entry point). Optional, additive. */
  personalized?: boolean;
}

/** Synchronous search entry input. */
export interface SearchRequest {
  query: string;
  options?: unknown;
}

/** Successful search response: order-preserving top-N card page (FR-3). */
export interface SearchResultPageDTO {
  cards: ResultCardVM[];
  meta: ResultMeta;
}

/** Grounding abstain / out-of-corpus response — non-technical, NO fabricated results. */
export interface AbstainDTO {
  reason: unknown;
}

/** Partial / lexical-only fallback results returned WITH explicit degradation. */
export interface DegradedResultDTO {
  cards: ResultCardVM[];
  meta: ResultMeta;
  mode: DegradationMode;
}

/** FR-1/SEC-5 validation failure inline error (non-technical, fail-closed). */
export interface ValidationErrorDTO {
  field?: string;
  message: string;
}

/** Terminal-state union returned by U2 and branched by the U5 ApiClient (FR-11). */
export type SearchResponse =
  | SearchResultPageDTO
  | AbstainDTO
  | DegradedResultDTO
  | ValidationErrorDTO;
