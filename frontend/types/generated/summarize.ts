/* Curated from shared/dtos/summarization.schema.json (SSOT — established 2026-06-22,
 * FR-17 / FD §8). Producer: U7 Summarization. Consumer: U7/U5 frontend. SEC-9: only the
 * fields below are exposed (no tokens/cost/cache-key/model id; assets expose a signed url
 * only — never object_ref). Run `pnpm gen:types` to refresh the raw schema dump under
 * types/.schema-raw/ for drift review. */

import type { DocModel } from './docModel';

export type SummarizeTask = 'summary' | 'translate';
/** translate only; summary is fixed `full`. */
export type SummarizeScope = 'abstract' | 'full';
/** summary only; translation is single (no persona). */
export type Persona = 'expert' | 'beginner';

/** Request to POST /api/summarize. paperId = ResultCardVM.arxivId, version = 1 (Q8=A). */
export interface SummarizeRequest {
  task: SummarizeTask;
  paperId: string;
  version: number;
  scope?: SummarizeScope;
  persona?: Persona;
  targetLang?: 'ko';
  abstract?: string;
}

/** Per-claim grounding anchor (§3). Drives "출처 보기" → full-text highlight (Q5=C). */
export interface AnchorVM {
  field: string;
  target: 'section' | 'table' | 'figure';
  span: string;
  label: string;
}

export interface ReproducibilityVM {
  code: string;
  data: string;
}

/** Structured summary — the 6 persona-driven fields + grounding anchors (§3). */
export interface SummaryVM {
  tldr: string;
  contributions: string[];
  method: string;
  results: string;
  limitations: string;
  reproducibility: ReproducibilityVM;
  anchors: AnchorVM[];
}

/** Structured Korean translation as a "translated doc-model" mirroring the source structure
 * (FR-13): section titles, paragraphs, list items, and table/figure captions are translated,
 * while structural/verbatim fields (block & section ids, formula LaTeX, table numeric cells,
 * figure assetRefs) are copied from the source unchanged. Block/section ids mirror the source
 * doc-model so it renders with the SAME rich viewer as the original body. keptTerms = terms
 * kept untranslated; standardGlossary = DocSuri standard (shared-seed) terms present in THIS
 * paper — see StandardGlossaryItem. */
export interface TranslationVM {
  docModel: DocModel;
  keptTerms: string[];
  standardGlossary?: StandardGlossaryItem[];
}

/** A DocSuri standard glossary term present in the paper (shared seed). Both kinds are editable as
 * strong overrides. `translated` is set only for mapping terms (e.g. attention→어텐션), where it
 * pre-fills the editor; when absent the term is a keep-as-is standard term (kept in English). */
export interface StandardGlossaryItem {
  term: string;
  translated?: string;
}

/** Honest source note (e.g. abstract-based fallback). Internal — no sensitive fields. */
export interface SummaryMeta {
  source?: string;
  fallback?: string;
}

// ---- Response union (status-discriminated; mirrors backend to_dict / SEC-9) ----

export interface SummaryOkDTO {
  status: 'ok';
  task: 'summary';
  meta: SummaryMeta;
  cached: boolean;
  summary: SummaryVM;
}

export interface TranslationOkDTO {
  status: 'ok';
  task: 'translate';
  meta: SummaryMeta;
  cached: boolean;
  translation: TranslationVM;
  scope?: SummarizeScope;
}

/** Long summary running as a background job (BR-S6/BR-S8): client polls again after the hint. */
export interface SummaryPendingDTO {
  status: 'pending';
  retryAfterMs?: number;
}

export interface SummaryAbstainDTO {
  status: 'abstain';
  reason: unknown;
}

export interface CostDegradedDTO {
  status: 'cost_degraded';
  message: string;
}

export interface SourceUnavailableDTO {
  status: 'source_unavailable';
  reason: unknown;
}

/** Gap #2: validation failure carries a non-technical `message` (→ "check your input").
 * Named distinctly from search's ValidationErrorDTO (status-discriminated here). */
export interface SummarizeValidationErrorDTO {
  status: 'validation_error';
  field?: string;
  message: string;
}

/** Gap #3: auth required (401). */
export interface UnauthorizedDTO {
  status: 'unauthorized';
}

export type SummarizeResponseDTO =
  | SummaryOkDTO
  | TranslationOkDTO
  | SummaryPendingDTO
  | SummaryAbstainDTO
  | CostDegradedDTO
  | SourceUnavailableDTO
  | SummarizeValidationErrorDTO
  | UnauthorizedDTO;

// ---- Figure/table assets (FR-17, display-only) ----

/** A single figure/table for the detail/viewer. SEC-9: `url` is a short-lived signed URL;
 * the S3 object_ref / internal manifest fields are NEVER exposed. Produced by U1, presigned
 * by U7. Anchors (AnchorVM.target = figure|table) link by matching label/caption + ordinal. */
export interface AssetRef {
  assetId: string;
  type: 'figure' | 'table';
  ordinal: number;
  caption: string;
  sourceMode: 'structured' | 'page-crop';
  url: string;
  pageRef?: number | null;
  bbox?: number[] | null;
}

export interface AssetsOkDTO {
  status: 'ok';
  assets: AssetRef[];
}

/** OA license not permitted (or assets not configured) → no assets shown (BR-SF-11). */
export interface AssetsLicenseUnavailableDTO {
  status: 'license_unavailable';
}

export type PaperAssetsResponseDTO = AssetsOkDTO | AssetsLicenseUnavailableDTO | UnauthorizedDTO;
