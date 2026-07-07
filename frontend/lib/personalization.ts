import { getApiClient } from '@/lib/api';
import type { AnchorVM, Persona, SummarizeScope } from '@/types/generated';
import type { BehaviorEventCreate } from '@/types/personalization';

const DEDUPE_BUCKET_MS = 30_000;

function dedupeBucket(): number {
  return Math.floor(Date.now() / DEDUPE_BUCKET_MS);
}

function paperVersionKey(paperId: string, version: number): string {
  return `${paperId}:v${version}`;
}

export function hashQuery(query: string): string {
  let hash = 0x811c9dc5;
  for (const ch of query.trim().toLowerCase()) {
    hash ^= ch.charCodeAt(0);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, '0');
}

function sendBehaviorEvent(event: BehaviorEventCreate): void {
  void getApiClient()
    .recordBehaviorEvent(event)
    .catch(() => undefined);
}

export function recordSearchExecuted(query: string, resultCount: number): void {
  const queryHash = hashQuery(query);
  sendBehaviorEvent({
    eventType: 'search_executed',
    subject: { kind: 'search', queryHash },
    source: 'frontend_anchor',
    metadata: { resultCount },
    dedupeKey: `search:${queryHash}:${dedupeBucket()}`,
  });
}

export function recordPaperOpened(paperId: string, version: number): void {
  sendBehaviorEvent({
    eventType: 'paper_opened',
    subject: { kind: 'paper', paperId },
    source: 'frontend_anchor',
    metadata: { entrySurface: 'detail' },
    dedupeKey: `paper:${paperVersionKey(paperId, version)}:${dedupeBucket()}`,
  });
}

// 완독 (read-completion, #346): fired once per open when the reader scrolls to the end of the
// doc-model body. Pairs with recordPaperOpened so the dashboard's 완독률 = read_completed / paper_opened.
export function recordReadCompleted(paperId: string, version: number): void {
  sendBehaviorEvent({
    eventType: 'read_completed',
    subject: { kind: 'paper', paperId },
    source: 'frontend_anchor',
    metadata: { entrySurface: 'detail' },
    dedupeKey: `read:${paperVersionKey(paperId, version)}:${dedupeBucket()}`,
  });
}

export function recordLibraryAdded(paperId: string): void {
  sendBehaviorEvent({
    eventType: 'library_added',
    subject: { kind: 'paper', paperId },
    source: 'frontend_anchor',
    metadata: { savedSource: 'library' },
    dedupeKey: `library:add:${paperId}:${dedupeBucket()}`,
  });
}

export function recordLibraryRemoved(paperId: string): void {
  sendBehaviorEvent({
    eventType: 'library_removed',
    subject: { kind: 'paper', paperId },
    source: 'frontend_anchor',
    metadata: {},
    dedupeKey: `library:remove:${paperId}:${dedupeBucket()}`,
  });
}

export function recordSummaryRequest(
  paperId: string,
  mode: 'summary' | 'translation',
  options: { persona?: Persona; scope?: SummarizeScope } = {},
): void {
  sendBehaviorEvent({
    eventType: 'summary_translation_requested',
    subject: { kind: mode === 'summary' ? 'summary' : 'translation', paperId },
    source: 'frontend_anchor',
    metadata: {
      mode,
      ...(options.persona ? { selectedPersona: options.persona } : {}),
      ...(options.scope ? { translationScope: options.scope } : {}),
    },
    dedupeKey: `${mode}:${paperId}:${options.persona ?? options.scope ?? 'default'}:${dedupeBucket()}`,
  });
}

export function recordSourceAnchorClicked(paperId: string, anchor: AnchorVM): void {
  sendBehaviorEvent({
    eventType: 'source_anchor_clicked',
    subject: { kind: 'source_anchor', paperId, anchorId: anchor.field },
    source: 'frontend_anchor',
    metadata: { anchorId: anchor.field, sectionKind: anchor.target },
    dedupeKey: `anchor:${paperId}:${anchor.field}:${dedupeBucket()}`,
  });
}

export function recordGlossaryUpdated(glossaryVersion: number): void {
  sendBehaviorEvent({
    eventType: 'glossary_updated',
    subject: { kind: 'glossary' },
    source: 'frontend_anchor',
    metadata: { glossaryVersion },
    dedupeKey: `glossary:${glossaryVersion}:${dedupeBucket()}`,
  });
}
