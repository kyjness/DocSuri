import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentChatScreen } from '@/components/agent/AgentChatScreen';

describe('AgentChatScreen', () => {
  it('starts in novelty mode and sends a multi-turn message through the mock transport', async () => {
    const user = userEvent.setup();
    render(<AgentChatScreen />);

    await user.click(screen.getByTestId('agent-mode-novelty'));
    expect(screen.queryByTestId('agent-mode-picker')).not.toBeInTheDocument();

    await user.type(screen.getByTestId('agent-composer-input'), 'RAG 평가 자동화 아이디어');
    await user.click(screen.getByTestId('agent-composer-submit'));

    expect(await screen.findByText(/차별점은 데이터셋 조건/)).toBeInTheDocument();
    expect(screen.getByText(/Novelty 분석 결과/)).toBeInTheDocument();
    expect(screen.getByText(/도메인 지식 기반 실패 유형 분해/)).toBeInTheDocument();
    expect(screen.getByTestId('agent-timeline')).toBeInTheDocument();
    expect(screen.getAllByTestId('agent-timeline-event').length).toBeGreaterThan(0);
    expect(screen.getByText(/소스: corpus/)).toBeInTheDocument();
    expect(screen.getAllByText('완료').length).toBeGreaterThan(0);
    expect(screen.queryByText('completed')).not.toBeInTheDocument();
  });

  it('loads a previous session from the drawer', async () => {
    const user = userEvent.setup();
    render(<AgentChatScreen />);

    await user.click(screen.getByTestId('agent-menu'));
    expect(await screen.findByText('LLM 평가 근거 정리')).toBeInTheDocument();
    expect(screen.getByText(/Research .* 완료/)).toBeInTheDocument();
    await user.click(screen.getByText('LLM 평가 근거 정리'));

    expect(await screen.findByText(/벤치마크 신뢰도/)).toBeInTheDocument();
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
});
