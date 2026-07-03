// ApiClient — single, typed entry point to the backend (LC-2).
//
// All backend access goes through here -> U6 gateway (no direct module calls,
// BR-U5-17). Applies differential retry (idempotent GET only), timeout, and
// in-flight dedup (P-R1, P-P4, BR-U5-18); normalizes failures to UserFacingError.
import type { Transport, TransportRequest, TransportResponse } from './transport';
import { UserFacingError, normalizeHttpError } from './errors';
import { classifySearchResponse, type SearchOutcome } from './classify';
import {
  classifySummarizeResponse,
  classifyDocModelResponse,
  classifyAssetsResponse,
  type SummarizeOutcome,
  type DocModelOutcome,
  type AssetsOutcome,
} from './classifySummarize';
import { recordPath } from '../observability';
import type {
  SummarizeRequest,
  DocModelRequest,
  SearchRequest,
  SignupRequest,
  SignupResult,
  LoginRequest,
  SessionInfo,
  SavedSearchCreateDTO,
  SavedSearchDTO,
  SavedSearchPageDTO,
  LibraryItemCreateDTO,
  LibraryItemDTO,
  LibraryPageDTO,
  HistoryPageDTO,
  SubscriptionDTO,
} from '@/types/generated';
import type { PaperMetaVM } from '@/types/paperMeta';
import type {
  AccountProfileVM,
  ConsentSettingsVM,
  OrcidProfileVM,
  RecentlyViewedItemVM,
} from '@/types/mypage';
import type {
  GlossaryTermUpsertDTO,
  GlossaryUpsertResultDTO,
  GlossaryTermDTO,
  GlossaryListDTO,
} from '@/types/glossary';
import type { CitationNode, CitationTreeQuery, CitationTreeResponse } from '@/types/citationGraph';
import type {
  BehaviorEventCreate,
  DeletePersonalizationEventsResult,
  EventRecordResult,
  PersonalizationSettings,
  ResetPersonalizationProfileResult,
} from '@/types/personalization';
import type {
  AgentMode,
  AgentAttachment,
  AgentAttachmentKind,
  AgentAttachmentStatus,
  AgentJobState,
  AgentMessage,
  AgentSendMessageRequest,
  AgentSendMessageResult,
  AgentSessionSnapshot,
  AgentSessionSummary,
  AgentTimelineEvent,
} from '@/lib/agentChat/types';

export interface ApiClientOptions {
  timeoutMs?: number;
  retryBackoffMs?: number;
}

/** Cursor-based pagination input (U4 collections). No offset/total-count (BR-U5). */
export interface PageQuery {
  limit?: number;
  cursor?: string;
  query?: string;
}

const DEFAULT_PAGE_LIMIT = 20;
const AGENT_ID_SEP = ':';

type BackendResearchJob = {
  jobId: string;
  title: string;
  state: 'active' | 'completed' | 'failed' | 'cancelled';
  updatedAt: string;
};
type BackendResearchMessage = {
  messageId: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  attachments?: unknown[];
  createdAt: string;
};
type BackendNoveltyJob = {
  jobId: string;
  topic: string;
  state: string;
  updatedAt: string;
};
type BackendNoveltyMessage = BackendResearchMessage;
type BackendNoveltyEvent = {
  eventId: string;
  state: string;
  message: string;
  payload?: Record<string, unknown>;
  createdAt: string;
};
type BackendNoveltyArtifact = {
  artifactId: string;
  kind: string;
  title: string;
  payload?: Record<string, unknown>;
  createdAt: string;
};

function encodeAgentSessionId(mode: AgentMode, rawId: string): string {
  return `${mode}${AGENT_ID_SEP}${rawId}`;
}

function parseAgentSessionId(
  id: string,
  fallback: AgentMode = 'evidence',
): { mode: AgentMode; rawId: string } {
  const [mode, rawId] = id.split(AGENT_ID_SEP, 2);
  if ((mode === 'evidence' || mode === 'novelty') && rawId) return { mode, rawId };
  if (id.startsWith('agent-novelty-')) return { mode: 'novelty', rawId: id };
  if (id.startsWith('agent-evidence-')) return { mode: 'evidence', rawId: id };
  return { mode: fallback, rawId: id };
}

function mapResearchJob(job: BackendResearchJob): AgentSessionSummary {
  return {
    id: encodeAgentSessionId('evidence', job.jobId),
    title: job.title,
    mode: 'evidence',
    state: mapResearchState(job.state),
    updatedAt: job.updatedAt,
  };
}

function mapNoveltyJob(job: BackendNoveltyJob): AgentSessionSummary {
  return {
    id: encodeAgentSessionId('novelty', job.jobId),
    title: job.topic,
    mode: 'novelty',
    state: mapNoveltyState(job.state),
    updatedAt: job.updatedAt,
  };
}

function mapResearchState(state: BackendResearchJob['state']): AgentJobState {
  if (state === 'active') return 'running';
  if (state === 'cancelled') return 'failed';
  return state;
}

