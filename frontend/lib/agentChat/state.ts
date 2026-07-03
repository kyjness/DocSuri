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
} from './types';

export const MAX_AGENT_MESSAGE_CHARS = 4000;
export const MAX_AGENT_ATTACHMENTS = 5;
export const MAX_AGENT_ATTACHMENT_BYTES = 10 * 1024 * 1024;

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
};

export type AgentChatAction =
  | { type: 'sessionsLoaded'; sessions: AgentSessionSummary[] }
  | { type: 'startSession'; session: AgentSessionSummary }
  | { type: 'loadSession'; snapshot: AgentSessionSnapshot }
  | { type: 'refreshSession'; snapshot: AgentSessionSnapshot }
  | { type: 'newChat' }
  | { type: 'setDraft'; draft: string }
  | { type: 'addAttachment'; attachment: AgentAttachment }
  | { type: 'removeAttachment'; id: string }
  | { type: 'sendStart'; message: AgentMessage }
  | { type: 'sendSuccess'; result: AgentSendMessageResult }
  | { type: 'sendFailure'; message: string }
  | { type: 'deleteSession'; id: string };

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
        jobState: action.snapshot.session.state,
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
    case 'newChat':
      return { ...initialAgentChatState, sessions: state.sessions };
    case 'setDraft':
      return { ...state, draft: action.draft.slice(0, MAX_AGENT_MESSAGE_CHARS), error: null };
    case 'addAttachment':
      if (state.attachments.length >= MAX_AGENT_ATTACHMENTS) {
        return { ...state, error: `첨부는 최대 ${MAX_AGENT_ATTACHMENTS}개까지 가능합니다.` };
      }
      return { ...state, attachments: [...state.attachments, action.attachment], error: null };
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
        messages: markLastPendingFailed(state.messages),
        jobState: 'failed',
        submitting: false,
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
      };
    default:
      return state;
  }
}

export function createDraftSession(mode: AgentMode, createdAt = new Date().toISOString()) {
  return {
    id: `agent-${mode}-${Date.now()}`,
    title: mode === 'evidence' ? 'Research' : 'Novelty',
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
      state.attachments.every((item) => item.status === 'ready'),
  );
}

export function mergeTimelineEvents(
  current: AgentTimelineEvent[],
  incoming: AgentTimelineEvent[],
): AgentTimelineEvent[] {
  const byId = new Map(current.map((event) => [event.id, event]));
  for (const event of incoming) byId.set(event.id, event);
  return sortTimelineEvents([...byId.values()]);
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

export function createAttachmentFromFile(file: { name: string; size?: number }, index = 0) {
  const name = file.name.trim() || 'untitled';
  const kind = classifyAttachmentKind(name);
  const sizeBytes = file.size ?? 0;
  const attachment: AgentAttachment = {
    id: `att-${slug(name)}-${sizeBytes}-${index}`,
    name,
    kind,
    sizeBytes,
    status: 'ready',
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

function markLastPendingFailed(messages: AgentMessage[]): AgentMessage[] {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].status === 'pending') {
      return messages.map((message, idx) =>
        idx === i ? { ...message, status: 'failed' as const } : message,
      );
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
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 32);
}
