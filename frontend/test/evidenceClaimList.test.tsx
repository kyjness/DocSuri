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
  EvidenceResultView,
} from '@/components/agent/AgentChatScreen';
import { sourceHref, sourceLabel } from '@/lib/agentChat/evidenceResult';
import type { EvidenceSourceRef } from '@/lib/agentChat/evidenceResult';

function ref(over: Partial<EvidenceSourceRef>): EvidenceSourceRef {
  return { paperId: '2401.01234', recordRef: 'rec-1', ...over };
}

describe('sourceHref', () => {
  it('sends a corpus paper to our own detail page, where the full text lives', () => {
    // 네임스페이스가 없는 것이 곧 "코퍼스 논문"이다. arxiv.org로 내보내면 본문·요약·번역이
    // 다 여기 있는데 밖으로 내보내는 셈이라, 이 목적지 판단만은 프론트에 남는다.
    expect(sourceHref(ref({ paperId: '2401.01234' }))).toBe('/paper/2401.01234');
  });

  it('sends a live-lookup paper outside — it has no detail page here', () => {
    expect(
      sourceHref(ref({ paperId: 'arxiv:2405.09876v1', namespace: 'arxiv' })),
    ).toBe('https://arxiv.org/abs/2405.09876v1');
    expect(
      sourceHref(ref({ paperId: 'doi:10.1145/3580305', namespace: 'doi' })),
    ).toBe('https://doi.org/10.1145/3580305');
  });

  it('refuses to build a link for an uploaded document — that URL would be fabricated', () => {
    // 스키마가 "실재 arXiv id 없음, arxiv.org URL 조립 금지"라고 못 박은 자리다.
    expect(sourceHref(ref({ paperId: 'userdoc:9c1f', namespace: 'userdoc' }))).toBeNull();
  });

  it('reads the namespace the backend sent rather than re-parsing the prefix', () => {
    // 어휘를 아는 쪽이 판정한다. 프론트가 접두어를 직접 자르면 어휘가 두 벌이 되고,
    // 접두어가 하나 늘 때 이쪽만 안 고쳐져 화면이 조용히 링크를 잃는다.
    // 저장된 옛 턴에는 이 필드가 없다. 없는 값을 "코퍼스"로 단정하면 `/paper/arxiv%3A…`로
    // 보내 반드시 404다 — 접두어가 보이면 링크를 만들지 않는다.
    expect(sourceHref(ref({ paperId: 'arxiv:2405.09876v1' }))).toBeNull();
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

describe('answer prose roles', () => {
  const segment = (over: Record<string, unknown>) => ({
    text: '문장',
    refs: [] as number[],
    kind: 'synthesis' as const,
    ...over,
  });

  function renderAnswer(segments: ReturnType<typeof segment>[]) {
    return render(
      <EvidenceResultView
        scope="msg-role"
        result={{
          state: 'ok',
          claims: [{ statement: '명제', supporting: [ref({ title: '논문' })], conflicting: [] }],
          coverage: { paperCount: 1 },
          answer: { segments, checks: { demoted: 0, regenerated: false, fallback: false } },
        }}
      />,
    );
  }

  it('sets the conclusion and the divergence apart from the supporting sentences', () => {
    renderAnswer([
      segment({ text: '데이터가 적을 때는 LoRA가 낫다', refs: [1], kind: 'cited', role: 'conclusion' }),
      segment({ text: '파라미터를 1만 배 줄인다', refs: [1], kind: 'cited', role: 'evidence' }),
      segment({ text: '갈리는 지점은 분포 안이냐다', role: 'divergence' }),
    ]);

    const roles = screen
      .getAllByText(/LoRA가 낫다|1만 배|분포 안이냐다/)
      .map((node) => node.closest('[data-segment-role]')?.getAttribute('data-segment-role'));
    expect(roles).toEqual(['conclusion', 'evidence', 'divergence']);
    // 라벨은 결론·갈림 지점에만 — 근거 서술까지 달면 신호가 소음이 된다.
    expect(screen.getAllByTestId('evidence-answer-role').map((n) => n.textContent)).toEqual([
      '결론',
      '갈리는 지점',
    ]);
  });

  it('keeps every sentence when the model declared no role — structure is lost, text is not', () => {
    // 옛 턴·폴백 답변·어휘 밖 선언이 전부 이 경로다. 여기서 문장을 버리면 판단이 사라진다.
    renderAnswer([
      segment({ text: '역할 없는 문장 하나', refs: [1], kind: 'cited' }),
      segment({ text: '역할 없는 문장 둘' }),
    ]);

    expect(screen.getByText('역할 없는 문장 하나')).toBeInTheDocument();
    expect(screen.getByText('역할 없는 문장 둘')).toBeInTheDocument();
    expect(screen.queryByTestId('evidence-answer-role')).not.toBeInTheDocument();
  });

  it('renders in array order — a role must not reorder the argument', () => {
    // 프롬프트가 결론을 맨 앞에 두라고 하지만, 순서를 화면이 바꾸면 모델이 의도한 논지
    // 전개가 어긋난다. 결론이 뒤에 오면 뒤에 그린다.
    renderAnswer([
      segment({ text: '먼저 온 근거', refs: [1], kind: 'cited', role: 'evidence' }),
      segment({ text: '나중 온 결론', refs: [1], kind: 'cited', role: 'conclusion' }),
    ]);

    const texts = screen
      .getAllByText(/먼저 온 근거|나중 온 결론/)
      .map((node) => node.textContent);
    expect(texts).toEqual(['먼저 온 근거', '나중 온 결론']);
  });
});