function mapNoveltyState(state: string): AgentJobState {
  if (state === 'queued') return 'queued';
  if (state === 'completed' || state === 'failed' || state === 'degraded') return state;
  if (state === 'cancelled') return 'failed';
  return 'running';
}

function mapTimelineState(state: AgentJobState): AgentTimelineEvent['state'] {
  if (state === 'failed') return 'failed';
  if (state === 'degraded') return 'degraded';
  if (state === 'completed') return 'completed';
  return 'running';
}

function mapAgentMessage(message: BackendResearchMessage): AgentMessage {
  const role = message.role === 'user' ? 'user' : 'agent';
  return {
    id: message.messageId,
    role,
    content: message.content,
    createdAt: message.createdAt,
    attachments: mapAgentAttachments(message.attachments),
    status: 'sent' as const,
  };
}

function mapAgentAttachments(attachments?: unknown[]): AgentAttachment[] | undefined {
  if (!attachments?.length) return undefined;
  return attachments.map((item, index) => {
    const record = item && typeof item === 'object' ? (item as Record<string, unknown>) : {};
    const name =
      stringValue(record.name) ?? stringValue(record.fileName) ?? stringValue(record.filename);
    const kind = attachmentKind(record.kind, stringValue(record.contentType), name);
    return {
      id: stringValue(record.id) ?? stringValue(record.attachmentId) ?? `attachment-${index}`,
      name: name ?? `첨부 ${index + 1}`,
      kind,
      sizeBytes: numberValue(record.sizeBytes) ?? numberValue(record.size) ?? 0,
      status: attachmentStatus(record.status),
      error: stringValue(record.error),
    };
  });
}

function mapNoveltyEvent(event: BackendNoveltyEvent, index: number): AgentTimelineEvent {
  const state = mapNoveltyState(event.state);
  return {
    id: event.eventId,
    stage: event.state,
    label: event.message,
    detail: timelineDetail(event.payload),
    state: mapTimelineState(state),
    sequence: index + 1,
  };
}

function mapNoveltyResultMessage(
  artifacts: BackendNoveltyArtifact[],
  fallbackCreatedAt: string,
): AgentMessage | null {
  if (artifacts.length === 0) return null;
  return {
    id: `novelty-result-${artifacts.map((artifact) => artifact.artifactId).join('-')}`,
    role: 'agent',
    content: [
      'Novelty 분석 결과',
      ...artifacts.map((artifact) => `- ${artifact.title}: ${artifactSummary(artifact)}`),
    ].join('\n'),
    createdAt: artifacts.at(-1)?.createdAt ?? fallbackCreatedAt,
    status: 'sent',
  };
}

function artifactSummary(artifact: BackendNoveltyArtifact): string {
  const payload = artifact.payload ?? {};
  const count = countFromPayload(payload);
  if (artifact.kind === 'experiment_plan') {
    return [
      stringValue(payload.researchQuestion),
      listValue(payload.hypotheses),
      listValue(payload.datasets),
      listValue(payload.metrics),
      listValue(payload.risks),
    ]
      .filter(Boolean)
      .join(' / ');
  }
  const firstItem = firstItemTitle(payload);
  if (firstItem) return count ? `${firstItem} 외 ${count}건` : firstItem;
  return count ? `${count}건` : '결과 생성됨';
}

function timelineDetail(payload?: Record<string, unknown>): string | undefined {
  if (!payload) return undefined;
  const parts = [
    labeled('소스', payload.source ?? payload.sourceType ?? payload.type),
    labeled('쿼리', payload.query),
    labeled('요약', payload.outputSummary),
    countFromPayload(payload) ? `결과 ${countFromPayload(payload)}건` : undefined,
    safeReason(payload),
  ];
  return parts.filter(Boolean).join(' · ') || undefined;
}

function labeled(label: string, value: unknown): string | undefined {
  const text = stringValue(value);
  return text ? `${label}: ${text}` : undefined;
}

function safeReason(payload: Record<string, unknown>): string | undefined {
  if (hasValue(payload.error)) return '사유: 처리 중 오류가 발생했습니다.';
  if (hasValue(payload.degradedReasons) || hasValue(payload.reason)) {
    return '사유: 일부 연동이 저하되어 가능한 결과만 표시합니다.';
  }
  return undefined;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function hasValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'string') return value.trim().length > 0;
  return value !== null && value !== undefined;
}

function listValue(value: unknown): string | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.map(stringValue).filter(Boolean).slice(0, 2).join(', ') || undefined;
}

function attachmentStatus(value: unknown): AgentAttachmentStatus {
  return value === 'rejected' ? 'rejected' : 'ready';
}

function attachmentKind(value: unknown, contentType?: string, name?: string): AgentAttachmentKind {
  if (value === 'pdf' || value === 'markdown' || value === 'text') return value;
  const lowerName = name?.toLowerCase() ?? '';
  const lowerType = contentType?.toLowerCase() ?? '';
  if (lowerType.includes('pdf') || lowerName.endsWith('.pdf')) return 'pdf';
  if (lowerType.includes('markdown') || lowerName.endsWith('.md')) return 'markdown';
  if (lowerType.includes('text') || lowerName.endsWith('.txt')) return 'text';
  return 'unknown';
}

