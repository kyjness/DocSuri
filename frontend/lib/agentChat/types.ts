export const AGENT_MODES = ['evidence', 'novelty'] as const;

export type AgentMode = (typeof AGENT_MODES)[number];
export type AgentJobState = 'idle' | 'queued' | 'running' | 'completed' | 'failed' | 'degraded';
export type AgentMessageRole = 'user' | 'agent';
export type AgentAttachmentKind = 'pdf' | 'markdown' | 'text' | 'unknown';
export type AgentAttachmentStatus = 'ready' | 'reading' | 'rejected';
export type AgentTimelineState = 'running' | 'completed' | 'failed' | 'degraded';

export interface AgentAttachment {
  id: string;
  name: string;
  kind: AgentAttachmentKind;
  sizeBytes: number;
  status: AgentAttachmentStatus;
  error?: string;
  /** PR3 — backend upload metadata for user PDFs; origin is encoded by paperId=userdoc:{uuid}. */
  objectKey?: string;
  paperId?: string;
  recordRef?: string;
  /** Browser-local source used only for the raw PDF upload. Never sent in JSON payloads. */
  sourceFile?: Blob;
  /** US-EV4(#268)/US-NV2(#252) — md/txt 본문(≤256KiB). PDF는 raw upload로 전달된다. */
  contentText?: string;
}

export interface AgentTimelineEvent {
  id: string;
  stage: string;
  label: string;
  detail?: string;
  state: AgentTimelineState;
  sequence?: number;
  source?: string;
}

/**
 * 서버가 확정하는 메시지 분류(FR-44). 프론트는 분류하지 않고 렌더링만 나눈다.
 * - steering: 조사 중 잡에 보낸 지시 (다음 판단 시점에 반영)
 * - on_demand_request: 종단 잡에 보낸 생성/질문 요청
 * - agent_reply: 에이전트 답변. resultingArtifactRef가 있으면 산출물을 만든 것
 * - notice: 시스템 안내(불가 사유·게이트 거부 등)
 */
export type AgentMessageKind = 'steering' | 'on_demand_request' | 'agent_reply' | 'notice';

export interface AgentMessage {
  id: string;
  role: AgentMessageRole;
  content: string;
  createdAt: string;
  attachments?: AgentAttachment[];
  status?: 'pending' | 'sent' | 'failed';
  kind?: AgentMessageKind;
  /** 이 답변이 생성한 산출물(artifactId) — 없으면 답변만 한 턴이다(BLM §5.5). */
  resultingArtifactRef?: string;
}

export interface AgentSessionSummary {
  id: string;
  title: string;
  mode: AgentMode;
  state: AgentJobState;
  updatedAt: string;
}

export interface AgentSessionSnapshot {
  session: AgentSessionSummary;
  messages: AgentMessage[];
  events: AgentTimelineEvent[];
  /** evidence — 아직 실행 중인 턴(v3 §5). 새로고침 뒤 이벤트 구독을 다시 붙이는 좌표다. */
  activeTurnId?: string | null;
}

/** evidence 턴 수락(202) — 실행은 백그라운드, 진행은 turnId로 구독한다(v3 §5.1). */
export interface AgentTurnAccepted {
  session: AgentSessionSummary;
  turnId: string;
}

/** evidence 턴 종단 — 터미널 result 프레임(또는 폴링)에서 만든 답변 메시지. */
export interface AgentTurnFinished {
  turnId: string;
  message: AgentMessage;
  outcome: AgentJobState;
  cancelled: boolean;
}

export interface AgentSessionListResponse {
  sessions: AgentSessionSummary[];
}

export interface AgentSendMessageRequest {
  content: string;
  mode: AgentMode;
  attachments?: AgentAttachment[];
}

export interface AgentSendMessageResult {
  session: AgentSessionSummary;
  messages: AgentMessage[];
  events: AgentTimelineEvent[];
  outcome: AgentJobState;
  retryable?: boolean;
  errorMessage?: string;
}
