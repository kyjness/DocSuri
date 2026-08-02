import { describe, expect, it } from 'vitest';

import {
  anchorTypeLabel,
  canJumpToSource,
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

describe('출처 이동 가능 여부', () => {
  it('앵커가 없으면 이동 링크를 렌더하지 않는다 — 깨진 링크를 만들지 않는다', () => {
    expect(canJumpToSource(ref({ anchor: null, sourceScope: 'abstract' }))).toBe(false);
    expect(canJumpToSource(ref())).toBe(true);
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
