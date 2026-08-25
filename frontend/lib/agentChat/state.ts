import type {
  AgentAttachment,
  AgentAttachmentKind,
  AgentJobState,
  AgentMessage,
  AgentMode,
  AgentSendMessageResult,
  AgentSessionSnapshot,
  AgentSessionSummary,
  AgentTimelineEvent,
  AgentTurnAccepted,
  AgentTurnFinished,
} from './types';

export const MAX_AGENT_MESSAGE_CHARS = 4000;
export const MAX_AGENT_ATTACHMENTS = 5;
export const MAX_AGENT_ATTACHMENT_BYTES = 10 * 1024 * 1024;
// US-EV4(#268)/US-NV2(#252) — 동봉 본문 상한. BE 계약(ATTACHMENT_TEXT_MAX_CHARS)과 동일.
export const MAX_AGENT_ATTACHMENT_TEXT_CHARS = 262_144;

export interface AgentChatState {
  session: AgentSessionSummary | null;
  sessions: AgentSessionSummary[];
  mode: AgentMode | null;
  messages: AgentMessage[];
  events: AgentTimelineEvent[];
  draft: string;
  attachments: AgentAttachment[];
  jobState: AgentJobState;
  submitting: boolean;
  error: string | null;
  /** evidence — 실행 중인 턴(v3 §5). 있으면 이벤트 구독이 유일한 답변 작성자이고 입력은 닫힌다. */
  activeTurnId: string | null;
  cancelRequested: boolean;
}

export const initialAgentChatState: AgentChatState = {
  session: null,
  sessions: [],
  mode: null,
  messages: [],
  events: [],
  draft: '',
  attachments: [],
  jobState: 'idle',
  submitting: false,
  error: null,
  activeTurnId: null,
  cancelRequested: false,
};

export type AgentChatAction =
  | { type: 'sessionsLoaded'; sessions: AgentSessionSummary[] }
  | { type: 'startSession'; session: AgentSessionSummary }
  | { type: 'loadSession'; snapshot: AgentSessionSnapshot }
  | { type: 'refreshSession'; snapshot: AgentSessionSnapshot }
  | { type: 'eventsReceived'; events: AgentTimelineEvent[] }
  | { type: 'newChat' }
  | { type: 'setDraft'; draft: string }
  | { type: 'addAttachment'; attachment: AgentAttachment }
  | { type: 'attachmentContentReady'; id: string; contentText: string }
  | { type: 'removeAttachment'; id: string }
  | { type: 'sendStart'; message: AgentMessage }
  | { type: 'sendSuccess'; result: AgentSendMessageResult }
  | { type: 'sendFailure'; message: string }
  | { type: 'turnAccepted'; accepted: AgentTurnAccepted }
  | { type: 'turnFinished'; finished: AgentTurnFinished }
  | { type: 'cancelRequested' }
  | { type: 'deleteSession'; id: string }
  | { type: 'resetSessions' };

