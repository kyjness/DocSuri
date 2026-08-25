import { describe, expect, it } from 'vitest';

import {
  anchorTypeLabel,
  examinedRangeMessage,
  sourceScopeBadge,
} from '@/lib/agentChat/evidenceResult';
import type { EvidenceSourceRef } from '@/lib/agentChat/evidenceResult';

function ref(overrides: Partial<EvidenceSourceRef> = {}): EvidenceSourceRef {
  return { paperId: 'p1', recordRef: 'r1', anchor: 's4.tbl1', ...overrides };
}

describe('근거 칩 — 인용 객체 종류 (FR-47 v2)', () => {
  it('표·그림·식·알고리즘에 사용자 어휘 라벨을 붙인다', () => {
    expect(anchorTypeLabel(ref({ anchorType: 'table' }))).toBe('표');
    expect(anchorTypeLabel(ref({ anchorType: 'figure' }))).toBe('그림');
    expect(anchorTypeLabel(ref({ anchorType: 'formula' }))).toBe('식');
    expect(anchorTypeLabel(ref({ anchorType: 'code' }))).toBe('알고리즘');
  });

  it('본문 계열에는 라벨을 붙이지 않는다 — 대다수라 라벨이 소음이 된다', () => {
    expect(anchorTypeLabel(ref({ anchorType: 'paragraph' }))).toBeNull();
    expect(anchorTypeLabel(ref())).toBeNull();
  });
});

describe('근거 범위 배지', () => {
  it('전문 인용에는 배지를 붙이지 않는다', () => {
    expect(sourceScopeBadge(ref({ sourceScope: 'fulltext' }))).toBeNull();
    expect(sourceScopeBadge(ref())).toBeNull();
  });

  it('초록 범위와 그림 해석은 무엇이 다른지 설명한다', () => {
    expect(sourceScopeBadge(ref({ sourceScope: 'abstract' }))?.label).toBe('초록');
    expect(sourceScopeBadge(ref({ sourceScope: 'abstract' }))?.hint).toContain('본문을 가져오지');
    expect(sourceScopeBadge(ref({ sourceScope: 'figure' }))?.label).toBe('그림 해석');
    expect(sourceScopeBadge(ref({ sourceScope: 'figure' }))?.hint).toContain('인용문이 아니라');
  });
});

describe('확인 범위 문장 (FR-37 v2)', () => {
  it('탐색이 완결됐으면 아무것도 표시하지 않는다', () => {
    expect(
      examinedRangeMessage({ paperCount: 3, examined: 3, candidates: 3, stoppedReason: 'sufficient' }),
    ).toBeNull();
  });

  it('예산 소진은 이어가기를 제안한다', () => {
    const message = examinedRangeMessage({
      paperCount: 2,
      examined: 5,
      candidates: 12,
      stoppedReason: 'budget_exhausted',
    });

    expect(message).toBe('관련 논문 12편 중 5편까지 확인했습니다. 이어서 확인할까요?');
  });

  it('부분 실패는 원인을 사용자 말로 설명한다', () => {
    const message = examinedRangeMessage({
      paperCount: 2,
      examined: 4,
      candidates: 9,
      stoppedReason: 'partial_failure',
    });

    expect(message).toContain('본문을 가져오지 못했습니다');
  });

  it('내부 용어를 화면 문구에 쓰지 않는다', () => {
    const message = examinedRangeMessage({
      paperCount: 1,
      examined: 1,
      candidates: 5,
      stoppedReason: 'budget_exhausted',
    });

    expect(message).not.toMatch(/degraded|budget|exhausted/i);
  });

  it('수치가 없으면(구 백엔드 응답) 문장을 만들지 않는다', () => {
    expect(examinedRangeMessage({ paperCount: 2 })).toBeNull();
  });
});

describe('실시간 조회 불가 (v3 §7)', () => {
  it('탐색이 완결됐어도 조회가 죽었으면 그 사실을 밝힌다', () => {
    // 후보를 전부 확인하고 끝난 턴도 코퍼스 밖은 못 본 것이다. 안 밝히면 "그런 논문이
    // 세상에 없다"로 읽히는데, 사용자가 할 일이 정반대다(다시 물어보기 vs 주제 넓히기).
    const message = examinedRangeMessage({
      paperCount: 3,
      examined: 3,
      candidates: 3,
      stoppedReason: 'sufficient',
      liveLookupDegraded: true,
    });

    expect(message).toContain('실시간 조회');
  });

  it('잘린 탐색이면 두 사실을 함께 낸다', () => {
    const message = examinedRangeMessage({
      paperCount: 2,
      examined: 5,
      candidates: 12,
      stoppedReason: 'budget_exhausted',
      liveLookupDegraded: true,
    });

    expect(message).toContain('12편 중 5편');
    expect(message).toContain('실시간 조회');
  });

  it('조회가 멀쩡하면 아무 말도 덧붙이지 않는다', () => {
    expect(
      examinedRangeMessage({
        paperCount: 3,
        examined: 3,
        candidates: 3,
        stoppedReason: 'sufficient',
        liveLookupDegraded: false,
      }),
    ).toBeNull();
  });

  it('내부 용어를 쓰지 않는다', () => {
    const message = examinedRangeMessage({ paperCount: 1, liveLookupDegraded: true });

    expect(message).not.toMatch(/degraded|arxiv|openalex|semantic/i);
  });
});
