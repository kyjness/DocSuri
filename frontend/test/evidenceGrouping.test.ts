/**
 * 근거를 논문 단위로 묶는 규칙(v3 §2.1) — 순서·상충·줄 내용·앵커 링크.
 *
 * 화면을 열어야만 보이는 것들이라 여기서 기계로 고정한다. 특히 **순서**: 논문 순서도 논문 안
 * 줄 순서도 조립이 정한 근거 순서에서 나온다. 여기서 다시 정렬하면 판단 산문의 `[n]`이 다른
 * 근거를 가리킨다(BR-EV-5).
 */
import { describe, expect, it } from 'vitest';

import {
  anchorHref,
  evidenceLine,
  groupClaimsByPaper,
} from '@/lib/agentChat/evidenceResult';
import type { EvidenceClaim, EvidenceSourceRef } from '@/lib/agentChat/evidenceResult';

function ref(over: Partial<EvidenceSourceRef> & { paperId: string }): EvidenceSourceRef {
  return { recordRef: `rec-${over.paperId}`, ...over };
}

function claim(statement: string, supporting: EvidenceSourceRef[], conflicting: EvidenceSourceRef[] = []): EvidenceClaim {
  return { statement, supporting, conflicting };
}

describe('groupClaimsByPaper', () => {
  it('names each paper once instead of repeating it per claim', () => {
    // 실측: 논문 2편에 근거 10건이면 종전 화면은 같은 제목을 일곱 번 찍었다.
    const grouped = groupClaimsByPaper([
      claim('a', [ref({ paperId: 'p1' })]),
      claim('b', [ref({ paperId: 'p1' })]),
      claim('c', [ref({ paperId: 'p2' })]),
    ]);

    expect(grouped.papers.map((g) => g.paperId)).toEqual(['p1', 'p2']);
    expect(grouped.papers[0].rows.map((r) => r.number)).toEqual([1, 2]);
    expect(grouped.papers[1].rows.map((r) => r.number)).toEqual([3]);
  });

  it('orders papers by first appearance, never by how many claims they carry', () => {
    // 조립 순서를 뒤집으면 `[n]`이 다른 근거를 가리킨다. 근거가 많은 논문을 앞으로 당기지 않는다.
    const grouped = groupClaimsByPaper([
      claim('a', [ref({ paperId: 'p2' })]),
      claim('b', [ref({ paperId: 'p1' })]),
      claim('c', [ref({ paperId: 'p1' })]),
    ]);

    expect(grouped.papers.map((g) => g.paperId)).toEqual(['p2', 'p1']);
  });

  it('lifts a contested claim out so the disagreement stays in one place', () => {
    // 논문으로 묶으면 이 근거가 두 블록으로 갈라져 "이 둘이 여기서 엇갈린다"를 못 본다 —
    // 표가 있던 이유가 그것이다. 그리고 DOM id가 중복되어 앵커 이동이 깨진다.
    const grouped = groupClaimsByPaper([
      claim('갈린다', [ref({ paperId: 'p1' })], [ref({ paperId: 'p2' })]),
      claim('안 갈린다', [ref({ paperId: 'p1' })]),
    ]);

    expect(grouped.contested.map((c) => c.number)).toEqual([1]);
    // 쟁점으로 뺐으면 논문 그룹에는 **없어야** 한다.
    expect(grouped.papers.flatMap((g) => g.rows.map((r) => r.number))).toEqual([2]);
  });

  it('gives every row a unique key when a claim cites the same paper twice', () => {
    // **매 턴 일어난다.** 게이트는 supporting을 논문으로 중복 제거하지 않으므로(gate.py),
    // 한 명제가 같은 논문의 두 블록을 인용하면 같은 그룹에 같은 번호의 행이 둘 생긴다.
    // 배포본 실측: 근거 19건 중 10건 · 25건 중 6건 · 10건 중 3건이 이 모양이었다.
    const grouped = groupClaimsByPaper([
      claim('a', [
        ref({ paperId: 'p1', anchor: 's1.p1' }),
        ref({ paperId: 'p1', anchor: 's4.tbl1' }),
      ]),
    ]);

    const rows = grouped.papers[0].rows;
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.key)).toEqual([...new Set(rows.map((r) => r.key))]);
  });

  it('marks exactly one row per number as the anchor target', () => {
    // `[n]`의 DOM id는 한 곳에만 있어야 한다 — 중복 id는 유효하지 않은 HTML이고 점프가
    // 첫 번째로만 간다. 같은 번호가 **논문을 건너서도** 나온다(두 논문이 함께 지지).
    const grouped = groupClaimsByPaper([
      claim('a', [
        ref({ paperId: 'p1', anchor: 's1.p1' }),
        ref({ paperId: 'p1', anchor: 's4.tbl1' }),
        ref({ paperId: 'p2', anchor: 's2.p1' }),
      ]),
      claim('b', [ref({ paperId: 'p1' })]),
    ]);

    const anchors = grouped.papers.flatMap((g) => g.rows.filter((r) => r.anchor));
    expect(anchors.map((r) => r.number).sort()).toEqual([1, 2]);
  });

  it('has no contested section when nothing conflicts', () => {
    const grouped = groupClaimsByPaper([claim('a', [ref({ paperId: 'p1' })])]);

    expect(grouped.contested).toEqual([]);
  });
});

