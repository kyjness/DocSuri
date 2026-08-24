import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import {
  agentReducer,
  canSend,
  createAttachmentFromFile,
  createUserMessage,
  initialAgentChatState,
  mergeTimelineEvents,
  sortTimelineEvents,
} from '@/lib/agentChat/state';
import type { AgentSessionSummary, AgentTimelineEvent } from '@/lib/agentChat/types';

const evidenceSession: AgentSessionSummary = {
  id: 's-evidence',
  title: '근거 세션',
  mode: 'evidence',
  state: 'idle',
  updatedAt: '2026-07-01T00:00:00Z',
};

const noveltySession: AgentSessionSummary = {
  id: 's-novelty',
  title: '차별화 세션',
  mode: 'novelty',
  state: 'idle',
  updatedAt: '2026-07-01T00:01:00Z',
};

describe('agent chat reducer/helpers', () => {
  it('locks mode after the first session is selected', () => {
    const selected = agentReducer(initialAgentChatState, {
      type: 'startSession',
      session: evidenceSession,
    });
    const switched = agentReducer(selected, { type: 'startSession', session: noveltySession });

    expect(switched.mode).toBe('evidence');
    expect(switched.session?.id).toBe('s-evidence');
  });

  it('accepts only allowed attachment types within size bounds', () => {
    expect(createAttachmentFromFile({ name: 'paper.pdf', size: 1024 }).status).toBe('ready');
    expect(createAttachmentFromFile({ name: 'draft.md', size: 1024 }).kind).toBe('markdown');
    expect(createAttachmentFromFile({ name: 'slides.pptx', size: 1024 }).status).toBe('rejected');
    expect(createAttachmentFromFile({ name: 'huge.pdf', size: 11 * 1024 * 1024 }).status).toBe(
      'rejected',
    );
  });

  it('keeps timeline events unique and sequence ordered', () => {
    const merged = mergeTimelineEvents(
      [
        { id: 'b', stage: 'two', label: 'B', state: 'running', sequence: 2 },
        { id: 'a', stage: 'one', label: 'A', state: 'running', sequence: 1 },
      ],
      [
        { id: 'b', stage: 'two', label: 'B done', state: 'completed', sequence: 2 },
        { id: 'c', stage: 'three', label: 'C', state: 'completed', sequence: 3 },
      ],
    );

    expect(merged.map((event) => event.id)).toEqual(['a', 'b', 'c']);
    expect(merged[1].label).toBe('B done');
  });

  it('merges SSE progress events into the active timeline', () => {
    const running = agentReducer(initialAgentChatState, {
      type: 'startSession',
      session: { ...noveltySession, state: 'running' },
    });
    const withEvent = agentReducer(running, {
      type: 'eventsReceived',
      events: [{ id: 'evt-1', stage: 'retrieving', label: '검색 중', state: 'running' }],
    });
    const updated = agentReducer(withEvent, {
      type: 'eventsReceived',
      events: [{ id: 'evt-1', stage: 'completed', label: '검색 완료', state: 'completed' }],
    });

    expect(updated.events).toEqual([
      { id: 'evt-1', stage: 'completed', label: '검색 완료', state: 'completed' },
    ]);
  });

  it('keeps unsequenced timeline events in received order', () => {
    fc.assert(
      fc.property(fc.uniqueArray(fc.string({ minLength: 1 }), { minLength: 1 }), (ids) => {
        const events: AgentTimelineEvent[] = ids.map((id) => ({
          id,
          stage: id,
          label: id,
          state: 'running',
        }));

        expect(sortTimelineEvents(events).map((event) => event.id)).toEqual(ids);
      }),
    );
  });

  it('keeps draft and attachments available when send fails', () => {
    const attachment = createAttachmentFromFile({ name: 'draft.pdf', size: 1024 });
    const ready = agentReducer(
      agentReducer(
        agentReducer(initialAgentChatState, { type: 'startSession', session: evidenceSession }),
        { type: 'setDraft', draft: '다시 시도할 메시지' },
      ),
      { type: 'addAttachment', attachment },
    );
    const sending = agentReducer(ready, {
      type: 'sendStart',
      message: createUserMessage(ready.draft, ready.attachments),
    });
    const failed = agentReducer(sending, { type: 'sendFailure', message: '실패' });

    expect(failed.draft).toBe('다시 시도할 메시지');
    expect(failed.attachments).toEqual([attachment]);
    expect(failed.messages.at(-1)?.status).toBe('failed');
  });

  it('refreshes an active session without clearing the next draft', () => {
    const attachment = createAttachmentFromFile({ name: 'next.pdf', size: 1024 });
    const editing = agentReducer(
      agentReducer(
        agentReducer(initialAgentChatState, {
          type: 'startSession',
          session: { ...noveltySession, state: 'running' },
        }),
        { type: 'setDraft', draft: '다음 질문' },
      ),
      { type: 'addAttachment', attachment },
    );

    const refreshed = agentReducer(editing, {
      type: 'refreshSession',
      snapshot: {
        session: { ...noveltySession, state: 'completed' },
        messages: [],
        events: [{ id: 'done', stage: 'done', label: '완료', state: 'completed' }],
      },
    });

    expect(refreshed.draft).toBe('다음 질문');
    expect(refreshed.attachments).toEqual([attachment]);
    expect(refreshed.jobState).toBe('completed');
  });

  it('requires a mode, draft, session, and valid attachments before sending', () => {
    const withMode = agentReducer(initialAgentChatState, {
      type: 'startSession',
      session: evidenceSession,
    });
    const withDraft = agentReducer(withMode, { type: 'setDraft', draft: '요약해 주세요' });
    expect(canSend(withDraft)).toBe(true);

    const rejected = agentReducer(withDraft, {
      type: 'addAttachment',
      attachment: createAttachmentFromFile({ name: 'bad.exe', size: 1 }),
    });
    expect(canSend(rejected)).toBe(false);
  });

  it('preserves richer detail/sequence when a lean SSE snapshot re-sends the same event (#349)', () => {
    const polled: AgentTimelineEvent = {
      id: 'evt-1',
      stage: 'searching',
      label: '유사 연구 탐색',
      detail: '소스 arXiv · 쿼리 "diffusion" · 결과 12건',
      state: 'running',
      sequence: 3,
    };
    // AgentChatScreen.mapSseProgressEvent emits only these four fields — no detail/sequence.
    const sseSnapshot: AgentTimelineEvent = {
      id: 'evt-1',
      stage: 'completed',
      label: '완료',
      state: 'completed',
    };

    const [merged] = mergeTimelineEvents([polled], [sseSnapshot]);

    // incoming stage/label/state win…
    expect(merged.state).toBe('completed');
    expect(merged.stage).toBe('completed');
    // …but the richer detail/sequence survive the snapshot.
    expect(merged.detail).toBe('소스 arXiv · 쿼리 "diffusion" · 결과 12건');
    expect(merged.sequence).toBe(3);
  });

  // --- v3 §5 evidence 턴 수명주기: 수락 → 구독 → 종단/취소 ---

  function acceptedState() {
    const started = agentReducer(
      agentReducer(initialAgentChatState, { type: 'startSession', session: evidenceSession }),
      { type: 'sendStart', message: createUserMessage('질문') },
    );
    return agentReducer(started, {
      type: 'turnAccepted',
      accepted: {
        session: { ...evidenceSession, id: 'evidence:s1', state: 'running' },
        turnId: 't1',
      },
    });
  }

  it('accepting a turn keeps the user message, opens the active turn, and closes the composer', () => {
    const state = acceptedState();

    expect(state.activeTurnId).toBe('t1');
    expect(state.jobState).toBe('running');
    expect(state.submitting).toBe(false);
    expect(state.messages.map((m) => [m.role, m.status])).toEqual([['user', 'sent']]);
    expect(state.session?.id).toBe('evidence:s1');
    expect(canSend({ ...state, draft: '다음 질문' })).toBe(false); // 진행 중엔 입력이 닫힌다
  });

  it('finishing the turn appends the answer once and reopens the composer', () => {
    const answer = {
      id: 't1-agent',
      role: 'agent' as const,
      content: '[abstain] out_of_corpus',
      createdAt: '2026-07-01T00:00:02Z',
      status: 'sent' as const,
    };
    const finished = agentReducer(acceptedState(), {
      type: 'turnFinished',
      finished: { turnId: 't1', message: answer, outcome: 'completed', cancelled: false },
    });
    const twice = agentReducer(finished, {
      type: 'turnFinished',
      finished: { turnId: 't1', message: answer, outcome: 'completed', cancelled: false },
    });

    expect(finished.activeTurnId).toBeNull();
    expect(finished.jobState).toBe('completed');
    expect(finished.messages.map((m) => m.id)).toEqual([finished.messages[0].id, 't1-agent']);
    expect(twice.messages).toHaveLength(2); // 스냅샷과 같은 id — 두 번 붙지 않는다
    expect(canSend({ ...finished, draft: '다음 질문' })).toBe(true);
  });

  it('a cancelled turn closes the timeline with a 취소됨 line', () => {
    const withEvents = agentReducer(acceptedState(), {
      type: 'eventsReceived',
      events: [{ id: 't1:1', stage: 'tool', label: '도구 실행', state: 'running', sequence: 1 }],
    });
    const requested = agentReducer(withEvents, { type: 'cancelRequested' });
    expect(requested.cancelRequested).toBe(true);

    const finished = agentReducer(requested, {
      type: 'turnFinished',
      finished: {
        turnId: 't1',
        message: { id: 't1-agent', role: 'agent', content: '[abstain] cancelled', createdAt: 'x', status: 'sent' },
        outcome: 'completed',
        cancelled: true,
      },
    });

    expect(finished.cancelRequested).toBe(false);
    expect(finished.events.map((e) => [e.id, e.state])).toEqual([
      ['t1:1', 'running'],
      ['t1:cancelled', 'failed'],
    ]);
  });

  it('loading a session with a pending turn re-attaches the subscription', () => {
    const loaded = agentReducer(initialAgentChatState, {
      type: 'loadSession',
      snapshot: {
        session: { ...evidenceSession, id: 'evidence:s1', state: 'completed' },
        messages: [],
        events: [],
        activeTurnId: 't9',
      },
    });

    expect(loaded.activeTurnId).toBe('t9');
    expect(loaded.jobState).toBe('running');
  });

  it('ignores a stale turnFinished for a different turn', () => {
    const state = acceptedState();
    const other = agentReducer(state, {
      type: 'turnFinished',
      finished: {
        turnId: 't0',
        message: { id: 't0-agent', role: 'agent', content: 'x', createdAt: 'x', status: 'sent' },
        outcome: 'completed',
        cancelled: false,
      },
    });
    expect(other).toBe(state);
  });

  it('keeps the session title on a follow-up turn (the accept response carries the new topic)', () => {
    const first = acceptedState(); // 제목 '근거 세션'
    const followUp = agentReducer(first, {
      type: 'turnAccepted',
      accepted: {
        session: { ...evidenceSession, id: 'evidence:s1', title: '두 번째 질문', state: 'running' },
        turnId: 't2',
      },
    });

    expect(followUp.session?.title).toBe(first.session?.title);
    expect(followUp.session?.state).toBe('running');
    expect(followUp.activeTurnId).toBe('t2');
  });
});
