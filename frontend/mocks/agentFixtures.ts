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
        id: 'msg-demo-2b',
        role: 'agent',
        // U11 evidence 결과(JSON) — 화면 테스트가 판단 산문 + 근거표 렌더를 검증한다(v3 §2.1·§8).
        content: JSON.stringify({
          state: 'ok',
          answer: {
            segments: [
              {
                text: '벤치마크를 재사용하면 점수가 부풀려져요',
                refs: [1],
                kind: 'cited',
                role: 'conclusion',
              },
              {
                text: '오염을 걷어내고 다시 재면 순위는 대체로 유지돼요',
                refs: [2],
                kind: 'cited',
                role: 'evidence',
              },
              {
                text: '갈리는 지점은 재사용 사이에 데이터가 얼마나 갱신됐느냐예요',
                refs: [],
                kind: 'synthesis',
                role: 'divergence',
              },
            ],
            checks: { demoted: 0, regenerated: false, fallback: false },
          },
          claims: [
            {
              statement: '벤치마크 재사용은 데이터 누수 위험을 높인다.',
              supporting: [
                {
                  paperId: '2401.01234',
                  recordRef: 'rec-2401-01234-07',
                  title: 'Benchmark Contamination in Large Language Model Evaluation',
                  anchor: '4.2절',
                  quote: 'benchmark reuse inflates scores across successive releases',
                },
              ],
              conflicting: [],
            },
            // 상충이 있는 명제 — 근거 목록이 존재하는 이유이고, 코퍼스 안팎 출처가 한
            // 명제에 섞이는 모양이다(코퍼스 논문은 상세로, 코퍼스 밖은 arxiv.org로 간다).
            {
              statement: '오염을 제거한 재평가에서도 순위는 대체로 유지된다.',
              supporting: [
                {
                  paperId: '2403.05555',
                  recordRef: 'rec-2403-05555-01',
                  title: 'Decontaminated Re-evaluation of Open LLM Leaderboards',
                  anchor: '5.1절',
                  quote: 'rank correlation remains above 0.9 after decontamination',
                },
              ],
              conflicting: [
                {
                  paperId: 'arxiv:2405.09876v1',
                  recordRef: 'external:arxiv:2405.09876v1',
                  // 코퍼스 밖 출처는 백엔드가 네임스페이스를 판정해 싣는다 — 화면은
                  // 접두어를 자르지 않는다.
                  namespace: 'arxiv',
                  title: 'Rank Instability Under Contamination Removal',
                  quote: 'removing contaminated items reorders the top five systems',
                  sourceScope: 'abstract',
                },
              ],
            },
          ],
          coverage: { paperCount: 3, queryUsed: 'LLM 평가 데이터 누수' },
        }),
        createdAt: '2026-07-01T00:10:30Z',
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
        at: '2026-07-01T00:01:03.100Z',
      },
      {
        id: 'demo-ev-2',
        stage: 'evidence',
        label: '근거 교차확인',
        detail: '서로 다른 논문에서 반복되는 주장과 충돌 지점을 분리했습니다.',
        state: 'completed',
        sequence: 2,
        at: '2026-07-01T00:01:24.600Z',
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
        at: '2026-07-01T00:04:05.400Z',
      },
      {
        id: 'demo-nv-2',
        stage: 'external',
        label: '외부 소스 점검',
        detail: 'GitHub mock 응답은 성공, dataset mock 응답은 저하 상태입니다.',
        state: 'degraded',
        sequence: 2,
        at: '2026-07-01T00:04:18.900Z',
      },
    ],
  },
  {
    // 조사 중인 잡 — 스티어링 입력 안내와 시스템 안내 메시지 렌더링을 다룬다(FR-44).
    session: {
      id: 'agent-novelty-running',
      title: '조사 중인 Novelty 잡',
      mode: 'novelty',
      state: 'running',
      updatedAt: '2026-07-01T00:06:00Z',
    },
    messages: [
      {
        id: 'msg-demo-5',
        role: 'user',
        content: 'BM25 계열 위주로 봐줘',
        createdAt: '2026-07-01T00:06:00Z',
        status: 'sent',
        kind: 'steering',
      },
      {
        id: 'msg-demo-6',
        role: 'agent',
        content: '조사가 종료된 뒤 도착한 메시지입니다 — 다시 보내주시면 이어서 답변해 드릴게요.',
        createdAt: '2026-07-01T00:06:30Z',
        status: 'sent',
        kind: 'notice',
      },
    ],
    events: [],
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

export function mockResetAgentSessions(mode: AgentMode): void {
  sessions = sessions.filter((item) => item.session.mode !== mode);
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
        title: mode === 'evidence' ? '새 Evidence 세션' : '새 Novelty 세션',
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
  // 채팅 assistant 메시지는 텍스트 ack — 구조화 아티팩트는 /result seam(mockTransport
  // noveltyArtifacts → 실제 apiClient 매퍼)으로만 흐른다. 실 백엔드와 동일한 분리.
  return `${prefix}유사 연구는 이미 완료된 축과 아직 약한 축으로 나뉩니다. 차별점은 데이터셋 조건, 실패 유형 분해, 재현 가능한 비교 실험으로 잡는 것이 좋습니다.${attachmentNote}`;
}

function titleFrom(content: string, mode: AgentMode): string {
  const cleaned = content.trim().replace(/\s+/g, ' ').slice(0, 24);
  if (cleaned) return cleaned;
  return mode === 'evidence' ? '새 Evidence 세션' : '새 Novelty 세션';
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}
