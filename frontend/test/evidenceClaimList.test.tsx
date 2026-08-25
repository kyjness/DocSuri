/**
 * 근거 목록(v3 §2.1) — 출처 링크와 **접기**.
 *
 * 표를 목록으로 바꾼 이유는 두 가지다: 가장 흔한 턴이 논문 한두 편이라 3열 격자가 같은
 * id를 반복하는 껍데기가 됐고, 폰에서는 가로 스크롤 안에 인용문까지 들어가 못 읽었다.
 * 여기서 고정하는 것은 그 목록이 지켜야 할 세 가지다 — 번호는 안 흔들린다, 접힌 근거도
 * 링크 대상으로 남는다, 갈 곳 없는 출처는 링크를 만들지 않는다.
 */
import { render, screen } from '@testing-library/react';
import { useState } from 'react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import {
  EVIDENCE_VISIBLE_CLAIMS,
  EvidenceClaimList,
} from '@/components/agent/AgentChatScreen';
import {
  isExternalSource,
  sourceHref,
  sourceLabel,
} from '@/lib/agentChat/evidenceResult';
import type { EvidenceSourceRef } from '@/lib/agentChat/evidenceResult';

function ref(over: Partial<EvidenceSourceRef>): EvidenceSourceRef {
  return { paperId: '2401.01234', recordRef: 'rec-1', ...over };
}

describe('sourceHref', () => {
  it('sends a corpus paper to our own detail page, where the full text lives', () => {
    // arxiv.org로 내보내면 본문·요약·번역이 다 여기 있는데 밖으로 내보내는 셈이다.
    expect(sourceHref(ref({ paperId: '2401.01234' }))).toBe('/paper/2401.01234');
    expect(isExternalSource(ref({ paperId: '2401.01234' }))).toBe(false);
  });

  it('sends a live-lookup paper outside — it has no detail page here', () => {
    expect(sourceHref(ref({ paperId: 'arxiv:2405.09876v1' }))).toBe(
      'https://arxiv.org/abs/2405.09876v1',
    );
    expect(sourceHref(ref({ paperId: 'doi:10.1145/3580305' }))).toBe(
      'https://doi.org/10.1145/3580305',
    );
  });

  it('refuses to build a link for an uploaded document — that URL would be fabricated', () => {
    // 스키마가 "실재 arXiv id 없음, arxiv.org URL 조립 금지"라고 못 박은 자리다.
    expect(sourceHref(ref({ paperId: 'userdoc:9c1f' }))).toBeNull();
  });

  it('refuses an unknown namespace rather than sending it to a route that must 404', () => {
    expect(sourceHref(ref({ paperId: 'pmid:123456' }))).toBeNull();
    expect(sourceHref(ref({ paperId: '  ' }))).toBeNull();
  });
});

describe('sourceLabel', () => {
  it('falls back to the identifier only when there is no title', () => {
    expect(sourceLabel(ref({ title: 'Attention Is All You Need' }))).toBe(
      'Attention Is All You Need',
    );
    expect(sourceLabel(ref({ title: '   ' }))).toBe('2401.01234');
    expect(sourceLabel(ref({}))).toBe('2401.01234');
  });
});

describe('folding a long evidence list', () => {
  const claims = Array.from({ length: 9 }, (_, i) => ({
    statement: `근거 명제 ${i + 1}`,
    supporting: [ref({ title: `논문 ${i + 1}` })],
    conflicting: [],
  }));

  it('shows the first six and keeps the rest addressable behind "더 보기"', async () => {
    const user = userEvent.setup();
    function Host() {
      const [expanded, setExpanded] = useState(false);
      return (
        <EvidenceClaimList
          claims={claims}
          scope="msg-1"
          expanded={expanded}
          onExpand={() => setExpanded(true)}
        />
      );
    }
    render(<Host />);

    const rows = screen.getAllByTestId('evidence-row');
    expect(rows).toHaveLength(claims.length);
    // **접힌 근거도 DOM에 남는다.** 판단 산문의 `[9]`가 가리킬 대상이 사라지면 링크가 죽는다.
    expect(rows.filter((row) => !row.hasAttribute('hidden'))).toHaveLength(
      EVIDENCE_VISIBLE_CLAIMS,
    );
    // 번호는 접기와 무관하다 — 조립이 정한 순서가 곧 `[n]`이다(BR-EV-5).
    expect(rows[8]).toHaveAttribute('id', 'evidence-msg-1-row-9');

    await user.click(screen.getByTestId('evidence-show-more'));
    expect(
      screen.getAllByTestId('evidence-row').filter((row) => !row.hasAttribute('hidden')),
    ).toHaveLength(claims.length);
    expect(screen.queryByTestId('evidence-show-more')).not.toBeInTheDocument();
  });

  it('does not offer "더 보기" when everything already fits', () => {
    render(<EvidenceClaimList claims={claims.slice(0, EVIDENCE_VISIBLE_CLAIMS)} scope="msg-2" />);

    expect(screen.queryByTestId('evidence-show-more')).not.toBeInTheDocument();
    expect(
      screen.getAllByTestId('evidence-row').filter((row) => !row.hasAttribute('hidden')),
    ).toHaveLength(EVIDENCE_VISIBLE_CLAIMS);
  });
});

describe('a citation number pointing into the folded part', () => {
  it('opens the fold — otherwise the jump silently does nothing', async () => {
    // 감춰진 요소로는 스크롤되지 않는다. 접기 상태를 목록 안에 두면 산문이 그것을 못 건드리고,
    // `[9]`를 눌러도 화면이 그대로 있는다 — 링크가 있는데 죽어 있는 가장 나쁜 모양이다.
    const { EvidenceResultView } = await import('@/components/agent/AgentChatScreen');
    const claims = Array.from({ length: 9 }, (_, i) => ({
      statement: `근거 명제 ${i + 1}`,
      supporting: [ref({ title: `논문 ${i + 1}` })],
      conflicting: [],
    }));
    const user = userEvent.setup();
    render(
      <EvidenceResultView
        scope="msg-3"
        result={{
          state: 'ok',
          claims,
          coverage: { paperCount: 9 },
          answer: {
            segments: [{ text: '아홉 번째 근거가 핵심이다', refs: [9], kind: 'cited' }],
            checks: { demoted: 0, regenerated: false, fallback: false },
          },
        }}
      />,
    );

    const hiddenBefore = screen
      .getAllByTestId('evidence-row')
      .filter((row) => row.hasAttribute('hidden'));
    expect(hiddenBefore).toHaveLength(claims.length - EVIDENCE_VISIBLE_CLAIMS);

    await user.click(screen.getByTestId('evidence-answer-ref'));

    expect(
      screen.getAllByTestId('evidence-row').filter((row) => row.hasAttribute('hidden')),
    ).toHaveLength(0);
  });
});
