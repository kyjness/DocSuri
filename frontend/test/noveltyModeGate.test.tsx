/**
 * 한시 배포에서 Novelty 모드를 안 내보낸다(로드맵 ⑪).
 *
 * ⑩-2 재정의를 하지 않기로 했으므로 지금 노출된 Novelty는 그 재정의 **이전**의 v2다.
 * 게이트를 Research와 같은 모양으로 건다 — 목 전송(로컬·테스트)에서는 그대로 보이고,
 * 실 API를 붙인 배포에서만 명시적으로 켜야 보인다. 반대로 걸면 배포에서 env 하나를
 * 빠뜨리는 것이 곧 노출이 되는데, 그 실패는 배포본을 열어보기 전까지 아무 데도 안 보인다.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

async function renderChat() {
  const { AgentChatScreen } = await import('@/components/agent/AgentChatScreen');
  render(<AgentChatScreen />);
}

afterEach(() => {
  delete process.env.NEXT_PUBLIC_DOCSURI_REAL_API;
  delete process.env.NEXT_PUBLIC_DOCSURI_NOVELTY_ENABLED;
  vi.resetModules();
});

describe('Novelty mode gate', () => {
  it('keeps Novelty visible on the mock transport so local dev is unchanged', async () => {
    delete process.env.NEXT_PUBLIC_DOCSURI_REAL_API;
    vi.resetModules();

    await renderChat();

    expect(screen.getByTestId('agent-mode-novelty')).toBeInTheDocument();
  });

  it('hides Novelty on a real-API deployment unless it is turned on', async () => {
    process.env.NEXT_PUBLIC_DOCSURI_REAL_API = '1';
    process.env.NEXT_PUBLIC_DOCSURI_EVIDENCE_AGENT_ENABLED = '1';
    delete process.env.NEXT_PUBLIC_DOCSURI_NOVELTY_ENABLED;
    vi.resetModules();

    await renderChat();

    expect(screen.queryByTestId('agent-mode-novelty')).not.toBeInTheDocument();
    // Research는 남는다 — 숨기는 것은 Novelty 하나이지 모드 선택 화면 전체가 아니다.
    expect(screen.getByTestId('agent-mode-evidence')).toBeInTheDocument();
  });

  it('shows Novelty on a deployment that opts in', async () => {
    process.env.NEXT_PUBLIC_DOCSURI_REAL_API = '1';
    process.env.NEXT_PUBLIC_DOCSURI_EVIDENCE_AGENT_ENABLED = '1';
    process.env.NEXT_PUBLIC_DOCSURI_NOVELTY_ENABLED = '1';
    vi.resetModules();

    await renderChat();

    expect(screen.getByTestId('agent-mode-novelty')).toBeInTheDocument();
  });
});
