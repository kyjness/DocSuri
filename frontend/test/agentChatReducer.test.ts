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
});
