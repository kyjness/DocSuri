// Personal glossary — hand-authored view/transport types for the Phase 1
// "badge-tap → add my term" flow. Mirrors the backend POST /api/glossary contract
// 1:1. Hand-authored, NOT codegen'd (like paperMeta.ts): promote to shared/dtos and
// regenerate once the backend glossary contract is finalized.

/** Request to POST /api/glossary. `termFrom` is the kept-as-is English term the user
 * tapped; `termTo` is their preferred Korean rendering. Phase 1 treats it as a simple
 * noun applied to translation via deterministic post-substitution. */
export interface GlossaryTermUpsertDTO {
  termFrom: string;
  termTo: string;
}

/** Result of a successful upsert. `glossaryVer` is the user's bumped glossary version;
 * the bump invalidates their cached summaries/translations server-side so the next
 * request reflects the new term. */
export interface GlossaryUpsertResultDTO {
  status: 'ok';
  glossaryVer: number;
}

/** One saved personal term (GET /api/glossary). Only the two display fields are exposed. */
export interface GlossaryTermDTO {
  termFrom: string;
  termTo: string;
}

/** The caller's saved personal terms — used to pre-fill the badge editor (Phase 2a). */
export interface GlossaryListDTO {
  status: 'ok';
  terms: GlossaryTermDTO[];
}
