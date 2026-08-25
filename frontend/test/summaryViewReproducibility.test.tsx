/**
 * 재현성 칸이 비어 있는 것과 "논문에 언급 없음"은 **다른 뜻**이다.
 *
 * 프롬프트는 찾아봤는데 없으면 '논문에 언급 없음'이라고 쓰라고 시킨다 — 그러니 값이 비어
 * 있다는 것은 논문에 없다는 뜻이 아니라 **모델이 답을 안 했다**는 뜻이다. 라벨만 덩그러니
 * 두면 둘이 같아 보이고, 사용자는 "이 논문은 코드를 안 냈구나"로 잘못 읽는다.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SummaryView } from '@/components/SummaryView';
import type { SummaryVM } from '@/types/generated';

function vm(code: string, data: string): SummaryVM {
  return {
    tldr: 't',
    contributions: ['c'],
    method: 'm',
    results: 'r',
    limitations: 'l',
    reproducibility: { code, data },
    anchors: [],
  } as SummaryVM;
}

describe('SummaryView 재현성', () => {
  it('모델이 확인한 "언급 없음"은 그대로 보여 준다', () => {
    render(<SummaryView summary={vm('논문에 언급 없음', '논문에 언급 없음')} />);

    expect(screen.getAllByText('논문에 언급 없음')).toHaveLength(2);
    expect(screen.queryByText('확인하지 못했어요')).not.toBeInTheDocument();
  });

  it('빈 값은 "확인하지 못했어요"로 구분해 그린다', () => {
    render(<SummaryView summary={vm('', '   ')} />);

    // 공백만 있는 것도 빈 값이다 — 모델이 스키마를 맞추려고 공백을 넣는 일이 있다.
    expect(screen.getAllByText('확인하지 못했어요')).toHaveLength(2);
  });

  it('한쪽만 비어도 나머지는 값을 보여 준다', () => {
    render(<SummaryView summary={vm('https://github.com/x/y', '')} />);

    expect(screen.getByText(/github\.com\/x\/y/)).toBeInTheDocument();
    expect(screen.getAllByText('확인하지 못했어요')).toHaveLength(1);
  });
});
