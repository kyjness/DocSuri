'use client';

import { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { UserFacingError, getApiClient } from '@/lib/api';
import { parseNoveltySseEvents } from '@/lib/agentChat/sse';
import { NotionExportPanel } from './NotionExportPanel';
import {
  MAX_AGENT_ATTACHMENT_TEXT_CHARS,
  agentReducer,
  canSend,
  createAttachmentFromFile,
  createDraftSession,
  createUserMessage,
  initialAgentChatState,
} from '@/lib/agentChat/state';
import type {
  AgentAttachment,
  AgentJobState,
  AgentMessage,
  AgentMode,
  AgentSessionSummary,
  AgentTimelineEvent,
  AgentTimelineState,
} from '@/lib/agentChat/types';
import {
  abstainReasonLabel,
  anchorHref,
  evidenceLine,
  groupClaimsByPaper,
  sourceHref,
  sourceLabel,
  parseAgentContent,
  type EvidenceResultPayload,
  type EvidenceSourceRef,
  anchorTypeLabel,
  canJumpToSource,
  examinedRangeMessage,
  sourceScopeBadge,
} from '@/lib/agentChat/evidenceResult';
import type {
  EvidenceAnswer,
  EvidenceClaim,
  EvidenceCoverage,
  EvidencePaperGroup,
  EvidenceRow,
} from '@/lib/agentChat/evidenceResult';
import type { AnswerSegmentRole } from '@/types/generated/evidence';
import {
  SIMILAR_WORK_COLUMNS,
  confidenceLabel,
  detailCell,
  itemsOf,
  listField,
  pickRefs,
  pickText,
  sourceRefsOf,
} from '@/lib/agentChat/noveltyResult';
import type {
  NoveltyArtifact,
  NoveltyPayloadItem,
  NoveltyResultPayload,
  NoveltySourceRef,
} from '@/lib/agentChat/noveltyResult';
import styles from './AgentChatScreen.module.css';

const MODE_LABEL: Record<AgentMode, string> = {
  evidence: 'Evidence',
  novelty: 'Novelty',
};

const JOB_STATE_LABEL: Record<AgentJobState, string> = {
  idle: '대기',
  queued: '대기',
  running: '진행 중',
  completed: '완료',
  failed: '실패',
  degraded: '저하',
};
const AGENT_REFRESH_MS = 1000;
// 종단 잡의 온디맨드 답장을 기다리는 폴링 상한 — 워커가 죽어도 무한히 돌지 않는다.
const AGENT_REPLY_WAIT_MS = 120_000;
const STREAM_CHAR_MS = 8;
const SSE_FETCH_TIMEOUT_MS = 5000;
const EVIDENCE_MODE_ENABLED =
  !process.env.NEXT_PUBLIC_DOCSURI_REAL_API ||
  process.env.NEXT_PUBLIC_DOCSURI_EVIDENCE_AGENT_ENABLED === '1';
// 데모 배포에서는 Novelty를 내보내지 않는다(로드맵 ⑪ — ⑩-2 재정의를 하지 않기로 했고,
// 지금 노출된 것은 그 재정의 이전의 v2다). Evidence와 **같은 모양**으로 건다: 목 전송
// (로컬·테스트)에서는 그대로 보이고, 실 API를 붙인 배포에서만 명시적으로 켜야 보인다.
// 반대로 걸면(기본 노출) 배포에서 env 하나를 빠뜨리는 것이 곧 노출이 되는데, 그 실패는
// 배포본을 열어보기 전까지 아무 데도 안 보인다.
const NOVELTY_MODE_ENABLED =
  !process.env.NEXT_PUBLIC_DOCSURI_REAL_API ||
  process.env.NEXT_PUBLIC_DOCSURI_NOVELTY_ENABLED === '1';

export function AgentChatScreen() {
  const api = useMemo(() => getApiClient(), []);
  const [state, dispatch] = useReducer(agentReducer, initialAgentChatState);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const awaitingAgentResponseRef = useRef(false);
  const lastSseEventIdRef = useRef<string | null>(null);
  const seenAgentMessageIdsRef = useRef<Set<string>>(new Set());
  const activeSessionId = state.session?.id;
  const activeMode = state.session?.mode;
  const pollSession = shouldPollSession(
    state.jobState,
    state.messages,
    state.submitting,
    state.activeTurnId,
  );

  useEffect(() => {
    let alive = true;
    api
      .listAgentSessions()
      .then((sessions) => {
        if (alive) dispatch({ type: 'sessionsLoaded', sessions });
      })
      .catch(() => {
        if (alive) {
          dispatch({
            type: 'sendFailure',
            message: '과거 세션을 불러오지 못했습니다.',
          });
        }
      });
    return () => {
      alive = false;
    };
  }, [api]);

  useEffect(() => {
    lastSseEventIdRef.current = null;
  }, [activeSessionId]);

  useEffect(() => {
    const agentMessageIds = state.messages
      .filter((message) => message.role === 'agent')
      .map((message) => message.id);
    const newestAgentMessageId = agentMessageIds.at(-1);
    const seen = seenAgentMessageIdsRef.current;
    const shouldStream =
      awaitingAgentResponseRef.current &&
      Boolean(newestAgentMessageId) &&
      !seen.has(newestAgentMessageId ?? '');
    for (const id of agentMessageIds) seen.add(id);
    if (shouldStream && newestAgentMessageId) {
      awaitingAgentResponseRef.current = false;
      setStreamingMessageId(newestAgentMessageId);
    }
  }, [state.messages]);

  useEffect(() => {
    if (!activeSessionId || !activeSessionId.includes(':') || !pollSession) return;
    const jobRunning = state.jobState === 'queued' || state.jobState === 'running';
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let waited = 0;
    const refresh = async () => {
      try {
        const snapshot = await api.loadAgentSession(activeSessionId);
        if (alive) dispatch({ type: 'refreshSession', snapshot });
      } catch {
        // Keep the last known snapshot; the next user action can retry explicitly.
      } finally {
        // 실행 중인 잡은 종단까지 계속 따라가고, 답장 대기는 상한까지만 기다린다.
        waited += AGENT_REFRESH_MS;
        if (alive && (jobRunning || waited < AGENT_REPLY_WAIT_MS)) {
          timer = setTimeout(refresh, AGENT_REFRESH_MS);
        }
      }
    };
    void refresh();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [activeSessionId, api, pollSession, state.jobState]);

  // v3 §5.3 — evidence 턴 이벤트 구독. activeTurnId가 있는 동안 이 effect가 답변의 유일한
  // 작성자다(스냅샷 폴링은 멈춘다). 끊기면 클라이언트가 after=seq로 다시 붙고, 그래도 안
  // 되면 GET /turns/{id} 폴링으로 내려간다 — 새로고침 뒤에도 같은 길로 재부착된다.
  const activeTurnId = state.activeTurnId;
  useEffect(() => {
    if (!activeTurnId || activeMode !== 'evidence') return;
    let alive = true;
    // 버려진 구독은 서버 제너레이터를 상한(10분)까지 초당 폴링하게 둔다 — 끊어 준다.
    const subscription = new AbortController();
    awaitingAgentResponseRef.current = true;
    api
      .followEvidenceTurn(
        activeTurnId,
        (events) => {
          if (alive) dispatch({ type: 'eventsReceived', events });
        },
        subscription.signal,
      )
      .then((finished) => {
        if (alive) dispatch({ type: 'turnFinished', finished });
      })
      .catch((error) => {
        if (!alive) return;
        awaitingAgentResponseRef.current = false;
        dispatch({
          type: 'sendFailure',
          message:
            error instanceof UserFacingError
              ? error.message
              : '답변을 받지 못했습니다. 세션을 다시 열어 주세요.',
        });
      });
    return () => {
      alive = false;
      subscription.abort();
    };
  }, [activeTurnId, activeMode, api]);

  useEffect(() => {
    if (
      !activeSessionId ||
      activeMode !== 'novelty' ||
      (state.jobState !== 'queued' && state.jobState !== 'running')
    ) {
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refreshEvents = async () => {
      try {
        const events = await loadNoveltySseEvents(activeSessionId, lastSseEventIdRef.current);
        if (!alive) return;
        if (events.length) {
          lastSseEventIdRef.current = events.at(-1)?.id ?? lastSseEventIdRef.current;
          dispatch({ type: 'eventsReceived', events });
        }
      } catch {
        // The full session poll remains the fallback if the event stream is unavailable.
      } finally {
        if (alive) timer = setTimeout(refreshEvents, AGENT_REFRESH_MS);
      }
    };
    void refreshEvents();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [activeMode, activeSessionId, state.jobState]);

  function startMode(mode: AgentMode) {
    resetStreamingState();
    dispatch({ type: 'startSession', session: createDraftSession(mode) });
  }

  async function loadSession(session: AgentSessionSummary) {
    try {
      resetStreamingState();
      const snapshot = await api.loadAgentSession(session.id);
      dispatch({ type: 'loadSession', snapshot });
      setDrawerOpen(false);
    } catch {
      dispatch({ type: 'sendFailure', message: '세션을 불러오지 못했습니다.' });
    }
  }

  async function deleteSession(session: AgentSessionSummary) {
    try {
      await api.deleteAgentSession(session.id);
      dispatch({ type: 'deleteSession', id: session.id });
    } catch {
      dispatch({ type: 'sendFailure', message: '세션을 삭제하지 못했습니다.' });
    }
  }

  async function resetAllSessions() {
    try {
      await api.resetAgentSessions();
      resetStreamingState();
      dispatch({ type: 'resetSessions' });
      setDrawerOpen(false);
    } catch {
      dispatch({ type: 'sendFailure', message: '세션을 초기화하지 못했습니다.' });
    }
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!canSend(state) || !state.session || !state.mode) return;

    const content = state.draft.trim();
    const attachments = state.attachments.filter((item) => item.status === 'ready');
    const userMessage = createUserMessage(content, attachments);
    awaitingAgentResponseRef.current = true;
    setStreamingMessageId(null);
    dispatch({ type: 'sendStart', message: userMessage });

    try {
      if (state.mode === 'evidence') {
        // v3 §5.1 — 수락만 받고 돌아온다. 진행·답변은 activeTurnId 구독 effect가 받는다.
        const accepted = await api.acceptEvidenceTurn(state.session.id, {
          content,
          mode: state.mode,
          attachments,
        });
        dispatch({ type: 'turnAccepted', accepted });
        return;
      }
      const result = await api.sendAgentMessage(state.session.id, {
        content,
        mode: state.mode,
        attachments,
      });
      dispatch({ type: 'sendSuccess', result });
    } catch (error) {
      awaitingAgentResponseRef.current = false;
      dispatch({
        type: 'sendFailure',
        message:
          error instanceof UserFacingError ? error.message : '에이전트 요청을 처리하지 못했습니다.',
      });
    }
  }

  function attach(files: FileList | null) {
    if (!files) return;
    Array.from(files).forEach((file, idx) => {
      const attachment = createAttachmentFromFile(file, state.attachments.length + idx);
      // US-EV4(#268)/US-NV2(#252) — md/txt는 본문을 읽어 동봉한다. 읽기가 끝날 때까지
      // 'reading'으로 전송을 막아(canSend all-ready) 본문 없는 전송 레이스를 없앤다.
      const needsContent = attachment.status === 'ready' && attachment.kind !== 'pdf';
      dispatch({
        type: 'addAttachment',
        attachment: needsContent ? { ...attachment, status: 'reading' } : attachment,
      });
      if (needsContent) {
        readAttachmentText(file)
          .then((text) =>
            dispatch({
              type: 'attachmentContentReady',
              id: attachment.id,
              contentText: text.slice(0, MAX_AGENT_ATTACHMENT_TEXT_CHARS),
            }),
          )
          .catch(() =>
            dispatch({ type: 'attachmentContentReady', id: attachment.id, contentText: '' }),
          );
      }
    });
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  async function cancelTurn() {
    if (!state.activeTurnId || state.cancelRequested) return;
    dispatch({ type: 'cancelRequested' });
    try {
      await api.cancelEvidenceTurn(state.activeTurnId);
    } catch {
      // 취소 요청 실패 — 턴은 계속 돌고 결과는 구독이 받는다. 버튼만 되살릴 이유가 없다.
    }
  }

  function resetStreamingState() {
    awaitingAgentResponseRef.current = false;
    seenAgentMessageIdsRef.current = new Set();
    setStreamingMessageId(null);
  }

  return (
    <section
      className={styles.shell}
      data-mode={state.mode ?? undefined}
      data-testid="agent-chat-screen"
    >
      <div className={styles.toolbar}>
        <button
          type="button"
          className={styles.iconButton}
          onClick={() => setDrawerOpen(true)}
          aria-label="과거 세션"
          data-testid="agent-menu"
        >
          <MenuIcon />
        </button>
        <div className={styles.status}>
          <span>{state.mode ? MODE_LABEL[state.mode] : '에이전트'}</span>
          {state.jobState !== 'idle' ? <JobStateBadge state={state.jobState} /> : null}
        </div>
      </div>

      {!state.mode ? (
        <AgentModePicker
          onSelect={startMode}
          evidenceEnabled={EVIDENCE_MODE_ENABLED}
          noveltyEnabled={NOVELTY_MODE_ENABLED}
        />
      ) : null}

      <AgentMessageList messages={state.messages} streamingMessageId={streamingMessageId} />
      <AgentProgressTimeline events={state.events} jobState={state.jobState} />

      {/* US-NV8(#258) — novelty 결과가 터미널이면 미리보기→승인 export 패널 노출 */}
      {state.mode === 'novelty' &&
      state.session &&
      (state.jobState === 'completed' || state.jobState === 'degraded') ? (
        <NotionExportPanel jobId={state.session.id} />
      ) : null}

      {state.error ? (
        <p className={styles.error} role="status" data-testid="agent-error">
          {state.error}
        </p>
      ) : null}

      <AgentAttachmentDrawer
        attachments={state.attachments}
        onRemove={(id) => dispatch({ type: 'removeAttachment', id })}
      />

      <form className={styles.composer} onSubmit={submit}>
        <button
          type="button"
          className={styles.attachButton}
          onClick={() => fileInputRef.current?.click()}
          aria-label="파일 추가"
          data-testid="agent-attach-button"
          disabled={!state.mode || state.submitting || Boolean(state.activeTurnId)}
        >
          +
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className={styles.fileInput}
          accept=".pdf,.md,.markdown,.txt,application/pdf,text/plain,text/markdown"
          multiple
          onChange={(e) => attach(e.currentTarget.files)}
          data-testid="agent-file-input"
        />
        <textarea
          className={styles.input}
          value={state.draft}
          onChange={(e) => dispatch({ type: 'setDraft', draft: e.target.value })}
          placeholder={state.mode ? '메시지를 입력하세요' : '먼저 모드를 선택하세요'}
          aria-label="에이전트 메시지"
          data-testid="agent-composer-input"
          disabled={!state.mode || state.submitting || Boolean(state.activeTurnId)}
          rows={1}
        />
        {state.mode === 'evidence' && state.activeTurnId ? (
          // v3 §2.8 — 취소는 처음부터 끝까지 가능하다. 하던 단계가 끝나는 대로 멈추고
          // 그때까지의 근거로 부분 답을 만든다.
          <button
            type="button"
            className={styles.sendButton}
            onClick={() => void cancelTurn()}
            disabled={state.cancelRequested}
            data-testid="agent-composer-cancel"
          >
            {state.cancelRequested ? '취소 중…' : '취소'}
          </button>
        ) : (
          <button
            type="submit"
            className={styles.sendButton}
            disabled={!canSend(state)}
            data-testid="agent-composer-submit"
          >
            전송
          </button>
        )}
      </form>

      {/* 조사 중에도 입력은 열려 있다 — 다만 지시는 즉시가 아니라 다음 판단 시점에
          반영되므로(BLM §6), 반응이 없어 먹혔다고 오해하지 않게 알린다. */}
      {state.mode === 'novelty' &&
      (state.jobState === 'queued' || state.jobState === 'running') ? (
        <p className={styles.composerHint} data-testid="agent-steering-hint">
          지시는 다음 판단 시점에 반영됩니다.
        </p>
      ) : null}

      {drawerOpen ? (
        <AgentSessionDrawer
          sessions={state.sessions}
          activeId={state.session?.id ?? null}
          onClose={() => setDrawerOpen(false)}
          onNew={() => {
            resetStreamingState();
            dispatch({ type: 'newChat' });
            setDrawerOpen(false);
          }}
          onLoad={loadSession}
          onDelete={deleteSession}
          onResetAll={resetAllSessions}
        />
      ) : null}
    </section>
  );
}

function readAttachmentText(file: File): Promise<string> {
  // jsdom은 File.text()가 없다 — 브라우저·테스트 양쪽에서 동작하는 FileReader 폴백.
  if (typeof file.text === 'function') return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

function AgentModePicker({
  onSelect,
  evidenceEnabled,
  noveltyEnabled,
}: {
  onSelect: (mode: AgentMode) => void;
  evidenceEnabled: boolean;
  noveltyEnabled: boolean;
}) {
  return (
    <div className={styles.modePicker} data-testid="agent-mode-picker">
      <button
        type="button"
        onClick={() => onSelect('evidence')}
        disabled={!evidenceEnabled}
        aria-label={evidenceEnabled ? 'Evidence' : 'Evidence 준비 중'}
        data-mode="evidence"
        data-testid="agent-mode-evidence"
      >
        <strong>Evidence</strong>
        <span>질문을 던지면 논문 근거로 판단해 답해요</span>
        <span className={styles.modeHint}>판단 · 근거 목록 · 논문 간 상충까지</span>
      </button>
      {noveltyEnabled ? (
        <button
          type="button"
          onClick={() => onSelect('novelty')}
          data-mode="novelty"
          data-testid="agent-mode-novelty"
        >
          <strong>Novelty</strong>
          <span>Evidence로 근거부터 자동 확인한 뒤, 차별화 아이디어를 제안해요</span>
          <span className={styles.modeHint}>유사 연구 비교표 · 실험 아이디어 · 실험 계획까지</span>
        </button>
      ) : null}
    </div>
  );
}

function AgentSessionDrawer({
  sessions,
  activeId,
  onClose,
  onNew,
  onLoad,
  onDelete,
  onResetAll,
}: {
  sessions: AgentSessionSummary[];
  activeId: string | null;
  onClose: () => void;
  onNew: () => void;
  onLoad: (session: AgentSessionSummary) => void;
  onDelete: (session: AgentSessionSummary) => void;
  onResetAll: () => void;
}) {
  // US-EV8(#272) — 파괴적 동작이라 브라우저 confirm 대신 인라인 2단계 확인.
  const [confirmingReset, setConfirmingReset] = useState(false);
  return (
    <div className={styles.drawerOverlay} data-testid="agent-session-drawer">
      <aside className={styles.drawer} aria-label="과거 세션">
        <div className={styles.drawerHeader}>
          <button type="button" onClick={onNew} data-testid="agent-session-new">
            새 채팅
          </button>
          <button type="button" className={styles.closeButton} onClick={onClose} aria-label="닫기">
            ×
          </button>
        </div>
        <div className={styles.sessionList}>
          {sessions.map((session) => (
            <div
              key={session.id}
              className={styles.sessionRow}
              data-active={session.id === activeId}
              data-mode={session.mode}
            >
              <button type="button" onClick={() => onLoad(session)}>
                <span>{session.title}</span>
                <small>
                  {MODE_LABEL[session.mode]} · {JOB_STATE_LABEL[session.state]} ·{' '}
                  {formatSessionUpdatedAt(session.updatedAt)}
                </small>
              </button>
              <button
                type="button"
                className={styles.deleteButton}
                onClick={() => onDelete(session)}
                aria-label={`${session.title} 삭제`}
              >
                삭제
              </button>
            </div>
          ))}
          {sessions.length === 0 ? <p className={styles.empty}>저장된 세션이 없습니다.</p> : null}
        </div>
        <div className={styles.drawerFooter}>
          {confirmingReset ? (
            <div className={styles.resetConfirm}>
              <span>모든 세션을 삭제할까요?</span>
              <button
                type="button"
                onClick={() => {
                  setConfirmingReset(false);
                  onResetAll();
                }}
                data-testid="agent-session-reset-confirm"
              >
                삭제
              </button>
              <button type="button" onClick={() => setConfirmingReset(false)}>
                취소
              </button>
            </div>
          ) : (
            <button
              type="button"
              className={styles.resetButton}
              onClick={() => setConfirmingReset(true)}
              disabled={sessions.length === 0}
              data-testid="agent-session-reset"
            >
              전체 초기화
            </button>
          )}
        </div>
      </aside>
    </div>
  );
}

function AgentMessageList({
  messages,
  streamingMessageId,
}: {
  messages: AgentMessage[];
  streamingMessageId: string | null;
}) {
  return (
    <div className={styles.messages} data-testid="agent-message-list">
      {messages.length === 0 ? <p className={styles.empty}>대화를 시작하세요.</p> : null}
      {messages.map((message) => (
        <AgentMessageItem
          key={message.id}
          message={message}
          streaming={message.id === streamingMessageId}
        />
      ))}
    </div>
  );
}

function AgentMessageItem({ message, streaming }: { message: AgentMessage; streaming: boolean }) {
  return (
    <article
      className={styles.message}
      data-role={message.role}
      data-status={message.status ?? 'sent'}
      data-streaming={streaming && message.role === 'agent'}
      data-testid="agent-message"
    >
      <AgentMessageContent message={message} streaming={streaming} />
      {message.attachments?.length ? (
        <div className={styles.messageFiles}>
          {message.attachments.map((file) => (
            <span key={file.id}>{file.name}</span>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function AgentMessageContent({
  message,
  streaming,
}: {
  message: AgentMessage;
  streaming: boolean;
}) {
  // evidence orchestrator 결과(JSON/[abstain]/[error])는 agent(assistant) 메시지에서만 나온다.
  // 사용자가 타이핑한 텍스트가 우연히 JSON처럼 보여도 파싱을 시도하지 않도록 role로 분기한다.
  if (message.role !== 'agent') {
    return <p>{message.content}</p>;
  }

  // 시스템 안내(불가 사유·게이트 거부) — 답변과 섞이지 않게 구분해 보여준다.
  if (message.kind === 'notice') {
    return (
      <p className={styles.abstainNotice} data-testid="agent-notice">
        {message.content}
      </p>
    );
  }

  const parsed = parseAgentContent(message.content);

  // 구조화 결과(근거 카드/보류/오류)는 스트리밍하지 않고 즉시 렌더링한다 — JSON을 한 글자씩
  // 노출하면 완성 전까지 깨져 보인다. 일반 텍스트 답변만 타자기 효과로 스트리밍한다.
  if (parsed.kind === 'evidence') {
    return <EvidenceResultView result={parsed.result} scope={message.id} />;
  }
  if (parsed.kind === 'novelty') {
    return <NoveltyResultView result={parsed.result} />;
  }
  if (parsed.kind === 'abstain') {
    return <p className={styles.abstainNotice}>{abstainReasonLabel(parsed.reason)}</p>;
  }
  if (parsed.kind === 'error') {
    return <p className={styles.abstainNotice}>일시적인 오류로 답변을 생성하지 못했습니다.</p>;
  }
  return <StreamingText text={parsed.text} streaming={streaming} />;
}

function StreamingText({ text, streaming }: { text: string; streaming: boolean }) {
  const visible = useStreamingText(text, streaming);
  return <p>{visible}</p>;
}

function useStreamingText(content: string, enabled: boolean): string {
  const [visible, setVisible] = useState(enabled ? '' : content);

  useEffect(() => {
    if (!enabled) {
      setVisible(content);
      return;
    }
    let index = 0;
    setVisible('');
    const timer = setInterval(() => {
      index += 1;
      setVisible(content.slice(0, index));
      if (index >= content.length) clearInterval(timer);
    }, STREAM_CHAR_MS);
    return () => clearInterval(timer);
  }, [content, enabled]);

  return visible;
}

/**
 * 판단 산문 + 근거 목록(v3 §2.1·§8).
 *
 * 종전에는 "핵심 주장" 카드를 나열했다 — 화면이 근거 카드 생성기를 광고하고 있었고,
 * 판단이 어디에도 없었다(§9 ★1·11). 이제 산문 판단이 먼저 오고 그 아래 근거 목록이 붙는다.
 * `[n]`은 목록의 명제 번호이고, 눌러 그 명제로 이동한다(접혀 있으면 목록이 함께 펴진다).
 */
export function EvidenceResultView({
  result,
  scope,
}: {
  result: EvidenceResultPayload;
  scope: string;
}) {
  // 접기 상태는 **여기서** 산다. 판단 산문의 `[9]`가 접힌 근거를 가리키면 점프가 아무 일도
  // 하지 않으므로(감춰진 요소로는 스크롤되지 않는다), 그 번호를 누를 때 목록이 함께 펴져야
  // 한다. 상태를 목록 안에 두면 산문이 그것을 건드릴 수 없다.
  // 접기 상태는 **논문별**이다. 상태를 그룹 안에 두면 판단 산문이 못 건드리는데, 산문의
  // `[9]`가 접힌 줄을 가리키면 그 논문 그룹이 함께 펴져야 한다.
  const [expandedPapers, setExpandedPapers] = useState<ReadonlySet<string>>(() => new Set());
  // 문장 0건짜리 answer는 없는 것과 같다 — 판정을 한 번만 하고 그 결과를 쓴다.
  const answer = result.answer?.segments.length ? result.answer : null;
  if (result.claims.length === 0) {
    // 근거가 없어도 판단 문장이 있으면 그것을 보여준다 — 기권 문구로 덮으면 답이 사라진다.
    if (answer) {
      return <AnswerProse answer={answer} scope={scope} />;
    }
    return <p className={styles.abstainNotice}>제시할 수 있는 근거를 찾지 못했습니다.</p>;
  }
  return (
    <div className={styles.evidenceClaims}>
      {answer ? (
        <AnswerProse
          answer={answer}
          scope={scope}
          onRefJump={(n) => {
            // 그 번호가 어느 논문 그룹에 있는지는 그룹핑이 안다 — 화면이 다시 세지 않는다.
            const owner = groupClaimsByPaper(result.claims).papers.find((g) =>
              g.rows.some((row) => row.number === n),
            );
            if (owner) {
              setExpandedPapers((open) => new Set(open).add(owner.paperId));
            }
          }}
        />
      ) : null}
      <EvidenceClaimList
        claims={result.claims}
        scope={scope}
        expandedPapers={expandedPapers}
        onExpandPaper={(paperId) => setExpandedPapers((open) => new Set(open).add(paperId))}
      />
      {/* 이 수는 검색 범위가 아니라 **근거로 쓴 논문 수**다. 종전 라벨("검색 범위 · 참고
          논문 N편 · 검색어: <사용자 질문>")은 둘 다 거짓말이었다 — 검색은 코퍼스 전체를
          돌았고, 실려 있던 "검색어"는 모델이 쓴 질의가 아니라 사용자 질문 원문이라 바로
          위 말풍선을 되풀이할 뿐이었다. */}
      <p className={styles.evidenceCoverage}>
        근거로 쓴 논문 {result.coverage.paperCount}편
      </p>
      <ExaminedRange coverage={result.coverage} />
    </div>
  );
}

const SYNTHESIS_HINT = '여러 근거를 종합한 문장이에요 — 원문에 그대로 있진 않아요';

/**
 * 판단 산문 — 문장마다 **역할**이 있고 화면이 그것을 쓴다(§4.2).
 *
 * 종전에는 문장 배열을 한 단락으로 그냥 이어붙였다. 결론도 갈림 지점도 근거 서술과 같은
 * 줄에 섞여 흘러서, 판단이 있는데 "줄줄 나열"로 읽혔다.
 *
 * **표시 순서는 배열 순서다** — 역할로 다시 정렬하지 않는다. 프롬프트가 결론을 맨 앞에
 * 두라고 하고, 순서를 여기서 바꾸면 모델이 의도한 논지 전개가 어긋난다.
 *
 * 역할이 없으면(옛 턴·폴백 답변·어휘 밖 선언) 전부 `evidence`로 읽혀 종전과 같은 평평한
 * 산문이 나간다 — 구조를 못 얻을 뿐 문장이 사라지지 않는다.
 */
function AnswerProse({
  answer,
  scope,
  onRefJump,
}: {
  answer: EvidenceAnswer;
  scope: string;
  onRefJump?: (refNumber: number) => void;
}) {
  return (
    <div className={styles.evidenceAnswer} data-testid="evidence-answer">
      {answer.segments.map((segment, idx) => {
        const role = segment.role ?? 'evidence';
        const roleLabel = ANSWER_ROLE_LABEL[role];
        return (
          <p key={idx} className={styles.answerSegment} data-segment-role={role}>
            {roleLabel ? (
              <span className={styles.answerRoleLabel} data-testid="evidence-answer-role">
                {roleLabel}
              </span>
            ) : null}
            <span
              className={
                segment.kind === 'synthesis' ? styles.answerSynthesis : styles.answerCited
              }
              data-segment-kind={segment.kind}
            >
              {segment.text}
            </span>
            {segment.refs.map((ref) => (
              <a
                key={ref}
                className={styles.answerRef}
                href={`#${evidenceRowId(scope, ref)}`}
                data-testid="evidence-answer-ref"
                onClick={() => onRefJump?.(ref)}
              >
                [{ref}]
              </a>
            ))}
            {/* 기계가 확인하지 못한 문장은 숨기지도, 같은 급으로 보이게 하지도 않는다(§2.1). */}
            {segment.kind === 'synthesis' ? (
              <span className={styles.answerSynthesisBadge} title={SYNTHESIS_HINT}>
                종합
              </span>
            ) : null}
          </p>
        );
      })}
    </div>
  );
}

/* 역할 표시는 결론·갈림 지점에만 붙는다 — 근거 서술은 대다수라 라벨을 달면 소음이 된다.
   키를 생성 타입에 묶어야 스키마에 역할이 늘 때 **컴파일이 막는다**. `Record<string, …>`이면
   타입 검사가 통과한 채로 그 문장만 표시를 잃고, 그 사실은 화면에서만 보인다. */
const ANSWER_ROLE_LABEL: Partial<Record<AnswerSegmentRole, string>> = {
  conclusion: '결론',
  divergence: '갈리는 지점',
};

// 행 id는 **메시지 단위**다. 한 세션에 evidence 턴이 둘이면 `[n]`이 둘 다 같은 번호를
// 쓰므로, 메시지로 좁히지 않으면 뒤 답변의 `[1]`이 앞 메시지의 표로 뛰고 DOM id도 겹친다.
function evidenceRowId(scope: string, row: number): string {
  return `evidence-${scope}-row-${row}`;
}

function ExaminedRange({ coverage }: { coverage: EvidenceCoverage }) {
  // 확인 범위(FR-37 v2) — 탐색이 완결되지 않았을 때만 나온다.
  const message = examinedRangeMessage(coverage);
  if (!message) return null;
  return (
    <p className={styles.evidenceExamined} data-testid="evidence-examined-range">
      {message}
    </p>
  );
}

/** 논문마다 처음에 펴 두는 근거 수. 넘는 만큼은 접고 눌러서 편다. */
export const EVIDENCE_VISIBLE_PER_PAPER = 3;

/**
 * 근거 목록 — **논문 하나가 블록 하나다**(§2.1).
 *
 * 종전에는 근거 하나가 블록이었다. 논문이 한두 편인 흔한 턴에서 같은 제목이 근거마다 반복돼
 * (실측: 논문 2편에 근거 10건 → 제목이 일곱 번) 화면이 이름으로 덮였고, 각 줄이 한국어 명제와
 * 영어 인용문을 둘 다 들어 같은 사실이 세 번 나왔다(판단 산문 → 명제 → 인용문).
 *
 * **상충 근거는 위로 빼낸다.** 논문으로 묶으면 그 근거가 두 블록으로 갈라져 엇갈림을
 * 한자리에서 못 본다 — 표가 있던 이유가 그것이다(BR-EV-5).
 *
 * 순서는 조립이 정한 그대로다. **접기도 순서를 바꾸지 않는다**: 접힌 줄의 번호는 그대로이고
 * DOM에도 남는다 — 산문의 `[9]`가 가리킬 대상이 없으면 링크가 죽는다.
 */
export function EvidenceClaimList({
  claims,
  scope,
  expandedPapers,
  onExpandPaper,
}: {
  claims: EvidenceClaim[];
  scope: string;
  expandedPapers?: ReadonlySet<string>;
  onExpandPaper?: (paperId: string) => void;
}) {
  const { contested, papers } = groupClaimsByPaper(claims);
  return (
    <div className={styles.evidenceList} data-testid="evidence-list">
      {contested.length > 0 ? (
        <section className={styles.evidenceContested} data-testid="evidence-contested">
          <h4 className={styles.evidenceGroupHeading}>쟁점</h4>
          {contested.map(({ number, claim }) => (
            <article key={number} id={evidenceRowId(scope, number)} data-testid="evidence-row">
              <p className={styles.evidenceStatement}>
                <span className={styles.evidenceRowNumber}>[{number}]</span>
                {claim.statement}
              </p>
              <EvidenceRefList refs={claim.supporting} stance="support" />
              <EvidenceRefList refs={claim.conflicting} stance="conflict" />
            </article>
          ))}
        </section>
      ) : null}
      {papers.map((group) => (
        <EvidencePaperBlock
          key={group.paperId}
          group={group}
          claims={claims}
          scope={scope}
          expanded={expandedPapers?.has(group.paperId) ?? false}
          onExpand={() => onExpandPaper?.(group.paperId)}
        />
      ))}
    </div>
  );
}

function EvidencePaperBlock({
  group,
  claims,
  scope,
  expanded,
  onExpand,
}: {
  group: EvidencePaperGroup;
  claims: EvidenceClaim[];
  scope: string;
  expanded: boolean;
  onExpand: () => void;
}) {
  const collapsed = !expanded && group.rows.length > EVIDENCE_VISIBLE_PER_PAPER;
  return (
    <section className={styles.evidencePaper}>
      <p className={styles.evidencePaperHead}>
        <SourceLink refKey={group.ref} />
        <small className={styles.evidencePaperCount}>{group.rows.length}건</small>
      </p>
      {group.rows.map((row, idx) => (
        <article
          key={row.number}
          id={evidenceRowId(scope, row.number)}
          className={styles.evidenceRow}
          data-testid="evidence-row"
          hidden={collapsed && idx >= EVIDENCE_VISIBLE_PER_PAPER}
        >
          <EvidenceRowLine
            row={row}
            statement={claims[row.number - 1]?.statement ?? ''}
          />
        </article>
      ))}
      {collapsed ? (
        <button
          type="button"
          className={styles.evidenceMore}
          onClick={onExpand}
          data-testid="evidence-show-more"
        >
          {group.rows.length - EVIDENCE_VISIBLE_PER_PAPER}건 더 보기
        </button>
      ) : null}
    </section>
  );
}

function EvidenceRowLine({ row, statement }: { row: EvidenceRow; statement: string }) {
  const line = evidenceLine(row.ref, statement);
  const { mark, label } = STANCE[row.stance];
  const chip = anchorTypeLabel(row.ref);
  const href = anchorHref(row.ref);
  return (
    <>
      <span className={styles.evidenceRowHead}>
        <span className={styles.evidenceRowNumber}>[{row.number}]</span>
        <span className={styles.evidenceStanceMark} aria-label={label}>
          {mark}
        </span>
        <AnchorChip refKey={row.ref} href={href} label={chip} />
      </span>
      <p className={styles.evidenceRowText} data-line-kind={line.kind}>
        {line.kind === 'quote' ? `\u201C${line.text}\u201D` : line.text}
      </p>
    </>
  );
}

/** 인용 위치 — 이제 **누르면 그 블록으로 간다**(종전에는 죽은 텍스트였다). */
function AnchorChip({
  refKey: ref,
  href,
  label,
}: {
  refKey: EvidenceSourceRef;
  href: string | null;
  label: string | null;
}) {
  const badge = sourceScopeBadge(ref);
  const text = label ?? (ref.anchor ? `\u00A7 ${ref.anchor}` : null);
  return (
    <>
      {text && href ? (
        <a className={styles.evidenceAnchor} href={href} data-testid="evidence-anchor-link">
          {text}
        </a>
      ) : text ? (
        <span className={styles.evidenceAnchor}>{text}</span>
      ) : null}
      {badge ? (
        <span
          className={styles.evidenceScopeBadge}
          title={badge.hint}
          data-testid="evidence-scope-badge"
        >
          {badge.label}
        </span>
      ) : null}
    </>
  );
}

const STANCE = {
  support: { mark: '✓', label: '지지' },
  conflict: { mark: '✗', label: '상충' },
} as const;

type Stance = keyof typeof STANCE;

/**
 * 쟁점 블록의 출처 목록 — **여기서만** 논문 이름이 줄마다 나온다.
 *
 * 논문 그룹에서는 이름이 헤더에 한 번만 있으면 되지만, 쟁점은 정의상 논문이 엇갈리는
 * 자리라 어느 쪽이 무엇을 말했는지가 줄에 있어야 한다.
 */
function EvidenceRefList({ refs, stance }: { refs: EvidenceSourceRef[]; stance: Stance }) {
  if (refs.length === 0) return null;
  const { mark, label } = STANCE[stance];
  return (
    <ul className={styles.evidenceRefs} data-stance={stance}>
      {refs.map((ref, idx) => (
        <li key={idx} className={styles.evidenceRef}>
          <span className={styles.evidenceSource}>
            <span className={styles.evidenceStanceMark} aria-label={label}>
              {mark}
            </span>
            <SourceLink refKey={ref} />
            <AnchorChip refKey={ref} href={anchorHref(ref)} label={anchorTypeLabel(ref)} />
          </span>
          {ref.quote ? <blockquote className={styles.evidenceQuote}>{ref.quote}</blockquote> : null}
        </li>
      ))}
    </ul>
  );
}


/**
 * 출처 논문 — **제목을 링크로** 건다.
 *
 * 종전에는 `arxiv:2106.09685v2` 같은 식별자를 그냥 텍스트로 찍었다. 사용자는 그것을 보고
 * 무슨 논문인지 알 수 없고, 눌러 갈 수도 없었다. 목적지 규칙은 `sourceHref`가 정한다 —
 * 갈 곳이 없으면(사용자 업로드 문서·미지의 네임스페이스) 링크를 만들지 않는다. 깨진 링크는
 * 링크가 없는 것보다 나쁘다.
 */
function SourceLink({ refKey: ref }: { refKey: EvidenceSourceRef }) {
  const href = sourceHref(ref);
  const label = sourceLabel(ref);
  if (!href) {
    return <span className={styles.evidencePaperTitle}>{label}</span>;
  }
  const external = href.startsWith('http');
  return (
    <a
      className={styles.evidencePaperTitle}
      href={href}
      data-testid="evidence-source-link"
      {...(external ? { target: '_blank', rel: 'noreferrer noopener' } : {})}
    >
      {label}
      {external ? <span aria-label="새 창에서 열림"> ↗</span> : null}
    </a>
  );
}

// 첫 사용자가 각 섹션이 "무엇을·왜" 보여주는지 바로 알 수 있도록 kind별 한 줄 설명.
const NOVELTY_ARTIFACT_HINT: Record<string, string> = {
  evidence: '검색된 논문을 질의 의도에 맞춰 정렬하고 관련도/근거 강도 점수를 붙였어요',
  similar_works: '이미 나와 있는 비슷한 연구들을 찾아 정리했어요',
  external_findings: 'GitHub·데이터셋에서 관련 구현체·자료를 찾았어요',
  novelty_candidates: '위 근거를 바탕으로 제안하는 차별화 실험 아이디어예요',
  experiment_plan: '선택한 아이디어를 검증하기 위한 구체적인 실험 설계예요',
  risk_signals: '업로드한 원고를 검토해 나온 참고용 신호예요',
};

function NoveltyResultView({ result }: { result: NoveltyResultPayload }) {
  if (result.artifacts.length === 0) {
    return <p className={styles.abstainNotice}>표시할 분석 결과가 없습니다.</p>;
  }
  return (
    <div className={styles.noveltyArtifacts}>
      {result.artifacts.map((artifact) => (
        <section key={artifact.artifactId} className={styles.noveltyArtifact}>
          <h4 className={styles.noveltyArtifactTitle}>{artifact.title}</h4>
          {NOVELTY_ARTIFACT_HINT[artifact.kind] ? (
            <p className={styles.noveltyArtifactHint}>{NOVELTY_ARTIFACT_HINT[artifact.kind]}</p>
          ) : null}
          <NoveltyArtifactBody artifact={artifact} />
        </section>
      ))}
    </div>
  );
}

function NoveltyArtifactBody({ artifact }: { artifact: NoveltyArtifact }) {
  if (artifact.kind === 'similar_works') {
    return <SimilarWorksTable items={itemsOf(artifact.payload)} />;
  }
  if (artifact.kind === 'risk_signals') {
    return <RiskSignalList items={itemsOf(artifact.payload)} />;
  }
  if (artifact.kind === 'experiment_plan') {
    return <ExperimentPlanView plan={artifact.payload} />;
  }
  if (artifact.kind === 'novelty_candidates') {
    return <NoveltyCandidatesView items={itemsOf(artifact.payload)} />;
  }
  // external_findings·알 수 없는 kind — 공통 목록 렌더링.
  return <NoveltyItemList items={itemsOf(artifact.payload)} />;
}

function SimilarWorksTable({ items }: { items: NoveltyPayloadItem[] }) {
  if (items.length === 0) {
    return <p className={styles.abstainNotice}>정리할 유사 연구를 찾지 못했습니다.</p>;
  }
  // US-NV3(#253) — 새 스키마(칼럼 키 존재) 아티팩트에서만 상세 칼럼을 편다. null 칸은
  // 추측하지 않았다는 뜻이라 '근거 부족'으로 표시한다(기권 우선, 추측 금지).
  const showDetails = items.some((item) =>
    SIMILAR_WORK_COLUMNS.some((column) => column.key in item),
  );
  return (
    <>
      {showDetails ? (
        <p className={styles.noveltyTableScrollHint}>← 좌우로 밀면 전체 항목을 볼 수 있어요</p>
      ) : null}
      <div className={styles.noveltyTableWrap}>
        <table className={styles.noveltyTable}>
          <thead>
            <tr>
              <th>연구</th>
              <th>요약</th>
              {showDetails
                ? SIMILAR_WORK_COLUMNS.map((column) => <th key={column.key}>{column.label}</th>)
                : null}
              <th>근거</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, idx) => (
              <tr key={idx}>
                <td>{item.title}</td>
                <td>{item.summary ?? item.rationale ?? ''}</td>
                {showDetails
                  ? SIMILAR_WORK_COLUMNS.map((column) => {
                      const value = detailCell(item, column.key);
                      return (
                        <td key={column.key}>
                          {value ?? <span className={styles.noveltyCellAbstain}>근거 부족</span>}
                        </td>
                      );
                    })
                  : null}
                <td>
                  <EvidenceStatusBadge status={item.evidenceStatus} />
                  <NoveltySourceRefLinks refs={sourceRefsOf(item.sourceRefs)} />
                  <NoveltyEvidenceMeta item={item} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function NoveltyItemList({ items }: { items: NoveltyPayloadItem[] }) {
  if (items.length === 0) {
    return <p className={styles.abstainNotice}>표시할 항목이 없습니다.</p>;
  }
  return (
    <ul className={styles.noveltyItems}>
      {items.map((item, idx) => (
        <li key={idx} className={styles.noveltyItem}>
          <div className={styles.noveltyItemHead}>
            <strong>{item.title}</strong>
            <EvidenceStatusBadge status={item.evidenceStatus} />
          </div>
          {item.summary || item.rationale ? <p>{item.summary ?? item.rationale}</p> : null}
          <NoveltySourceRefLinks refs={sourceRefsOf(item.sourceRefs)} />
          <NoveltyEvidenceMeta item={item} />
        </li>
      ))}
    </ul>
  );
}

const RISK_TYPE_LABEL: Record<string, string> = {
  sentence_similarity: '문장 유사도',
  ai_style: 'AI 문체 신호',
};

function RiskSignalList({ items }: { items: NoveltyPayloadItem[] }) {
  if (items.length === 0) {
    return <p className={styles.abstainNotice}>감지된 위험 신호가 없습니다.</p>;
  }
  return (
    <div className={styles.noveltyRisks}>
      {/* US-NV5 AC: 판정이 아닌 검토 신호임을 명시 — 오탐 가능성 고지. */}
      <p className={styles.noveltyRiskCaveat}>
        아래 항목은 검토가 필요한 신호일 뿐, 표절·AI 작성 여부에 대한 판정이 아닙니다. 오탐이 있을
        수 있습니다.
      </p>
      <ul className={styles.noveltyItems}>
        {items.map((item, idx) => (
          <li key={idx} className={styles.noveltyItem}>
            <div className={styles.noveltyItemHead}>
              <strong>{item.title}</strong>
              {item.riskType ? (
                <span className={styles.noveltyRiskType}>
                  {RISK_TYPE_LABEL[item.riskType] ?? item.riskType}
                </span>
              ) : null}
            </div>
            {item.summary ? <p>{item.summary}</p> : null}
            <NoveltyEvidenceMeta item={item} />
          </li>
        ))}
      </ul>
    </div>
  );
}

// 목록 필드 키는 v1(camelCase)·v2(snake_case)에서 철자가 같다 — 두 벌 키가
// 필요한 곳(가설·차별화 포인트·출처)만 pickText/pickRefs로 읽는다.
// hypotheses는 v1 저장분의 복수 가설 목록 — 계속 보여준다.
const PLAN_LIST_FIELDS: Array<{ key: string; label: string }> = [
  { key: 'hypotheses', label: '가설 목록' },
  { key: 'baselines', label: '베이스라인' },
  { key: 'procedure', label: '절차' },
  { key: 'datasets', label: '데이터셋' },
  { key: 'metrics', label: '지표' },
  { key: 'resources', label: '자원' },
  { key: 'risks', label: '리스크' },
];

function ExperimentPlanView({ plan }: { plan: Record<string, unknown> }) {
  const hypothesis = pickText(plan, 'hypothesis', 'researchQuestion');
  const angle = pickText(plan, 'novelty_angle', 'noveltyAngle');
  return (
    <div className={styles.noveltyPlan}>
      {hypothesis ? (
        <>
          <span className={styles.fieldLabel}>가설</span>
          <p className={styles.noveltyPlanQuestion}>{hypothesis}</p>
        </>
      ) : null}
      {angle ? (
        <>
          <span className={styles.fieldLabel}>차별화 포인트</span>
          <p className={styles.noveltyPlanAngle}>{angle}</p>
        </>
      ) : null}
      {PLAN_LIST_FIELDS.map(({ key, label }) => {
        const values = listField(plan, key);
        if (values.length === 0) return null;
        return (
          <div key={key} className={styles.noveltyPlanField}>
            <strong>{label}</strong>
            <ul>
              {values.map((value, idx) => (
                <li key={idx}>{value}</li>
              ))}
            </ul>
          </div>
        );
      })}
      <NoveltySourceRefLinks refs={pickRefs(plan, 'source_refs', 'sourceRefs')} />
    </div>
  );
}

function NoveltyCandidatesView({ items }: { items: NoveltyPayloadItem[] }) {
  if (items.length === 0) {
    return <p className={styles.abstainNotice}>제안할 방향을 찾지 못했습니다.</p>;
  }
  return (
    <ul className={styles.noveltyItems} data-testid="novelty-candidates">
      {items.map((item, idx) => {
        const payload = item as unknown as Record<string, unknown>;
        const excluded = pickText(payload, 'excluded_claims', 'excludedClaims');
        const feasibility = pickText(payload, 'feasibility_notes', 'feasibilityNotes');
        return (
          <li key={idx} className={styles.noveltyItem}>
            <div className={styles.noveltyItemHead}>
              <strong>{pickText(payload, 'angle', 'title')}</strong>
            </div>
            <p>{pickText(payload, 'rationale', 'summary')}</p>
            {feasibility ? (
              <p className={styles.noveltyArtifactHint}>실행 고려사항 — {feasibility}</p>
            ) : null}
            {/* bounded 제안 규칙(BR-NV11): 근거로 뒷받침되지 않는 주장은 명시적으로 제외된다. */}
            {excluded ? (
              <p className={styles.abstainNotice}>주장하지 않는 것 — {excluded}</p>
            ) : null}
            <NoveltySourceRefLinks
              refs={pickRefs(payload, 'supporting_refs', 'supportingRefs', 'source_refs')}
            />
          </li>
        );
      })}
    </ul>
  );
}

function EvidenceStatusBadge({ status }: { status?: string }) {
  if (!status) return null;
  const supported = status === 'supported';
  return (
    <span className={supported ? styles.noveltyBadgeSupported : styles.noveltyBadgeInsufficient}>
      {supported ? '근거 있음' : '근거 부족'}
    </span>
  );
}

function NoveltyEvidenceMeta({ item }: { item: NoveltyPayloadItem }) {
  const confidence = confidenceLabel(item.confidence);
  if (!item.evidenceNote && !confidence && !item.queryUsed) return null;
  return (
    <div className={styles.noveltyEvidenceMeta}>
      {item.evidenceNote ? <span>{item.evidenceNote}</span> : null}
      {confidence ? <strong>관련도/근거 강도 {confidence}</strong> : null}
      {item.queryUsed ? <small>query: {item.queryUsed}</small> : null}
    </div>
  );
}

function NoveltySourceRefLinks({ refs }: { refs: NoveltySourceRef[] }) {
  if (refs.length === 0) return null;
  return (
    <ul className={styles.noveltyRefs}>
      {refs.map((ref, idx) => {
        const label = ref.title || ref.identifier || ref.url || '출처';
        const href = ref.url && /^https?:\/\//.test(ref.url) ? ref.url : null;
        return (
          <li key={idx}>
            {href ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {label}
              </a>
            ) : (
              <span>{label}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * 진행 과정 — **한 줄로 접힌다.** 눌러야 단계가 펼쳐진다.
 *
 * 종전에는 단계가 세로로 쭉 나열됐고 실행 중인 것은 스스로 열려 있었다. 주장형 질문은
 * 도구 호출이 8~10회 붙으므로, 답이 오기 전에 화면이 진행 로그로 덮였다 — 사용자가 보러
 * 온 것은 답이지 로그가 아니다. 접힌 줄은 그 대신 **지금 무엇을 하고 있는지 한 줄**과
 * 누적 시간을 말한다.
 *
 * `accepted`는 목록에서 뺀다. "질문 접수"는 단계가 아니라 스트림이 붙었다는 신호이고
 * (수락 직후 침묵을 막으려고 서버가 동기로 내보낸다), 여기서는 **첫 단계까지 걸린 시간의
 * 기준점(t0)**으로만 쓴다.
 */
export function AgentProgressTimeline({
  events,
  jobState,
}: {
  events: AgentTimelineEvent[];
  jobState: AgentJobState;
}) {
  const [open, setOpen] = useState(false);
  if (events.length === 0) return null;
  const displayEvents = normalizeTimelineDisplay(events, jobState);
  const steps = withStepDurations(displayEvents);
  // 취소 표식은 **세지 않고 접힌 줄이 말한다.** 도구 호출이 아니라 단계 수에 넣으면 3단계짜리
  // 턴이 "4단계"가 되지만, 통째로 빼면 사용자가 취소했다는 사실이 화면에서 사라진다. 접힌
  // 줄이 기본 상태이므로 거기 적으면 펼치지 않고도 보이고, 단계 목록은 실제로 돈 것만 남는다.
  const marker = displayEvents.find((event) => event.stage === 'cancelled');
  // **단계가 0개여도 숨기지 않는다.** 수락 직후에는 `accepted` 프레임 하나뿐인데, 그것은
  // 목록에서 빠지므로 여기서 null을 내면 화면이 통째로 빈다 — 서버가 그 프레임을 폴링 전에
  // 동기로 내보내는 이유("수락 직후 침묵 금지", streaming.py)를 정면으로 무효화한다. 첫
  // decide 왕복은 수십 초가 걸릴 수 있고, 그동안 사용자에게는 아무 표시도 없게 된다.
  const running =
    !marker && (steps.length === 0 || steps.some((step) => step.state === 'running'));
  // 누적은 **단계 합에서 파생한다**. 따로 재면 간격 규칙을 손댈 때 둘이 조용히 어긋나
  // "3단계 · 24.5초"인데 단계 합은 21.5초인 상태가 된다 — 아무 검사도 그 불일치를 안 본다.
  const total = steps.reduce((sum, step) => sum + (step.durationMs ?? 0), 0) || undefined;
  return (
    <details
      className={styles.timeline}
      data-testid="agent-timeline"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary aria-label="탐구 프로세스">
        <span className={styles.timelineHeadline}>
          {running ? (steps[steps.length - 1]?.label ?? ACCEPTED_LABEL) : (marker?.label ?? '진행 과정')}
        </span>
        <small className={styles.timelineMeta}>
          {steps.length}단계
          {total !== undefined ? ` · ${formatDuration(total)}` : ''}
        </small>
        {running ? <span className={styles.spinner} aria-hidden="true" /> : null}
      </summary>
      <div className={styles.timelineSteps}>
        {steps.map((step) => (
          <AgentTimelineItem key={step.id} event={step} />
        ))}
      </div>
    </details>
  );
}

/** 이벤트 목록 → 실제 단계(접수 제외) + 앞 단계와의 간격. */
export function withStepDurations(
  events: AgentTimelineEvent[],
): Array<AgentTimelineEvent & { durationMs?: number }> {
  let previous = msOf(events.find((event) => event.stage === TIMELINE_ACCEPTED_STAGE));
  const steps = [];
  for (const event of events) {
    if (NON_STEP_STAGES.has(event.stage)) continue;
    const at = msOf(event);
    // 간격은 **앞 단계가 끝난 뒤부터** 이 단계가 기록될 때까지다 — 판단(decide) 왕복이
    // 그 안에 들어간다. 기준점이 없으면(재접속) 시간을 그리지 않는다: 0으로 그리면
    // 가장 오래 걸리는 첫 단계가 "즉시"로 보인다.
    const durationMs =
      at !== undefined && previous !== undefined && at >= previous ? at - previous : undefined;
    if (at !== undefined) previous = at;
    steps.push({ ...event, durationMs });
  }
  return steps;
}

const TIMELINE_ACCEPTED_STAGE = 'accepted';
const ACCEPTED_LABEL = '질문 접수';
/**
 * 단계가 아닌 프레임 — 진행이 아니라 **상태 표식**이다.
 *
 * `accepted`는 스트림이 붙었다는 신호이고(첫 단계까지의 기준점으로만 쓴다), `cancelled`는
 * 프론트가 만들어 끼우는 표식이다(`state.cancelledTimelineEvent`). 둘 다 도구 호출이 아니라
 * 세면 "3단계"가 "4단계"가 되고, 시각이 없어 소요 시간도 못 붙는다.
 */
const NON_STEP_STAGES = new Set([TIMELINE_ACCEPTED_STAGE, 'cancelled']);

function msOf(event?: AgentTimelineEvent): number | undefined {
  if (!event?.at) return undefined;
  const ms = Date.parse(event.at);
  return Number.isNaN(ms) ? undefined : ms;
}

/** 소요 시간 표기 — 1초 미만은 소수 한 자리, 1분 넘으면 분·초. */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}초`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}분 ${Math.round(seconds - minutes * 60)}초`;
}

/**
 * 세션 스냅샷을 계속 다시 읽어야 하는지 — 실행 중인 잡을 따라갈 때, 그리고 아직
 * 답을 못 받은 사용자 메시지가 있을 때다.
 *
 * 후자가 없으면 온디맨드 턴(BLM §5)의 답장이 화면에 영영 붙지 않는다: 종단 잡의
 * 대화 턴은 워커가 비동기로 처리하는데 잡 상태는 completed에서 변하지 않으므로,
 * 잡 상태만 보는 조건은 폴링을 시작조차 하지 않는다.
 */
export function shouldPollSession(
  jobState: AgentJobState,
  messages: AgentMessage[],
  submitting = false,
  activeTurnId: string | null = null,
): boolean {
  // evidence 턴이 실행 중이면 이벤트 구독이 유일한 작성자다 — 스냅샷이 끼어들면 답변
  // 자리를 먼저 채우고 폴링을 꺼 버린다.
  if (activeTurnId) return false;
  if (jobState === 'queued' || jobState === 'running') return true;
  if (submitting) return false;
  const last = messages.at(-1);
  return last?.role === 'user' && last.status !== 'failed';
}

export function normalizeTimelineDisplay(
  events: AgentTimelineEvent[],
  jobState: AgentJobState = 'running',
): AgentTimelineEvent[] {
  let lastTerminalIndex = -1;
  for (let i = events.length - 1; i >= 0; i -= 1) {
    if (events[i].state !== 'running') {
      lastTerminalIndex = i;
      break;
    }
  }
  if (lastTerminalIndex < 0 && isTerminalJobState(jobState)) {
    return events.map((event) =>
      event.state === 'running' ? { ...event, state: 'completed' } : event,
    );
  }
  if (lastTerminalIndex <= 0) return events;
  return events.map((event, index) =>
    index < lastTerminalIndex && event.state === 'running'
      ? { ...event, state: 'completed' satisfies AgentTimelineState }
      : event,
  );
}

function isTerminalJobState(state: AgentJobState): boolean {
  return state === 'completed' || state === 'failed' || state === 'degraded';
}

async function loadNoveltySseEvents(
  sessionId: string,
  afterEventId: string | null,
): Promise<AgentTimelineEvent[]> {
  const url = noveltySseUrl(sessionId, afterEventId);
  if (!url) return [];
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SSE_FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      headers: { accept: 'text/event-stream' },
      credentials: 'same-origin',
      cache: 'no-store',
      signal: controller.signal,
    });
    if (!res.ok) return [];
    return parseNoveltySseEvents(await res.text());
  } finally {
    clearTimeout(timer);
  }
}

function noveltySseUrl(sessionId: string, afterEventId: string | null): string | null {
  const prefix = 'novelty:';
  if (!sessionId.startsWith(prefix)) return null;
  const rawId = sessionId.slice(prefix.length);
  if (!rawId) return null;
  const params = new URLSearchParams();
  if (afterEventId) params.set('after', afterEventId);
  const query = params.toString();
  return `/bff/api/novelty/jobs/${encodeURIComponent(rawId)}/events${query ? `?${query}` : ''}`;
}

// SSE 파서는 evidence 동기 턴 스트리밍(US-EV2)과 공유하도록 lib로 이동 — 테스트 호환 재노출.
export { parseNoveltySseEvents } from '@/lib/agentChat/sse';

function AgentTimelineItem({ event }: { event: AgentTimelineEvent & { durationMs?: number } }) {
  const { durationMs } = event;
  return (
    <div
      className={styles.timelineEvent}
      data-state={event.state}
      data-testid="agent-timeline-event"
    >
      <div className={styles.timelineEventHead}>
        <span className={styles.timelineEventLabel}>{event.label}</span>
        {durationMs !== undefined ? (
          <small className={styles.timelineDuration}>{formatDuration(durationMs)}</small>
        ) : null}
        <JobStateBadge state={event.state} />
      </div>
      {event.detail ? <p className={styles.timelineEventDetail}>{event.detail}</p> : null}
    </div>
  );
}

function JobStateBadge({ state }: { state: AgentTimelineState | AgentJobState }) {
  return (
    <small className={styles.stateBadge} data-state={state}>
      {state === 'queued' || state === 'running' ? (
        <span className={styles.spinner} aria-hidden="true" />
      ) : null}
      {JOB_STATE_LABEL[state]}
    </small>
  );
}

function AgentAttachmentDrawer({
  attachments,
  onRemove,
}: {
  attachments: AgentAttachment[];
  onRemove: (id: string) => void;
}) {
  if (attachments.length === 0) return null;
  return (
    <div className={styles.attachments} data-testid="agent-attachment-drawer">
      {attachments.map((attachment) => (
        <div key={attachment.id} className={styles.attachment} data-status={attachment.status}>
          <span>{attachment.name}</span>
          {attachment.error ? <small>{attachment.error}</small> : null}
          <button type="button" onClick={() => onRemove(attachment.id)} aria-label="첨부 제거">
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

function MenuIcon() {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M4 7h16" />
      <path d="M4 12h16" />
      <path d="M4 17h16" />
    </svg>
  );
}

function formatSessionUpdatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}
