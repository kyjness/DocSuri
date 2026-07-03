/**
 * Extract the arXiv revision from a paper id. The doc-model / assets / full-text-translation
 * artifacts are keyed (paperId, version), where version is the arXiv revision — e.g.
 * "2304.10557v6" → 6 (the stored doc-model is doc-model/2304.10557/v6.json). A bare id with no
 * explicit revision ("2401.00001") maps to 1 (arXiv's implicit v1).
 *
 * This replaces the previous hardcoded `version = 1`, which made every detail page request the
 * v1 artifact regardless of the paper's actual revision — so any paper whose current doc-model
 * was a later revision (v6) got the stale/older v1 (or a perpetual "building" poll) instead of
 * the real body.
 */
export function arxivVersion(id: string): number {
  const match = /v(\d+)$/.exec(id);
  return match ? Number(match[1]) : 1;
}
