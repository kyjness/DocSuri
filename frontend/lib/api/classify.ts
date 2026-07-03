// Structural classification of the SearchResponse union (FR-11, BR-U5-9).
//
// The union has no discriminant field, so we classify by structure. Because the
// DTOs are additionalProperties:false, the shapes are unambiguous:
//   - { reason }                 -> abstain
//   - { cards, meta, mode }      -> degraded
//   - { cards, meta }            -> page (empty when meta.resultCount === 0)
//   - { message }                -> invalid (ValidationErrorDTO)
import type { ResultCardVM, ResultMeta } from '@/types/generated';

export type SearchOutcome =
  | { kind: 'page'; cards: ResultCardVM[]; meta: ResultMeta }
  | { kind: 'empty'; meta: ResultMeta }
  | { kind: 'abstain'; reason: unknown }
  | { kind: 'degraded'; cards: ResultCardVM[]; meta: ResultMeta; mode: unknown }
  | { kind: 'invalid'; field?: string; message: string };

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null;
}

export function classifySearchResponse(body: unknown): SearchOutcome {
  if (!isRecord(body)) {
    return { kind: 'invalid', message: '검색 결과를 해석할 수 없습니다.' };
  }
  if ('reason' in body) {
    return { kind: 'abstain', reason: body.reason };
  }
  if ('cards' in body && 'meta' in body && 'mode' in body) {
    return {
      kind: 'degraded',
      cards: body.cards as ResultCardVM[],
      meta: body.meta as ResultMeta,
      mode: body.mode,
    };
  }
  if ('cards' in body && 'meta' in body) {
    const meta = body.meta as ResultMeta;
    if (!meta || meta.resultCount === 0) {
      return { kind: 'empty', meta: meta ?? { resultCount: 0, degraded: false } };
    }
    if (meta.degraded === true) {
      // E5 (BR-U5-8/12): a page-shaped body can signal degraded via meta.degraded without a
      // top-level `mode` key. The check above (top-level `mode` present) only caught the case
      // where the backend ALSO sent `mode`; this catches the meta-only signal so it still
      // resolves to the same 'degraded' outcome instead of silently falling through as 'page'.
      return { kind: 'degraded', cards: body.cards as ResultCardVM[], meta, mode: undefined };
    }
    return { kind: 'page', cards: body.cards as ResultCardVM[], meta };
  }
  if ('message' in body) {
    return {
      kind: 'invalid',
      field: typeof body.field === 'string' ? body.field : undefined,
      message: typeof body.message === 'string' ? body.message : '입력을 확인해 주세요.',
    };
  }
  return { kind: 'invalid', message: '검색 결과를 해석할 수 없습니다.' };
}