function countFromPayload(payload: Record<string, unknown>): number | undefined {
  const explicit = payload.count ?? payload.foundCount ?? payload.resultCount;
  if (typeof explicit === 'number') return explicit;
  return Array.isArray(payload.items) ? payload.items.length : undefined;
}

function firstItemTitle(payload: Record<string, unknown>): string | undefined {
  const items = payload.items;
  if (!Array.isArray(items)) return undefined;
  const first = items[0];
  if (!first || typeof first !== 'object') return undefined;
  const item = first as Record<string, unknown>;
  return stringValue(item.title) ?? stringValue(item.summary);
}

function toResearchBody(req: AgentSendMessageRequest) {
  if (
    process.env.NEXT_PUBLIC_DOCSURI_REAL_API &&
    process.env.NEXT_PUBLIC_DOCSURI_RESEARCH_AGENT_ENABLED !== '1'
  ) {
    throw new UserFacingError('unknown', 'Research는 아직 실배포에서 사용할 수 없습니다.');
  }
  return toChatBody(req);
}

function toChatBody(req: AgentSendMessageRequest) {
  return { content: req.content, attachments: req.attachments ?? [] };
}

function toNoveltyBody(req: AgentSendMessageRequest, created: boolean) {
  if (!created) {
    if (process.env.NEXT_PUBLIC_DOCSURI_REAL_API) {
      throw new UserFacingError(
        'unknown',
        'Novelty 후속 대화는 아직 실배포에서 사용할 수 없습니다.',
      );
    }
    return toChatBody(req);
  }
  const manuscript = req.attachments?.[0];
  if (manuscript && process.env.NEXT_PUBLIC_DOCSURI_REAL_API) {
    throw new UserFacingError(
      'unknown',
      '파일 업로드 연동 전에는 Novelty 첨부 분석을 사용할 수 없습니다.',
    );
  }
  return {
    inputType: manuscript ? 'manuscript' : 'natural_language',
    topic: req.content,
    manuscript: manuscript
      ? {
          fileName: manuscript.name,
          contentType: contentTypeFor(manuscript),
          objectKey: null,
        }
      : null,
    constraints: {},
    exportToNotion: false,
  };
}

function contentTypeFor(attachment: AgentAttachment): string {
  if (attachment.kind === 'pdf') return 'application/pdf';
  if (attachment.kind === 'markdown') return 'text/markdown';
  return 'text/plain';
}

function pageQuery(params?: PageQuery): string {
  const sp = new URLSearchParams({ limit: String(params?.limit ?? DEFAULT_PAGE_LIMIT) });
  if (params?.cursor) sp.set('cursor', params.cursor);
  if (params?.query) sp.set('query', params.query);
  return `?${sp.toString()}`;
}

export class ApiClient {
  private readonly timeoutMs: number;
  private readonly retryBackoffMs: number;
  private readonly inflight = new Map<string, Promise<TransportResponse>>();

  constructor(
    private readonly transport: Transport,
    options: ApiClientOptions = {},
  ) {
    this.timeoutMs = options.timeoutMs ?? 8000;
    this.retryBackoffMs = options.retryBackoffMs ?? 200;
  }

  // ---- hero-slice active methods --------------------------------------

