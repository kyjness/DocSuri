import { describe, expect, it } from 'vitest';
import {
  abstainReasonLabel,
  examinedRangeMessage,
  parseAgentContent,
} from '@/lib/agentChat/evidenceResult';

describe('parseAgentContent', () => {
  it('parses a successful EvidenceResult JSON payload', () => {
    const content = JSON.stringify({
      state: 'ok',
      claims: [
        {
          statement: 'Cottention achieves native linear memory complexity.',
          supporting: [
            {
              paperId: '2409.18747v1',
              recordRef: '2409.18747v1',
              anchor: null,
              quote: 'Cottention achieves native linear memory complexity.',
            },
          ],
          conflicting: [],
        },
      ],
      coverage: { paperCount: 3, queryUsed: 'transformer attention' },
    });

    const parsed = parseAgentContent(content);
    expect(parsed.kind).toBe('evidence');
    if (parsed.kind === 'evidence') {
      expect(parsed.result.claims).toHaveLength(1);
      expect(parsed.result.claims[0].supporting[0].paperId).toBe('2409.18747v1');
      expect(parsed.result.coverage.paperCount).toBe(3);
    }
  });

  it('passes through the structured judgement payload', () => {
    const content = JSON.stringify({
      state: 'ok',
      claims: [],
      coverage: { paperCount: 0 },
      answer: {
        segments: [
          { text: '데이터가 적을 때는 LoRA가 유리해요', refs: [1], kind: 'cited' },
          { text: '갈리는 지점은 도메인 거리예요', refs: [], kind: 'synthesis' },
        ],
        checks: { demoted: 0, regenerated: false, fallback: false },
      },
    });

    const parsed = parseAgentContent(content);
    expect(parsed.kind).toBe('evidence');
    if (parsed.kind === 'evidence') {
      expect(parsed.result.answer?.segments).toHaveLength(2);
      expect(parsed.result.answer?.segments[0].refs).toEqual([1]);
      expect(parsed.result.answer?.segments[1].kind).toBe('synthesis');
    }
  });

  it('parses an abstain response and maps it to a human-readable label', () => {
    const parsed = parseAgentContent('[abstain] insufficient_evidence');
    expect(parsed.kind).toBe('abstain');
    if (parsed.kind === 'abstain') {
      expect(parsed.reason).toBe('insufficient_evidence');
      // §2.3 — 시스템 통보가 아니라 다음에 무엇을 해보라고 말하는 데까지 간다.
      expect(abstainReasonLabel(parsed.reason)).toContain('다른 표현으로');
    }
  });

  it('falls back to a generic label for an unknown abstain reason', () => {
    // 원인을 지어내지 않는다 — 백엔드가 실제 코드(internal_error 등)를 보존하게 고친 것과 짝이다.
    expect(abstainReasonLabel('internal_error')).toContain('다시 물어봐');
  });

  it('keeps a label for llm_unavailable — the assembler still emits it', () => {
    // 백엔드가 이 사유를 **지어내는** 것을 막았을 뿐 생산자가 사라진 게 아니다
    // (`assembler`가 치명 오류에서 낸다). 항목을 지우면 진짜 LLM 실패가 일반
    // 폴백 문구로 떨어져 사유가 화면에서 사라진다.
    const label = abstainReasonLabel('llm_unavailable');
    expect(label).not.toBe(abstainReasonLabel('some_code_nobody_emits'));
    expect(label).toContain('분석을 끝내지 못했어요');
  });

  it('parses an error response', () => {
    const parsed = parseAgentContent('[error] evidence_unavailable');
    expect(parsed.kind).toBe('error');
  });

  it('treats plain text (e.g. user messages, novelty mode) as text', () => {
    const parsed = parseAgentContent('transformer 모델의 attention 메커니즘에 대한 최근 연구 동향은?');
    expect(parsed.kind).toBe('text');
    if (parsed.kind === 'text') {
      expect(parsed.text).toContain('transformer');
    }
  });

  it('does not choke on JSON-looking text that is not an EvidenceResult', () => {
    const parsed = parseAgentContent('{"foo": "bar"}');
    expect(parsed.kind).toBe('text');
  });

  it('labels a cancelled turn as cancelled, not as missing evidence (v3 §2.8)', () => {
    expect(abstainReasonLabel('cancelled')).toBe(
      '취소했어요. 확인한 논문에서는 아직 근거를 찾기 전이었어요.',
    );
    expect(
      examinedRangeMessage({ paperCount: 2, examined: 2, candidates: 16, stoppedReason: 'cancelled' }),
    ).toBe('취소됨 · 후보 16편 중 2편 확인');
  });
});