describe('evidenceLine', () => {
  it('uses the original quote — the Korean statement is what the prose already said', () => {
    const line = evidenceLine(ref({ paperId: 'p1', anchor: 's1.p1', quote: 'verbatim text' }), '명제');

    expect(line).toEqual({ kind: 'quote', text: 'verbatim text' });
  });

  it('falls back to the statement for table/figure/formula, where the quote is a cell dump', () => {
    // 실측: `PPL | 8.08 | 11.44 | 11.82 | …` — 명제 없이는 무슨 말인지 모른다.
    for (const anchorType of ['table', 'figure', 'formula', 'code'] as const) {
      const line = evidenceLine(
        ref({ paperId: 'p1', anchor: 's4.tbl1', anchorType, quote: 'PPL | 8.08 | 11.44' }),
        '정확도가 12%p 오른다',
      );
      expect(line).toEqual({ kind: 'statement', text: '정확도가 12%p 오른다' });
    }
  });

  it('falls back to the statement when the source carries no quote at all', () => {
    // 계약상 `sourceScope='figure'`는 quote 없이 가능하다 — 별도 분기를 두지 않는다.
    const line = evidenceLine(ref({ paperId: 'p1', sourceScope: 'figure' }), '그림에서 읽은 것');

    expect(line).toEqual({ kind: 'statement', text: '그림에서 읽은 것' });
  });
});

describe('anchorHref', () => {
  it('opens the body viewer scrolled to the cited block, label included', () => {
    // **`anchorLabel`이 함께 가야 한다.** 블록 id가 그 문서에 없으면 뷰어가 라벨로
    // 떨어지는데(`resolveAnchorId`), 안 실으면 폴백이 죽어 스크롤이 조용히 안 된다.
    // 근거의 앵커는 `표 3`·`4.2절` 같은 라벨꼴이 흔해 그 폴백이 가장 필요한 쪽이다.
    expect(anchorHref(ref({ paperId: '2106.09685v2', anchor: 's4.p3' }))).toBe(
      '/paper/2106.09685v2/doc-model?version=2&anchorId=s4.p3&anchorLabel=s4.p3',
    );
  });

  it('sends an abstract citation to the detail page, where the abstract lives', () => {
    // 본문 뷰어는 `s0` 섹션을 목록에서 빼므로 그 id로는 스크롤이 **조용히** 안 된다.
    expect(anchorHref(ref({ paperId: '2106.09685', anchor: 's0.p1' }))).toBe('/paper/2106.09685');
  });

  it('does not build a body link for a paper we have no doc-model for', () => {
    expect(anchorHref(ref({ paperId: 'arxiv:2405.1v1', namespace: 'arxiv', anchor: 's1.p1' }))).toBe(
      'https://arxiv.org/abs/2405.1v1',
    );
    expect(anchorHref(ref({ paperId: 'userdoc:9c1f', namespace: 'userdoc', anchor: 's1.p1' }))).toBeNull();
  });

  it('leaves the plain detail link when there is no anchor', () => {
    expect(anchorHref(ref({ paperId: '2106.09685' }))).toBe('/paper/2106.09685');
  });
});
