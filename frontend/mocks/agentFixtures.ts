import type {
  AgentMode,
  AgentSendMessageRequest,
  AgentSendMessageResult,
  AgentSessionSnapshot,
  AgentSessionSummary,
  AgentTimelineEvent,
} from '@/lib/agentChat/types';

const baseSessions: AgentSessionSnapshot[] = [
  {
    session: {
      id: 'agent-evidence-demo',
      title: 'LLM 평가 근거 정리',
      mode: 'evidence',
      state: 'completed',
      updatedAt: '2026-07-01T00:10:00Z',
    },
    messages: [
      {
        id: 'msg-demo-1',
        role: 'user',
        content: 'LLM 평가 데이터셋의 최근 논문 근거를 정리해 주세요.',
        createdAt: '2026-07-01T00:09:00Z',
        status: 'sent',
      },
      {
        id: 'msg-demo-2',
        role: 'agent',
        content:
          '내부 코퍼스 기준으로 벤치마크 신뢰도, 데이터 누수, 평가 재현성 쟁점을 우선 비교했습니다.',
        createdAt: '2026-07-01T00:10:00Z',
        status: 'sent',
      },
    ],
    events: [
      {
        id: 'demo-ev-1',
        stage: 'corpus',
        label: '내부 전문 검색',
        detail: 'U2 full 검색 결과에서 후보 논문을 정렬했습니다.',
        state: 'completed',
        sequence: 1,
      },
      {
        id: 'demo-ev-2',
        stage: 'evidence',
        label: '근거 교차확인',
        detail: '서로 다른 논문에서 반복되는 주장과 충돌 지점을 분리했습니다.',
        state: 'completed',
        sequence: 2,
      },
    ],
  },
  {
    session: {
      id: 'agent-novelty-demo',
      title: 'RAG 실험 Novelty 점검',
      mode: 'novelty',
      state: 'degraded',
      updatedAt: '2026-07-01T00:05:00Z',
    },
    messages: [
      {
        id: 'msg-demo-3',
        role: 'user',
        content: '도메인별 RAG 평가 자동화를 연구하고 싶습니다.',
        createdAt: '2026-07-01T00:04:00Z',
        status: 'sent',
      },
      {
        id: 'msg-demo-4',
        role: 'agent',
        content:
          '유사 아이디어는 평가셋 자동 생성과 검색 품질 진단에 집중되어 있습니다. 차별점은 도메인 지식 기반 실패 유형 분해로 잡을 수 있습니다.',
        createdAt: '2026-07-01T00:05:00Z',
        status: 'sent',
      },
    ],
    events: [
      {
        id: 'demo-nv-1',
        stage: 'corpus',
        label: '유사 논문 검색',
        detail: '내부 코퍼스에서 RAG 평가 자동화 관련 논문을 찾았습니다.',
        state: 'completed',
        sequence: 1,
      },
      {
        id: 'demo-nv-2',
        stage: 'external',
        label: '외부 소스 점검',
        detail: 'GitHub mock 응답은 성공, dataset mock 응답은 저하 상태입니다.',
        state: 'degraded',
        sequence: 2,
      },
    ],
  },
];

let sessions = [...baseSessions];

