'use client';

import { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { UserFacingError, getApiClient } from '@/lib/api';
import {
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
} from '@/lib/agentChat/types';
import styles from './AgentChatScreen.module.css';

const MODE_LABEL: Record<AgentMode, string> = {
  evidence: 'Research',
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
const AGENT_REFRESH_MS = 2000;
const RESEARCH_MODE_ENABLED =
  !process.env.NEXT_PUBLIC_DOCSURI_REAL_API ||
  process.env.NEXT_PUBLIC_DOCSURI_RESEARCH_AGENT_ENABLED === '1';

export function AgentChatScreen() {
  const api = useMemo(() => getApiClient(), []);
  const [state, dispatch] = useReducer(agentReducer, initialAgentChatState);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const activeSessionId = state.session?.id;

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
    if (
      !activeSessionId ||
      state.submitting ||
      (state.jobState !== 'queued' && state.jobState !== 'running')
    ) {
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      try {
        const snapshot = await api.loadAgentSession(activeSessionId);
        if (alive) dispatch({ type: 'refreshSession', snapshot });
      } catch {
        // Keep the last known snapshot; the next user action can retry explicitly.
      } finally {
        if (alive) timer = setTimeout(refresh, AGENT_REFRESH_MS);
      }
    };
    timer = setTimeout(refresh, AGENT_REFRESH_MS);
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [activeSessionId, api, state.jobState, state.submitting]);

  function startMode(mode: AgentMode) {
    dispatch({ type: 'startSession', session: createDraftSession(mode) });
  }

  async function loadSession(session: AgentSessionSummary) {
    try {
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

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!canSend(state) || !state.session || !state.mode) return;

    const content = state.draft.trim();
    const attachments = state.attachments.filter((item) => item.status === 'ready');
    const userMessage = createUserMessage(content, attachments);
    dispatch({ type: 'sendStart', message: userMessage });

    try {
      const result = await api.sendAgentMessage(state.session.id, {
        content,
        mode: state.mode,
        attachments,
      });
      dispatch({ type: 'sendSuccess', result });
    } catch (error) {
      dispatch({
        type: 'sendFailure',
        message:
          error instanceof UserFacingError
            ? error.message
            : '에이전트 요청을 처리하지 못했습니다.',
      });
    }
  }

  function attach(files: FileList | null) {
    if (!files) return;
    Array.from(files).forEach((file, idx) => {
      dispatch({
        type: 'addAttachment',
        attachment: createAttachmentFromFile(file, state.attachments.length + idx),
      });
    });
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  return (
    <section className={styles.shell} data-mode={state.mode ?? undefined} data-testid="agent-chat-screen">
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
          {state.jobState !== 'idle' ? (
            <small data-state={state.jobState}>{JOB_STATE_LABEL[state.jobState]}</small>
          ) : null}
        </div>
      </div>

      {!state.mode ? (
        <AgentModePicker onSelect={startMode} researchEnabled={RESEARCH_MODE_ENABLED} />
      ) : null}

      <AgentMessageList messages={state.messages} />
      <AgentProgressTimeline events={state.events} />

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
          disabled={!state.mode || state.submitting}
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
          disabled={!state.mode || state.submitting}
          rows={1}
        />
        <button
          type="submit"
          className={styles.sendButton}
          disabled={!canSend(state)}
          data-testid="agent-composer-submit"
        >
          전송
        </button>
      </form>

      {drawerOpen ? (
        <AgentSessionDrawer
          sessions={state.sessions}
          activeId={state.session?.id ?? null}
          onClose={() => setDrawerOpen(false)}
          onNew={() => {
            dispatch({ type: 'newChat' });
            setDrawerOpen(false);
          }}
          onLoad={loadSession}
          onDelete={deleteSession}
        />
      ) : null}
    </section>
  );
}

function AgentModePicker({
  onSelect,
  researchEnabled,
}: {
  onSelect: (mode: AgentMode) => void;
  researchEnabled: boolean;
}) {
  return (
    <div className={styles.modePicker} data-testid="agent-mode-picker">
      <button
        type="button"
        onClick={() => onSelect('evidence')}
        disabled={!researchEnabled}
        aria-label={researchEnabled ? 'Research' : 'Research 준비 중'}
        data-mode="evidence"
        data-testid="agent-mode-evidence"
      >
        <strong>Research</strong>
        <span>작성 논문 근거 형성</span>
      </button>
      <button
        type="button"
        onClick={() => onSelect('novelty')}
        data-mode="novelty"
        data-testid="agent-mode-novelty"
      >
        <strong>Novelty</strong>
        <span>유사도 검사 및 차별점 추천</span>
      </button>
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
}: {
  sessions: AgentSessionSummary[];
  activeId: string | null;
  onClose: () => void;
  onNew: () => void;
  onLoad: (session: AgentSessionSummary) => void;
  onDelete: (session: AgentSessionSummary) => void;
}) {
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
      </aside>
    </div>
  );
}

function AgentMessageList({ messages }: { messages: AgentMessage[] }) {
  return (
    <div className={styles.messages} data-testid="agent-message-list">
      {messages.length === 0 ? <p className={styles.empty}>대화를 시작하세요.</p> : null}
      {messages.map((message) => (
        <article
          key={message.id}
          className={styles.message}
          data-role={message.role}
          data-status={message.status ?? 'sent'}
          data-testid="agent-message"
        >
          <p>{message.content}</p>
          {message.attachments?.length ? (
            <div className={styles.messageFiles}>
              {message.attachments.map((file) => (
                <span key={file.id}>{file.name}</span>
              ))}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function AgentProgressTimeline({ events }: { events: AgentTimelineEvent[] }) {
  if (events.length === 0) return null;
  return (
    <section className={styles.timeline} aria-label="탐구 프로세스" data-testid="agent-timeline">
      {events.map((event) => (
        <AgentTimelineItem key={event.id} event={event} />
      ))}
    </section>
  );
}

function AgentTimelineItem({ event }: { event: AgentTimelineEvent }) {
  const [open, setOpen] = useState(event.state === 'running' || event.state === 'degraded');
  return (
    <details
      className={styles.timelineEvent}
      data-state={event.state}
      data-testid="agent-timeline-event"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>
        <span>{event.label}</span>
        <small>{JOB_STATE_LABEL[event.state]}</small>
      </summary>
      {event.detail ? <p>{event.detail}</p> : null}
    </details>
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
