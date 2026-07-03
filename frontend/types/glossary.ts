// Personal glossary — hand-authored view/transport types for the Phase 1
// "badge-tap → add my term" flow. Mirrors the backend POST /api/glossary contract
// 1:1. Hand-authored, NOT codegen'd (like paperMeta.ts): promote to shared/dtos and
// regenerate once the backend glossary contract is finalized.

/** Request to POST /api/glossary. `termFrom` is the kept-as-is English term the user
 * tapped; `termTo` is their preferred Korean rendering. `promptEnforced` selects strong
 * (프롬프트 강제 — rides into the prompt, re-generates the full-text translation) vs the
 * default weak (후치환 — read-time overlay on the shared base, no re-generation). */
export interface GlossaryTermUpsertDTO {
  termFrom: string;
  termTo: string;
  /** Strong (강한) when true; omitted/false = weak (약한) post-substitution. */
  promptEnforced?: boolean;
}

/** Result of a successful upsert. `glossaryVer` is the user's bumped glossary version;
 * the bump invalidates their cached summaries/translations server-side so the next
 * request reflects the new term. */
export interface GlossaryUpsertResultDTO {
  status: 'ok';
  glossaryVer: number;
}

/** One saved personal term (GET /api/glossary). `promptEnforced` lets the editor render a
 * saved term as strong (강한) vs weak (약한). */
export interface GlossaryTermDTO {
  termFrom: string;
  termTo: string;
  promptEnforced?: boolean;
}

/** The caller's saved personal terms — used to pre-fill the badge editor (Phase 2a). */
export interface GlossaryListDTO {
  status: 'ok';
  terms: GlossaryTermDTO[];
}