export function mockListAgentSessions(mode?: AgentMode): AgentSessionSummary[] {
  return sessions
    .map((snapshot) => snapshot.session)
    .filter((session) => (mode ? session.mode === mode : true))
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export function mockLoadAgentSession(id: string): AgentSessionSnapshot | null {
  const snapshot = sessions.find((item) => item.session.id === id);
  return snapshot ? clone(snapshot) : null;
}

export function mockDeleteAgentSession(id: string): boolean {
  const before = sessions.length;
  sessions = sessions.filter((item) => item.session.id !== id);
  return sessions.length !== before;
}

export function mockSendAgentMessage(
  sessionId: string,
  req: AgentSendMessageRequest,
): AgentSendMessageResult {
  const now = new Date().toISOString();
  const snapshot = ensureSession(sessionId, req.mode, now);
  const userMessage = {
    id: `msg-${sessionId}-${snapshot.messages.length + 1}`,
    role: 'user' as const,
    content: req.content,
    createdAt: now,
    attachments: req.attachments,
    status: 'sent' as const,
  };

  const failed = /오류|error/i.test(req.content);
  const degraded = /저하|degraded/i.test(req.content);
  const outcome: AgentSendMessageResult['outcome'] = failed
    ? 'failed'
    : degraded
      ? 'degraded'
      : 'completed';
  const events = makeEvents(req.mode, outcome);
  const nextSession = {
    ...snapshot.session,
    title: titleFrom(req.content, req.mode),
    state: outcome,
    updatedAt: now,
  };

  if (failed) {
    const nextSnapshot = {
      session: nextSession,
      messages: [...snapshot.messages, userMessage],
      events,
    };
    sessions = upsertSnapshot(nextSnapshot);
    return {
      session: nextSession,
      messages: nextSnapshot.messages,
      events,
      outcome,
      retryable: true,
      errorMessage: '에이전트 응답 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.',
    };
  }

  const agentMessage = {
    id: `msg-${sessionId}-${snapshot.messages.length + 2}`,
    role: 'agent' as const,
    content: responseFor(req.mode, degraded, req.attachments?.length ?? 0),
    createdAt: now,
    status: 'sent' as const,
  };
  const nextSnapshot = {
    session: nextSession,
    messages: [...snapshot.messages, userMessage, agentMessage],
    events,
  };
  sessions = upsertSnapshot(nextSnapshot);
  return { session: nextSession, messages: nextSnapshot.messages, events, outcome };
}

function ensureSession(id: string, mode: AgentMode, now: string): AgentSessionSnapshot {
  return (
    mockLoadAgentSession(id) ?? {
      session: {
        id,
        title: mode === 'evidence' ? '새 Research 세션' : '새 Novelty 세션',
        mode,
        state: 'idle',
        updatedAt: now,
      },
      messages: [],
      events: [],
    }
  );
}

function upsertSnapshot(snapshot: AgentSessionSnapshot): AgentSessionSnapshot[] {
  return [snapshot, ...sessions.filter((item) => item.session.id !== snapshot.session.id)];
}

function makeEvents(
  mode: AgentMode,
  outcome: 'completed' | 'failed' | 'degraded',
): AgentTimelineEvent[] {
  const common: AgentTimelineEvent[] = [
    {
      id: `${mode}-corpus`,
      stage: 'corpus',
      label: '내부 corpus full 검색',
      detail: 'U2 전문 검색 결과에서 관련 논문 후보를 모았습니다.',
      state: 'completed',
      sequence: 1,
    },
    {
      id: `${mode}-external`,
      stage: 'external',
      label: mode === 'novelty' ? 'GitHub/데이터셋 검색' : '외부 근거 보강',
      detail: 'mock adapter를 통해 외부 소스 결과를 정규화했습니다.',
      state: outcome === 'degraded' ? 'degraded' : 'completed',
      sequence: 2,
    },
  ];
  return [
    ...common,
    {
      id: `${mode}-synthesis`,
      stage: 'synthesis',
      label: mode === 'novelty' ? '차별화 아이디어 형성' : '근거 비교·정리',
      detail:
        outcome === 'failed'
          ? '응답 생성 단계에서 실패했습니다.'
          : '유사 연구와 충돌 근거를 분리해 답변을 구성했습니다.',
      state: outcome,
      sequence: 3,
    },
  ];
}

function responseFor(mode: AgentMode, degraded: boolean, attachmentCount: number): string {
  const prefix = degraded ? '일부 소스가 저하되어 가능한 범위에서 정리했습니다. ' : '';
  const attachmentNote = attachmentCount ? ` 첨부 ${attachmentCount}개도 함께 고려했습니다.` : '';
  if (mode === 'evidence') {
    return `${prefix}관련 논문을 주제, 방법, 데이터셋 기준으로 묶고 서로 확인되는 근거를 우선 제시했습니다.${attachmentNote}`;
  }
  return `${prefix}유사 연구는 이미 완료된 축과 아직 약한 축으로 나뉩니다. 차별점은 데이터셋 조건, 실패 유형 분해, 재현 가능한 비교 실험으로 잡는 것이 좋습니다.${attachmentNote}`;
}

function titleFrom(content: string, mode: AgentMode): string {
  const cleaned = content.trim().replace(/\s+/g, ' ').slice(0, 24);
  if (cleaned) return cleaned;
  return mode === 'evidence' ? '새 Research 세션' : '새 Novelty 세션';
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}