export function agentReducer(state: AgentChatState, action: AgentChatAction): AgentChatState {
  switch (action.type) {
    case 'sessionsLoaded':
      return { ...state, sessions: sortSessions(action.sessions) };
    case 'startSession':
      if (state.mode && state.mode !== action.session.mode) return state;
      return {
        ...state,
        session: action.session,
        mode: action.session.mode,
        messages: [],
        events: [],
        draft: '',
        attachments: [],
        jobState: action.session.state,
        error: null,
      };
    case 'loadSession':
      return {
        ...state,
        session: action.snapshot.session,
        mode: action.snapshot.session.mode,
        messages: action.snapshot.messages,
        events: sortTimelineEvents(action.snapshot.events),
        draft: '',
        attachments: [],
        // 새로고침 뒤에도 실행 중인 턴은 구독을 다시 붙인다 — 아니면 답변이 영영 안 온다.
        jobState: action.snapshot.activeTurnId ? 'running' : action.snapshot.session.state,
        activeTurnId: action.snapshot.activeTurnId ?? null,
        cancelRequested: false,
        error: null,
      };
    case 'refreshSession':
      if (state.session?.id !== action.snapshot.session.id) return state;
      return {
        ...state,
        session: action.snapshot.session,
        sessions: sortSessions(upsertSession(state.sessions, action.snapshot.session)),
        messages: action.snapshot.messages,
        events: mergeTimelineEvents(state.events, action.snapshot.events),
        jobState: action.snapshot.session.state,
        error: jobStateMessage(action.snapshot.session.state),
      };
    case 'eventsReceived':
      return action.events.length
        ? { ...state, events: mergeTimelineEvents(state.events, action.events) }
        : state;
    case 'turnAccepted': {
      // 후속 턴의 수락 응답은 그 질문을 topic으로 싣는다 — 세션 제목은 첫 질문이므로
      // 같은 세션이면 기존 제목을 지키고 상태만 running으로 올린다.
      const accepted = action.accepted.session;
      const session =
        state.session && state.session.id === accepted.id
          ? { ...state.session, state: accepted.state, updatedAt: accepted.updatedAt }
          : accepted;
      return {
        ...state,
        session,
        sessions: sortSessions(upsertSession(state.sessions, session)),
        messages: markLastPending(state.messages, 'sent'),
        draft: '',
        attachments: [],
        jobState: 'running',
        submitting: false,
        activeTurnId: action.accepted.turnId,
        cancelRequested: false,
        error: null,
      };
    }
    case 'turnFinished': {
      if (state.activeTurnId && state.activeTurnId !== action.finished.turnId) return state;
      const { message, outcome, cancelled, turnId } = action.finished;
      const session = state.session
        ? { ...state.session, state: outcome, updatedAt: message.createdAt }
        : state.session;
      return {
        ...state,
        session,
        sessions: session ? sortSessions(upsertSession(state.sessions, session)) : state.sessions,
        messages: state.messages.some((item) => item.id === message.id)
          ? state.messages
          : [...state.messages, message],
        // 취소는 타임라인에도 남는다 — 마지막 줄이 영원히 돌지 않게 닫는다.
        events: cancelled
          ? mergeTimelineEvents(state.events, [cancelledTimelineEvent(turnId)])
          : state.events,
        jobState: outcome,
        activeTurnId: null,
        cancelRequested: false,
        error: outcome === 'failed' ? jobStateMessage(outcome) : null,
      };
    }
    case 'cancelRequested':
      return state.activeTurnId ? { ...state, cancelRequested: true } : state;
    case 'newChat':
      return { ...initialAgentChatState, sessions: state.sessions };
    case 'resetSessions':
      // US-EV8(#272) 전체 초기화 — 세션 목록과 현재 대화 모두 기본 상태로.
      return { ...initialAgentChatState };
    case 'setDraft':
      return { ...state, draft: action.draft.slice(0, MAX_AGENT_MESSAGE_CHARS), error: null };
    case 'addAttachment':
      if (state.attachments.length >= MAX_AGENT_ATTACHMENTS) {
        return { ...state, error: `첨부는 최대 ${MAX_AGENT_ATTACHMENTS}개까지 가능합니다.` };
      }
      return { ...state, attachments: [...state.attachments, action.attachment], error: null };
    case 'attachmentContentReady':
      // US-EV4(#268)/US-NV2(#252) — 본문 읽기 완료 → 전송 가능(ready). 읽기 실패는
      // 빈 본문으로 ready 처리하고 BE가 '[첨부 안내]'로 미포함을 알린다.
      return {
        ...state,
        attachments: state.attachments.map((item) =>
          item.id === action.id
            ? { ...item, status: 'ready' as const, contentText: action.contentText }
            : item,
        ),
      };
    case 'removeAttachment':
      return {
        ...state,
        attachments: state.attachments.filter((item) => item.id !== action.id),
        error: null,
      };
    case 'sendStart':
      return {
        ...state,
        messages: [...state.messages, action.message],
        jobState: 'running',
        submitting: true,
        error: null,
      };
    case 'sendSuccess':
      return {
        ...state,
        session: action.result.session,
        sessions: sortSessions(upsertSession(state.sessions, action.result.session)),
        messages: action.result.messages,
        events: mergeTimelineEvents(state.events, action.result.events),
        draft: '',
        attachments: [],
        jobState: action.result.outcome,
        submitting: false,
        error: resultMessage(action.result),
      };
    case 'sendFailure':
      return {
        ...state,
        messages: markLastPending(state.messages, 'failed'),
        jobState: 'failed',
        submitting: false,
        activeTurnId: null,
        cancelRequested: false,
        error: action.message,
      };
    case 'deleteSession':
      if (state.session?.id !== action.id) {
        return {
          ...state,
          sessions: state.sessions.filter((item) => item.id !== action.id),
        };
      }
      return {
        sessions: state.sessions.filter((item) => item.id !== action.id),
        session: null,
        mode: null,
        messages: [],
        events: [],
        draft: '',
        attachments: [],
        jobState: 'idle',
        submitting: false,
        error: null,
        activeTurnId: null,
        cancelRequested: false,
      };
    default:
      return state;
  }
}

export function createDraftSession(mode: AgentMode, createdAt = new Date().toISOString()) {
  return {
    id: `agent-${mode}-${Date.now()}`,
    title: mode === 'evidence' ? 'Evidence' : 'Novelty',
    mode,
    state: 'idle' as const,
    updatedAt: createdAt,
  };
}

export function createUserMessage(
  content: string,
  attachments: AgentAttachment[] = [],
  createdAt = new Date().toISOString(),
): AgentMessage {
  return {
    id: `msg-user-${Date.now()}`,
    role: 'user',
    content: content.trim(),
    createdAt,
    attachments: attachments.filter((item) => item.status === 'ready'),
    status: 'pending',
  };
}