  /** Submit a search; returns a classified terminal outcome (FR-11). */
  async search(query: string): Promise<SearchOutcome> {
    const body: SearchRequest = { query };
    // idempotent: false — POST /api/search records search history on the backend.
    // Retrying on 500 would create duplicate history entries.
    const res = await this.request({
      method: 'POST',
      path: '/api/search',
      body,
      idempotent: false,
    });
    if (res.status === 200 || res.status === 400) {
      return classifySearchResponse(res.body);
    }
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  // ---- summarization slice (US-S1/S2/S3/S5, FR-12~14) ------------------

  /** Summarize or translate a single paper; classified terminal outcome (BR-SF-14).
   * task=summary takes persona; task=translate takes scope (abstract|full). */
  async summarize(req: SummarizeRequest): Promise<SummarizeOutcome> {
    const res = await this.request({
      method: 'POST',
      path: '/api/summarize',
      body: req,
      idempotent: true,
      // dedup yes (BR-U5-18), retry no — a cost-bearing LLM POST must never double-bill (P-R1, NFR-C1).
      retryable: false,
    });
    if (res.status === 200 || res.status === 400) {
      return classifySummarizeResponse(res.body);
    }
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** Paper header metadata (title/authors/abstract) for the detail route. Backed by the
   * discovery (U2) endpoint GET /api/papers/{id} (corpus data — title/authors/abstract are not
   * U7's). Returns null on 404 so the detail page degrades to the arXiv id + link-out. The
   * PaperMetaVM type is still hand-authored (mirrors discovery's PaperMetaDTO) pending shared-
   * schema promotion + codegen. */
  async getPaperMeta(arxivId: string): Promise<PaperMetaVM | null> {
    const res = await this.request({
      method: 'GET',
      path: `/api/papers/${encodeURIComponent(arxivId)}`,
      idempotent: true,
    });
    if (res.status === 200) return res.body as PaperMetaVM;
    if (res.status === 404) return null;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** U8 citation tree for the paper detail page. GET is idempotent and can be cached by
   * the gateway/backend; save is a user-scoped library mutation. */
  async getCitationTree(
    paperId: string,
    params: CitationTreeQuery = {},
  ): Promise<CitationTreeResponse> {
    const sp = new URLSearchParams();
    if (params.expandNodeId) sp.set('expandNodeId', params.expandNodeId);
    if (params.refresh) sp.set('refresh', 'true');
    const query = sp.toString();
    const res = await this.request({
      method: 'GET',
      path: `/api/papers/${encodeURIComponent(paperId)}/citation-tree${query ? `?${query}` : ''}`,
      idempotent: true,
    });
    if (res.status === 200) return res.body as CitationTreeResponse;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async saveCitationNode(paperId: string, node: CitationNode): Promise<LibraryItemDTO> {
    const res = await this.request({
      method: 'POST',
      path: `/api/papers/${encodeURIComponent(paperId)}/citation-tree/save`,
      body: { node },
      idempotent: false,
    });
    if (res.status === 200 || res.status === 201) return res.body as LibraryItemDTO;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** Structured doc-model for the rich view (D4; replaces the old full-text viewer). OA license-gated.
   * url-free (SEC-9) — figures join the /assets signed urls by assetId. On a cache miss the
   * backend reads-only (lazy build is a separate step); a not-yet-built artifact → source_unavailable. */
  async getDocModel(req: DocModelRequest): Promise<DocModelOutcome> {
    const path = `/api/papers/${encodeURIComponent(req.paperId)}/doc-model?version=${encodeURIComponent(
      String(req.version),
    )}`;
    const res = await this.request({ method: 'GET', path, idempotent: true });
    if (res.status === 200 || res.status === 400) {
      return classifyDocModelResponse(res.body);
    }
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** Figure/table assets for the detail/viewer (FR-17, display-only; OA license-gated).
   * Returns signed URLs only (SEC-9). Independent of the full-text viewer. */
  async getAssets(paperId: string, version: number): Promise<AssetsOutcome> {
    const path = `/api/papers/${encodeURIComponent(paperId)}/assets?version=${encodeURIComponent(
      String(version),
    )}`;
    const res = await this.request({ method: 'GET', path, idempotent: true });
    if (res.status === 200 || res.status === 401) {
      return classifyAssetsResponse(res.body);
    }
    throw normalizeHttpError(res.status, pick(res.body, 'message'));
  }

  /** The user's saved personal terms (Phase 2a), to pre-fill the badge editor. Idempotent
   * GET. The caller treats any failure as "no saved terms" (pre-fill is optional). */
  async listGlossaryTerms(): Promise<GlossaryTermDTO[]> {
    const res = await this.request({ method: 'GET', path: '/api/glossary', idempotent: true });
    if (res.status === 200) return (res.body as GlossaryListDTO).terms ?? [];
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** Add/override a personal glossary term (Phase 1, badge-tap). State-changing, so
   * NOT idempotent (no auto-retry — a double POST would just re-upsert the same term).
   * A successful upsert bumps the user's glossary version server-side, invalidating
   * their cached summaries/translations so the next request reflects the new term. */
  async upsertGlossaryTerm(req: GlossaryTermUpsertDTO): Promise<GlossaryUpsertResultDTO> {
    const res = await this.request({
      method: 'POST',
      path: '/api/glossary',
      body: req,
      idempotent: false,
    });
    if (res.status === 200 || res.status === 201) return res.body as GlossaryUpsertResultDTO;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async recordBehaviorEvent(req: BehaviorEventCreate): Promise<EventRecordResult> {
    const res = await this.request({
      method: 'POST',
      path: '/api/personalization/events',
      body: req,
      idempotent: false,
    });
    if (res.status === 200) return res.body as EventRecordResult;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async getPersonalizationSettings(): Promise<PersonalizationSettings> {
    const res = await this.request({
      method: 'GET',
      path: '/api/personalization/settings',
      idempotent: true,
    });
    if (res.status === 200) return res.body as PersonalizationSettings;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async updatePersonalizationEnabled(enabled: boolean): Promise<PersonalizationSettings> {
    const res = await this.request({
      method: 'PATCH',
      path: '/api/personalization/settings',
      body: { enabled },
      idempotent: false,
    });
    if (res.status === 200) return res.body as PersonalizationSettings;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async deletePersonalizationEvents(): Promise<DeletePersonalizationEventsResult> {
    const res = await this.request({
      method: 'POST',
      path: '/api/personalization/delete-events',
      idempotent: false,
    });
    if (res.status === 200) return res.body as DeletePersonalizationEventsResult;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async resetPersonalizationProfile(): Promise<ResetPersonalizationProfileResult> {
    const res = await this.request({
      method: 'POST',
      path: '/api/personalization/reset-profile',
      idempotent: false,
    });
    if (res.status === 200) return res.body as ResetPersonalizationProfileResult;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  // ---- agent chat frontend seam (U11/U12) -------------------------------

  async listAgentSessions(mode?: AgentMode): Promise<AgentSessionSummary[]> {
    const modes: AgentMode[] = mode ? [mode] : ['evidence', 'novelty'];
    const results = await Promise.allSettled(
      modes.map((item) => this.listAgentSessionsForMode(item)),
    );
    const fulfilled = results.filter(
      (result): result is PromiseFulfilledResult<AgentSessionSummary[]> =>
        result.status === 'fulfilled',
    );
    if (!fulfilled.length) {
      throw (results.find((result) => result.status === 'rejected') as PromiseRejectedResult)
        .reason;
    }
    const sessions = fulfilled.flatMap((result) => result.value);
    return sessions.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }

  private async listAgentSessionsForMode(mode: AgentMode): Promise<AgentSessionSummary[]> {
    const path = mode === 'evidence' ? '/api/research/jobs?limit=20' : '/api/novelty/jobs?limit=20';
    const res = await this.request({
      method: 'GET',
      path,
      idempotent: true,
    });
    if (res.status === 200) {
      const jobs = (res.body as { jobs?: unknown[] }).jobs ?? [];
      return jobs.map((job) =>
        mode === 'evidence'
          ? mapResearchJob(job as BackendResearchJob)
          : mapNoveltyJob(job as BackendNoveltyJob),
      );
    }
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async loadAgentSession(id: string): Promise<AgentSessionSnapshot> {
    const target = parseAgentSessionId(id);
    if (target.mode === 'novelty') return this.loadNoveltySession(target.rawId);
    return this.loadResearchSession(target.rawId);
  }

  private async loadResearchSession(id: string): Promise<AgentSessionSnapshot> {
    const res = await this.request({
      method: 'GET',
      path: `/api/research/jobs/${encodeURIComponent(id)}`,
      idempotent: true,
    });
    if (res.status === 200) {
      const body = res.body as { job: BackendResearchJob; messages?: BackendResearchMessage[] };
      return {
        session: mapResearchJob(body.job),
        messages: (body.messages ?? []).map((message) => mapAgentMessage(message)),
        events: [],
      };
    }
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  private async loadNoveltySession(id: string): Promise<AgentSessionSnapshot> {
    const [jobRes, messageRes, resultRes] = await Promise.all([
      this.request({
        method: 'GET',
        path: `/api/novelty/jobs/${encodeURIComponent(id)}`,
        idempotent: true,
      }),
      this.request({
        method: 'GET',
        path: `/api/novelty/jobs/${encodeURIComponent(id)}/messages`,
        idempotent: true,
      }),
      this.request({
        method: 'GET',
        path: `/api/novelty/jobs/${encodeURIComponent(id)}/result`,
        idempotent: true,
      }),
    ]);
    if (jobRes.status !== 200) throw normalizeHttpError(jobRes.status, serverMessage(jobRes.body));
    if (messageRes.status !== 200) {
      throw normalizeHttpError(messageRes.status, serverMessage(messageRes.body));
    }
    if (![200, 404, 409].includes(resultRes.status)) {
      throw normalizeHttpError(resultRes.status, serverMessage(resultRes.body));
    }
    const jobBody = jobRes.body as { job: BackendNoveltyJob; events?: BackendNoveltyEvent[] };
    const messageBody = messageRes.body as { messages?: BackendNoveltyMessage[] };
    const resultBody = resultRes.body as {
      artifacts?: BackendNoveltyArtifact[];
    };
    const messages = (messageBody.messages ?? []).map((message) => mapAgentMessage(message));
    const resultMessage = mapNoveltyResultMessage(
      resultRes.status === 200 ? (resultBody.artifacts ?? []) : [],
      jobBody.job.updatedAt,
    );
    return {
      session: mapNoveltyJob(jobBody.job),
      messages: resultMessage ? [...messages, resultMessage] : messages,
      events: (jobBody.events ?? []).map((event, index) => mapNoveltyEvent(event, index)),
    };
  }

  async sendAgentMessage(
    sessionId: string,
    req: AgentSendMessageRequest,
  ): Promise<AgentSendMessageResult> {
    const target = parseAgentSessionId(sessionId, req.mode);
    const created = sessionId.startsWith(`agent-${req.mode}-`);
    const path =
      target.mode === 'evidence'
        ? created
          ? '/api/research/jobs'
          : `/api/research/jobs/${encodeURIComponent(target.rawId)}/messages`
        : created
          ? '/api/novelty/jobs'
          : `/api/novelty/jobs/${encodeURIComponent(target.rawId)}/messages`;
    const res = await this.request({
      method: 'POST',
      path,
      body: target.mode === 'evidence' ? toResearchBody(req) : toNoveltyBody(req, created),
      idempotent: false,
    });
    if (res.status !== 200 && res.status !== 201) {
      throw normalizeHttpError(res.status, serverMessage(res.body));
    }
    const nextId =
      created && target.mode === 'evidence'
        ? encodeAgentSessionId('evidence', (res.body as { jobId: string }).jobId)
        : created && target.mode === 'novelty'
          ? encodeAgentSessionId('novelty', (res.body as { jobId: string }).jobId)
          : sessionId;
    const snapshot = await this.loadAgentSession(nextId);
    return {
      session: snapshot.session,
      messages: snapshot.messages,
      events: snapshot.events,
      outcome: snapshot.session.state === 'failed' ? 'failed' : snapshot.session.state,
    };
  }

  async deleteAgentSession(id: string): Promise<void> {
    const target = parseAgentSessionId(id);
    const res = await this.request({
      method: 'DELETE',
      path:
        target.mode === 'evidence'
          ? `/api/research/jobs/${encodeURIComponent(target.rawId)}`
          : `/api/novelty/jobs/${encodeURIComponent(target.rawId)}`,
      idempotent: false,
    });
    if (res.status === 200 || res.status === 204) return;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async signup(req: SignupRequest): Promise<SignupResult> {
    const res = await this.request({
      method: 'POST',
      path: '/auth/signup',
      body: req,
      idempotent: false,
    });
    if (res.status === 200 || res.status === 201) return res.body as SignupResult;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /**
   * Authenticate (US-A2). The real backend (POST /auth/login) sets the httpOnly
   * session cookie and returns only {status, message} — NOT a SessionInfo body;
   * callers refresh via currentSession() (GET /auth/session) after success.
   * MFA is an admin-only control (BR-A7) with no login-time challenge, so any
   * non-success is normalized to a user-facing error (401 → generalized auth).
   */
  async login(req: LoginRequest, recaptchaToken?: string): Promise<void> {
    const res = await this.request({
      method: 'POST',
      path: '/auth/login',
      body: req,
      headers: recaptchaToken ? { 'X-Recaptcha-Token': recaptchaToken } : undefined,
      idempotent: false,
    });
    if (res.status === 200 || res.status === 204) return;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /**
   * Activate a PENDING account from the emailed link's token (US-A1, BR-A5). Hits the
   * backend GET /auth/verify-email via the BFF; resolves on 200, throws a
   * UserFacingError on an expired/invalid token (4xx) so the page can show a retry path.
   */
  async verifyEmail(token: string): Promise<void> {
    const res = await this.request({
      method: 'GET',
      path: `/auth/verify-email?token=${encodeURIComponent(token)}`,
      idempotent: true,
    });
    if (res.status === 200) return;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /**
   * Resend the account-verification email (US-A1 recourse). The backend returns a
   * generic success regardless of whether the address exists / is still PENDING
   * (no account enumeration), so this resolves on 200 and only throws on transport
   * or non-2xx failures.
   */
  async resendVerification(email: string): Promise<void> {
    const res = await this.request({
      method: 'POST',
      path: '/auth/resend-verification',
      body: { email },
      idempotent: false,
    });
    if (res.status === 200 || res.status === 204) return;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async logout(): Promise<void> {
    await this.request({ method: 'POST', path: '/auth/logout', idempotent: false });
  }

  /**
   * Request a password-reset email (FR-26/BR-A8). The backend returns a generic success
   * regardless of whether the address exists / is active (no account enumeration), so this
   * resolves on 200 and only throws on transport or non-2xx failures.
   */
  async requestPasswordReset(email: string): Promise<void> {
    const res = await this.request({
      method: 'POST',
      path: '/auth/password-reset/request',
      body: { email },
      idempotent: false,
    });
    if (res.status === 200 || res.status === 204) return;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** Set a new password from the emailed reset token (FR-26/BR-A8). 4xx → user-facing error
   * (expired/invalid token or weak password) so the page can show a retry path. */
  async confirmPasswordReset(token: string, newPassword: string): Promise<void> {
    const res = await this.request({
      method: 'POST',
      path: '/auth/password-reset/confirm',
      body: { token, newPassword },
      idempotent: false,
    });
    if (res.status === 200 || res.status === 204) return;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** Change the logged-in user's password (FR-28/BR-A10). Backend invalidates all sessions on
   * success, so the caller must re-login afterward. */
  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    const res = await this.request({
      method: 'POST',
      path: '/auth/change-password',
      body: { currentPassword, newPassword },
      idempotent: false,
    });
    if (res.status === 200 || res.status === 204) return;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** Request an email-change confirmation link to a new address (FR-28/BR-A10). Password
   * accounts must re-authenticate (currentPassword). Generic success (enumeration-safe). */
  async requestEmailChange(newEmail: string, currentPassword: string): Promise<void> {
    const res = await this.request({
      method: 'POST',
      path: '/auth/email-change/request',
      body: { newEmail, currentPassword },
      idempotent: false,
    });
    if (res.status === 200 || res.status === 204) return;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** Returns the current session, or null when anonymous (401 is not an error). */
  async currentSession(): Promise<SessionInfo | null> {
    const res = await this.request({ method: 'GET', path: '/auth/session', idempotent: true });
    if (res.status === 200) return res.body as SessionInfo;
    if (res.status === 401) return null;
    throw normalizeHttpError(res.status);
  }

  // ---- saved searches (US-L1/FR-8) ------------------------------------

  /** Page of the user's saved searches (cursor-based, most-recent first). */
  async listSavedSearches(params?: PageQuery): Promise<SavedSearchPageDTO> {
    const res = await this.request({
      method: 'GET',
      path: `/library/saved-searches${pageQuery(params)}`,
      idempotent: true,
    });
    if (res.status === 200) return res.body as SavedSearchPageDTO;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async saveSearch(req: SavedSearchCreateDTO): Promise<SavedSearchDTO> {
    const res = await this.request({
      method: 'POST',
      path: '/library/saved-searches',
      body: req,
      idempotent: false,
    });
    if (res.status === 200 || res.status === 201) return res.body as SavedSearchDTO;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async deleteSavedSearch(id: string): Promise<void> {
    const res = await this.request({
      method: 'DELETE',
      path: `/library/saved-searches/${encodeURIComponent(id)}`,
      idempotent: false,
    });
    if (res.status === 204 || res.status === 200) return;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** Re-run a saved search through the gateway (U6 -> U2); classified like search. */
  async rerunSavedSearch(id: string): Promise<SearchOutcome> {
    return this.rerun(`/library/saved-searches/${encodeURIComponent(id)}/rerun`);
  }

  // ---- library (US-L2/FR-9) -------------------------------------------

  /** Page of the user's library (cursor-based). Renders preserved meta snapshots. */
  async listLibrary(params?: PageQuery): Promise<LibraryPageDTO> {
    const res = await this.request({
      method: 'GET',
      path: `/library/items${pageQuery(params)}`,
      idempotent: true,
    });
    if (res.status === 200) return res.body as LibraryPageDTO;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** Idempotent add; returns the same item shape whether new or already present. */
  async addToLibrary(req: LibraryItemCreateDTO): Promise<LibraryItemDTO> {
    const res = await this.request({
      method: 'POST',
      path: '/library/items',
      body: req,
      idempotent: false,
    });
    if (res.status === 200 || res.status === 201) return res.body as LibraryItemDTO;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async removeFromLibrary(id: string): Promise<void> {
    const res = await this.request({
      method: 'DELETE',
      path: `/library/items/${encodeURIComponent(id)}`,
      idempotent: false,
    });
    if (res.status === 204 || res.status === 200) return;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  // ---- search history (US-L3/FR-10) -----------------------------------

  /** Page of recent search history (cursor-based, most-recent first). */
  async listHistory(params?: PageQuery): Promise<HistoryPageDTO> {
    const res = await this.request({
      method: 'GET',
      path: `/library/history${pageQuery(params)}`,
      idempotent: true,
    });
    if (res.status === 200) return res.body as HistoryPageDTO;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** Re-run a history entry through the gateway (U6 -> U2); classified like search. */
  async rerunHistory(id: string): Promise<SearchOutcome> {
    return this.rerun(`/library/history/${encodeURIComponent(id)}/rerun`);
  }

  /** Clear the user's entire search history. */
  async clearHistory(): Promise<void> {
    const res = await this.request({
      method: 'DELETE',
      path: '/library/history',
      idempotent: false,
    });
    if (res.status === 204 || res.status === 200) return;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  // ---- mypage (U10) -----------------------------------------------------
  // getSubscription/subscribe/cancelSubscription are REAL (backend/modules/mypage, mock-only
  // PG/billing per Q10). The rest below are MOCK-ONLY placeholders — U3 is implementing the
  // real OAuth/profile/consent/withdrawal contract separately; these methods route to the
  // same path shape so swapping the transport later (real BFF) needs no caller changes.

  async getSubscription(): Promise<SubscriptionDTO> {
    const res = await this.request({
      method: 'GET',
      path: '/mypage/subscription',
      idempotent: true,
    });
    if (res.status === 200) return res.body as SubscriptionDTO;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async subscribe(): Promise<SubscriptionDTO> {
    const res = await this.request({
      method: 'POST',
      path: '/mypage/subscription',
      idempotent: false,
    });
    if (res.status === 200 || res.status === 201) return res.body as SubscriptionDTO;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async cancelSubscription(): Promise<SubscriptionDTO> {
    const res = await this.request({
      method: 'POST',
      path: '/mypage/subscription/cancel',
      idempotent: false,
    });
    if (res.status === 200) return res.body as SubscriptionDTO;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** 로그인 경로 + 가입날짜 (MOCK — U3가 계정 컬럼을 추가하기 전까지). */
  async getAccountProfile(): Promise<AccountProfileVM> {
    const res = await this.request({
      method: 'GET',
      path: '/mypage/account-profile',
      idempotent: true,
    });
    if (res.status === 200) return res.body as AccountProfileVM;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** ORCID 공개 프로필 (REAL — U3 `GET /mypage/orcid-profile`, FR-27/BR-A13). 이름·소속은
   * 로그인 시 캐시한 값, works는 ORCID Public API 라이브. loginProvider !== 'ORCID'면 404 -> null. */
  async getOrcidProfile(): Promise<OrcidProfileVM | null> {
    const res = await this.request({
      method: 'GET',
      path: '/mypage/orcid-profile',
      idempotent: true,
    });
    if (res.status === 200) return res.body as OrcidProfileVM;
    if (res.status === 404) return null;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** 최근 본 논문 (MOCK — U9 paper_opened 이벤트 구현 전까지). 백엔드가 아직 이 경로를
   * 제공하지 않으면 404 → 빈 목록으로 우아하게 처리(메뉴는 비어 보일 뿐 에러 아님). */
  async getRecentlyViewed(): Promise<RecentlyViewedItemVM[]> {
    const res = await this.request({
      method: 'GET',
      path: '/mypage/recently-viewed',
      idempotent: true,
    });
    if (res.status === 200) return (res.body as { items: RecentlyViewedItemVM[] }).items ?? [];
    if (res.status === 404) return [];
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** 동의 항목 (MOCK). privacyPolicy/termsOfService는 읽기 전용(필수, 철회 불가) — nightlyPush만
   * updateNightlyPushConsent로 갱신 가능. */
  async getConsents(): Promise<ConsentSettingsVM> {
    const res = await this.request({ method: 'GET', path: '/mypage/consents', idempotent: true });
    if (res.status === 200) return res.body as ConsentSettingsVM;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  async updateNightlyPushConsent(nightlyPushAgreed: boolean): Promise<ConsentSettingsVM> {
    const res = await this.request({
      method: 'POST',
      path: '/mypage/consents',
      body: { nightlyPushAgreed },
      idempotent: false,
    });
    if (res.status === 200) return res.body as ConsentSettingsVM;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  /** 회원탈퇴 — REAL U3 소프트 삭제 (POST /auth/account/delete): status=DEACTIVATED 전이 +
   * 전 세션 즉시 무효화 + 유예 기간 내 복구 가능. 비밀번호 계정은 현재 비밀번호 재인증 필수
   * (감사 H7); 소셜-only 계정은 생략 가능. 성공 시 200/204. */
  async withdrawAccount(currentPassword?: string): Promise<void> {
    const res = await this.request({
      method: 'POST',
      path: '/auth/account/delete',
      body: currentPassword ? { currentPassword } : undefined,
      idempotent: false,
    });
    if (res.status === 200 || res.status === 204) return;
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  // ---- internals ------------------------------------------------------

  /** Shared rerun path: POST -> SearchResultSetDTO, classified like a live search. */
  private async rerun(path: string): Promise<SearchOutcome> {
    const res = await this.request({ method: 'POST', path, idempotent: false });
    if (res.status === 200 || res.status === 400) {
      return classifySearchResponse(res.body);
    }
    throw normalizeHttpError(res.status, serverMessage(res.body));
  }

  private async request(req: TransportRequest): Promise<TransportResponse> {
    const key = `${req.method} ${req.path} ${JSON.stringify(req.body ?? null)}`;
    if (req.idempotent) {
      const existing = this.inflight.get(key);
      if (existing) return existing;
    }
    const promise = this.sendWithPolicy(req).finally(() => {
      if (req.idempotent) this.inflight.delete(key);
    });
    if (req.idempotent) this.inflight.set(key, promise);
    return promise;
  }

  private async sendWithPolicy(req: TransportRequest): Promise<TransportResponse> {
    const attempts = (req.retryable ?? req.idempotent) ? 2 : 1;
    const stop = recordPath(req.path.split('?')[0]);
    for (let i = 0; i < attempts; i++) {
      const lastAttempt = i === attempts - 1;
      try {
        const res = await this.withTimeout((signal) => this.transport.send({ ...req, signal }));
        if (res.status >= 500 && !lastAttempt) {
          await delay(this.retryBackoffMs * (i + 1));
          continue;
        }
        stop(res.status >= 500 ? 'error' : 'ok');
        return res;
      } catch {
        if (!lastAttempt) {
          await delay(this.retryBackoffMs * (i + 1));
          continue;
        }
        stop('error');
        throw new UserFacingError('network');
      }
    }
    // Unreachable, but keeps the type checker happy.
    stop('error');
    throw new UserFacingError('network');
  }

  private withTimeout(
    send: (signal: AbortSignal) => Promise<TransportResponse>,
  ): Promise<TransportResponse> {
    const controller = new AbortController();
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => {
        controller.abort();
        reject(new Error('timeout'));
      }, this.timeoutMs);
      send(controller.signal).then(
        (v) => {
          clearTimeout(t);
          resolve(v);
        },
        (e) => {
          clearTimeout(t);
          reject(e);
        },
      );
    });
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function pick(body: unknown, key: string): unknown {
  return typeof body === 'object' && body !== null
    ? (body as Record<string, unknown>)[key]
    : undefined;
}

// Backend error envelopes disagree on the key: the U6 gateway/middleware emit {message}
// (errors.ts, auth.py, gateway.py), but FastAPI module HTTPExceptions serialize the curated,
// user-safe reason as {detail} (e.g. "이미 등록된 이메일 주소입니다.", the BR-A1 password rules).
// Reading only `message` swallowed every module 4xx reason into the generic "문제가 발생했습니다."
// Read both — message first, then detail. (5xx still maps to a generic message in normalizeHttpError.)
function serverMessage(body: unknown): unknown {
  return pick(body, 'message') ?? pick(body, 'detail');
}
