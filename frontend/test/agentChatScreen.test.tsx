import { beforeEach, describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  AgentChatScreen,
  normalizeTimelineDisplay,
  parseNoveltySseEvents,
  shouldPollSession,
} from '@/components/agent/AgentChatScreen';
import type { AgentMessage } from '@/lib/agentChat/types';
import { resetMockNotionConnection } from '@/lib/api/mockTransport';

describe('AgentChatScreen', () => {
  beforeEach(() => {
    resetMockNotionConnection();
  });

  it('marks previous running timeline steps complete when a terminal event arrives', () => {
    expect(
      normalizeTimelineDisplay([
        { id: '1', stage: 'queued', label: 'queued', state: 'running' },
        { id: '2', stage: 'retrieving', label: 'retrieving', state: 'running' },
        { id: '3', stage: 'degraded', label: 'done', state: 'degraded' },
      ]).map((event) => event.state),
    ).toEqual(['completed', 'completed', 'degraded']);
  });

  it('keeps polling a completed job while an on-demand reply is outstanding', () => {
    const message = (role: AgentMessage['role'], id: string): AgentMessage => ({
      id,
      role,
      content: 'x',
      createdAt: '2026-07-01T00:00:00Z',
      status: 'sent',
    });

    // 종단 잡의 온디맨드 턴은 워커가 비동기로 답한다 — 잡 상태(completed)만 보면
    // 폴링이 시작되지 않아 답장이 화면에 영영 붙지 않는다.
    expect(shouldPollSession('completed', [message('user', 'u1')])).toBe(true);
    // 답장이 도착하면 멈춘다.
    expect(shouldPollSession('completed', [message('user', 'u1'), message('agent', 'a1')])).toBe(
      false,
    );
    // 전송 실패한 메시지는 서버에 없다 — 기다릴 답장도 없다.
    expect(
      shouldPollSession('completed', [{ ...message('user', 'u1'), status: 'failed' }]),
    ).toBe(false);
    // 전송 중에는 sendAgentMessage가 스냅샷을 가져오므로 중복 폴링하지 않는다.
    expect(shouldPollSession('completed', [message('user', 'u1')], true)).toBe(false);
    // 실행 중인 잡은 대화와 무관하게 계속 따라간다.
    expect(shouldPollSession('running', [])).toBe(true);
  });

  it('parses Novelty progress events from SSE frames', () => {
    const events = parseNoveltySseEvents(
      [
        'event: progress',
        'data: {"eventId":"evt-1","state":"retrieving_external","message":"외부 검색","payload":{"source":"github","count":2}}',
        '',
        'event: progress',
        'data: {"eventId":"evt-2","state":"completed","message":"완료"}',
        '',
      ].join('\n'),
    );

    expect(events).toEqual([
      {
        id: 'evt-1',
        stage: 'retrieving_external',
        label: '외부 검색',
        // N-001(#257) — SSE 이벤트도 payload 상세(source/count)를 표시한다.
        detail: '소스: github · 결과 2건',
        state: 'running',
      },
      {
        id: 'evt-2',
        stage: 'completed',
        label: '완료',
        detail: undefined,
        state: 'completed',
      },
    ]);
  });

  it('starts in novelty mode and sends a multi-turn message through the mock transport', async () => {
    const user = userEvent.setup();
    render(<AgentChatScreen />);

    await user.click(screen.getByTestId('agent-mode-novelty'));
    expect(screen.queryByTestId('agent-mode-picker')).not.toBeInTheDocument();

    await user.type(screen.getByTestId('agent-composer-input'), 'RAG 평가 자동화 아이디어');
    await user.click(screen.getByTestId('agent-composer-submit'));

    // 구조화 novelty 아티팩트가 카드로 렌더링된다(#253~#256) — 플랫 텍스트·raw JSON이 아니라.
    expect(await screen.findByText('유사 연구 표')).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    // US-NV3(#253) 상세 칼럼 — 값 있는 칸은 그대로, 근거 없는 칸은 '근거 부족'(기권).
    expect(screen.getByText('문제정의')).toBeInTheDocument();
    expect(screen.getByText('공개 RAG 벤치마크 3종')).toBeInTheDocument();
    expect(screen.getAllByText('근거 부족').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/Prior RAG benchmark에서 RAG 평가 자동화/)).toBeInTheDocument();
    expect(screen.getByText('관련도/근거 강도 86%')).toBeInTheDocument();
    expect(screen.getByText('query: RAG evaluation automation benchmark')).toBeInTheDocument();
    expect(screen.getByText(/차별점은 데이터셋 조건/)).toBeInTheDocument();
    expect(screen.getByText('도메인 지식 기반 실패 유형 분해')).toBeInTheDocument();
    // FR-32 — 방향 제안은 bounded다. 무엇을 주장하지 않는지가 카드에 함께 보여야 한다.
    expect(screen.getByTestId('novelty-candidates')).toBeInTheDocument();
    expect(screen.getByText(/주장하지 않는 것 — .*새롭다고 확정하지 않으며/)).toBeInTheDocument();
    expect(screen.getByText(/실행 고려사항 — .*소규모 검증/)).toBeInTheDocument();
    expect(screen.getByText(/RAG 평가 자동화 프로토콜.*유사합니다/)).toBeInTheDocument();
    expect(screen.getByText(/판정이 아닙니다/)).toBeInTheDocument();
    expect(
      screen.getByText('유사 연구 대비 실패 유형을 더 세밀하게 분해한다.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/"artifacts"/)).not.toBeInTheDocument();
    expect(screen.getByTestId('agent-timeline')).toBeInTheDocument();
    expect(screen.getAllByTestId('agent-timeline-event').length).toBeGreaterThan(0);
    expect(screen.getByText(/소스: corpus/)).toBeInTheDocument();
    expect(screen.getAllByText('완료').length).toBeGreaterThan(0);
    expect(screen.queryByText('completed')).not.toBeInTheDocument();
  });

  it('tells the user that steering lands at the next decision point', async () => {
    const user = userEvent.setup();
    render(<AgentChatScreen />);

    await user.click(screen.getByTestId('agent-menu'));
    await user.click(await screen.findByText('조사 중인 Novelty 잡'));

    // 조사 중에도 입력은 열려 있다 — 다만 즉시 반영이 아니므로 먹혔다고 오해하지
    // 않게 안내한다(BLM §6).
    expect(await screen.findByTestId('agent-steering-hint')).toBeInTheDocument();
    expect(screen.getByTestId('agent-composer-input')).not.toBeDisabled();
  });

  it('renders system notices apart from agent answers', async () => {
    const user = userEvent.setup();
    render(<AgentChatScreen />);

    await user.click(screen.getByTestId('agent-menu'));
    await user.click(await screen.findByText('조사 중인 Novelty 잡'));

    const notice = await screen.findByTestId('agent-notice');
    expect(notice).toHaveTextContent(/조사가 종료된 뒤 도착한 메시지입니다/);
  });

  it('loads a previous session from the drawer', async () => {
    const user = userEvent.setup();
    render(<AgentChatScreen />);

    await user.click(screen.getByTestId('agent-menu'));
    expect(await screen.findByText('LLM 평가 근거 정리')).toBeInTheDocument();
    expect(screen.getByText(/Research .* 완료/)).toBeInTheDocument();
    await user.click(screen.getByText('LLM 평가 근거 정리'));

    expect(await screen.findByText(/벤치마크 신뢰도/)).toBeInTheDocument();
    expect(
      screen
        .getAllByTestId('agent-message')
        .every((message) => message.getAttribute('data-streaming') === 'false'),
    ).toBe(true);
  });

  it('renders an evidence result message as a card with citation anchors', async () => {
    const user = userEvent.setup();
    render(<AgentChatScreen />);

    await user.click(screen.getByTestId('agent-menu'));
    await user.click(await screen.findByText('LLM 평가 근거 정리'));

    // 비교표: statement + 출처(paperId · 인용 앵커 · quote). raw JSON은 노출되지 않는다(#339).
    expect(
      await screen.findByText('벤치마크 재사용은 데이터 누수 위험을 높인다.'),
    ).toBeInTheDocument();
    expect(screen.getByText('2401.01234')).toBeInTheDocument();
    expect(screen.getByText('§ 4.2절')).toBeInTheDocument();
    expect(screen.getByText(/benchmark reuse inflates scores/)).toBeInTheDocument();
    expect(screen.getByText(/참고 논문 3편/)).toBeInTheDocument();
    expect(screen.queryByText(/"claims"/)).not.toBeInTheDocument();
  });

  it('shows rejected attachments and blocks send until they are removed', async () => {
    const user = userEvent.setup();
    render(<AgentChatScreen />);

    await user.click(screen.getByTestId('agent-mode-evidence'));
    await user.type(screen.getByTestId('agent-composer-input'), '첨부 검토');
    await user.upload(
      screen.getByTestId('agent-file-input'),
      new File([new Uint8Array(11 * 1024 * 1024)], 'huge.pdf', { type: 'application/pdf' }),
    );

    expect(await screen.findByTestId('agent-attachment-drawer')).toHaveTextContent(
      '첨부 파일은 10MB 이하만 사용할 수 있습니다.',
    );
    expect(screen.getByTestId('agent-composer-submit')).toBeDisabled();
  });

  it('sends a novelty manuscript by attaching a markdown file', async () => {
    const user = userEvent.setup();
    render(<AgentChatScreen />);

    await user.click(screen.getByTestId('agent-mode-novelty'));
    await user.type(screen.getByTestId('agent-composer-input'), '내 초안의 novelty 확인');
    await user.upload(
      screen.getByTestId('agent-file-input'),
      new File(['# 초안\nRAG 평가 자동화 프로토콜'], 'draft.md', { type: 'text/markdown' }),
    );

    // US-NV2(#252) — 본문 읽기(reading)가 끝나 ready가 될 때까지 전송이 막힌다.
    await waitFor(() => expect(screen.getByTestId('agent-composer-submit')).toBeEnabled());
    await user.click(screen.getByTestId('agent-composer-submit'));

    // manuscript 잡 생성 → 본문 업로드 → 결과 아티팩트 렌더링까지 관통한다.
    expect(await screen.findByText('유사 연구 표')).toBeInTheDocument();
  });

  it('exports a novelty result to Notion after explicit approval', async () => {
    const user = userEvent.setup();
    render(<AgentChatScreen />);

    await user.click(screen.getByTestId('agent-mode-novelty'));
    await user.type(screen.getByTestId('agent-composer-input'), 'RAG 평가 자동화 아이디어');
    await user.click(screen.getByTestId('agent-composer-submit'));
    expect(await screen.findByText('유사 연구 표')).toBeInTheDocument();

    // US-NV8(#258) — 입력 폼은 버튼을 누른 뒤에만 열리고, 취소하면 다시 닫힌다.
    await user.click(await screen.findByTestId('notion-export-open'));
    expect(await screen.findByTestId('notion-token-input')).toBeInTheDocument();
    await user.click(screen.getByTestId('notion-connect-cancel'));
    expect(screen.queryByTestId('notion-token-input')).not.toBeInTheDocument();
    await user.click(screen.getByTestId('notion-export-open'));
    await user.type(
      await screen.findByTestId('notion-token-input'),
      'not a real notion integration value',
    );
    await user.type(screen.getByTestId('notion-parent-input'), '0'.repeat(32));
    await user.click(screen.getByTestId('notion-connect-save'));

    // 미리보기(아티팩트 목록) → 명시 승인 → 저장 위치 링크. 자동 export 없음.
    expect(await screen.findByTestId('notion-export-preview')).toBeInTheDocument();
    await user.click(screen.getByTestId('notion-export-approve'));

    const link = await screen.findByTestId('notion-export-link');
    expect(link.getAttribute('href')).toContain('notion.so');
  });

  // mock 세션 저장소를 비우므로 파일 내 마지막 테스트로 유지한다.
  it('resets all sessions from the drawer after inline confirm', async () => {
    const user = userEvent.setup();
    render(<AgentChatScreen />);

    await user.click(screen.getByTestId('agent-menu'));
    expect(await screen.findByText('LLM 평가 근거 정리')).toBeInTheDocument();

    await user.click(screen.getByTestId('agent-session-reset'));
    await user.click(await screen.findByTestId('agent-session-reset-confirm'));

    // US-EV8(#272) — 전체 초기화 후 드로어가 닫히고 기본 상태(모드 선택)로 돌아간다.
    await waitFor(() =>
      expect(screen.queryByTestId('agent-session-drawer')).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId('agent-mode-picker')).toBeInTheDocument();

    await user.click(screen.getByTestId('agent-menu'));
    expect(await screen.findByText('저장된 세션이 없습니다.')).toBeInTheDocument();
    expect(screen.getByTestId('agent-session-reset')).toBeDisabled();
  });
});