export function canSend(state: AgentChatState): boolean {
  return Boolean(
    state.mode &&
      state.session &&
      state.draft.trim() &&
      !state.submitting &&
      !state.activeTurnId &&
      state.attachments.every((item) => item.status === 'ready'),
  );
}

export function cancelledTimelineEvent(turnId: string): AgentTimelineEvent {
  return {
    id: `${turnId}:cancelled`,
    stage: 'cancelled',
    label: '취소됨',
    state: 'failed',
    sequence: Number.MAX_SAFE_INTEGER,
  };
}

export function mergeTimelineEvents(
  current: AgentTimelineEvent[],
  incoming: AgentTimelineEvent[],
): AgentTimelineEvent[] {
  const byId = new Map(current.map((event) => [event.id, event]));
  for (const event of incoming) {
    const existing = byId.get(event.id);
    byId.set(event.id, existing ? mergeTimelineEvent(existing, event) : event);
  }
  return sortTimelineEvents([...byId.values()]);
}

// A lean SSE snapshot (id/stage/label/state only) must not erase the richer detail that the
// polling path already resolved for the same event id. Incoming stage/label/state win, but
// detail/sequence fall back to the prior event when the snapshot omits them (#349).
// `??` (not `||`) so a valid sequence of 0 is not discarded as falsy.
function mergeTimelineEvent(
  prev: AgentTimelineEvent,
  next: AgentTimelineEvent,
): AgentTimelineEvent {
  return {
    ...prev,
    ...next,
    detail: next.detail ?? prev.detail,
    sequence: next.sequence ?? prev.sequence,
  };
}

export function sortTimelineEvents(events: AgentTimelineEvent[]): AgentTimelineEvent[] {
  return events
    .map((event, index) => ({ event, index }))
    .sort((a, b) => {
      const aSeq = a.event.sequence;
      const bSeq = b.event.sequence;
      if (aSeq == null && bSeq == null) return a.index - b.index;
      if (aSeq == null) return 1;
      if (bSeq == null) return -1;
      if (aSeq !== bSeq) return aSeq - bSeq;
      return a.index - b.index;
    })
    .map(({ event }) => event);
}

export function createAttachmentFromFile(
  file: { name: string; size?: number; arrayBuffer?: Blob['arrayBuffer'] },
  index = 0,
) {
  const name = file.name.trim() || 'untitled';
  const kind = classifyAttachmentKind(name);
  const sizeBytes = file.size ?? 0;
  const attachment: AgentAttachment = {
    id: `att-${slug(name)}-${sizeBytes}-${index}`,
    name,
    kind,
    sizeBytes,
    status: 'ready',
    ...(kind === 'pdf' && typeof file.arrayBuffer === 'function'
      ? { sourceFile: file as unknown as Blob }
      : {}),
  };

  if (kind === 'unknown') {
    return {
      ...attachment,
      status: 'rejected' as const,
      error: 'PDF, Markdown, TXT 파일만 첨부할 수 있습니다.',
    };
  }
  if (sizeBytes > MAX_AGENT_ATTACHMENT_BYTES) {
    return {
      ...attachment,
      status: 'rejected' as const,
      error: '첨부 파일은 10MB 이하만 사용할 수 있습니다.',
    };
  }
  return attachment;
}

export function classifyAttachmentKind(name: string): AgentAttachmentKind {
  const lower = name.toLowerCase();
  if (lower.endsWith('.pdf')) return 'pdf';
  if (lower.endsWith('.md') || lower.endsWith('.markdown')) return 'markdown';
  if (lower.endsWith('.txt')) return 'text';
  return 'unknown';
}

function sortSessions(sessions: AgentSessionSummary[]): AgentSessionSummary[] {
  return [...sessions].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

function upsertSession(
  sessions: AgentSessionSummary[],
  session: AgentSessionSummary,
): AgentSessionSummary[] {
  return [session, ...sessions.filter((item) => item.id !== session.id)];
}

/** 낙관적으로 붙여둔 마지막 사용자 메시지의 상태를 확정한다(수락=sent, 실패=failed). */
function markLastPending(
  messages: AgentMessage[],
  status: 'sent' | 'failed',
): AgentMessage[] {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].status === 'pending') {
      return messages.map((message, idx) => (idx === i ? { ...message, status } : message));
    }
  }
  return messages;
}

function resultMessage(result: AgentSendMessageResult): string | null {
  return jobStateMessage(result.outcome, result.errorMessage);
}

function jobStateMessage(state: AgentJobState, errorMessage?: string): string | null {
  if (state === 'failed') {
    return errorMessage ?? '에이전트 응답 생성에 실패했습니다.';
  }
  if (state === 'degraded') {
    return '일부 외부 근거 소스가 응답하지 않아 가능한 범위에서 답변했습니다.';
  }
  return null;
}

function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 32);
}
