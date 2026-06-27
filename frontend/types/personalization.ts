export type BehaviorEventType =
  | 'search_executed'
  | 'paper_opened'
  | 'library_added'
  | 'library_removed'
  | 'summary_translation_requested'
  | 'source_anchor_clicked'
  | 'glossary_updated';

export interface BehaviorSubject {
  kind: 'paper' | 'search' | 'summary' | 'translation' | 'source_anchor' | 'glossary';
  paperId?: string;
  queryHash?: string;
  category?: string;
  anchorId?: string;
}

export interface BehaviorEventCreate {
  eventType: BehaviorEventType;
  subject: BehaviorSubject;
  occurredAt?: string;
  source?: 'backend' | 'frontend_anchor';
  metadata?: Record<string, unknown>;
  dedupeKey: string;
}

export interface EventRecordResult {
  recorded: boolean;
  duplicate: boolean;
  reason: 'recorded' | 'duplicate' | 'disabled' | 'degraded';
}

export interface PersonalizationSettings {
  userId: string;
  enabled: boolean;
  rawEventsDeletedAt?: string | null;
  profileResetAt?: string | null;
  updatedAt: string;
}

export interface DeletePersonalizationEventsResult {
  deletedEvents: number;
}

export interface ResetPersonalizationProfileResult {
  status: 'reset';
}
