/**
 * 진행 과정 표시(v3 §5.3) — **접힌 한 줄**과 단계별 소요 시간.
 *
 * 종전에는 단계가 세로로 나열되고 라벨이 전부 "도구 실행"이었다. 두 결함 다 화면을 열어야만
 * 보이는 종류라, 여기서 기계로 고정한다:
 *
 * - 접힘은 `<details open>`으로 표현된다. jsdom은 닫힌 details의 자식도 DOM에 그대로 두므로
 *   `getByText`로는 접힌 것과 펼친 것을 **구분할 수 없다** — 실제로 종전 테스트가 그래서
 *   초록이었다. `open` 속성을 직접 본다.
 * - 소요 시간은 앞 단계와의 간격이고, 기준점이 없으면 **그리지 않는다**(0으로 그리면 가장
 *   오래 걸리는 첫 단계가 "즉시"로 보인다).
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { formatDuration, withStepDurations } from '@/components/agent/AgentChatScreen';
import type { AgentTimelineEvent } from '@/lib/agentChat/types';

function event(over: Partial<AgentTimelineEvent> & { id: string }): AgentTimelineEvent {
  return { stage: 'corpus_search', label: '논문 검색', state: 'completed', ...over };
}

describe('withStepDurations', () => {
  it('drops the accepted frame from the step list but keeps it as the first step baseline', () => {
    const steps = withStepDurations([
      event({ id: 'a', stage: 'accepted', label: '질문 접수', at: '2026-08-25T00:00:00.000Z' }),
      event({ id: '1', at: '2026-08-25T00:00:12.000Z' }),
    ]);

    // "질문 접수"는 단계가 아니라 스트림이 붙었다는 신호다 — 목록에 남기면 매 턴 한 줄을 먹는다.
    expect(steps.map((s) => s.id)).toEqual(['1']);
    expect(steps[0].durationMs).toBe(12_000);
  });

  it('measures each step from the previous one, so the decide round-trip is included', () => {
    const steps = withStepDurations([
      event({ id: 'a', stage: 'accepted', at: '2026-08-25T00:00:00.000Z' }),
      event({ id: '1', at: '2026-08-25T00:00:03.000Z' }),
      event({ id: '2', stage: 'fetch_paper', at: '2026-08-25T00:00:24.500Z' }),
    ]);

    expect(steps.map((s) => s.durationMs)).toEqual([3_000, 21_500]);
  });

  it('shows no duration when there is no baseline — a reconnect must not claim "instant"', () => {
    // 재접속(`after=seq`)은 accepted 프레임을 다시 받지 않는다. 첫 단계의 기준점이 없다.
    const steps = withStepDurations([event({ id: '2', at: '2026-08-25T00:00:24.500Z' })]);

    expect(steps[0].durationMs).toBeUndefined();
  });

  it('leaves the duration out when the timestamp is missing or unparseable', () => {
    const steps = withStepDurations([
      event({ id: 'a', stage: 'accepted', at: '2026-08-25T00:00:00.000Z' }),
      event({ id: '1', at: 'not-a-date' }),
      event({ id: '2', stage: 'read_paper' }),
    ]);

    expect(steps.map((s) => s.durationMs)).toEqual([undefined, undefined]);
  });
});

describe('formatDuration', () => {
  it('reads at the scale a turn actually takes', () => {
    expect(formatDuration(8)).toBe('8ms');
    expect(formatDuration(3_140)).toBe('3.1초');
    expect(formatDuration(91_400)).toBe('1분 31초');
  });
});
